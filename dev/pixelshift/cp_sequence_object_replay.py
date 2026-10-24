"""Create a native sequence object and bind its native per-frame descriptor.

Original capture-caller suffix, checked pool allocation/locks, constructor,
complete selector, MakerNote field lookup/update and descriptor stores run
in one RAM. The image-parameter object, pool backing, OS/config/debug and
MakerNote directory are fixtures. The earlier capture prefix and image-parameter
allocation are not executed. Stage zero comes from the native constructor;
selected Pixel Shift callbacks stop before their first child handler. No
sensor positioning, hardware completion, exposure or installable patch.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_sequence_replay import profile as sequence_profile, machine
from cp_native_lock_replay import profile as lock_profile, setup as setup_locks
from cp_stage_replay import profile as stage_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, sequence = sequence_profile(directory)
    _, locks = lock_profile(directory)
    delta = -0x218 if sequence['selector'] == 0x48335c else 0
    p = dict(begin=0x4755de+delta, end=0x47562c+delta, sequence=sequence, locks=locks)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, length):
        return list(md.disasm(data[at-0x108000:at-0x108000+length], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Original sequence-object call changed: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, length, register):
        values = [v for r, v in literals(code(at, length)) if r == register]
        if len(values) != 1:
            raise ValueError('Native sequence-object binding is not unique')
        return values[0]

    p['construct'] = call(p['begin']+0x2c)
    if call(p['begin']+0x36) != sequence['selector']:
        raise ValueError('Original caller does not construct before selecting the descriptor')
    p['pool'] = literal(p['construct']+12, 0x14, 'r0')
    p['allocate'] = call(p['construct']+0x22)
    p['type_bind'] = call(p['construct']+0x52)
    p['type_table'] = literal(p['type_bind']+6, 8, 'r2')
    p['return_callback'] = literal(p['construct']+0x56, 8, 'r0')
    p['initial_callback'] = literal(p['begin'], 14, 'r1')
    p['context'] = call(p['allocate']+12)
    p['config'] = call(sequence['selector']+0x102)
    p['block_lookup'] = call(p['config']+0x1c)
    p['block_index'] = call(p['config']+0x3a)
    p['log'] = call(sequence['boundary']+0x46)
    p['log_filter'] = literal(p['log']+6, 8, 'ip')+6
    p['error_counter'] = literal(p['construct']+0xdc, 8, 'r4')
    p['regions'] = locks['regions']+[
        (p['begin'], p['end']), (p['construct'], p['construct']+0x128),
        (p['allocate'], p['allocate']+0x84), (p['context'], p['context']+0x34),
        (p['type_bind'], p['type_bind']+0x20),
        (sequence['initializer'], sequence['initializer']+0x15e),
        (sequence['selector'], sequence['selector']+0x14c),
        (sequence['classify'], sequence['classify']+0x3c),
        (sequence['first_getter'], sequence['first_getter']+12),
        (sequence['second_getter'], sequence['second_getter']+0x28),
        (sequence['low_getter'], sequence['low_getter']+12),
        (sequence['boundary'], sequence['boundary']+0x4a),
        (p['log'], p['log']+0x5c), (p['config'], p['config']+0x1c0),
        (p['block_lookup'], p['block_lookup']+0x68),
        (p['block_index'], p['block_index']+0x50)]
    return data, p


def replay(directory, *, mode=23, ordinal=0, first=0, interrupt_context=0,
           exif_present=True, failure=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    s, locks = p['sequence'], p['locks']
    cpu = machine(data, [])
    frame, node, next_node, exif = 0x32000000, 0x33000010, 0x33000090, 0x34000010
    cpu.mem_map(frame, 0x8000)
    cpu.mem_map(0x33000000, 4096)
    cpu.mem_map(0x34000000, 4096)
    for at, length in ((p['pool']-4, 32), (s['descriptors']-4, 348),
            (s['first_byte'], 1), (s['second_byte'], 1), (s['debug'], 0x100),
            (s['continuation_state'], 1), (p['log_filter'], 4), (p['error_counter'], 4)):
        for page in range(at & ~4095, (at+length+4095)&~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    os_state = setup_locks(cpu, directory, interrupt_context=interrupt_context,
                           irq_masked=failure == 'masked')
    count = 0 if failure == 'empty' else 2
    pool_before = struct.pack('<6I', node if count else 0, 2, count, 0xffffffff, node, 0x100)
    cpu.mem_write(p['pool']-4, b'\x6b'*4+pool_before+b'\x6b'*4)
    cpu.mem_write(node-4, b'\xa5'*0x108)
    cpu.mem_write(node, struct.pack('<I', next_node))
    cpu.mem_write(next_node, bytes(4))
    cpu.mem_write(p['error_counter'], struct.pack('<I', 5))  # Original log throttle input only.
    cpu.mem_write(p['log_filter'], struct.pack('<H', 1 << 9))  # Native filter rejects category2.
    cpu.mem_write(s['descriptors']-4, b'\xa5'*348)
    cpu.mem_write(frame, b'\x6b'*0x7000)
    for offset, value in ((0x66e8, 1), (0x5c10, 0), (0x210, mode), (0x208, ordinal),
                          (0x5c04, 0), (0x5c08, 0), (0x5a30, exif if exif_present else 0)):
        cpu.mem_write(frame+offset, struct.pack('<I', value))
    for offset, value in ((0x5c38, 1), (0x5c3a, 0), (0x5c0c, 1)):
        cpu.mem_write(frame+offset, bytes([value]))
    cpu.mem_write(s['first_byte'], bytes([first]))
    cpu.mem_write(s['second_byte'], bytes(1))
    cpu.mem_write(s['continuation_state'], bytes(1))
    cpu.mem_write(exif-4, b'\x6b'*0xa08)
    cpu.mem_write(exif+4, struct.pack('<HHII', 0x9400, 7, 0x200, 0x200))
    source_frame = bytes(cpu.mem_read(frame, 0x7000))
    original_node = bytes(cpu.mem_read(node-4, 0x108))
    original_exif = bytes(cpu.mem_read(exif-4, 0xa08))
    stack, finish = 0x3001f000, 0x3001e000
    phase, allocations, stages, log_calls, lookup_results = 'descriptors', [], [], 0, []
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    constructor_entry_state = None
    descriptor_id, callback, boundary = None, None, None
    supported_stage = None

    def hook(uc, at, size, unused):
        nonlocal descriptor_id, callback, boundary, log_calls, constructor_entry_state
        if at in locks['waits']:
            raise ValueError('Synthetic uncontended sequence pool reached an OS wait')
        if phase == 'callback' and at == supported_stage['children'][0]:
            boundary = 'before_first_stage_child'
            uc.emu_stop()
            return
        regions = p['regions']+([(callback, supported_stage['reject']+4)] if phase == 'callback' else [])
        if not any(lo <= at and at+size <= hi for lo, hi in regions):
            raise ValueError('Native sequence object reached an unresolved dependency: '+hex(at))
        if at == p['construct']:
            if uc.reg_read(arm.UC_ARM_REG_R1) != frame:
                raise ValueError('Original constructor did not receive the supplied image parameter')
            constructor_entry_state = (uc.reg_read(arm.UC_ARM_REG_SP),
                [uc.reg_read(register) for register in protected])
        if at == p['begin']+0x30:
            if constructor_entry_state != (uc.reg_read(arm.UC_ARM_REG_SP),
                    [uc.reg_read(register) for register in protected]):
                raise ValueError('Native constructor did not preserve its caller stack/registers')
            allocated = uc.reg_read(arm.UC_ARM_REG_R0)
            allocations.append(allocated)
            if not allocated:
                boundary = 'sequence_allocation_failed'
                uc.emu_stop()  # Do not continue the caller with a NULL object.
        if at == s['boundary']:
            descriptor_id = uc.reg_read(arm.UC_ARM_REG_R2)
        if at == p['log']:
            log_calls += 1
        if at == p['config']+0x20:
            lookup_results.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if phase == 'callback' and at == callback:
            stages.append(cpu.mem_read(node+0x27, 1)[0])

    def write_hook(uc, access, at, size, value, unused):
        if stack-4096 <= at and at+size <= stack+0x58:
            return
        allowed = []
        if phase == 'descriptors':
            allowed = [(s['descriptors'], 340)]
        elif phase == 'create':
            allowed = [(p['pool'], 4), (p['pool']+8, 4), (node, 0x44),
                       (os_state['object'], 12), (os_state['tcb']+0x10, 4)]
            if exif_present:
                allowed += [(exif+0x200+ordinal+0x4f, 1)]
        if not any(lo <= at and at+size <= lo+n for lo, n in allowed):
            raise ValueError('Native sequence object changed unrelated bytes: '+hex(at))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        cpu.emu_start(s['initializer'] | 1, s['initializer']+0x15e, count=1000)
        records = bytes(cpu.mem_read(s['descriptors'], 340))
        phase = 'create'
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_R6, frame)
        cpu.emu_start(p['begin'] | 1, p['end'], count=15000)
        expected_index = (4 if first else 9)+(1 if mode != 23 and ordinal else 0)
        root = struct.unpack('<6I', cpu.mem_read(p['pool'], 24))
        if failure:
            expected_status = 0xfffffffe if failure == 'masked' else 0xffffffff
            if (boundary != 'sequence_allocation_failed' or allocations != [0]
                    or bytes(cpu.mem_read(p['pool'], 24)) != pool_before
                    or bytes(cpu.mem_read(node-4, 0x108)) != original_node
                    or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                    or struct.unpack('<I', cpu.mem_read(stack-40, 4))[0] != expected_status):
                raise ValueError('Native empty/locked sequence allocation did not preserve its original failure')
        else:
            expected = bytearray(original_node[4:4+0x44])
            struct.pack_into('<3I', expected, 0, frame,
                struct.unpack_from('<I', data, p['type_table']+8-0x108000)[0], 2)
            expected[0xc:0x20] = records[expected_index*20:expected_index*20+20]
            struct.pack_into('<I', expected, 0x20, 0)
            struct.pack_into('<HBB', expected, 0x24, 0xffff, 1, 0)
            struct.pack_into('<7I', expected, 0x28, p['return_callback'], 0, 0, 0, 0, 0, 0)
            if (cpu.reg_read(arm.UC_ARM_REG_PC) != p['end'] or allocations != [node]
                    or descriptor_id != expected_index or root[:3] != (next_node, 2, 1)
                    or bytes(cpu.mem_read(node, 0x44)) != bytes(expected)
                    or bytes(cpu.mem_read(node-4, 4)) != b'\xa5'*4
                    or bytes(cpu.mem_read(node+0x44, 0x40)) != original_node[0x48:0x88]
                    or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                    or lookup_results != ([0] if exif_present else [0xfffffffd]) or log_calls != 1):
                raise ValueError('Original sequence constructor/selector/descriptor stores differ')
            updated_exif = bytearray(original_exif)
            if exif_present:
                updated_exif[4+0x200+ordinal+0x4f] = expected_index
            if bytes(cpu.mem_read(exif-4, 0xa08)) != bytes(updated_exif):
                raise ValueError('Native selector MakerNote update differs from its original lookup')
            callback = struct.unpack('<I', cpu.mem_read(node+0x14, 4))[0] & ~1
            if expected_index in (4, 9):
                _, supported_stage = stage_profile(directory, expected_index)
                if supported_stage['entry'] != callback:
                    raise ValueError('Native object callback differs from its selected descriptor')
                phase = 'callback'
                cpu.reg_write(arm.UC_ARM_REG_R0, node)
                cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
                cpu.emu_start(callback | 1, finish, count=100)
                if boundary != 'before_first_stage_child' or stages != [0]:
                    raise ValueError('Native-initialized stage0 did not select its first original child')
            else:
                boundary = 'descriptor_bound_control_case'
        if (bytes(cpu.mem_read(frame, 0x7000)) != source_frame
                or bytes(cpu.mem_read(p['pool']-4, 4)) != b'\x6b'*4
                or bytes(cpu.mem_read(p['pool']+24, 4)) != b'\x6b'*4
                or bytes(cpu.mem_read(s['descriptors']-4, 4)) != b'\xa5'*4
                or bytes(cpu.mem_read(s['descriptors']+340, 4)) != b'\xa5'*4
                or bytes(cpu.mem_read(os_state['object'], 12)) != bytes(12)
                or bytes(cpu.mem_read(os_state['tcb']+0x10, 4)) != bytes(4)):
            raise ValueError('Native sequence object modified source/guards or left lock ownership')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    return dict(boundary=boundary, native_allocation_succeeded=not bool(failure),
        sequence_index=descriptor_id, constructor_stage=cpu.mem_read(node+0x27, 1)[0] if not failure else None,
        stage_zero_callback_dispatched=bool(stages),
        original_pool_allocator_executed=True, complete_selector_executed=not bool(failure),
        native_free_count=root[2], original_descriptor_initializer_executed=True,
        original_descriptor_stores_executed=not bool(failure),
        first_stage_child_executed=False, exif_lookup_status=lookup_results,
        exif_sequence_byte_written=bool(not failure and exif_present),
        native_log_filter_executed=not bool(failure), logging_transport_executed=False,
        host_assigned_allocation_result_or_descriptor=False, host_assigned_initial_stage=False,
        image_parameter_and_pool_os_inputs_are_fixtures=True,
        constructor_stack_and_registers_preserved=True,
        outer_capture_prefix_executed=False, actual_image_parameter_allocation_executed=False,
        callback_invocation_is_fixture=True, positioning_or_exposure_executed=False,
        camera_io=False, installable=False)


def compare(c2, reference):
    rows = []
    inputs = [dict(mode=mode, ordinal=ordinal, first=first, interrupt_context=context, exif_present=present)
        for mode in (2, 23) for ordinal in range(4) for first in (0, 1)
        for context in (0, 1) for present in (False, True)]
    inputs += [dict(failure=failure, interrupt_context=context)
               for failure in ('empty', 'masked') for context in (0, 1)]
    for values in inputs:
        a, b = replay(c2, **values), replay(reference, **values)
        if a != b:
            raise ValueError('Native C2/CR sequence object allocation/selection differs')
        rows.append(dict(input=values, target=a, reference=b))
    return dict(schema='a7c2-native-sequence-object/1', paired_cases=len(rows), cases=rows,
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
