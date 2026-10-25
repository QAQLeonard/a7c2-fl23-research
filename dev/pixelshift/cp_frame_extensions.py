"""Original manager notification and complete frame-header dependencies.

Setup supplies registered actor/configuration backing, not API returns or
sensor feedback. Original code still produces queue messages and helper results.
No camera access, capture completion, positioning or boot safety is modeled.
"""
from functools import lru_cache
import struct

from cp_actor_delivery_replay import profile as actor_profile
from cp_actor_queue_replay import setup as setup_queue
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    from cp_frame_header_replay import profile as header_profile
    data, h = header_profile(directory)
    _, actor = actor_profile(directory)
    from cp_queued_end_replay import profile as clear_profile
    _, clear = clear_profile(directory)
    from cp_dispatch_replay import profile as dispatch_profile
    _, dispatch = dispatch_profile(directory)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at-0x108000:at-0x108000+size], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Original frame extension branch changed: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Original frame extension binding is not unique')
        return values[0]

    n = h['notification']
    p = dict(actor=actor, clear=clear, dispatch=dispatch, notification=n, notification_actor=literal(n+6, 0x18, 'r0'),
        callback=literal(n+0x24, 12, 'r1') & ~1,
        notification_invoker=literal(n+6, 0x18, 'r2') & ~1)
    p['target'] = literal(p['callback'], 12, 'r0')
    p['target_initialize'] = call(p['callback']+8)
    p['worker_debug'] = literal(actor['completion']['worker']+10, 0x1c, 'sl')
    # The selected call traverses two original thunks into its full body.
    p['helper_thunks'] = [h['image_helper']]
    for _ in range(2):
        p['helper_thunks'].append(call(p['helper_thunks'][-1]))
    p['helper_body'] = call(p['helper_thunks'][-1]+8)
    p['bank_getter'] = call(p['helper_body']+0x14)
    p['bank_predicate'] = call(p['bank_getter']+0x14)
    p['helper_flags'] = literal(p['helper_body']+0x18, 12, 'sb')
    p['banks'] = literal(p['bank_getter']+0x32, 8, 'r1')
    p['aux_getter'] = call(p['helper_body']+0x2a)
    p['aux'] = literal(p['aux_getter'], 12, 'r0')
    p['header_helpers'] = [call(h['header']+offset) for offset in (0x1e0, 0x22a, 0x242, 0x3a8)]
    p['header_end'] = h['header']+0x410
    p['regions'] = actor['regions']+clear['regions']+[
        (dispatch['dispatcher'], dispatch['dispatcher']+0x120),
        (dispatch['handler'], dispatch['handler']+0x30), (dispatch['getter'], dispatch['getter']+10),
        (dispatch['check'], dispatch['check']+0x28),
        (dispatch['notify'], dispatch['notify']+14),
        (n, n+0x3a), (p['callback'], p['callback']+12),
        (p['notification_invoker'], p['notification_invoker']+12),
        (p['target_initialize'], p['target_initialize']+0x46),
        (p['helper_thunks'][0], p['helper_thunks'][0]+4),
        (p['helper_thunks'][1], p['helper_thunks'][1]+4),
        (p['helper_thunks'][2], p['helper_thunks'][2]+12),
        (p['helper_body'], p['helper_body']+0xf4),
        (p['bank_getter'], p['bank_getter']+0x44),
        (p['bank_predicate'], p['bank_predicate']+0x30),
        (p['aux_getter'], p['aux_getter']+10),
        (h['header'], p['header_end'])]
    p['regions'] += [(at, at+size) for at, size in zip(p['header_helpers'], (0x5c, 0x22, 0x5c, 0x20))]
    return data, p


def prepare(cpu, directory, kernel, *, queue_start=0, bank_gate=0, aux_flag=0):
    """Independent actor binding and configuration-memory fixtures only."""
    _, p = profile(directory)
    actor = p['actor']
    c, q = actor['completion'], actor['queue']

    def map_range(at, size):
        for page in range(at & ~4095, (at+size+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)

    for at, size in ((p['notification_actor'], 4), (p['target'], 0x38),
                     (p['helper_flags'], 0x30), (p['banks'], 3*0x1350),
                     (p['aux'], 0x180), (c['manager'], 32), (actor['profiling_flag'], 4),
                     (p['worker_debug'], 3), (p['clear']['group']['ordinal'], 1)):
        map_range(at, size)
    cpu.mem_write(p['target'], bytes(0x38))
    cpu.mem_write(p['notification_actor'], struct.pack('<I', c['manager']))
    cpu.mem_write(p['helper_flags'], bytes(0x30))
    cpu.mem_write(p['banks'], bytes(3*0x1350))
    cpu.mem_write(p['aux'], bytes(0x180))
    for index in range(3):
        cpu.mem_write(p['banks']+index*0x1350+0x28, struct.pack('<I', bank_gate))
        cpu.mem_write(p['banks']+index*0x1350+0x820, struct.pack('<I', bank_gate))
    cpu.mem_write(p['aux']+2, bytes([aux_flag]))
    cpu.mem_write(actor['profiling_flag'], bytes(4))
    cpu.mem_write(p['worker_debug'], b'\xff\xff\0')
    queue = setup_queue(cpu, directory, kernel_state=kernel, start=queue_start)
    writes = queue['writes']+[(c['manager'], 32), (p['target'], 0x38),
                             (p['aux'], 0x180), (p['banks'], 3*0x1350),
                             (p['clear']['group']['ordinal'], 1),
                             (p['dispatch']['parameter'], 4), (p['dispatch']['source'], 4),
                             (p['dispatch']['changed'], 1), (p['dispatch']['row']+12, 4)]
    return dict(profile=p, queue=queue, writes=writes)
