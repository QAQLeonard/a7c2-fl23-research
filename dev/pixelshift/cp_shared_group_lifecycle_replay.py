"""Native shared-group birth, retained references and recycling in one RAM.

Original first-shot caller code builds callback records, allocates through the
native registered image pool, constructs the group, publishes both pointers
and retains a reference. Original reuse/addref, virtual release and group-end
paths then recycle the same native-allocated object without resetting the pool.
Memory registration, OS/config state, the surrounding image object and stage
invocations are fixtures. No actual image/exposure completion is supplied.
An unrelated outstanding allocation keeps native region retirement out of scope.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_group_end_replay import profile as group_profile
from cp_image_parameter_replay import prepare_registered_pool, profile as image_profile
from cp_pool_return_replay import profile as pool_profile, observer as pool_observer
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, g = group_profile(directory)
    _, image = image_profile(directory)
    _, pool = pool_profile(directory)
    p = dict(group=g, image=image, pool=pool, first=g['descriptor']+0x88,
             first_end=g['descriptor']+0xf0, reuse=g['descriptor']-0x24,
             reuse_end=g['descriptor']+0x86)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, n):
        return list(md.disasm(data[at-0x108000:at-0x108000+n], at))

    def literal(at, n, register):
        values = [v for r, v in literals(code(at, n)) if r == register]
        if len(values) != 1:
            raise ValueError('Native shared-group binding is not unique')
        return values[0]

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Native shared-group call changed: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    p['current'] = literal(p['first']+0x42, 8, 'r0')
    p['retained'] = literal(p['first']+0x4c, 8, 'r0')
    p['construct_invoker'] = literal(p['first'], 12, 'r1') & ~1
    p['release_invoker'] = literal(p['first']+0x1e, 12, 'r1') & ~1
    p['vtable'] = literal(g['factory']+0x3a, 12, 'r0')+8
    p['nested_vtable'] = literal(g['factory']+0x5a, 12, 'r0')+8
    p['fill'] = call(g['constructor']+0x76)
    p['empty_time'] = call(g['cleanup']+14)
    p['clear_group_cache'] = call(g['cleanup']+0x68)
    p['cleanup_flag_getter'] = call(g['cleanup']+0xba)
    if (p['retained'] != g['group'] or pool['root'] != image['primary']
            or pool['state'] != image['state'] or pool['second'] != image['secondary']
            or call(g['factory']+0x10) != image['source']
            or call(p['first']+0x3c) != g['factory']):
        raise ValueError('Native group birth/end/acquisition do not share the same pool and pointers')
    p['regions'] = image['regions']+pool['regions']+[
        (p['first'], p['first_end']), (p['reuse'], p['reuse']+0x1c),
        (g['descriptor']+0x78, p['reuse_end']),
        (g['factory'], g['factory']+0x108), (g['constructor'], g['constructor']+0xb6),
        (p['construct_invoker'], p['construct_invoker']+8),
        (p['release_invoker'], p['release_invoker']+8),
        (p['fill'], image['zero']+0x124), (g['addref'], g['addref']+0x62),
        (g['release'], g['release']+0xb6), (g['end'], g['end']+0x5a),
        (g['cleanup'], g['cleanup']+0xd2), (p['empty_time'], p['empty_time']+0x270),
        (p['clear_group_cache'], p['clear_group_cache']+0x80),
        (p['cleanup_flag_getter'], p['cleanup_flag_getter']+0x14)]
    p['regions'] += [(at, at+12) for at in g['reset_chain']]
    return data, p


def replay(directory, *, reuses=3, free_count=2, dirty=0, ready_state=2):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    g, image, pool = p['group'], p['image'], p['pool']
    cpu, _, initial = prepare_registered_pool(directory, ready_state=ready_state, free_count=free_count,
                                               dirty=dirty, reserved_count=1)
    base, stride, kernel = initial['base'], initial['stride'], initial['kernel']
    next_node = base+stride
    # Pre-existing cache bookkeeping is an independent empty-cache fixture.
    # The shared constructor does not initialize this byte. Without it, dirty
    # backing legitimately requests further cache/resource work at cleanup.
    for index in range(initial['total']):
        cpu.mem_write(base+index*stride+0x52d8, b'\0')
    for at in (p['current'], p['retained'], g['ended'], g['callback'], g['ordinal'],
               g['cleanup_flag'], g['debug']+0xa7):
        if not any(lo <= at <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(at & ~4095, 4096)
    cpu.mem_map(0x34000000, 0x7000)
    frame, stack, finish = 0x34000010, 0x3001f000, 0x3001e000
    cpu.mem_write(frame-4, b'\x6b'*0x6028)
    frame_before = bytes(cpu.mem_read(frame-4, 0x6028))
    cpu.mem_write(p['current'], b'\xa5'*4)
    cpu.mem_write(p['retained'], b'\xa5'*4)
    cpu.mem_write(g['ended'], b'\0')
    cpu.mem_write(g['callback'], bytes(4))
    cpu.mem_write(g['ordinal'], b'\3')
    cpu.mem_write(g['cleanup_flag'], b'\0')
    cpu.mem_write(g['debug']+0xa7, b'\0')
    source_state = bytes(cpu.mem_read(image['state']-4, 0x68))
    source_backing = bytes(cpu.mem_read(base-4, initial['total']*stride+8))
    seen_pool, observe_pool = pool_observer(cpu, pool)
    phase, factory_calls, constructor_calls, source_returns, cleanups, pool_returns = 'birth', 0, 0, [], 0, 0
    references, independent_addrefs = [], 0
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    factory_entry = None

    def hook(uc, at, n, unused):
        nonlocal factory_calls, constructor_calls, factory_entry, cleanups, pool_returns, independent_addrefs
        observe_pool(at)
        if seen_pool['boundary']:
            raise ValueError('Uncontended shared lifecycle reached an OS wait')
        if at == g['resource']:
            raise ValueError('Empty-resource lifecycle unexpectedly requested physical resource release')
        if not any(lo <= at and at+n <= hi for lo, hi in p['regions']):
            raise ValueError('Native shared lifecycle reached an unresolved dependency: '+hex(at))
        if at == g['factory']:
            factory_calls += 1
            factory_entry = (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(register) for register in protected])
        if at == p['first']+0x40:
            if (factory_entry != (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(register) for register in protected])
                    or uc.reg_read(arm.UC_ARM_REG_R0) != base):
                raise ValueError('Native shared factory did not return its allocated object with preserved registers')
        if at == g['factory']+0x14:
            source_returns.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at == g['constructor']:
            constructor_calls += 1
        if at == g['addref']:
            independent_addrefs += 1
        if at == g['cleanup']:
            cleanups += 1
        if at == pool['entry']:
            pool_returns += 1

    def write_hook(uc, access, at, n, value, unused):
        allowed = kernel['writes']+[(kernel['lock']['object'], 12), (kernel['core']+0x10, 4),
            (image['primary'], 24), (base, stride), (stack-4096, 4096+0x40),
            (p['current'], 4), (p['retained'], 4), (frame+0x5aa0, 4),
            (g['ordinal'], 1), (g['ended'], 1), (g['callback'], 4), (g['cleanup_flag'], 1)]
        if not any(lo <= at and at+n <= lo+size for lo, size in allowed):
            raise ValueError('Native shared lifecycle changed unrelated state: '+hex(at))

    def run(entry, stop=finish, **registers):
        for name, value in registers.items():
            uc_reg = getattr(arm, 'UC_ARM_REG_'+name.upper())
            cpu.reg_write(uc_reg, value)
        cpu.emu_start(entry | 1, stop, count=50000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != stop or cpu.reg_read(arm.UC_ARM_REG_SP) != stack:
            raise ValueError('Original shared lifecycle missed its boundary or unbalanced its caller stack')

    def check_count(expected, free):
        count = struct.unpack('<I', cpu.mem_read(base+4, 4))[0]
        available = struct.unpack('<I', cpu.mem_read(image['primary']+8, 4))[0]
        if count != expected or available != free:
            raise ValueError('Native shared reference/pool transition differs')
        references.append(count)

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        run(p['first'], p['first_end'], sp=stack, lr=finish | 1, r4=frame)
        if (source_returns != [base] or factory_calls != 1 or constructor_calls != 1
                or struct.unpack('<3I', cpu.mem_read(base, 12))[:2] != (p['vtable'], 2)
                or struct.unpack('<I', cpu.mem_read(p['current'], 4))[0] != base
                or struct.unpack('<I', cpu.mem_read(p['retained'], 4))[0] != base
                or struct.unpack('<I', cpu.mem_read(frame+0x5aa0, 4))[0] != base
                or bytes(cpu.mem_read(base+0x52e8, 36)) != b'\xff'*36):
            raise ValueError('Native first-shot group allocation/publication differs')
        expected_body = bytearray(source_backing[4:4+stride])
        struct.pack_into('<2I', expected_body, 0, p['vtable'], 2)
        release_record = struct.pack('<5I', p['release_invoker'] | 1, 0, g['cleanup'] | 1, 0, 0)
        if bytes(cpu.mem_read(stack+4, 20)) != release_record:
            raise ValueError('Original first-shot caller built a different shared cleanup record')
        expected_body[8:0x1c] = release_record
        expected_body[0x1c:0x5278] = bytes(0x525c)
        struct.pack_into('<I', expected_body, 0x5310, p['nested_vtable'])
        expected_body[0x5314:0x5328] = bytes(20)
        expected_body[0x5a2c:0x5a3c] = bytes(16)
        for offset in (0x54b0, 0x5494, 0x54b4, 0x54bc, 0x54c0, 0x5a48, 0x5a44, 0x5a3c, 0x5a98, 0x5a94):
            expected_body[offset:offset+4] = bytes(4)
        for offset in (0x5a71, 0x5a70, 0x54c4):
            expected_body[offset] = 0
        struct.pack_into('<I', expected_body, 0x5a4c, 2)
        struct.pack_into('<I', expected_body, 0x5a74, 0xffffffff)
        expected_body[0x5a78:0x5a8c] = bytes(20)
        expected_body[0x52e8:0x530c] = b'\xff'*36
        for row in range(3):
            expected_body[0x5ab0+row*0x80:0x5ac4+row*0x80] = bytes(20)
            expected_body[0x5b14+row*0x80:0x5b19+row*0x80] = bytes(5)
        if bytes(cpu.mem_read(base, stride)) != bytes(expected_body):
            raise ValueError('Native shared constructor differs from independent full-object bytes')
        check_count(2, free_count-1)
        table = struct.unpack('<I', cpu.mem_read(base, 4))[0]
        native_release = struct.unpack('<I', cpu.mem_read(table+12, 4))[0] & ~1
        if native_release != g['release']:
            raise ValueError('Native constructed vtable does not supply the original group release')
        phase = 'first-frame-release'
        run(native_release, r0=base, lr=finish | 1)
        check_count(1, free_count-1)
        expected_body[4:8] = struct.pack('<I', 1)
        for _ in range(reuses):
            phase = 'reuse'
            # Original retained-pointer lookup, vtable addref and frame binding.
            # No host supplies a group pointer in R5 or changes reference count.
            run(p['reuse'], p['reuse_end'], r4=frame)
            check_count(2, free_count-1)
            phase = 'frame-release'
            run(native_release, r0=base, lr=finish | 1)
            check_count(1, free_count-1)
            if bytes(cpu.mem_read(base, stride)) != bytes(expected_body) or cleanups or pool_returns:
                raise ValueError('Releasing an image prematurely cleaned/recycled the retained shared group')
        phase = 'group-end'
        run(g['end'], lr=finish | 1)
        check_count(0, free_count)
        if (cleanups != 1 or pool_returns != 1 or independent_addrefs != 1+reuses
                or struct.unpack('<I', cpu.mem_read(p['retained'], 4))[0] != 0
                or cpu.mem_read(g['ended'], 1)[0] != 1 or cpu.mem_read(g['ordinal'], 1)[0] != 0
                or seen_pool['outer_pool_return_status'] != 0):
            raise ValueError('Native group end did not release exactly the retained allocation')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    expected_body[0:4] = struct.pack('<I', next_node)
    expected_body[4:8] = bytes(4)
    expected_body[0x1c:0x5c20] = bytes(0x5c04)
    expected_backing = bytearray(source_backing)
    expected_backing[4:4+stride] = expected_body
    if (bytes(cpu.mem_read(base-4, len(expected_backing))) != bytes(expected_backing)
            or bytes(cpu.mem_read(image['state']-4, 0x68)) != source_state
            or bytes(cpu.mem_read(kernel['entry']+12, 8)) != bytes(8)
            or bytes(cpu.mem_read(kernel['lock']['object'], 12)) != bytes(12)
            or bytes(cpu.mem_read(pool['mutex']['guard'], 4)) != bytes(4)):
        raise ValueError('Native full lifecycle did not restore its pool/locks or preserve other allocations')
    expected_frame = bytearray(frame_before)
    expected_frame[4+0x5aa0:4+0x5aa4] = struct.pack('<I', base)
    if bytes(cpu.mem_read(frame-4, len(expected_frame))) != bytes(expected_frame):
        raise ValueError('Native first/reuse slices changed unrelated frame data')
    return dict(native_pool_allocations=1, native_constructor_calls=1, native_addrefs=independent_addrefs,
        native_reference_counts=references, native_cleanup_calls=cleanups, native_pool_returns=pool_returns,
        free_count_before=free_count, free_count_after=free_count, native_allocation_stride=stride,
        native_retained_pointer_cleared=True, native_group_ended_flag=1,
        original_first_and_reuse_slices_executed=True, host_assigned_group_or_reference_count=False,
        registered_pool_and_os_inputs_are_fixtures=True, unrelated_outstanding_allocation_is_fixture=True,
        preexisting_empty_cache_state_is_fixture=True,
        actual_region_registration_or_retirement_executed=False, lifecycle_invocations_are_harness_driven=True,
        image_capture_completion_executed=False, live_resource_release_executed=False,
        full_capture_scheduler_executed=False, sensor_centering_or_exposure_executed=False,
        camera_io=False, installable=False)


def compare(c2, reference):
    rows = []
    for reuses in (0, 1, 3):
        for free_count in (2, 4):
            for dirty in (0, 0x6b):
                for ready_state in (2, 3):
                    values = dict(reuses=reuses, free_count=free_count, dirty=dirty, ready_state=ready_state)
                    a, b = replay(c2, **values), replay(reference, **values)
                    if a != b:
                        raise ValueError('Native C2/CR shared allocation-retention-recycle lifecycle differs')
                    rows.append(dict(input=values, target=a, reference=b))
    return dict(schema='a7c2-native-shared-group-lifecycle/1', paired_cases=len(rows), cases=rows,
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
