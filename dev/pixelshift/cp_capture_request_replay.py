"""Native capture-manager initialization, request queue and callback entry.

The original snapshot wrapper runs from entry through return, except its
three telemetry/logging transports. Complete native sender, message buffer
send/receive, invoker and capture entry prefix execute in the same RAM.
The worker is paused inside its capture callback after mode selection, not
reported complete. Queue/OS/config state, actor handoffs and callback client
invocation are fixtures. No sensor motion, exposure or hardware completion.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_actor_delivery_replay import profile as actor_profile
from cp_actor_queue_replay import setup as setup_queue
from cp_capture_context_replay import profile as context_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, actor = actor_profile(directory)
    _, context = context_profile(directory)
    c = actor['completion']
    delta = c['initialize']-0xb0dbec
    p = dict(wrapper=0xb21a3e+delta, wrapper_end=0xb21ace+delta,
             initialize=0xb0dccc+delta, initialize_end=0xb0dd44+delta,
             telemetry=0xb20c22+delta, request=0xb21912+delta,
             request_end=0xb21976+delta, control_getter=0xb2dc92+delta,
             actor=actor, context=context)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, n):
        return list(md.disasm(data[at-0x108000:at-0x108000+n], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'b.w'):
            raise ValueError('Native capture-request call changed: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, n, reg):
        values = [v for r, v in literals(code(at, n)) if r == reg]
        if len(values) != 1:
            raise ValueError('Native capture-request object binding is not unique')
        return values[0]

    p['root'] = literal(p['initialize']+8, 0x12, 'r4')
    p['default_callback'] = literal(p['initialize']+0x32, 0x12, 'r1')
    p['client_getter'] = call(p['request']+14)
    if (literal(p['client_getter'], 10, 'r0') != c['manager']
            or call(p['request']+0x34) != c['sender']
            or call(p['request']+0x56) != p['telemetry']):
        raise ValueError('Native request client uses a different actor or sender')
    p['invoker'] = literal(p['request']+0x12, 0x10, 'r1') & ~1
    p['callback'] = literal(p['request']+0x28, 8, 'r1') & ~1
    if (p['callback'] != (0x4750e8 if delta else 0x475300)
            or code(p['invoker'], 2)[0].op_str != 'r2, [r0, #8]'
            or code(p['invoker']+2, 2)[0].op_str != 'r0, r1'
            or code(p['invoker']+4, 2)[0].op_str != 'r2'):
        raise ValueError('Original invoker no longer dispatches the client callback arguments')
    p['capture_debug'] = literal(p['callback']+12, 8, 'r0')+0xa7
    p['worker_debug'] = literal(c['worker']+10, 0x1c, 'sl')
    p['control'] = literal(p['control_getter'], 0x10, 'r1')+0x3d58
    return data, p


def snapshot_caller(cpu, directory, capture, snapshot, source, capture_id, stack):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    if p['root'] != snapshot['root']:
        raise ValueError('Native capture initializer and snapshot use different manager objects')
    root = p['root']
    control = p['context']['root']+0x3be8
    # Input fields in the original binder's control object, not intermediate
    # capture-manager outputs. Initialization must begin with native state0.
    source_reference, source_tag = 0x54637281, 0x7a
    cpu.mem_write(control+0x28, struct.pack('<I', source_reference))
    cpu.mem_write(control+0xa4, bytes([source_tag]))
    cpu.mem_write(root+4, bytes(4))
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    values = [0x66550000+n for n in range(8)]
    for register, value in zip(protected, values):
        cpu.reg_write(register, value)
    finish = 0x3000c000
    cpu.reg_write(arm.UC_ARM_REG_R0, 0x11111111)
    cpu.reg_write(arm.UC_ARM_REG_R1, capture_id)
    cpu.reg_write(arm.UC_ARM_REG_R2, 4)
    cpu.reg_write(arm.UC_ARM_REG_R3, 0x87654321)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    gates, written, snapshot_calls, initializers, telemetry = [], [], 0, 0, []
    regions = capture['regions']+[(p['wrapper'], p['wrapper_end']),
                                 (p['initialize'], p['initialize_end'])]
    call_returns = [p['wrapper']+0x36, p['wrapper']+0x70, finish]

    def hook(uc, at, size, unused):
        nonlocal snapshot_calls, initializers
        if at == p['telemetry']:
            # Record the original four argument words. This transport is
            # omitted, and none of its return values is used to gate capture.
            if uc.reg_read(arm.UC_ARM_REG_LR) & ~1 not in call_returns:
                raise ValueError('Unexpected telemetry call cannot be omitted')
            telemetry.append([uc.reg_read(getattr(arm, 'UC_ARM_REG_R'+str(n))) for n in range(4)])
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if not any(lo <= at and at+size <= hi for lo, hi in regions):
            raise ValueError('Native full snapshot wrapper entered an unresolved dependency: '+hex(at))
        if at == p['initialize']:
            initializers += 1
        if at == capture['caller']+10:
            gates.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at == snapshot['entry']:
            snapshot_calls += 1
            if (uc.reg_read(arm.UC_ARM_REG_R0) != capture_id
                    or uc.reg_read(arm.UC_ARM_REG_R1) != source
                    or not gates or uc.reg_read(arm.UC_ARM_REG_R2) != gates[0]):
                raise ValueError('Original full caller did not supply the actual snapshot arguments')

    def write_hook(uc, access, at, size, value, unused):
        if stack-4096 <= at and at+size <= stack:
            return
        allowed = [(root, 0x28), (root+0x28, 0xd64), (root+0xd90, 13)]
        if not any(lo <= at and at+size <= lo+n for lo, n in allowed):
            raise ValueError('Native full caller changed unrelated state: '+hex(at))
        if at == root+0xd90:
            written.append((size, value))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        cpu.emu_start(p['wrapper'] | 1, finish, count=20000)
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    expected_header = struct.pack('<III', capture_id, 1, source_reference)+bytes([source_tag])+b'\xa5'*3
    expected_header += struct.pack('<6I', 0, p['default_callback'], 0, 0, 0, 0)
    if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
            or [cpu.reg_read(register) for register in protected] != values
            or initializers != 1 or snapshot_calls != 1 or len(gates) != 1
            or written != [(4, 0), (1, gates[0])]
            or telemetry != [[0, 7, source_reference, 0], [0, 4, gates[0], 0], [0, 5, 1, 0]]):
        raise ValueError('Native wrapper initialization/return/telemetry sequence differs')
    return dict(native_gate=gates[0], native_snapshot_flag=written[-1][1], native_snapshot_calls=1,
        native_manager_initializer_calls=1, wrapper_returned=True, stack_and_registers_preserved=True,
        telemetry_arguments=telemetry, telemetry_calls_omitted=3, telemetry_transport_executed=False,
        every_wrapper_dependency_executed=False, capture_id=capture_id, expected_header=expected_header,
        stop_pc=finish, host_assigned_manager_outputs=False)


def validate_header(cpu, directory, snapshot, evidence):
    if bytes(cpu.mem_read(snapshot['root'], 0x28)) != evidence['expected_header']:
        raise ValueError('Original capture-manager header differs from independent initialization model')


def select_via_queue(cpu, directory, capture, snapshot, *, start=0):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    a, c, q = p['actor'], p['actor']['completion'], p['actor']['queue']
    if not any(lo <= 0x30010000 <= hi for lo, hi, _ in cpu.mem_regions()):
        cpu.mem_map(0x30010000, 0x10000)
    queue = setup_queue(cpu, directory, start=start)
    for at in (c['manager'], a['profiling_flag'], p['control'], p['capture_debug'], p['worker_debug']):
        if not any(lo <= at <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(at & ~4095, 4096)
    if bytes(cpu.mem_read(a['profiling_flag'], 4)) != bytes(4):
        raise ValueError('This bounded queue fixture requires profiling disabled')
    client, finish, stack, worker_stack = 0x30008000, 0x3000c000, 0x3000e000, 0x3100f000
    cpu.mem_write(client-4, b'\x6b'*0x104)
    cpu.mem_write(client+0x2c, b'\1')
    cpu.mem_write(p['control']+0x10, b'\x6b'*12)
    cpu.mem_write(p['capture_debug'], b'\0')
    cpu.mem_write(p['worker_debug'], bytes(2))
    frame_before = bytes(cpu.mem_read(snapshot['root'], 0xe00))
    phase, sent, received, queue_returns, sender_returns = 'actor-init', [], [], [], []
    receiver, callback_ids, omitted, profiling_calls = None, [], 0, 0
    frame = snapshot['root']+8
    capture_id = struct.unpack('<I', cpu.mem_read(snapshot['root'], 4))[0]
    regions = a['regions']+capture['regions']+[(p['request'], p['request_end']),
        (p['client_getter'], p['client_getter']+10), (p['control_getter'], p['control_getter']+0x10),
        (p['invoker'], p['invoker']+8), (p['callback'], capture['selector_end'])]

    def hook(uc, at, size, unused):
        nonlocal receiver, omitted, profiling_calls
        if at == p['telemetry']:
            if phase != 'client' or (uc.reg_read(arm.UC_ARM_REG_LR) & ~1) != p['request']+0x5a:
                raise ValueError('Only the inspected request telemetry can be omitted')
            omitted += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if at in q['waits'] or at == q['receive_wait']:
            raise ValueError('Native queued capture request unexpectedly reached an OS wait')
        if not any(lo <= at and at+size <= hi for lo, hi in regions):
            raise ValueError('Native capture request entered an unresolved dependency: '+hex(at))
        if at == q['send']:
            if uc.reg_read(arm.UC_ARM_REG_R0) != q['ident'] or uc.reg_read(arm.UC_ARM_REG_R2) != 28:
                raise ValueError('Native capture sender used a different queue/record size')
            sent.append(bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), 28)))
        if at == c['sender']+0x2e:
            queue_returns.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at == p['request']+0x38:
            sender_returns.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at == q['receive']:
            receiver = uc.reg_read(arm.UC_ARM_REG_R1)
        if at == c['worker']+0x32:
            status = uc.reg_read(arm.UC_ARM_REG_R0)
            if status != 28 or receiver is None:
                raise ValueError('Native capture worker did not receive the full queued record')
            received.append(bytes(uc.mem_read(receiver, status)))
        if at == a['profiling']:
            profiling_calls += 1
        if at == p['callback']:
            callback_ids.append(uc.reg_read(arm.UC_ARM_REG_R0))

    def write_hook(uc, access, at, size, value, unused):
        allowed = queue['kernel']['writes']+queue['writes']+[
            (stack-4096, 4096), (worker_stack-4096, 4096), (c['manager'], 32),
            (client+0x22, 1), (client+0x2c, 1), (p['control']+0x14, 1), (frame+0x158, 8)]
        if not any(lo <= at and at+size <= lo+n for lo, n in allowed):
            raise ValueError('Native queued capture request changed unrelated state: '+hex(at))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(c['initialize'] | 1, finish, count=1000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or struct.unpack('<I', cpu.mem_read(c['manager']+0x18, 4))[0] != q['ident']
                or struct.unpack('<I', cpu.mem_read(c['manager']+8, 4))[0] != c['worker'] | 1):
            raise ValueError('Original actor initializer failed its native queue/worker binding')
        # Preserve the native worker printing-enable field. Its original
        # print/profiling guard reads the independently disabled global input.
        phase = 'client'
        protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
        saved = [0x55660000+n for n in range(8)]
        for register, value in zip(protected, saved):
            cpu.reg_write(register, value)
        cpu.reg_write(arm.UC_ARM_REG_R0, client)
        cpu.reg_write(arm.UC_ARM_REG_R1, capture_id)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(p['request'] | 1, finish, count=30000)
        expected_message = struct.pack('<7I', p['invoker'] | 1, 0, p['callback'] | 1, 0, 0, capture_id, 0)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(register) for register in protected] != saved
                or cpu.reg_read(arm.UC_ARM_REG_R0) != 0 or queue_returns != [0]
                or sender_returns != [1] or sent != [expected_message] or omitted != 1):
            raise ValueError('Original capture client/sender did not return with its expected queued request')
        phase = 'worker'
        cpu.reg_write(arm.UC_ARM_REG_R0, c['manager'])
        cpu.reg_write(arm.UC_ARM_REG_SP, worker_stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(c['worker'] | 1, capture['selector_end'], count=30000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != capture['selector_end'] or sent != received
                or callback_ids != [capture_id] or profiling_calls != 1):
            raise ValueError('Native worker/invoker did not deliver the original capture request to mode selection')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    expected_client = bytearray(b'\x6b'*0x104)
    expected_client[4+0x22] = expected_client[4+0x2c] = 0
    words = struct.unpack('<10I', cpu.mem_read(queue['root'], 40))
    frame_after = bytes(cpu.mem_read(snapshot['root'], 0xe00))
    if (bytes(cpu.mem_read(client-4, 0x104)) != bytes(expected_client)
            or bytes(cpu.mem_read(p['control']+0x10, 12)) != b'\x6b'*4+b'\0'+b'\x6b'*7
            or words[6:] != (128, (start+32)%128, (start+32)%128, 0)
            or frame_before[:0x160] != frame_after[:0x160]
            or frame_before[0x168:] != frame_after[0x168:]
            or bytes(cpu.mem_read(queue['ring']-4, 4)) != b'\x6b'*4
            or bytes(cpu.mem_read(queue['ring']+128, 4)) != b'\x6b'*4):
        raise ValueError('Native capture queue/client cleanup differs from independent byte checks')
    return dict(native_client_return=0, native_sender_return=1, native_queue_send_status=0,
        native_receive_bytes=28, callback_capture_id_matches=True, original_callback_entries=1,
        native_queue_free_bytes=128, native_queue_messages=0,
        native_queue_read_index=words[7], native_queue_write_index=words[8],
        original_actor_initializer_executed=True, complete_native_sender_executed=True,
        telemetry_calls_omitted=1, telemetry_transport_executed=False,
        worker_paused_inside_capture_callback=True, worker_returned=False,
        capture_callback_returned=False, host_assigned_callback_or_api_return=False,
        host_copied_payload_to_receiver=False, actor_handoff_is_fixture=True,
        queue_os_and_debug_state_are_fixtures=True, physical_exposure_executed=False)


def compare(c2, reference):
    from cp_capture_gate_replay import replay
    rows = []
    for mode in (2, 6, 33):
        for bit in (0, 1):
            for guard in (0, 1):
                for override in (0, 1):
                    for trinity in (0, 1):
                        for start in (0, 112):
                            args = dict(capture_mode=mode, pipeline=bit, native_state=guard,
                                override=override, trinity=trinity, native_context=True,
                                guard_actions=('enter',) if guard else ('exit',),
                                pipeline_source=dict(gpio_bit=bit, capture_mode=mode),
                                native_request=True, queue_start=start)
                            a, b = replay(c2, **args), replay(reference, **args)
                            if a != b:
                                raise ValueError('Native C2/CR manager/request/queue/capture-entry chain differs')
                            rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-capture-request/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
