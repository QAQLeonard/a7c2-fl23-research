"""Build a freestanding ARM64 core library offline; default is the mean kernel."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def build(destination, zig=None, *, source=None, entry='a7_average_u8'):
    from elftools.elf.elffile import ELFFile

    compiler = zig or os.environ.get('A7C2_ZIG') or shutil.which('zig')
    if not compiler:
        raise ValueError('Supply --zig or set A7C2_ZIG to the Zig executable')
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [str(compiler), 'cc', '-target', 'aarch64-linux-gnu', '-shared',
               '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-ffreestanding',
               '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
               '-fno-asynchronous-unwind-tables', '-nostdlib', '-g0',
               '-Wl,--no-undefined', '-Wl,-Bsymbolic', '-Wl,-z,noexecstack',
               str(source or ROOT / 'src/double_exposure/native/average.c'),
               '-o', str(destination)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180,
                            creationflags=0x08000000 if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('Native mean compilation failed:\n' + result.stderr)
    with destination.open('rb') as source:
        elf = ELFFile(source)
        if elf['e_machine'] != 'EM_AARCH64' or elf['e_type'] != 'ET_DYN':
            raise ValueError('Expected an AArch64 shared library')
        dynamic = elf.get_section_by_name('.dynamic')
        if any(tag.entry.d_tag in ('DT_NEEDED', 'DT_INIT', 'DT_INIT_ARRAY')
               for tag in dynamic.iter_tags()):
            raise ValueError('Mean library must have no dependencies/startup code')
        symbols = list(elf.get_section_by_name('.dynsym').iter_symbols())
        if any(symbol.name and symbol['st_shndx'] == 'SHN_UNDEF'
               for symbol in symbols):
            raise ValueError('Unexpected external symbol')
        if not any(symbol.name == entry and
                   symbol['st_info']['type'] == 'STT_FUNC' for symbol in symbols):
            raise ValueError('Missing native function: ' + entry)
        if any(section['sh_type'] in ('SHT_RELA', 'SHT_REL') and section.num_relocations()
               for section in elf.iter_sections()):
            raise ValueError('Unexpected library relocation')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output, args.zig))
