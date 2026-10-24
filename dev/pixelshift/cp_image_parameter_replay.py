"""Native image-parameter acquisition/initialization on registered-pool fixtures.

The original entry mutex, readiness check, checked pool allocator, secondary
pool check, release and complete constructor initialization run. Registered
memory areas and OS/pool backing are fixtures; actual region registration is
not executed. With the real capture population callback, stop before its body.
The no-callback variant returns naturally but is not the full capture path.
No camera I/O, sensor positioning, exposure or hardware success is supplied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_native_mutex_replay import profile as mutex_profile, setup as setup_kernel
from cp_native_lock_replay import profile as lock_profile
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    p = dict(construct=0x473a24 if target else 0x473c3c,
             invoker=0xb0dd66 if target else 0xb0dbc4,
             populate=0xb0c3e4 if target else 0xb0c242)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, n):
        return list(md.disasm(data[at-0x108000:at-0x108000+n], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Original image-parameter call changed: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, n, register):
        values = [v for r, v in literals(code(at, n)) if r == register]
        if len(values) != 1:
            raise ValueError('Original image-parameter state binding is not unique')
        return values[0]

    p['source'] = call(p['construct']+0x10)
    p['mutex_acquire'] = call(p['source']+0x16)
    p['ready'] = call(p['source']+0x20)
    p['take'] = call(p['source']+0x26)
    p['guard_destructor'] = call(p['source']+0x32)
    p['guard_release'] = call(p['guard_destructor']+0x14)
    p['state'] = literal(p['ready']+8, 8, 'r6')
    p['primary'] = literal(p['take']+0x20, 0x10, 'r5')
    p['activate'] = call(p['take']+0x2e)
    p['allocate'] = call(p['take']+0x4c)
    p['secondary_check'] = call(p['take']+0xcc)
    p['secondary'] = literal(p['secondary_check']+6, 12, 'r0')
    p['secondary_activate'] = call(p['secondary_check']+0x12)
    p['context'] = call(p['allocate']+12)
    p['zero'] = call(p['construct']+0x5c)
    p['debug'] = literal(p['construct']+0x1e, 8, 'r0')+0x1e
    p['fatal'] = call(p['construct']+0x1aa)
    p['types'] = [literal(p['construct']+offset, 12, 'r0')+8
                  for offset in (0x3e, 0x60, 0x7a, 0xae, 0xd6, 0xee)]
    _, mutex = mutex_profile(directory)
    _, locks = lock_profile(directory)
    if (p['mutex_acquire'] != mutex['acquire'] or call(p['guard_release']+0x10) != mutex['release']
            or code(p['invoker'], 8)[0].op_str != 'r3, [r0, #8]'):
        raise ValueError('Original image-parameter entry/release/invoker bindings differ')
    p['mutex'], p['locks'] = mutex, locks
    p['regions'] = mutex['regions']+locks['regions']+[
        (p['construct'], p['construct']+0x1bc), (p['source'], p['source']+0x3c),
        (p['ready'], p['ready']+0xa2), (p['take'], p['take']+0xd2),
        (p['activate'], p['activate']+0x13a), (p['allocate'], p['allocate']+0x84),
        (p['secondary_check'], p['secondary_check']+0x2a),
        (p['secondary_activate'], p['secondary_activate']+0xdc),
        (p['context'], p['context']+0x34), (p['zero'], p['zero']+0x124),
        (p['guard_destructor'], p['guard_destructor']+0x1c),
        (p['guard_release'], p['guard_release']+0x36), (p['invoker'], p['invoker']+8)]
    return data, p


def replay(directory, *, ready_state=3, free_count=2, with_callback=True, dirty=0x6b, dispatch=True):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    cpu = machine(data, [])
    kernel = setup_kernel(cpu, directory, dispatch=dispatch)
    base, stride, secondary_base = 0x32000010, 0x67b8, 0x33000010
    total = max(2, free_count)
    size = (total*stride+0x20+4095)&~4095
    cpu.mem_map(0x32000000, size)
    cpu.mem_map(0x33000000, 4096)
    for at, n in ((p['state']-4, 0x68), (p['primary']-4, 32),
                  (p['secondary']-4, 32), (p['debug'], 1)):
        for page in range(at&~4095, (at+n+4095)&~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    # Existing memory-area registration, not a synthetic return from an API.
    # The low-memory notification has already been raised in the small-pool
    # fixture. Large-pool cases naturally bypass that notification threshold.
    notification_history = int(free_count < 11)
    cpu.mem_write(p['state']-4, b'\xa5'*0x68)
    cpu.mem_write(p['state'], struct.pack('<4I', ready_state, 0x1111, 0x2222, notification_history))
    primary = struct.pack('<6I', base if free_count else 0, total, free_count,
                           0x1111, base, total*stride)
    secondary = struct.pack('<6I', secondary_base, 2, 2, 0x2222, secondary_base, 32)
    cpu.mem_write(p['primary'], primary)
    cpu.mem_write(p['secondary'], secondary)
    cpu.mem_write(base-4, bytes([dirty])*(total*stride+8))
    for n in range(total):
        cpu.mem_write(base+n*stride, struct.pack('<I', base+(n+1)*stride if n+1<total else 0))
    cpu.mem_write(secondary_base-4, b'\x6b'*40)
    cpu.mem_write(secondary_base, struct.pack('<I', secondary_base+16))
    cpu.mem_write(secondary_base+16, bytes(4))
    cpu.mem_write(p['debug'], b'\0')
    state_before = bytes(cpu.mem_read(p['state']-4, 0x68))
    primary_before = bytes(cpu.mem_read(p['primary']-4, 32))
    secondary_before = bytes(cpu.mem_read(p['secondary']-4, 32))
    backing_before = bytes(cpu.mem_read(base-4, total*stride+8))
    secondary_bytes = bytes(cpu.mem_read(secondary_base-4, 40))
    request, record, stack, finish = 0x30008000, 0x30008100, 0x3001f000, 0x3001e000
    request_words = (p['invoker'] | 1, 0, p['populate'] | 1, 0, 0) if with_callback else (0, 0, 0, 0, 0)
    record_words = (0x12345678, 0, 0, 0, 0)
    cpu.mem_write(request-4, b'\xa5'*4+struct.pack('<5I', *request_words)+b'\xa5'*4)
    cpu.mem_write(record-4, b'\x6b'*4+struct.pack('<5I', *record_words)+b'\x6b'*4)
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    values = [0x55330000+n for n in range(8)]
    for register, value in zip(protected, values):
        cpu.reg_write(register, value)
    source_entry = None
    source_returns, mutex_status, zero_calls, secondary_results = [], [], [], []
    boundary, population_args = None, None
    writable = kernel['writes']+[(kernel['lock']['object'], 12), (kernel['core']+0x10, 4),
        (p['primary'], 4), (p['primary']+8, 4), (base, stride), (stack-4096, 4096)]

    def hook(uc, at, length, unused):
        nonlocal boundary, population_args, source_entry
        if at == p['fatal']:
            if ((uc.reg_read(arm.UC_ARM_REG_LR) & ~1) != p['construct']+0x1ae
                    or source_returns != [0]):
                raise ValueError('Unexpected original diagnostic cannot be treated as allocation failure')
            boundary = 'native_constructor_null_allocation_error'
            uc.emu_stop()
            return
        if at == p['populate']:
            population_args = [uc.reg_read(arm.UC_ARM_REG_R0), uc.reg_read(arm.UC_ARM_REG_R1)]
            boundary = 'before_original_frame_population_body'
            uc.emu_stop()
            return
        if at in p['mutex']['waits'] or at in p['locks']['waits']:
            raise ValueError('Registered uncontended image-parameter fixture reached a wait')
        if not any(lo <= at and at+length <= hi for lo, hi in p['regions']):
            raise ValueError('Native image-parameter acquisition reached an unresolved dependency: '+hex(at))
        if at == p['source']:
            source_entry = (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(register) for register in protected])
        if at == p['source']+0x1a:
            status = uc.reg_read(arm.UC_ARM_REG_R0)
            mutex_status.append(status)
            if status != 0:
                boundary = 'native_entry_mutex_rejected'
                uc.emu_stop()  # The caller assumes acquisition; do not traverse protected work after rejection.
        if at == p['construct']+0x14:
            if source_entry != (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(register) for register in protected]):
                raise ValueError('Native acquisition did not preserve its caller stack/registers')
            source_returns.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at == p['zero']:
            zero_calls.append((uc.reg_read(arm.UC_ARM_REG_R0)-base, uc.reg_read(arm.UC_ARM_REG_R1)))
        if at == p['take']+0xd0:
            secondary_results.append(uc.reg_read(arm.UC_ARM_REG_R0))

    def write_hook(uc, access, at, length, value, unused):
        if not any(lo <= at and at+length <= lo+n for lo, n in writable):
            raise ValueError('Native image-parameter acquisition changed unrelated bytes: '+hex(at))

    cpu.reg_write(arm.UC_ARM_REG_R0, request)
    cpu.reg_write(arm.UC_ARM_REG_R1, record)
    cpu.reg_write(arm.UC_ARM_REG_R2, 0)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        cpu.emu_start(p['construct'] | 1, finish, count=40000)
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    expected_primary = bytearray(primary)
    expected_backing = bytearray(backing_before)
    rejected = bool(mutex_status and mutex_status[0])
    if rejected:
        if boundary != 'native_entry_mutex_rejected' or source_returns or zero_calls or secondary_results:
            raise ValueError('Rejected native entry lock did not stop before protected allocation')
    elif free_count:
        struct.pack_into('<I', expected_primary, 0, base+stride if free_count>1 else 0)
        struct.pack_into('<I', expected_primary, 8, free_count-1)
        expected = bytearray(backing_before[4:4+stride])
        struct.pack_into('<2I', expected, 0, p['types'][0], 1)
        expected[8:0x1c] = struct.pack('<5I', *record_words)
        for offset, type_index in ((0x218, 1), (0x2b0, 1), (0x348, 2), (0x3e0, 2),
                                   (0x478, 3), (0x4f0, 3), (0x568, 4), (0x600, 5)):
            struct.pack_into('<I', expected, offset, p['types'][type_index])
        expected_zeros = [(offset, 0x14) for offset in (0x21c, 0x2b4, 0x34c, 0x3e4,
                                                       0x47c, 0x4f4, 0x56c, 0x604)]
        expected_zeros += [(0x609c, 0x20), (0x6190, 0x18)]
        for offset, n in expected_zeros+[(0x60d0, 16)]:
            expected[offset:offset+n] = bytes(n)
        expected_backing[4:4+stride] = expected
        if zero_calls != expected_zeros or secondary_results != [1] or source_returns != [base]:
            raise ValueError('Native initialized fields/secondary memory check/acquisition return differs')
        if with_callback:
            if boundary != 'before_original_frame_population_body' or population_args != [base, 0]:
                raise ValueError('Original constructor did not invoke the original frame-population callback')
        elif (boundary is not None or cpu.reg_read(arm.UC_ARM_REG_PC) != finish
                or cpu.reg_read(arm.UC_ARM_REG_R0) != base
                or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(register) for register in protected] != values):
            raise ValueError('Original no-callback constructor did not return naturally')
    elif (boundary != 'native_constructor_null_allocation_error' or source_returns != [0]
          or zero_calls or secondary_results):
        raise ValueError('Native empty-pool failure did not reach the original constructor error boundary')
    if (bytes(cpu.mem_read(p['primary'], 24)) != bytes(expected_primary)
            or bytes(cpu.mem_read(p['primary']-4, 4)) != primary_before[:4]
            or bytes(cpu.mem_read(p['primary']+24, 4)) != primary_before[-4:]
            or bytes(cpu.mem_read(p['secondary']-4, 32)) != secondary_before
            or bytes(cpu.mem_read(base-4, total*stride+8)) != bytes(expected_backing)
            or bytes(cpu.mem_read(secondary_base-4, 40)) != secondary_bytes
            or bytes(cpu.mem_read(request-4, 28)) != b'\xa5'*4+struct.pack('<5I', *request_words)+b'\xa5'*4
            or bytes(cpu.mem_read(record-4, 28)) != b'\x6b'*4+struct.pack('<5I', *record_words)+b'\x6b'*4
            or bytes(cpu.mem_read(kernel['entry']+12, 8)) != bytes(8)
            or bytes(cpu.mem_read(kernel['lock']['object'], 12)) != bytes(12)
            or bytes(cpu.mem_read(p['mutex']['guard'], 4)) != bytes(4)):
        raise ValueError('Native image-parameter bytes, source metadata, neighboring data or lock release differ')
    # The primary descriptor lies inside the larger state region; exclude only
    # its two native-modified words when comparing the remaining source state.
    expected_state = bytearray(state_before)
    offset = p['primary']-(p['state']-4)
    expected_state[offset:offset+24] = expected_primary
    if (bytes(cpu.mem_read(p['state']-4, 0x68)) != bytes(expected_state)
            or mutex_status != ([0] if dispatch else [0xffffffe7])):
        raise ValueError('Native acquisition changed unrelated registered-memory state or failed entry lock')
    allocated = bool(free_count and not rejected)
    return dict(native_allocation_succeeded=allocated, native_acquisition_returned=not rejected,
        source_return_contract_checked=not rejected, entry_mutex_status=mutex_status[0],
        native_primary_free_count=free_count-1 if allocated else free_count,
        native_secondary_activation_results=secondary_results, native_zero_call_count=len(zero_calls),
        boundary=boundary or 'no_callback_constructor_returned',
        original_population_callback_invoked=bool(allocated and with_callback),
        population_callback_body_executed=False, constructor_returned=bool(allocated and not with_callback),
        registered_memory_regions_are_fixtures=True, original_region_registration_executed=False,
        prior_low_memory_notification_is_fixture=bool(notification_history),
        host_assigned_allocation_or_api_return=False, native_zero_function_executed=bool(zero_calls),
        capture_entry_connected=False, positioning_or_exposure_executed=False, camera_io=False, installable=False)


def compare(c2, reference):
    rows = []
    inputs = [dict(ready_state=state, free_count=count, with_callback=callback, dirty=dirty, dispatch=dispatch)
        for state in (2, 3) for count in (2, 12) for callback in (False, True)
        for dirty in (0x6b, 0xa5) for dispatch in (False, True)]
    inputs += [dict(ready_state=state, free_count=0, dispatch=dispatch)
               for state in (2, 3) for dispatch in (False, True)]
    for values in inputs:
        a, b = replay(c2, **values), replay(reference, **values)
        if a != b:
            raise ValueError('Native C2/CR image-parameter allocation/initialization differs')
        rows.append(dict(input=values, target=a, reference=b))
    return dict(schema='a7c2-native-image-parameter/1', paired_cases=len(rows), cases=rows,
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
