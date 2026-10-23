"""Fail-closed metadata-plan controls; no device, USB, or native memory API."""
import unittest
from support.kernel_mapping import SYMBOL_OFFSETS,bootstrap_plan,module_walk_step

BASE=0xffffff8008080000
SYMBOLS=''.join(f'{BASE+at:016x} T {name}\n' for name,at in SYMBOL_OFFSETS.items()).encode()
IOMEM=b'400000000-47fffffff : System RAM\n  400080000-40062ffff : Kernel code\n  400680000-40072efff : Kernel data\nf1000000-f1000fff : controller\n'
BOOT=b'12345678-1234-4234-8234-123456789abc\n'


class KernelMappingTests(unittest.TestCase):
    def test_module_walk(self):
        ram=[dict(start=0x400000000,end=0x4ffffffff)];virtual=0xffffff80005c9000
        words=[0x400002003,0x400003003,0x440001000|3|0x10|0x400]
        self.assertEqual(module_walk_step(virtual,0x400001000,[],ram)['physical'],0x400001000)
        self.assertEqual(module_walk_step(virtual,0x400001000,words[:1],ram)['physical'],0x400002010)
        self.assertEqual(module_walk_step(virtual,0x400001000,words[:2],ram)['physical'],0x400003e48)
        self.assertEqual(module_walk_step(virtual+7,0x400001000,words,ram)['physical'],0x440001007)

    def test_module_walk_rejects(self):
        ram=[dict(start=0x400000000,end=0x4ffffffff)];virtual=0xffffff80005c9000
        valid=[0x400002003,0x400003003,0x440001000|3|0x10|0x400]
        for stage in range(3):
            for entry in (0,1,2,0xf1000003,0xffffffffffffffff):
                words=valid[:stage]+[entry]
                with self.subTest(stage=stage,entry=entry):
                    with self.assertRaises(ValueError):module_walk_step(virtual,0x400001000,words,ram)
        for leaf in (valid[2]|(1<<53),valid[2]|(1<<6),valid[2]&~(1<<10),valid[2]&~0x1c):
            with self.assertRaises(ValueError):module_walk_step(virtual,0x400001000,valid[:2]+[leaf],ram)
        for address in (0,0xffffff8008080000,0xffffffc000000000):
            with self.assertRaises(ValueError):module_walk_step(address,0x400001000,[],ram)

    def test_data_policy_keeps_RAM_and_kernel_guards(self):
        ram=[dict(start=0x400000000,end=0x4ffffffff)];virtual=0xffffff80005c9000
        words=[0x400002003,0x400003003,0x440001413|(1<<53)]
        self.assertEqual(module_walk_step(virtual,0x400001000,words,ram,executable=False)['physical'],0x440001000)
        with self.assertRaises(ValueError):module_walk_step(virtual,0x400001000,words,ram)
        with self.assertRaises(ValueError):module_walk_step(virtual,0x400001000,words,ram,executable=0)
        for leaf in (words[2]|64,(words[2]&~0x1c),0xf1000413):
            with self.assertRaises(ValueError):module_walk_step(virtual,0x400001000,words[:2]+[leaf],ram,executable=False)

    def test_plan_never_admits_read(self):
        plan=bootstrap_plan(IOMEM,SYMBOLS,BOOT)
        self.assertFalse(plan['native_memory_read_admitted']);self.assertFalse(plan['loaded_code_verified'])
        reads={r['name']:r for r in plan['reads']}
        self.assertEqual(reads['image_header']['physical'],0x400080000)
        self.assertEqual(reads['root_first_word']['physical'],0x40072c000)
        self.assertEqual(reads['init_mm_pgd']['physical'],0x40069ec38)
        self.assertEqual(sum(r['bytes'] for r in reads.values()),96)

    def test_invalid_resources(self):
        values=[b'',IOMEM.replace(b'System RAM',b'reserved'),IOMEM.replace(b'Kernel code',b'Other code'),
            IOMEM+IOMEM.splitlines(keepends=True)[0],IOMEM.replace(b'  400680000',b'    400680000'),
            IOMEM.replace(b'40062ffff',b'400630000'),IOMEM.replace(b'40072efff',b'40072dfff'),
            IOMEM.replace(b'400680000-40072efff',b'400690000-40073efff'),
            IOMEM.replace(b'400000000-47fffffff',b'00000000-00000000'),
            IOMEM.replace(b'400000000-47fffffff',b'400000001-47fffffff'),
            IOMEM+b'  400680000-40072efff : Kernel data\n',
            IOMEM.replace(b'  400680000-40072efff',b'  500680000-50072efff')]
        for raw in values:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):bootstrap_plan(raw,SYMBOLS,BOOT)

    def test_invalid_symbols(self):
        first=SYMBOLS.splitlines(keepends=True)[0]
        values=[b'',SYMBOLS+first,SYMBOLS[len(first):],SYMBOLS.replace(b'ffffff8008080000',b'0000000000000000'),
            SYMBOLS.replace(b'_text\n',b'_text [foreign]\n'),SYMBOLS.replace(b'_end\n',b'other\n'),
            SYMBOLS.replace(b'ffffff800872c000',b'ffffff800872d000'),b'x'*4097]
        for raw in values:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):bootstrap_plan(IOMEM,raw,BOOT)

    def test_invalid_boot(self):
        for raw in (b'',BOOT[:-1],BOOT.upper(),BOOT+b'\0',b'not-a-boot-id\n'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):bootstrap_plan(IOMEM,SYMBOLS,raw)


if __name__=='__main__':unittest.main()
