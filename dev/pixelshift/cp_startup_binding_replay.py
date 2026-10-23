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
    descriptor = 0xbaf266+(0x1a6 if delta else 0)
    row = next(md.disasm(data[descriptor+12-0x108000:descriptor+16-0x108000], descriptor+12))
    wrapper = int(row.op_str.lstrip('#'), 0)
    row = next(md.disasm(data[wrapper+4-0x108000:wrapper+8-0x108000], wrapper+4))
    mask = int(row.op_str.lstrip('#'), 0)
    rows = list(md.disasm(data[mask-0x108000:mask-0x108000+0x3e], mask))
    mask_cache = next(value for reg, value in literals(rows) if reg == 'r1')
    route_table = next(value for reg, value in literals(rows) if reg == 'r3')
    at = 0x78593e+delta+0x32c
    row = next(md.disasm(data[at-0x108000:at-0x108000+4], at))
    if row.mnemonic != 'bl':
        raise ValueError('Original backend control-initializer call changed')
    poll_initializer = int(row.op_str.lstrip('#'), 0)
    at = 0x78593e+delta
    body = list(md.disasm(data[at-0x108000:at-0x108000+0xab6], at))
    dma_return = next(row.address+4 for row in body if row.mnemonic == 'bl'
                      and int(row.op_str.lstrip('#'), 0) == 0x78041e+delta)
    return data, dict(backend=backend, construct=0x785282+delta, bind=0x78593e+delta,
                     globals=globals_base, control_cache=control_cache,
                     flags=flags, irq_bounds=irq_lower-4, irq=irq,
                     dma_construct=0xbaea42+(0x1a6 if delta else 0),
                     dma_descriptor=descriptor, mask_cache=mask_cache, route_table=route_table,
                     dma_engine=0x54c39c+delta, dma_return=dma_return,
                     poll_branch=poll_initializer+0x7c)


def bind(cpu, directory, config, config_bytes, *, initial_register_word, continue_dma=False):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
    import unicorn.arm_const as arm
    data, p = profile(directory)
    backend, stack, finish = p['backend'], 0x3001f000, 0x3001e000
    bases = [0xf3400000, 0xf3410000, 0xf3480000, 0xf3510000, 0xf3580000,
             0xf3610000, 0xf3820000, 0xf3830000, 0xf3920000, 0xf3930000,
             0xf3a20000, 0xf3a30000, 0xf3c10000, 0xf3c20000, 0xf3c30000, 0xf5800000]
    register_ranges = [(base, 0x10000) for base in bases]+[(0xf1388000, 4096)]
    metadata = [(backend, 0x3200), (p['globals'], 0x2c), (p['control_cache'], 4), (p['flags'], 0x60)]
    dma_base, route_words = None, {}
    if continue_dma:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        at = p['dma_construct']-0x1ea
        rows = list(md.disasm(data[at-0x108000:at-0x108000+8], at))
        dma_base = next(value for reg, value in literals(rows) if reg == 'r0')
        metadata += [(dma_base, 5*0x1fc), (p['mask_cache'], 4)]
        register_ranges += [(0xf3a58000, 4096), (0xf40a0000, 4096), (0xf3c80000, 4096)]
        ids = [0x18, 0x19, 10, 11, 0x1a, 0x1b, 12, 13, 0x1c, 0x1d, 14, 15,
               0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x51, 0x52, 0x53]
        route_bases = {struct.unpack_from('<I', data, p['route_table']+12*i-0x108000)[0] for i in ids}
        register_ranges += [(base, 4096) for base in sorted(route_bases) if base]
        for ident in ids:
            offset = p['route_table']+12*ident-0x108000
            base = struct.unpack_from('<I', data, offset)[0]
            shift = data[offset+9]*4
            route_words[base+8] = (route_words.get(base+8, initial_register_word)
                                   & ~(0xf << shift)) | (1 << shift)
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
    dma_entries, dma_frame, dma_returned, pending_poll = [], None, False, None
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    saved = [0x66770000+n for n in range(8)]

    def code_hook(uc, at, length, unused):
        nonlocal boundary, irq_pending
        nonlocal dma_frame, dma_returned, pending_poll
        if at == p['dma_construct'] and not continue_dma:
            boundary = 'before_dma_object_constructor'
            uc.emu_stop()
            return
        if continue_dma and at == p['dma_construct']:
            dma_frame = (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(reg) for reg in protected])
        if continue_dma and at == p['dma_engine']:
            dma_entries.append(tuple(uc.reg_read(reg) for reg in
                                     (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)))
        if continue_dma and at == p['dma_return']:
            if dma_frame != (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(reg) for reg in protected]):
                raise ValueError('Complete original DMA constructor did not preserve its native caller frame')
            dma_returned = True
        if continue_dma and at == p['poll_branch']:
            status = uc.reg_read(arm.UC_ARM_REG_R1)
            base = uc.reg_read(arm.UC_ARM_REG_R0)
            if not status & 1:
                raise ValueError('Native pending bit unexpectedly cleared without an external device')
            pending_poll = dict(address=hex(base+0x810), value=status, wait_mask=0x10001)
            boundary = 'before_repeating_hardware_poll'
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
        dma_records = []
        if continue_dma:
            dma_registers = [0xf3a2e000, 0xf3a2f000, 0xf3a58000, 0xf40a0000, 0xf3c80000]
            modes = [0x440, 0x440, 0x440, 0x660, 0x19e]
            descriptor_ids = [[0x18, 0x19, 10, 11], [0x1a, 0x1b, 12, 13], [0x1c, 0x1d, 14, 15],
                              [0x43, 0x44, 0x45, 0x46, 0x47, 0x48], [0x51, 0x52, 0x53]]
            offsets = [[0x18, 0x24, 0x30, 0x3c]]*3+[[0x18, 0x24, 0x30, 0x3c, 0x48, 0x54],
                                                     [0x18, 0x30, 0x3c]]
            for n, (register, mode, ids_row, row_offsets) in enumerate(zip(dma_registers, modes, descriptor_ids, offsets)):
                obj = dma_base+n*0x1fc
                if (dma_entries[n] != (obj, n, register)
                        or struct.unpack('<I', cpu.mem_read(obj, 4))[0] != obj+0x18
                        or struct.unpack('<I', cpu.mem_read(obj+0x1dc, 4))[0] != register
                        or struct.unpack('<I', cpu.mem_read(obj+0x1e0, 4))[0] != n
                        or struct.unpack('<I', cpu.mem_read(obj+0x1e8, 4))[0] != mode):
                    raise ValueError('Native DMA record construction differs from its source layout')
                for offset, ident in zip(row_offsets, ids_row):
                    if (struct.unpack('<I', cpu.mem_read(obj+offset+4, 4))[0] != ident
                            or cpu.mem_read(obj+offset+8, 1)[0] != 1
                            or cpu.mem_read(obj+offset+10, 1)[0] != int(n < 3)):
                        raise ValueError('Native DMA interrupt descriptor differs')
                for offset, expected in ((0x804, mode), (0x808, word & ~0x11), (0x818, 1), (0x828, 1)):
                    if struct.unpack('<I', cpu.mem_read(register+offset, 4))[0] != expected:
                        raise ValueError('Native DMA register setup differs from independent arithmetic')
                dma_records.append(dict(index=n, register=hex(register), mode=mode, descriptor_ids=ids_row))
            if len(dma_entries) != 5 or not dma_returned or pending_poll is None:
                raise ValueError('Original DMA construction/return did not reach the pending controller boundary')
            for at, expected in route_words.items():
                if struct.unpack('<I', cpu.mem_read(at, 4))[0] != expected:
                    raise ValueError('Native DMA route-mask writes differ from original table/independent arithmetic')
        if (bytes(cpu.mem_read(config, 116)) != before or before != config_bytes
                or not reads or not writes or boundary != ('before_repeating_hardware_poll' if continue_dma else 'before_dma_object_constructor')
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
                original_dma_constructor_returned=dma_returned, native_dma_records=dma_records,
                independent_dma_register_words_checked=20 if continue_dma else 0,
                independent_dma_route_words_checked=len(route_words),
                dma_route_table_from_original_image=continue_dma,
                hardware_poll=pending_poll, dma_data_transfer_or_capture_emulated=False,
                config_preserved=True, same_ram=True, register_backing_is_synthetic_plain_ram=True,
                initial_register_word=initial_register_word, callback_descriptor_is_zero_fixture=True,
                hardware_acknowledgement_or_settling_supplied=False,
                physical_mmio_access_executed=False, complete_boot_executed=False)


def replay(directory, *, overrides=(255, 255), initial_register_word=0, continue_dma=False):
    return config_replay(directory, overrides=overrides,
        observe_config=lambda cpu, at, values: bind(cpu, directory, at, values,
                                                   initial_register_word=initial_register_word,
                                                   continue_dma=continue_dma))


def compare(c2, reference, *, continue_dma=False):
    rows = []
    for overrides in ((255, 255), (17, 6)):
        for word in (0, 0xa5a55a5a):
            args = dict(overrides=overrides, initial_register_word=word, continue_dma=continue_dma)
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
    parser.add_argument('--continue-dma', action='store_true', help='Execute DMA construction and stop at the first pending hardware poll')
    args = parser.parse_args()
    report = compare(args.c2, args.reference, continue_dma=args.continue_dma)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
