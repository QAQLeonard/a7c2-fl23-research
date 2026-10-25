"""Replay original 2.01 file-number helper in synthetic RAM, without SDK I/O."""
import os
from pathlib import Path
import struct
import unittest


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_MPR'), 'Set A7C2_NATIVE_MPR to a private original SDK library')
class NativeNumberCache(unittest.TestCase):
    def test_original_helper_marks_numeric_bits_and_high_water_once(self):
        from elftools.elf.elffile import ELFFile
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X30
        library = Path(os.environ['A7C2_NATIVE_MPR'])
        with library.open('rb') as stream:
            elf = ELFFile(stream)
            segment = next(s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD' and
                           s['p_vaddr'] <= 0x123000 and s['p_vaddr'] + s['p_filesz'] >= 0x124000)
            stream.seek(segment['p_offset'] + 0x123000 - segment['p_vaddr'])
            code = stream.read(4096)
        base, context, files, stop = 0x10000000, 0x40000000, 0x50000000, 0x70000000
        for slot, folder in ((0, 100), (1, 101), (3, 999)):
            with self.subTest(slot=slot, folder=folder):
                cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
                cpu.mem_map(base + 0x123000, 4096); cpu.mem_write(base + 0x123000, code)
                cpu.mem_map(base + 0x2fd000, 4096)
                cpu.mem_write(base + 0x2fdba8, struct.pack('<Q', context))
                cpu.mem_map(context, 0x16000)
                cpu.mem_map(files, (900 * 0x4e6 + 4095) & ~4095)
                cpu.mem_map(stop, 4096)
                cpu.mem_write(context + slot * 0x5570 + 0xb8, struct.pack('<Q', files))
                row = files + (folder - 100) * 0x4e6
                for index, number in enumerate((1, 7, 8, 9999, 1)):
                    cpu.reg_write(UC_ARM64_REG_X0, slot)
                    cpu.reg_write(UC_ARM64_REG_X1, folder)
                    cpu.reg_write(UC_ARM64_REG_X2, number)
                    cpu.reg_write(UC_ARM64_REG_X30, stop)
                    cpu.emu_start(base + 0x123298, stop, timeout=1000000, count=1000)
                    bitmap = bytes(cpu.mem_read(row, 0x4e6))
                    self.assertTrue(bitmap[number >> 3] & (1 << (number & 7)))
                    highest, count = struct.unpack_from('<HH', bitmap, 0x4e2)
                    self.assertEqual(highest, max((1, 7, 8, 9999, 1)[:index+1]))
                    self.assertEqual(count, min(index + 1, 4))
