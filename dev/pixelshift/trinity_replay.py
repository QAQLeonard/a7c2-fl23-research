"""Replay original Pixel Shift mode setup; stop before AP transport send.

TRINITY is the native firmware name. Replaying its CP parameter assignment
does not execute a capture, an actuator command, or a settling callback.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from native_replay import source


@lru_cache(maxsize=2)
def profile(directory):
    image, info = source(directory)
    target = info['model'] == 'ILCE-7CM2'
    entry = 0x3538160 if target else 0x3538648
    cp_entry = 0x359e88 if target else 0x359fe8
    cp_parameter = 0x165a8a0 if target else 0x16598a0
    code = image.instructions(entry, 0x50)
    if not any(i.mnemonic == 'mov' and i.op_str == 'w2, #0x40ee' for i in code):
        raise ValueError('Original TRINITY packet builder not recognized')
    return image, info, entry, cp_entry, cp_parameter


def configure(directory, *, mode, interval=0, test=0, capture_id=0x12345678, _arguments=None):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                                     UC_ARM64_REG_X2, UC_ARM64_REG_SP,
                                     UC_ARM64_REG_PC, UC_ARM64_REG_LR)
    image, info, entry, _, _ = profile(directory)
    send, trace = [int(info[k], 16) for k in ('send', 'trace')]
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = {send & ~4095, trace & ~4095}
    pages.update(range(entry & ~4095, (entry + 0x310 + 4095) & ~4095, 4096))
    for ins in image.instructions(entry, 0x310):
        if ins.mnemonic == 'adrp':
            pages.add(int(ins.op_str.split('#', 1)[1], 16))
    for page in pages:
        cpu.mem_map(page, 4096)
        at = image.offset(page, 4096)
        cpu.mem_write(page, image.data[at:at + 4096])
    cpu.mem_map(0x10000000, 0x10000)
    args, out = 0x10001000, 0x10002000
    before = struct.pack('<5I', capture_id, mode, interval, interval, test) if _arguments is None else bytes(_arguments)
    if len(before) != 20:
        raise ValueError('Original TRINITY arguments must be exactly twenty bytes')
    cpu.mem_write(args, before)
    cpu.mem_write(out, b'\xa5' * 4)
    cpu.reg_write(UC_ARM64_REG_X0, args)
    cpu.reg_write(UC_ARM64_REG_X1, out)
    cpu.reg_write(UC_ARM64_REG_SP, 0x1000f000)
    result = {'send_executed': False, 'trace_calls_omitted': 0}

    def hook(uc, address, size, _):
        if address == trace:
            result['trace_calls_omitted'] += 1
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif address == send:
            length = uc.reg_read(UC_ARM64_REG_X2)
            if length != 12:
                raise ValueError('Unexpected TRINITY packet length')
            result.update(packet=bytes(uc.mem_read(uc.reg_read(UC_ARM64_REG_X1), length)).hex(),
                          routing=uc.reg_read(UC_ARM64_REG_X0))
            uc.emu_stop()
        elif not entry <= address < entry + 0x310:
            raise ValueError('Unhandled native setup path: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(entry, 0x10003000, count=200)
    if 'packet' not in result:
        raise ValueError('Original mode setup did not reach its transport boundary')
    if bytes(cpu.mem_read(args, len(before))) != before or bytes(cpu.mem_read(out, 4)) != b'\xa5' * 4:
        raise ValueError('Native mode setup changed input/output before send')
    return result


def configure_arguments(directory, arguments):
    """Consume an unchanged original sequence-produced argument record."""
    return configure(directory, mode=0, _arguments=arguments)


def cp_assign(directory, wire):
    """Only the original four-instruction parameter assignment; no driver calls."""
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_PC
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    _, info, _, entry, parameter = profile(directory)
    data = (Path(directory) / 'cpapp-b.bin').read_bytes()
    raw = bytes.fromhex(wire)
    if len(raw) != 12 or struct.unpack_from('<H', raw, 2)[0] != 0x40ee:
        raise ValueError('Expected one native 12-byte TRINITY packet')
    code = data[entry - 0x108000:entry - 0x108000 + 14]
    instructions = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(code, entry))
    if [(i.mnemonic, i.op_str) for i in instructions[-1:]] != [('str.w', 'r1, [r0, #0x180]')]:
        raise ValueError('Original CP assignment not recognized')
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    cpu.mem_map(entry & ~4095, 4096)
    cpu.mem_write(entry, code)
    cpu.mem_map(parameter & ~4095, 4096)
    cpu.mem_write(parameter - 4, b'\xa5' * 12)
    cpu.mem_map(0x30000000, 4096)
    cpu.mem_write(0x30000000, raw)
    cpu.reg_write(UC_ARM_REG_R0, 0x30000000)

    def hook(uc, address, size, _):
        if not entry <= address < entry + 14:
            raise ValueError('CP assignment attempted an external call')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(entry | 1, entry + 14, count=4)
    if cpu.reg_read(UC_ARM_REG_PC) != entry + 14:
        raise ValueError('CP mode assignment did not finish')
    after = bytes(cpu.mem_read(parameter - 4, 12))
    if after[:4] + after[8:] != b'\xa5' * 8:
        raise ValueError('CP changed bytes beyond the mode parameter')
    return {'mode': struct.unpack_from('<I', after, 4)[0],
            'external_calls_executed': 0, 'actuator_executed': False}


def compare(c2, reference):
    cases = []
    inputs = [dict(mode=m, interval=n) for m in (1, 2) for n in range(9)]
    inputs += [dict(mode=0), dict(mode=1, test=1)]
    for values in inputs:
        a, b = configure(c2, **values), configure(reference, **values)
        if a != b or a['routing'] != 0x90030001:
            raise ValueError('Native C2/A7CR TRINITY setup differs')
        x, y = cp_assign(c2, a['packet']), cp_assign(reference, b['packet'])
        if x != y or x['mode'] != bytes.fromhex(a['packet'])[8]:
            raise ValueError('CP parameter does not follow native AP mode')
        cases.append(dict(input=values, ap=a, cp=x))
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    cases = compare(args.c2, args.reference)
    result = {'schema': 'a7c2-pixelshift-trinity-replay/1',
              'camera_io': False, 'status': 'OFFLINE_MODE_SETUP_ONLY',
              'physical_shift_verified': False, 'cases': cases}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({'cases': len(cases), 'camera_io': False, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
