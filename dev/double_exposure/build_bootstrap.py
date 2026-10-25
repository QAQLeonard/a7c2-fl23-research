"""Build native control, staging or one-shot file entry helpers offline."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def build(output, *, target='camera', zig=None, harness=False, component='control'):
    if component not in ('control', 'staging', 'entry'):
        raise ValueError('Unknown helper component')
    if harness and target != 'camera':
        raise ValueError('The loader harness requires the camera ABI target')
    zig = zig or os.environ.get('A7C2_ZIG') or shutil.which('zig')
    if not zig:
        raise ValueError('Supply Zig')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    windows = target == 'host' and os.name == 'nt'
    if windows and component != 'control':
        raise ValueError('Native POSIX staging tests run on Linux or ARM64/QEMU')
    triple = 'aarch64-linux-gnu.2.25' if target == 'camera' else (
        'x86_64-windows-gnu' if windows else 'x86_64-linux-gnu')
    stem, entry, source = {
        'control': ('a7c2-bootstrap', 'a7_boot_dispatch', 'bootstrap.c'),
        'staging': ('a7c2-staging', 'a7_stage_execute', 'staging.c'),
        'entry': ('a7c2-file-entry', 'a7_file_entry_run', 'file_entry.c'),
    }[component]
    destination = output / (stem + ('.dll' if windows else '.so'))
    with tempfile.TemporaryDirectory(prefix='bootstrap-', dir=output) as scratch:
        temporary = Path(scratch) / destination.name
        flags = [] if windows else ['-ldl']
        command = [str(zig), 'cc', '-target', triple, '-shared', '-fPIC', '-O2', '-g0', '-s',
                   '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wl,--no-undefined',
                   '-Wl,-z,noexecstack'] if not windows else [
                       str(zig), 'cc', '-target', triple, '-shared', '-O2', '-g0', '-s',
                       '-std=c11', '-Wall', '-Wextra', '-Werror']
        if not windows:
            exports = Path(scratch) / 'exports.map'
            exports.write_text('{ global: ' + entry + '; local: *; };\n', encoding='ascii')
            command += ['-Wl,-Bsymbolic', '-Xlinker', '--version-script', '-Xlinker', str(exports)]
            if component == 'staging':
                command += ['-Wl,-soname,' + destination.name]
        sources = [ROOT / 'src/double_exposure/native' / source]
        if component == 'entry':
            sources.extend(ROOT / 'src/double_exposure/native' / name for name in ('staging.c', 'bootstrap.c'))
        command += [*map(str, sources), *flags, '-o', str(temporary)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180,
                                creationflags=0x08000000 if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError(result.stderr)
        if target == 'camera':
            from elftools.elf.elffile import ELFFile
            with temporary.open('rb') as stream:
                elf = ELFFile(stream)
                if elf['e_machine'] != 'EM_AARCH64' or elf['e_type'] != 'ET_DYN':
                    raise ValueError('Expected AArch64 shared library')
                exports = {s.name for s in elf.get_section_by_name('.dynsym').iter_symbols()
                           if s['st_info']['type'] == 'STT_FUNC' and s['st_shndx'] != 'SHN_UNDEF'}
                if exports != {entry}:
                    raise ValueError('Unexpected bootstrap exports')
                dynamic = elf.get_section_by_name('.dynamic')
                # Zig's normal GNU CRT supplies a small DT_INIT scaffold.
                # No project constructor or libJit _init entry is installed.
                if component != 'entry' and any(t.entry.d_tag == 'DT_INIT_ARRAY' for t in dynamic.iter_tags()):
                    raise ValueError('Unexpected bootstrap constructors')
                if component == 'entry' and not any(t.entry.d_tag == 'DT_INIT_ARRAY' for t in dynamic.iter_tags()):
                    raise ValueError('File entry constructor is missing')
                needed = {t.needed for t in dynamic.iter_tags('DT_NEEDED')}
                permitted = {'libc.so.6', 'libdl.so.2', 'ld-linux-aarch64.so.1'}
                if component != 'control':
                    permitted.add('libpthread.so.0')
                if not needed <= permitted:
                    raise ValueError('Unexpected dependencies: ' + str(sorted(needed)))
                versions = elf.get_section_by_name('.gnu.version_r')
                if versions:
                    for _, entries in versions.iter_versions():
                        for entry in entries:
                            if not entry.name.startswith('GLIBC_') or tuple(map(int, entry.name[6:].split('.'))) > (2, 25):
                                raise ValueError('Unsupported libc symbol version')
            if temporary.stat().st_size > 64 * 1024:
                raise ValueError('Bootstrap exceeds the legacy transport size ceiling')
        os.replace(temporary, destination)
        if harness and component == 'control':
            runner = Path(scratch) / 'a7c2-bootstrap-harness'
            result = subprocess.run([str(zig), 'cc', '-target', triple, '-O2', '-g0', '-s',
                                     '-std=c11', '-Wall', '-Wextra', '-Werror', '-I',
                                     str(ROOT / 'src/double_exposure/native'),
                                     str(ROOT / 'dev/double_exposure/bootstrap_harness.c'),
                                     '-ldl', '-o', str(runner)], capture_output=True, text=True,
                                    timeout=180, creationflags=0x08000000 if os.name == 'nt' else 0)
            if result.returncode:
                raise RuntimeError(result.stderr)
            os.replace(runner, output / runner.name)
        if harness and component == 'staging':
            native = ROOT / 'src/double_exposure/native'
            for fault in (False, True):
                runner = Path(scratch) / ('a7c2-staging-fault-harness' if fault else 'a7c2-staging-harness')
                sources = [str(ROOT / 'dev/double_exposure/staging_harness.c')]
                flags = ['-DA7_STAGE_TESTING', str(native / source)] if fault else [
                    str(destination), '-Wl,-rpath,$ORIGIN']
                result = subprocess.run([str(zig), 'cc', '-target', triple, '-O2', '-g0', '-s',
                                         '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(native),
                                         *sources, *flags, '-o', str(runner)], capture_output=True,
                                        text=True, timeout=180,
                                        creationflags=0x08000000 if os.name == 'nt' else 0)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                os.replace(runner, output / runner.name)
        if harness and component == 'entry':
            runner = Path(scratch) / 'a7c2-file-entry-harness'
            result = subprocess.run([str(zig), 'cc', '-target', triple, '-O2', '-g0', '-s',
                                     '-std=c11', '-Wall', '-Wextra', '-Werror', '-DA7_ENTRY_NO_AUTORUN',
                                     '-I', str(ROOT / 'src/double_exposure/native'),
                                     str(ROOT / 'dev/double_exposure/file_entry_harness.c'),
                                     *map(str, sources), '-ldl', '-o', str(runner)], capture_output=True,
                                    text=True, timeout=180, creationflags=0x08000000 if os.name == 'nt' else 0)
            if result.returncode:
                raise RuntimeError(result.stderr)
            os.replace(runner, output / runner.name)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', choices=('camera', 'host'), default='camera')
    parser.add_argument('--zig')
    parser.add_argument('--harness', action='store_true')
    parser.add_argument('--component', choices=('control', 'staging', 'entry'), default='control')
    print(build(**vars(parser.parse_args())))
