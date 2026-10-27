"""Execute the existing AP single-row sound CSV reader offline.

This investigates reusing the original boot file-loader. libc file/string
operations are simulated. It does not install a hook or establish boot safety.
"""
import argparse
import json
from pathlib import Path
import re
import struct


CSV = (b'\n/* START */\n/usr/share/avsystemsound/\n'
       b'CUSTOM,0x0003,APP,custom-shutter.bin,0xEC0,0x0,AA_RT,6,3,0,0,0\n'
       b'/* END */\n')


def execute(ap, data=CSV, *, missing=False, boot_block=False,
            expected_path=b'/usr/share/avsystemsound/beeplist.txt', csv_limit=0x7800,
            expected_kinds=(3,)):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X30,
        UC_ARM64_REG_PC, UC_ARM64_REG_SP)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(0, (len(ap) + 4095) & ~4095)
    cpu.mem_write(0, ap)
    ram, stack, stop = 0x10000000, 0x20000000, 0x30000000
    for at, size in ((ram, 0x10000), (stack, 0x20000), (stop, 4096)):
        cpu.mem_map(at, size)
    before = bytearray([0xa5]) * (25 * 176)
    stock = bytearray(176)
    stock[:2] = b'\x06\x03'
    struct.pack_into('<QQ', stock, 16, 1216, 0x540)
    before[352:528] = stock
    before = bytes(before)
    cpu.mem_write(ram, before)
    cpu.reg_write(UC_ARM64_REG_X0, ram + 2 * 176)
    cpu.reg_write(UC_ARM64_REG_SP, stack + 0x1f000)
    cpu.reg_write(UC_ARM64_REG_X30, stop)
    if boot_block:
        from unicorn.arm64_const import UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21, UC_ARM64_REG_X29
        frame = stack + 0x1e000
        cpu.reg_write(UC_ARM64_REG_SP, frame)
        cpu.reg_write(UC_ARM64_REG_X29, frame)
        cpu.reg_write(UC_ARM64_REG_X19, 0x12345678)
        cpu.reg_write(UC_ARM64_REG_X20, 0x23456789)
        cpu.mem_write(frame + 0x78, struct.pack('<Q', 0x8099e8e00))
    external_calls = []
    initial_sp = cpu.reg_read(UC_ARM64_REG_SP)
    minimum_sp = [initial_sp]

    def string(at, limit=1024):
        out = bytearray()
        for i in range(limit):
            v = cpu.mem_read(at + i, 1)[0]
            if not v:
                break
            out.append(v)
        return bytes(out)

    def hook(uc, at, size, _):
        minimum_sp[0] = min(minimum_sp[0], uc.reg_read(UC_ARM64_REG_SP))
        if at == stop or (boot_block and at == 0x3060a34):
            uc.emu_stop()
            return
        if 0x2759800 <= at < 0x275a39c:
            return
        if boot_block and 0x3060a24 <= at < 0x3060a34:
            return
        x0, x1, x2, x3 = (uc.reg_read(r) for r in
            (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3))
        result = 0
        external_calls.append(at)
        if boot_block and at == 0x2885488:
            result = ram
        elif at == 0x165d270:
            uc.mem_write(x0, bytes([x1 & 255]) * x2)
            result = x0
        elif at == 0x165f990:
            if string(x0) != expected_path:
                raise ValueError('Unexpected original CSV path')
            result = 0 if missing else ram + 0xf000
        elif at == 0x165f4e0:
            if (x1, x2, x3) != (1, csv_limit, ram + 0xf000):
                raise ValueError('Unexpected fread ABI')
            uc.mem_write(x0, data[:csv_limit])
            result = min(len(data), csv_limit)
        elif at == 0x165e800:
            pass
        elif at == 0x165fd50:
            a, b = string(x0, x2), string(x1, x2)
            result = (a > b) - (a < b)
        elif at == 0x1660080:
            value = string(x1, x2)
            uc.mem_write(x0, value + bytes(x2 - len(value)))
            result = x0
        elif at == 0x165d0f0:
            result = len(string(x0, x1))
        elif at == 0x165e9f0:
            token = string(x0)
            match = re.match(rb'[+-]?(?:0[xX])?[0-9a-fA-F]+', token)
            count = len(match.group()) if match else 0
            result = int(token[:count], x2) if count else 0
            if x1:
                uc.mem_write(x1, struct.pack('<Q', x0 + count))
        elif at == 0x165d3e0:
            uc.mem_write(x0, bytes(uc.mem_read(x1, x2)))
            result = x0
        else:
            raise ValueError('Unsimulated reader external call at ' + hex(at) +
                             ' args=' + repr([hex(n) for n in (x0, x1, x2, x3)]))
        uc.reg_write(UC_ARM64_REG_X0, result & ((1 << 64) - 1))
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(0x3060a24 if boot_block else 0x2759ae8, stop + 4, count=1000000)
    if cpu.reg_read(UC_ARM64_REG_PC) != (0x3060a34 if boot_block else stop):
        raise ValueError('Reader exceeded offline instruction budget')
    if boot_block and (cpu.reg_read(UC_ARM64_REG_X19), cpu.reg_read(UC_ARM64_REG_X20), cpu.reg_read(UC_ARM64_REG_X21)) != (
            0x12345678, 0x23456789, 0x8099e8e00):
        raise ValueError('Native boot block changed required preserved state')
    if cpu.reg_read(UC_ARM64_REG_SP) != initial_sp:
        raise ValueError('Reader did not restore the caller stack pointer')
    after = bytes(cpu.mem_read(ram, len(before)))
    for i in range(25):
        if i+1 not in expected_kinds and after[i*176:(i+1)*176]!=before[i*176:(i+1)*176]:
            raise ValueError('Original reader changed a neighboring descriptor')
    row = after[352:528]
    return {'returned': cpu.reg_read(UC_ARM64_REG_X0),
            'priority': row[0], 'kind': row[1],
            'first_length': struct.unpack_from('<I', row, 4)[0],
            'loop_length': struct.unpack_from('<I', row, 8)[0],
            'bytes': struct.unpack_from('<Q', row, 16)[0],
            'offset': struct.unpack_from('<Q', row, 24)[0],
            'filename': row[44:172].split(b'\0', 1)[0].decode('ascii'),
            'neighbor_descriptors_byte_equal': True,
            'output_changed': after != before,
            'maximum_native_reader_stack_bytes': initial_sp - minimum_sp[0],
            'descriptors': [dict(kind=after[i*176+1],
                bytes=struct.unpack_from('<Q',after,i*176+16)[0],
                offset=struct.unpack_from('<Q',after,i*176+24)[0],
                filename=after[i*176+44:i*176+172].split(b'\0',1)[0].decode('ascii',errors='replace'))
                for i in range(3)],
            'external_calls_simulated': sorted(set(hex(n) for n in external_calls)),
            'camera_io': False, 'camera_boot_verified': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ap', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    result = execute(a.ap.read_bytes())
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
