"""Build the standalone mean processor for camera Linux or the test host.

Requires a local libjpeg-turbo 3.1.2 source tree (upstream commit
4e151a4ad91001b3aa8c2ece2205c15f487ce320), Zig, CMake and Ninja.
No downloads, camera access, application hooks or firmware installation.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def run(command, log):
    result = subprocess.run([str(x) for x in command], capture_output=True,
                            encoding='utf-8', errors='replace', timeout=600,
                            creationflags=0x08000000 if os.name == 'nt' else 0)
    with log.open('a', encoding='utf-8') as stream:
        stream.write(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError('Native JPEG build failed:\n' + result.stdout[-2000:] + result.stderr[-6000:])


def build(source, output, *, target='camera', zig=None, cmake=None, ninja=None, jobs=4):
    if target == 'host' and platform.system() not in ('Windows', 'Linux'):
        raise ValueError('Host JPEG tests currently support Windows and Linux')
    source, output = Path(source).resolve(), Path(output).resolve()
    if 'set(VERSION 3.1.2)' not in (source / 'CMakeLists.txt').read_text(encoding='utf-8'):
        raise ValueError('Supply the libjpeg-turbo 3.1.2 source tree')
    programs = [zig or os.environ.get('A7C2_ZIG') or shutil.which('zig'),
                cmake or shutil.which('cmake'), ninja or shutil.which('ninja')]
    if not all(programs):
        raise ValueError('Supply Zig, CMake and Ninja paths')
    zig, cmake, ninja = [Path(p).resolve() for p in programs]
    arch = 'aarch64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64'
    triple = ('aarch64-linux-musl' if target == 'camera' else
              arch + ('-windows-gnu' if os.name == 'nt' else '-linux-musl'))
    output.mkdir(parents=True, exist_ok=True)
    codec = output / 'codec'
    wrappers = output / 'toolchain'
    wrappers.mkdir(exist_ok=True)
    scripts = {}
    for name, command in [('cc', f'cc -target {triple}'), ('ar', 'ar'), ('ranlib', 'ranlib')]:
        wrapper = wrappers / (name + ('.cmd' if os.name == 'nt' else '.sh'))
        if os.name == 'nt':
            wrapper.write_text(f'@echo off\n"{zig}" {command} %*\n', encoding='utf-8')
        else:
            import shlex
            wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(str(zig))} {command} "$@"\n',
                               encoding='utf-8')
            wrapper.chmod(0o755)
        scripts[name] = wrapper.as_posix()
    toolchain = wrappers / 'toolchain.cmake'
    system = 'Windows' if 'windows' in triple else 'Linux'
    toolchain.write_text('\n'.join([
        f'set(CMAKE_SYSTEM_NAME {system})',
        f'set(CMAKE_SYSTEM_PROCESSOR {triple.split("-")[0]})',
        f'set(CMAKE_C_COMPILER "{scripts["cc"]}")',
        f'set(CMAKE_AR "{scripts["ar"]}")',
        f'set(CMAKE_RANLIB "{scripts["ranlib"]}")',
        'set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)', '']), encoding='utf-8')
    log = output / 'build.private.log'
    run([cmake, '-S', source, '-B', codec, '-G', 'Ninja',
         '-DCMAKE_MAKE_PROGRAM=' + ninja.as_posix(),
         '-DCMAKE_TOOLCHAIN_FILE=' + toolchain.as_posix(),
         '-DCMAKE_BUILD_TYPE=Release', '-DENABLE_SHARED=OFF', '-DENABLE_STATIC=ON',
         '-DWITH_TURBOJPEG=OFF', '-DWITH_SIMD=OFF', '-DWITH_TESTS=OFF'], log)
    run([cmake, '--build', codec, '--target', 'jpeg-static', '--parallel', str(jobs)], log)
    libraries = [p for p in codec.glob('*') if p.name in ('libjpeg.a', 'jpeg-static.lib')]
    if len(libraries) != 1:
        raise ValueError('Expected one static JPEG library: ' + str(libraries))
    executable = output / ('a7c2-average.exe' if 'windows' in triple else 'a7c2-average')
    native = ROOT / 'src/double_exposure/native'
    run([zig, 'cc', '-target', triple, '-static', '-O2', '-g0', '-s', '-std=c11',
         '-Wall', '-Wextra', '-Werror', '-I', source / 'src', '-I', codec,
         native / 'average.c', native / 'jpeg_average.c', libraries[0],
         '-o', executable], log)
    if target == 'camera':
        from elftools.elf.elffile import ELFFile
        with executable.open('rb') as stream:
            elf = ELFFile(stream)
            if elf['e_machine'] != 'EM_AARCH64' or elf['e_type'] != 'ET_EXEC':
                raise ValueError('Expected camera ARM64 executable')
            if any(s['p_type'] in ('PT_INTERP', 'PT_DYNAMIC') for s in elf.iter_segments()):
                raise ValueError('Camera executable must be static')
    for original, name in [('README.ijg', 'libjpeg-turbo-README.ijg.txt'),
                           ('LICENSE.md', 'libjpeg-turbo-LICENSE.txt')]:
        shutil.copyfile(source / original, output / name)
    (output / 'NOTICE.txt').write_text(
        'This software is based in part on the work of the Independent JPEG Group.\n'
        'JPEG codec: unmodified libjpeg-turbo 3.1.2, https://libjpeg-turbo.org/\n'
        'Original mean processor: project LICENSE; codec retains its own license.\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'LICENSE', output / 'LICENSE')
    result = {'target': triple, 'executable': str(executable),
              'bytes': executable.stat().st_size, 'codec': 'libjpeg-turbo 3.1.2',
              'camera_io': False, 'camera_integration_verified': False}
    (output / 'build.private.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return executable


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', choices=('camera', 'host'), default='camera')
    for name in ('zig', 'cmake', 'ninja'):
        parser.add_argument('--' + name)
    parser.add_argument('--jobs', type=int, default=4)
    args = vars(parser.parse_args())
    print(build(**args))
