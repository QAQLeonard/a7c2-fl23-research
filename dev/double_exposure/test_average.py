"""Run the actual AArch64 mean kernel with guarded synthetic image buffers.

These checks cover sample arithmetic, vector tails, stride/capacity checks,
and input preservation. They do not exercise a camera codec or filesystem.
"""
import ctypes
from pathlib import Path
import random
import struct
import tempfile
import unittest

from build_average import build


class NativeMean(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='a7c2-average-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.library = build(Path(cls.temp.name) / 'average.so')

    def setUp(self):
        from elftools.elf.elffile import ELFFile
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_INTR
        from unicorn.arm64_const import (UC_ARM64_REG_CPACR_EL1,
                                         UC_ARM64_REG_SP, UC_ARM64_REG_LR)

        self.cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.base, self.stop, self.desc = 0x10000000, 0x70000000, 0x40000000
        with self.library.open('rb') as source:
            elf = ELFFile(source)
            segments = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
            size = max(s['p_vaddr'] + s['p_memsz'] for s in segments)
            self.cpu.mem_map(self.base, (size + 4095) & ~4095)
            for segment in segments:
                self.cpu.mem_write(self.base + segment['p_vaddr'], segment.data())
            symbol = next(s for s in elf.get_section_by_name('.dynsym').iter_symbols()
                          if s.name == 'a7_average_u8')
            self.entry = self.base + symbol['st_value']
        self.cpu.mem_map(0x60000000, 0x10000)
        self.cpu.mem_map(self.stop, 4096)
        self.cpu.mem_map(self.desc, 4096)
        self.cpu.reg_write(UC_ARM64_REG_CPACR_EL1, 0x300000)
        self.cpu.reg_write(UC_ARM64_REG_SP, 0x6000f000)
        self.cpu.reg_write(UC_ARM64_REG_LR, self.stop)
        self.cpu.hook_add(UC_HOOK_INTR, self.forbidden_syscall)
        self.buffers = []

    def forbidden_syscall(self, *_):
        self.fail('The arithmetic library attempted a system call')

    def buffer(self, content):
        # Place the last byte immediately before an unmapped page. Both SIMD
        # overreads and output overruns fail, even when values look correct.
        base = 0x20000000 + len(self.buffers) * 0x100000
        size = (len(content) + 4095) & ~4095
        self.cpu.mem_map(base, size)
        self.cpu.mem_write(base, b'\xa5' * size)
        pointer = base + size - len(content)
        self.cpu.mem_write(pointer, content)
        self.buffers.append((base, size))
        return pointer

    def run_mean(self, a, b, out, missing=None):
        from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                                         UC_ARM64_REG_X2, UC_ARM64_REG_PC)
        originals = [bytes(self.cpu.mem_read(base, size)) for base, size in self.buffers]
        for index, plane in enumerate((a, b, out)):
            self.cpu.mem_write(self.desc + index * 64, struct.pack('<5Q', *plane))
        for index, reg in enumerate((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2)):
            self.cpu.reg_write(reg, 0 if missing == index else self.desc + index * 64)
        self.cpu.emu_start(self.entry, self.stop, count=4000000)
        self.assertEqual(self.cpu.reg_read(UC_ARM64_REG_PC), self.stop)
        result = ctypes.c_int32(self.cpu.reg_read(UC_ARM64_REG_X0)).value
        if result:
            for (base, size), before in zip(self.buffers, originals):
                self.assertEqual(bytes(self.cpu.mem_read(base, size)), before)
        return result

    def test_all_65536_sample_pairs_and_source_preservation(self):
        a = bytes(x for x in range(256) for _ in range(256))
        b = bytes(range(256)) * 256
        left, right, dest = self.buffer(a), self.buffer(b), self.buffer(bytes(65536))
        self.assertEqual(self.run_mean((left, 65536, 256, 256, 256),
                                       (right, 65536, 256, 256, 256),
                                       (dest, 65536, 256, 256, 256)), 0)
        self.assertEqual(bytes(self.cpu.mem_read(dest, 65536)),
                         bytes((x + y + 1) // 2 for x, y in zip(a, b)))
        self.assertEqual(bytes(self.cpu.mem_read(left, 65536)), a)
        self.assertEqual(bytes(self.cpu.mem_read(right, 65536)), b)

    def test_vector_tails_unaligned_planes_and_distinct_row_padding(self):
        rng = random.Random(712)
        for width in (1, 3, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65, 193):
            with self.subTest(row_bytes=width):
                # New CPU/mappings for each shape.
                self.setUp()
                rows = 5
                strides = (width + 3, width + 5, width + 7)
                inputs = [bytes(rng.randrange(256) for _ in range(s * (rows - 1) + width))
                          for s in strides[:2]]
                output = bytes([0xa5]) * (strides[2] * (rows - 1) + width)
                expected = bytearray(output)
                for y in range(rows):
                    for x in range(width):
                        expected[y * strides[2] + x] = (
                            inputs[0][y * strides[0] + x] +
                            inputs[1][y * strides[1] + x] + 1) // 2
                pointers = [self.buffer(value) for value in (*inputs, output)]
                planes = [(p, len(v), stride, width, rows)
                          for p, v, stride in zip(pointers, (*inputs, output), strides)]
                self.assertEqual(self.run_mean(*planes), 0)
                self.assertEqual(bytes(self.cpu.mem_read(pointers[2], len(output))), expected)
                for pointer, value in zip(pointers, inputs):
                    self.assertEqual(bytes(self.cpu.mem_read(pointer, len(value))), value)
                for (base, _), pointer in zip(self.buffers, pointers):
                    self.assertEqual(bytes(self.cpu.mem_read(base, pointer - base)),
                                     b'\xa5' * (pointer - base))

    def valid_planes(self):
        return [(self.buffer(bytes([value]) * 23), 23, 8, 7, 3)
                for value in (0, 255, 0xa5)]

    def test_invalid_geometry_and_short_buffers_do_not_write(self):
        for index in range(3):
            for field, value, expected in ((1, 22, -2), (2, 6, -1),
                                           (3, 0, -1), (4, 0, -1), (0, 0, -1)):
                with self.subTest(index=index, field=field):
                    self.setUp()
                    planes = [list(p) for p in self.valid_planes()]
                    planes[index][field] = value
                    self.assertEqual(self.run_mean(*planes), expected)

    def test_mismatched_shapes_and_null_descriptors_do_not_write(self):
        for index in range(3):
            with self.subTest(null_descriptor=index):
                planes = self.valid_planes()
                self.assertEqual(self.run_mean(*planes, missing=index), -1)
        for field, value in ((3, 6), (4, 2)):
            planes = [list(p) for p in self.valid_planes()]
            planes[1][field] = value
            self.assertEqual(self.run_mean(*planes), -1)

    def test_exact_and_partial_output_aliases_do_not_write(self):
        for source in range(2):
            for delta in (-1, 0, 1, 22):
                with self.subTest(source=source, delta=delta):
                    self.setUp()
                    planes = [list(p) for p in self.valid_planes()]
                    planes[2][0] = planes[source][0] + delta
                    self.assertEqual(self.run_mean(*planes), -3)

    def test_identical_input_is_unchanged(self):
        planes = self.valid_planes()
        planes[1] = planes[0]
        self.assertEqual(self.run_mean(*planes), 0)
        self.assertEqual(bytes(self.cpu.mem_read(planes[2][0], 23)),
                         bytes(7) + b'\xa5' + bytes(7) + b'\xa5' + bytes(7))

    def test_integer_and_address_wrap_do_not_read_or_write(self):
        maximum = (1 << 64) - 1
        for index in range(3):
            for pointer, size, stride, rows in ((0x1000, maximum, maximum, 3),
                                                (maximum - 4, 23, 8, 3)):
                with self.subTest(index=index, pointer=pointer, stride=stride):
                    self.setUp()
                    planes = [list(p) for p in self.valid_planes()]
                    planes[index] = [pointer, size, stride, 7, rows]
                    self.assertEqual(self.run_mean(*planes), -2)


if __name__ == '__main__':
    unittest.main()
