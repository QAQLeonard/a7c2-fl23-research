"""Execute each model's original imager construction and startup-config query.

The original constructor, singleton binding/getter, real vtable dispatch and
116-byte copy execute. Override bytes are explicit fixture inputs; original
constructor output is not replaced with host configuration. No complete boot,
address binding, hardware register access, sensor feedback or exposure runs.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    p = dict(construct=0x98bcbe if target else 0x98be7e,
             object_getter=0x98bcb4 if target else 0x98be74,
             install=0x98a4b2 if target else 0x98a672,
             root_getter=0x989d4a if target else 0x989f0a,
             query=0x989d5c if target else 0x989f1c,
             copy=0x61e60c if target else 0x61e824)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, length):
        return list(md.disasm(data[at-0x108000:at-0x108000+length], at))

    p['object'] = next(value for reg, value in literals(code(p['object_getter'], 10)) if reg == 'r0')
    p['root'] = next(value for reg, value in literals(code(p['root_getter'], 10)) if reg == 'r0')
    p['vtable'] = next(value+8 for reg, value in literals(code(p['construct']+0x10, 0x14)) if reg == 'r0')
    p['method'] = struct.unpack_from('<I', data, p['vtable']+0x1c-0x108000)[0] & ~1
    rows = code(p['method'], 12)
    p['overrides'] = next(value+0xa0 for reg, value in literals(rows) if reg == 'r2')
    if ('ldrb.w', 'r3, [r2, #0xa0]') not in [(row.mnemonic, row.op_str) for row in rows]:
        raise ValueError('Original imager configuration override binding changed')
    return data, p


def replay(directory, *, overrides=(255, 255), observe_config=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    pages = set()
    for at, length in ((p['object'], 0x700), (p['root'], 4), (p['overrides'], 2)):
        pages.update(range(at & ~4095, (at+length+4095) & ~4095, 4096))
    cpu = machine(data, pages)
    obj, output, stack, finish = p['object'], 0x30008000, 0x3001f000, 0x3001e000
    cpu.mem_write(obj-4, b'\x6b'*4+bytes(0x700)+b'\x6b'*4)
    cpu.mem_write(output-4, b'\x6b'*4+b'\xa5'*116+b'\x6b'*4)
    cpu.mem_write(p['root'], b'\xa5'*4)
    cpu.mem_write(p['overrides'], bytes(overrides))
    method_entries, copies, phase = 0, [], 'construct'
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    saved = [0x55440000+n for n in range(8)]

    def hook(uc, at, size, unused):
        nonlocal method_entries
        if not 0x108000 <= at or at+size > 0x108000+len(data):
            raise ValueError('Original imager construction/query left the supplied program')
        if at == p['method']:
            method_entries += 1
        if at == p['copy'] and phase == 'query':
            copies.append(tuple(uc.reg_read(reg) for reg in
                                (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)))

    def write_hook(uc, access, at, length, value, unused):
        if stack-4096 <= at and at+length <= stack:
            return
        allowed = {'construct': [(obj, 0x700)], 'install': [(p['root'], 4)],
                   'getter': [], 'query': [(obj+0x54f, 2), (output, 116)]}[phase]
        if not any(lo <= at and at+length <= lo+n for lo, n in allowed):
            raise ValueError('Original imager initialization/query changed unrelated state: '+hex(at))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)

    def run(entry):
        for reg, value in zip(protected, saved):
            cpu.reg_write(reg, value)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry | 1, finish, count=20000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish
                or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(reg) for reg in protected] != saved):
            raise ValueError('Complete original imager constructor/query did not preserve its return/ABI')

    try:
        cpu.reg_write(arm.UC_ARM_REG_R0, obj)
        run(p['construct'])
        constructed = bytes(cpu.mem_read(obj+0x54c, 116))
        if struct.unpack('<I', cpu.mem_read(obj, 4))[0] != p['vtable']:
            raise ValueError('Original imager constructor did not generate the actual query vtable')
        phase = 'install'
        run(p['install'])
        if struct.unpack('<I', cpu.mem_read(p['root'], 4))[0] != obj:
            raise ValueError('Original singleton installer bound a different imager')
        phase = 'getter'
        run(p['root_getter'])
        if cpu.reg_read(arm.UC_ARM_REG_R0) != p['root']:
            raise ValueError('Original startup getter does not share the installed singleton')
        phase = 'query'
        cpu.reg_write(arm.UC_ARM_REG_R1, output)
        run(p['query'])
        expected = bytearray(constructed)
        for offset, value in zip((4, 3), overrides):
            if value != 255:
                expected[offset] = value
        result = bytes(cpu.mem_read(output, 116))
        if (cpu.reg_read(arm.UC_ARM_REG_R0) != 0 or result != bytes(expected)
                or copies != [(output, obj+0x54c, 116)] or method_entries != 1
                or bytes(cpu.mem_read(p['overrides'], 2)) != bytes(overrides)
                or cpu.mem_read(obj-4, 4) != b'\x6b'*4
                or cpu.mem_read(obj+0x700, 4) != b'\x6b'*4
                or cpu.mem_read(output-4, 4) != b'\x6b'*4
                or cpu.mem_read(output+116, 4) != b'\x6b'*4):
            raise ValueError('Native startup configuration/query differs from constructor/override semantics')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    continuation = observe_config(cpu, output, result) if observe_config else None
    report = dict(native_config_hex=result.hex(), constructor_config_hex=constructed.hex(),
                  original_constructor_returned=True, native_singleton_binding=True,
                  real_vtable_query_executed=True, native_config_copy_bytes=116,
                  native_status=0, host_assigned_config_or_api_returns=False,
                  native_callee_saved_registers_preserved=True, overrides=overrides,
                  override_inputs_are_fixtures=True, full_startup_executed=False,
                  initial_bss_and_padding_are_zero_fixtures=True,
                  physical_mmio_access_executed=False, camera_io=False, installable=False)
    if continuation is not None:
        report['config_continuation'] = continuation
    return report


def compare(c2, reference):
    rows = []
    for overrides in ((255, 255), (33, 255), (255, 8), (17, 6)):
        a, b = replay(c2, overrides=overrides), replay(reference, overrides=overrides)
        differences = [n for n, (x, y) in enumerate(zip(bytes.fromhex(a['native_config_hex']),
                                                       bytes.fromhex(b['native_config_hex']))) if x != y]
        rows.append(dict(input=dict(overrides=overrides), target=a, reference=b,
                         model_configuration_difference_offsets=differences))
    return dict(schema='a7c2-native-startup-config/1', paired_cases=len(rows), cases=rows,
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
