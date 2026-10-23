"""Feed native imager config into original backend construction/address binding.

All register windows are explicitly synthetic plain RAM, including control
registers that native code writes/reads back. No real device, peripheral behavior,
ready acknowledgement, motion or exposure is modeled. Native setup stages are
harness-invoked; unrelated startup clock/interrupt registration does not run.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_device_acquire_replay import profile as acquire_profile
from cp_serial_replay import literals
from cp_startup_config_replay import replay as config_replay


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, a = acquire_profile(directory)
    delta = -0x218 if a['initialize'] != 0x779740 else 0
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    at = a['initialize']+0x3c
    code = list(md.disasm(data[at-0x108000:at-0x108000+0x14], at))
    backend = next(value for reg, value in literals(code) if reg == 'r0')
    helper = 0x786bf4+delta
    rows = list(md.disasm(data[helper-0x108000:helper-0x108000+0x34], helper))
    globals_base = next(value-0x28 for reg, value in literals(rows) if reg == 'r1')
    control = 0xb7150a+(0x1a6 if delta else 0)
    rows = list(md.disasm(data[control-0x108000:control-0x108000+0x1c], control))
    control_cache = next(value for reg, value in literals(rows) if reg == 'r1')
    helper = 0x784b18+delta
    rows = list(md.disasm(data[helper-0x108000:helper-0x108000+0x12], helper))
    flags = next(value for reg, value in literals(rows) if reg == 'ip')
    irq = 0x5e51ec+delta
    ma = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    rows = list(ma.disasm(data[irq-0x108000:irq-0x108000+0x44], irq))
    irq_lower = next(value for reg, value in literals(rows) if reg == 'r0')
    return data, dict(backend=backend, construct=0x785282+delta, bind=0x78593e+delta,
                     globals=globals_base, control_cache=control_cache,
                     flags=flags, irq_bounds=irq_lower-4, irq=irq,
                     dma_construct=0xbaea42+(0x1a6 if delta else 0))


def bind(cpu, directory, config, config_bytes, *, initial_register_word):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
    import unicorn.arm_const as arm
    data, p = profile(directory)
    backend, stack, finish = p['backend'], 0x3001f000, 0x3001e000
    bases = [0xf3400000, 0xf3410000, 0xf3480000, 0xf3510000, 0xf3580000,
             0xf3610000, 0xf3820000, 0xf3830000, 0xf3920000, 0xf3930000,
             0xf3a20000, 0xf3a30000, 0xf3c10000, 0xf3c20000, 0xf3c30000, 0xf5800000]
    register_ranges = [(base, 0x10000) for base in bases]+[(0xf1388000, 4096)]
    metadata = [(backend, 0x3200), (p['globals'], 0x2c), (p['control_cache'], 4), (p['flags'], 0x60)]
    for at, length in metadata+register_ranges:
        for page in range(at & ~4095, (at+length+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    for at, length in register_ranges:
        cpu.mem_write(at, struct.pack('<I', initial_register_word)*(length//4))
    cpu.mem_write(backend-4, b'\x6b'*4+bytes(0x3200)+b'\x6b'*4)
    for page in range(p['irq_bounds'] & ~4095, (p['irq_bounds']+8+4095) & ~4095, 4096):
        if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    cpu.mem_write(p['irq_bounds'], bytes(8))
    callback = 0x30010000
    cpu.mem_write(callback, bytes(32))
    before = bytes(cpu.mem_read(config, 116))
    writes, reads, boundary = [], [], None
    irq_results, irq_pending = [], None
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    saved = [0x66770000+n for n in range(8)]

    def code_hook(uc, at, length, unused):
        nonlocal boundary, irq_pending
        if at == p['dma_construct']:
            boundary = 'before_dma_object_constructor'
            uc.emu_stop()
            return
        if not 0x108000 <= at or at+length > 0x108000+len(data):
            raise ValueError('Native startup binding left the supplied original program: '+hex(at))
        if at == p['irq']:
            irq_pending = uc.reg_read(arm.UC_ARM_REG_R0)
        if irq_pending is not None and (at == p['irq']+0x78 or
                (at == p['irq']+0x68 and uc.reg_read(arm.UC_ARM_REG_R4) != 0)):
            value = uc.reg_read(arm.UC_ARM_REG_R0)
            irq_results.append((irq_pending, value if value < 0x80000000 else value-0x100000000))
            irq_pending = None

    def write_hook(uc, access, at, length, value, unused):
        if stack-4096 <= at and at+length <= stack:
            return
        if not any(lo <= at and at+length <= lo+n for lo, n in metadata+register_ranges):
            raise ValueError('Native startup binding changed uninspected state: '+hex(at))
        if any(lo <= at < lo+n for lo, n in register_ranges):
            writes.append((at, length, value))

    def read_hook(uc, access, at, length, value, unused):
        if config <= at and at+length <= config+116:
            reads.append((at-config, length))

    ch = cpu.hook_add(UC_HOOK_CODE, code_hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    rh = cpu.hook_add(UC_HOOK_MEM_READ, read_hook)

    def run(entry):
        for reg, value in zip(protected, saved):
            cpu.reg_write(reg, value)
        cpu.reg_write(arm.UC_ARM_REG_R0, backend)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry | 1, finish, count=30000)
        if boundary is None and (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(reg) for reg in protected] != saved):
            raise ValueError('Complete native backend startup stage did not preserve its return/ABI')

    try:
        run(p['construct'])
        cpu.reg_write(arm.UC_ARM_REG_R1, config)
        cpu.reg_write(arm.UC_ARM_REG_R2, callback)
        run(p['bind'])
        word = initial_register_word
        bias = struct.unpack('<b', config_bytes[5:6])[0]
        expected_registers = {
            0xf3480000: word | 1, 0xf3480010: word | 1,
            0xf3481040: (word | 7) & 0xfffff8ff | 0x400,
            0xf3481044: word & 0xffffc000 | config_bytes[3],
            0xf3481048: (word & 0xc000c000) | ((bias+2) & 0x3fff)
                         | (((config_bytes[4]+bias+2) << 16) & 0x3fff0000),
            0xf1388074: 0x8000000}
        for at, expected in expected_registers.items():
            if struct.unpack('<I', cpu.mem_read(at, 4))[0] != expected:
                raise ValueError('Native register setup differs from independent mask/config arithmetic: '+hex(at))
        if (bytes(cpu.mem_read(config, 116)) != before or before != config_bytes
                or not reads or not writes or boundary != 'before_dma_object_constructor'
                or irq_results != [(0xa2, -17)]
                or cpu.mem_read(backend-4, 4) != b'\x6b'*4
                or cpu.mem_read(backend+0x3200, 4) != b'\x6b'*4):
            raise ValueError('Original backend binding lost native config or changed neighboring state')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        cpu.hook_del(rh)
    return dict(original_backend_constructor_returned=True, original_address_binder_returned=False,
                boundary=boundary, original_address_binding_prefix_executed=True,
                native_irq_enable_results=irq_results,
                irq_id_bounds_are_zero_fixtures=True, native_irq_enable_succeeded=False,
                config_read_offsets=sorted(set(reads)), native_register_writes=len(writes),
                independent_register_words_checked=len(expected_registers),
                config_preserved=True, same_ram=True, register_backing_is_synthetic_plain_ram=True,
                initial_register_word=initial_register_word, callback_descriptor_is_zero_fixture=True,
                hardware_acknowledgement_or_settling_supplied=False,
                physical_mmio_access_executed=False, complete_boot_executed=False)


def replay(directory, *, overrides=(255, 255), initial_register_word=0):
    return config_replay(directory, overrides=overrides,
        observe_config=lambda cpu, at, values: bind(cpu, directory, at, values,
                                                   initial_register_word=initial_register_word))


def compare(c2, reference):
    rows = []
    for overrides in ((255, 255), (17, 6)):
        for word in (0, 0xa5a55a5a):
            args = dict(overrides=overrides, initial_register_word=word)
            a, b = replay(c2, **args), replay(reference, **args)
            if a['config_continuation'] != b['config_continuation']:
                raise ValueError('Original C2/CR startup binding prefix differs for its consumed fields')
            rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-startup-binding/1', paired_cases=len(rows), cases=rows,
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
