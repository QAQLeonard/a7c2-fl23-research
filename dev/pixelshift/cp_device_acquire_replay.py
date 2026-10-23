"""Follow original CR/C2 device acquisition through pool and real virtual entry.

Original pool initialization, atomic locks, object construction/zeroing and
virtual dispatch execute. Valid requests stop at the common resource initializer
or construct its original backend and continue to a register-writing initializer,
without supplying either result. Invalid channel admission returns natively.
Pool/OS backing state is synthetic. No device, peripheral response, ready state,
sensor movement, exposure, completed acquisition or patch is supplied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_native_lock_replay import profile as lock_profile, setup as setup_locks
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    delta = -0x218 if model == 'ILCE-7CM2' else 0
    p = dict(initialize=0x779740+delta, acquire=0x779ba4+delta,
             take=0x779bf6+delta, construct=0x7757fe+delta, base=0x775ef0+delta,
             common=0x7763e6+delta, zero=0x61ed00 if delta else 0x61ef18)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, length):
        return list(md.disasm(data[at-0x108000:at-0x108000+length], at))

    p['root'] = next(value for reg, value in literals(code(p['initialize'], 0x28)) if reg == 'lr')
    p['initialized'] = next(value for reg, value in literals(code(p['initialize'], 8)) if reg == 'ip')
    constructor = code(p['construct'], 0x1c)
    p['vtable'] = next(value+8 for reg, value in literals(constructor) if reg == 'r1')
    p['virtual_init'] = struct.unpack_from('<I', data, p['vtable']+8-0x108000)[0] & ~1
    acquire = code(p['acquire'], 0x52)
    if not any(row.mnemonic == 'blx' and row.op_str == 'r6' for row in acquire):
        raise ValueError('Original device acquisition no longer dispatches its real virtual initializer')
    _, locks = lock_profile(directory)
    p['locks'] = locks
    p['context'] = 0x5f267c if delta else 0x5f2894
    return data, p


def replay(directory, *, channel=0, kind=4, interrupt_context=0, construct_backend=False):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    root, stride = p['root'], 0x1450
    pages = set()
    for at, length in ((root, 0xa290), (p['initialized'], 1)):
        pages.update(range(at & ~4095, (at+length+4095) & ~4095, 4096))
    cpu = machine(data, pages)
    cpu.mem_write(root, bytes(0xa290))
    # Selected object's scratch storage starts nonzero so native zeroing is
    # observable independently of the synthetic pool's zero initial state.
    cpu.mem_write(root+0x10+0x894, b'\xa5'*0xaba)
    cpu.mem_write(root+0x10+0x1380, b'\xa5'*0x2c)
    cpu.mem_write(p['initialized'], b'\0')
    os = setup_locks(cpu, directory, interrupt_context=interrupt_context)
    cpu.mem_write(p['locks']['table']+(0x16-1)*4, struct.pack('<I', os['object']))
    delta = -0x218 if p['initialize'] != 0x779740 else 0
    backend_constructor = 0x785282+delta
    # Obtain the actual backend object address from the original initializer,
    # not a guessed model offset. Its MOVW/MOVT appears after the free-list loop.
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    block = list(md.disasm(data[p['initialize']+0x3c-0x108000:p['initialize']+0x50-0x108000],
                          p['initialize']+0x3c))
    backend = next(value for reg, value in literals(block) if reg == 'r0')
    if construct_backend:
        for page in range(backend & ~4095, (backend+0x3200+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
        cpu.mem_write(backend, bytes(0x3200))
    output, stack, finish = 0x30018000, 0x3001f000, 0x3001e000
    cpu.mem_write(output, b'\xa5'*4)
    boundary, constructed, virtual_seen = None, [], False
    register_inputs, common_seen, backend_returned = None, False, False
    register_initializers = {0x781574+delta: 'primary', 0x77f2b0+delta: 'secondary'}
    initializer_variant = None
    constructor_frame, constructor_returned, zero_calls = None, False, []
    expected_node, next_node = root+0x10, root+0x10+stride
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    saved = [0x55330000+n for n in range(8)]
    calls, atomics = [], []

    def hook(uc, at, size, unused):
        nonlocal boundary, virtual_seen, register_inputs, common_seen, initializer_variant
        nonlocal constructor_frame, constructor_returned
        if construct_backend and at in register_initializers:
            obj = uc.reg_read(arm.UC_ARM_REG_R0)
            register_inputs = {name: struct.unpack('<I', uc.mem_read(obj+offset, 4))[0]
                               for name, offset in (('register_base', 4), ('control_base', 0x20), ('mode', 0x48))}
            boundary = 'before_register_writing_initializer'
            initializer_variant = register_initializers[at]
            uc.emu_stop()
            return
        if at == p['common']:
            common_seen = True
        if at == p['common'] and not construct_backend:
            boundary = 'before_common_resource_initializer'
            uc.emu_stop()
            return
        if at in p['locks']['waits']:
            raise ValueError('Uncontended device-pool fixture reached WFE')
        regions = [(p['initialize'], p['initialize']+0x66),
                   (p['acquire'], p['acquire']+0x52), (p['take'], p['take']+0xe8),
                   (p['construct'], p['construct']+0x1c), (p['base'], p['base']+0xb6),
                   (p['zero'], p['zero']+0x124), (p['context'], p['context']+0x34),
                   (p['virtual_init'], p['virtual_init']+0xa0)]+p['locks']['regions']
        if construct_backend:
            regions += [(backend_constructor, backend_constructor+0x6ba),
                        (0x7864be+delta, 0x78687a+delta),
                        (0x78687a+delta, 0x786bc4+delta),
                        (p['common'], p['common']+0x6da),
                        (0x785272+delta, 0x785282+delta)]
        if not any(lo <= at and at+size <= hi for lo, hi in regions):
            raise ValueError('Device acquisition reached an unresolved dependency: '+hex(at))
        if at == p['construct']:
            constructed.append(uc.reg_read(arm.UC_ARM_REG_R0))
            constructor_frame = (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(reg) for reg in protected])
        if at == p['take']+0xd4:
            if constructor_frame != (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(reg) for reg in protected]):
                raise ValueError('Complete original constructor did not preserve its own caller frame')
            constructor_returned = True
        if at == p['zero']:
            zero_calls.append((uc.reg_read(arm.UC_ARM_REG_R0), uc.reg_read(arm.UC_ARM_REG_R1)))
        if at == p['virtual_init']:
            virtual_seen = True
        if at in p['locks']['entries'].values():
            calls.append(next(name for name, entry in p['locks']['entries'].items() if at == entry))
        if p['locks']['mnemonics'].get(at) in ('ldrex', 'strex'):
            atomics.append(p['locks']['mnemonics'][at])

    def write_hook(uc, access, at, length, value, unused):
        allowed = [(root, 0xa290), (p['initialized'], 1), (output, 4),
                   (os['object'], 12), (os['tcb']+0x10, 4), (stack-4096, 4096)]
        if construct_backend:
            allowed.append((backend, 0x3200))
        if not any(lo <= at and at+length <= lo+n for lo, n in allowed):
            raise ValueError('Device acquisition changed unrelated state: '+hex(at))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)

    def run(entry):
        for reg, value in zip(protected, saved):
            cpu.reg_write(reg, value)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry | 1, finish, count=20000)
        if boundary is None and (cpu.reg_read(arm.UC_ARM_REG_PC) != finish
                or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(reg) for reg in protected] != saved):
            raise ValueError('Original device-pool routine did not preserve its native return')

    try:
        run(p['initialize'])
        native_root = cpu.reg_read(arm.UC_ARM_REG_R0)
        if (native_root != root or struct.unpack('<3I', cpu.mem_read(root+4, 12)) != (expected_node, 8, 8)
                or any(struct.unpack('<I', cpu.mem_read(root+0x10+n*stride, 4))[0]
                       != root+0x10+(n+1)*stride for n in range(7))):
            raise ValueError('Original pool initializer did not construct its eight-node free list')
        if construct_backend:
            cpu.reg_write(arm.UC_ARM_REG_R0, backend)
            run(backend_constructor)
            if boundary:
                raise ValueError('Original backend constructor reached a new boundary: '+boundary)
            backend_returned = True
        cpu.reg_write(arm.UC_ARM_REG_R0, native_root)
        cpu.reg_write(arm.UC_ARM_REG_R1, output)
        cpu.reg_write(arm.UC_ARM_REG_R2, channel)
        cpu.reg_write(arm.UC_ARM_REG_R3, kind)
        run(p['acquire'])
        remaining = struct.unpack('<I', cpu.mem_read(root+12, 4))[0]
        if channel < 2:
            expected_boundary = 'before_register_writing_initializer' if construct_backend else 'before_common_resource_initializer'
            if (boundary != expected_boundary
                    or constructed != [expected_node]
                    or not constructor_returned or not virtual_seen or remaining != 7
                    or struct.unpack('<I', cpu.mem_read(root+4, 4))[0] != next_node
                    or struct.unpack('<I', cpu.mem_read(output, 4))[0] != expected_node
                    or struct.unpack('<I', cpu.mem_read(expected_node, 4))[0] != p['vtable']):
                raise ValueError('Native allocation/constructor/virtual-entry ownership differs')
            if (cpu.mem_read(expected_node+0x894, 0xaba) != bytes(0xaba)
                    or cpu.mem_read(expected_node+0x1380, 0x2c) != bytes(0x2c)
                    or (expected_node+0x894, 0xaba) not in zero_calls
                    or (expected_node+0x1380, 0x2c) not in zero_calls):
                raise ValueError('Original allocator did not clear both nonzero scratch fixtures')
            args = [cpu.reg_read(getattr(arm, 'UC_ARM_REG_R'+str(n))) for n in range(4)]
            backend = struct.unpack('<I', cpu.mem_read(root, 4))[0]
            if not construct_backend and args != [expected_node, kind, backend, channel]:
                raise ValueError('Native virtual initializer lost its acquired object or inputs')
            expected_calls = ['acquire_irq' if interrupt_context else 'acquire_task',
                              'release_irq' if interrupt_context else 'release_task']*(2 if construct_backend else 1)
            if calls != expected_calls:
                raise ValueError('Device allocator did not execute its native lock cycle')
            if not {'ldrex', 'strex'}.issubset(atomics):
                raise ValueError('Device allocator did not execute original atomic instructions')
            status = None
        else:
            status = cpu.reg_read(arm.UC_ARM_REG_R0)
            if (boundary is not None or constructed or virtual_seen or calls or remaining != 8
                    or status != 0x10004 or cpu.mem_read(output, 4) != b'\xa5'*4):
                raise ValueError('Native invalid-channel admission changed the pool or output')
        if (struct.unpack('<3I', cpu.mem_read(os['object'], 12)) != (0, 0, 0)
                or struct.unpack('<I', cpu.mem_read(os['tcb']+0x10, 4))[0] != 0):
            raise ValueError('Original allocator did not release its synthetic OS lock')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    return dict(boundary=boundary or 'returned', native_status=status, native_free_objects=remaining,
                original_pool_initializer_returned=True, original_constructor_executed=bool(constructed),
                original_constructor_returned=constructor_returned,
                native_zeroed_scratch_bytes=0xaba+0x2c if constructor_returned else 0,
                real_vtable_dispatch_executed=virtual_seen, native_lock_calls=calls,
                native_atomic_instructions_executed=bool(atomics), output_object_host_assigned=False,
                common_resource_initializer_entered=common_seen,
                common_resource_initializer_returned=False, acquisition_completed=False,
                original_backend_constructor_returned=backend_returned,
                original_backend_address_binder_returned=False,
                register_initializer_inputs=register_inputs,
                register_initializer_variant=initializer_variant,
                register_writing_initializer_executed=False,
                actual_device_or_mmio_executed=False, physical_shift_verified=False,
                synthetic_pool_and_os_state=True, camera_io=False, installable=False)


def compare(c2, reference):
    cases = []
    for context in (0, 1):
        for channel in (0, 1, 2):
            for kind in (4, 5, 11):
                for construct_backend in (False, True):
                    args = dict(channel=channel, kind=kind, interrupt_context=context,
                                construct_backend=construct_backend)
                    a, b = replay(c2, **args), replay(reference, **args)
                    if a != b:
                        raise ValueError('Native C2/CR device-pool/virtual entry differs')
                    cases.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-device-acquire/1', paired_cases=len(cases), cases=cases,
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
