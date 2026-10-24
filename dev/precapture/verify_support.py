"""Regression checks for offline service boundaries; no firmware or device I/O."""

import struct
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R
from support.boundaries import BoundaryRunner
from support.build import compile_shared
from support.ap_model import call_component, return_modeled_service
from support.memory import STACK as MODEL_STACK, STOP as MODEL_STOP
from support.elf import standalone_entry
from support.kernel import text_literal_dependencies

CODE, STACK, STOP = 0x10000000, 0x40000000, 0x50000000


class ServiceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for address, size in ((CODE, 4096), (STACK, 65536), (STOP, 4096)):
            self.cpu.mem_map(address, size)
        # mov x0,#7; add x0,x0,#1; ret. A declared service boundary at the
        # ADD must stop before modifying x0, not simulate a successful call.
        self.cpu.mem_write(CODE, struct.pack("<3I", 0xD28000E0, 0x91000400, 0xD65F03C0))

    def runner(self, *maps):
        return BoundaryRunner(
            self.cpu, [SimpleNamespace(calls=m) for m in maps], stop=STOP, stack=STACK
        )

    def test_service_stops_before_instruction(self):
        runner = self.runner({CODE + 4: "unexecuted-native-service"})
        result = runner.call(CODE, ())
        self.assertEqual(
            result, dict(at=CODE + 4, call="unexecuted-native-service", args=[7, 0, 0, 0])
        )
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_X0), 7)

    def test_all_modules_contribute_boundaries(self):
        runner = self.runner({CODE + 4: "first"}, {CODE + 8: "second"})
        self.assertEqual(runner.call(CODE, ())["call"], "first")
        self.assertEqual(runner.run(CODE + 8)["call"], "second")

    def test_return_is_an_observed_boundary(self):
        result = self.runner().call(CODE, ())
        self.assertEqual((result["at"], result["call"], result["args"][0]), (STOP, None, 8))

    def test_instruction_cap_is_not_completion(self):
        self.cpu.mem_write(CODE, struct.pack("<I", 0x14000000))  # b .
        with self.assertRaises(AssertionError):
            self.runner().call(CODE, (), count=5)

    def test_targets_reset_without_reinitializing_registers(self):
        runner = self.runner()
        first = runner.call(CODE, (), targets=(CODE + 4,))
        self.assertEqual(first["args"][0], 7)
        second = runner.run(CODE + 4)
        self.assertEqual((second["at"], second["args"][0]), (STOP, 8))
        self.assertEqual(len(runner.seen), 1)

    def test_signed_synthetic_inputs_and_stack(self):
        result = self.runner({CODE: "entry"}).call(CODE, (-1, 2, 3, 4))
        self.assertEqual(result["args"], [(1 << 64) - 1, 2, 3, 4])
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_SP), STACK + 0x8000)
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_LR), STOP)

    def test_extra_arguments_fail_before_execution(self):
        with self.assertRaises(ValueError):
            self.runner().call(CODE, (1, 2, 3, 4, 5))
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_PC), 0)


class ComponentModelTests(unittest.TestCase):
    def setUp(self):
        self.cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for address, size in ((CODE, 4096), (MODEL_STACK, 65536), (MODEL_STOP, 4096)):
            self.cpu.mem_map(address, size)
        self.cpu.mem_write(CODE, struct.pack("<I", 0xD65F03C0))  # ret

    def test_component_return_and_signed_input(self):
        self.assertEqual(call_component(self.cpu, CODE, (-1, 2, 3, 4, 5, 6, 7, 8)), 0xffffffff)
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_X7), 8)
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_SP), MODEL_STACK + 0x3000)

    def test_component_budget_exhaustion_fails(self):
        self.cpu.mem_write(CODE, struct.pack("<I", 0x14000000))  # b .
        with self.assertRaisesRegex(AssertionError, "Component did not return"):
            call_component(self.cpu, CODE, (), count=5)

    def test_extra_arguments_rejected_before_execution(self):
        with self.assertRaises(ValueError):
            call_component(self.cpu, CODE, tuple(range(9)))
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_PC), 0)

    def test_explicit_model_status_clobbers_scratch_only(self):
        for index in range(1, 31):
            self.cpu.reg_write(getattr(R, f"UC_ARM64_REG_X{index}"), index)
        self.cpu.reg_write(R.UC_ARM64_REG_LR, MODEL_STOP)
        return_modeled_service(self.cpu, -1022)
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_X0), (1 << 64) - 1022)
        for index in range(1, 18):
            self.assertEqual(self.cpu.reg_read(getattr(R, f"UC_ARM64_REG_X{index}")), 0xde000000 + index)
        for index in range(18, 30):
            self.assertEqual(self.cpu.reg_read(getattr(R, f"UC_ARM64_REG_X{index}")), index)
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_PC), MODEL_STOP)

    def test_model_return_needs_explicit_status(self):
        with self.assertRaises(TypeError):
            return_modeled_service(self.cpu)


class StandaloneEntryTests(unittest.TestCase):
    @staticmethod
    def fixture(bits=64, *, entry=0x1004, machine=None, kind=2,
                segments=None, endian=1):
        """Independent minimal ELF, with entry deliberately past load origin."""
        machine = machine if machine is not None else (183 if bits == 64 else 40)
        segments = segments if segments is not None else [
            (1, 5, 0x200, 0x1000, 0x1000, 16, 32)]
        ident = b'\x7fELF' + bytes((2 if bits == 64 else 1, endian, 1)) + bytes(9)
        raw = bytearray(0x240)
        if bits == 64:
            header = struct.pack('<HHIQQQIHHHHHH', kind, machine, 1, entry,
                                 64, 0, 0, 64, 56, len(segments), 64, 0, 0)
        else:
            header = struct.pack('<HHIIIIIHHHHHH', kind, machine, 1, entry,
                                 52, 0, 0, 52, 32, len(segments), 40, 0, 0)
        raw[:16 + len(header)] = ident + header
        for index, (ptype, flags, offset, va, pa, fs, ms) in enumerate(segments):
            if bits == 64:
                ph = struct.pack('<II6Q', ptype, flags, offset, va, pa, fs, ms, 4)
                at = 64 + index * 56
            else:
                ph = struct.pack('<8I', ptype, offset, va, pa, fs, ms, flags, 4)
                at = 52 + index * 32
            raw[at:at + len(ph)] = ph
        return bytes(raw)

    def test_header_entry_not_linker_origin(self):
        for bits, arch in ((32, 'arm'), (64, 'aarch64')):
            with self.subTest(arch=arch):
                self.assertEqual(standalone_entry(self.fixture(bits), arch), 0x1004)

    def test_wrong_architecture_type_and_alignment_rejected(self):
        for options in (dict(machine=40), dict(kind=3), dict(entry=0),
                        dict(entry=0x1005), dict(entry=0x1010), dict(entry=0x100e)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                standalone_entry(self.fixture(**options), 'aarch64')
        with self.assertRaises(ValueError):
            standalone_entry(self.fixture(32), 'aarch64')
        with self.assertRaises(ValueError):
            standalone_entry(self.fixture(), 'x86')

    def test_invalid_segments_rejected(self):
        valid = (1, 5, 0x200, 0x1000, 0x1000, 16, 32)
        cases = [
            [(1, 4, 0x200, 0x1000, 0x1000, 16, 32)],  # no execute
            [(1, 5, 0x200, 0x1000, 0x2000, 16, 32)],  # aliased entry
            [(1, 5, 0x238, 0x1000, 0x1000, 16, 32)],  # truncated file
            [(1, 5, 0x200, 0x1000, 0x1000, 32, 16)],  # invalid BSS size
            [valid, valid],                            # ambiguous entry
            [valid, (3, 4, 0x220, 0x2000, 0x2000, 4, 4)],  # interpreter
            [valid, (1, 6, 0x220, 0x2000, 0x3000, 4, 4)],  # data alias
            [valid, (1, 6, 0x220, (1 << 64) - 4, (1 << 64) - 4, 4, 8)],
        ]
        for segments in cases:
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                standalone_entry(self.fixture(segments=segments), 'aarch64')

    def test_big_endian_rejected(self):
        raw = bytearray(self.fixture())
        raw[5] = 2
        # The parser can read the identification before interpreting the header.
        with self.assertRaises(ValueError):
            standalone_entry(bytes(raw), 'aarch64')


class LiteralScopeTests(unittest.TestCase):
    """Synthetic ELF metadata checks; no source identity or native execution."""

    @staticmethod
    def fixture(word=0x58000080, relocations=(), backward=False):
        class Symbol(dict):
            def __init__(self, name, offset):
                super().__init__(st_value=offset, st_shndx=1)
                self.name = name
        raw = bytearray(24)
        struct.pack_into('<I', raw, 16 if backward else 0, word)
        symbols = [Symbol('$d' if backward else '$x', 0),
                   Symbol('$x' if backward else '$d', 16)]
        symbols.append(Symbol('fixture_symbol', 0))
        sections = {'.text': SimpleNamespace(data=lambda: bytes(raw)),
                    '.symtab': SimpleNamespace(iter_symbols=lambda: iter(symbols), get_symbol=lambda n: symbols[n]),
                    '.rela.text': SimpleNamespace(iter_relocations=lambda: iter(relocations))}
        return SimpleNamespace(elf=SimpleNamespace(
            get_section_by_name=lambda n: sections[n], get_section_index=lambda n: 1,
            get_section=lambda n: SimpleNamespace(name='.text')))

    def test_width_and_signed_displacement(self):
        for word,width in ((0x58000080,8),(0x18000080,4),(0x98000080,4)):
            found=text_literal_dependencies(self.fixture(word),[(0,4)])
            self.assertEqual([(r['begin'],r['bytes'],r['readers']) for r in found],[(16,width,[0])])
        found=text_literal_dependencies(self.fixture(0x58ffff80,backward=True),[(16,20)])
        self.assertEqual((found[0]['begin'],found[0]['readers']),(0,[16]))

    def test_inline_data_cannot_be_decoded_as_code(self):
        for bounds in ((0,20),(16,24),(1,4),(0,3),(4,4)):
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):
                text_literal_dependencies(self.fixture(),[bounds])

    def test_vector_and_prefetch_are_not_scalar_pointer_loads(self):
        for word in (0x5c000080,0xd8000080):
            with self.subTest(word=word),self.assertRaises(ValueError):
                text_literal_dependencies(self.fixture(word),[(0,4)])

    def test_exact_abs64_and_adjacent_call_have_distinct_extents(self):
        rows=[dict(r_offset=12,r_info_type=283,r_info_sym=2,r_addend=0),
              dict(r_offset=16,r_info_type=257,r_info_sym=2,r_addend=32)]
        found=text_literal_dependencies(self.fixture(relocations=rows),[(0,4),(0,4)])
        self.assertEqual(found[0]['readers'],[0])
        self.assertEqual(found[0]['relocations'],[dict(type=257,symbol='fixture_symbol',
            target_section='.text',symbol_offset=0,addend=32)])

    def test_partial_wrong_type_and_duplicate_relocations_reject(self):
        for offset,kind,repeated in ((12,257,False),(20,257,False),(16,283,False),(16,257,True)):
            rows=[dict(r_offset=offset,r_info_type=kind,r_info_sym=2,r_addend=0)]
            if repeated:rows*=2
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                text_literal_dependencies(self.fixture(relocations=rows),[(0,4)])


class BuildFailureTests(unittest.TestCase):
    def test_failed_compiler_is_not_a_valid_fixture(self):
        with patch("support.build.subprocess.run", return_value=SimpleNamespace(
                returncode=1, stderr="target compile failed")) as run:
            with self.assertRaisesRegex(RuntimeError, "target compile failed"):
                compile_shared('zig', 'thumb', 'unused.elf',
                    ['unused.c'])
        self.assertEqual(run.call_count, 1)

    def test_timeout_propagates_without_retry(self):
        with patch("support.build.subprocess.run", side_effect=subprocess.TimeoutExpired(
                "zig", 120)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                compile_shared('zig', 'aarch64', 'unused.elf',
                    ['unused.c'])
        self.assertEqual(run.call_count, 1)

    def test_unknown_target_never_launches_compiler(self):
        with patch("support.build.subprocess.run") as run:
            with self.assertRaises(KeyError):
                compile_shared('zig', 'x86', 'unused.elf',
                    ['unused.c'])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
