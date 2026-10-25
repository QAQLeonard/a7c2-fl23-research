"""Build offline integer-only component ELFs, never execute or deploy them.

Keep optimization, debug information and symbol binding explicit: these
settings differ between existing fixtures and affect reproducible evidence.
Target-libc ABI objects use a separate compile-only path in aarch64_abi.py.
"""

import subprocess

from .elf import codegen_flags

TARGETS = {"aarch64": "aarch64-linux-gnu", "thumb": "thumb-linux-gnueabi"}


def compile_shared(zig, arch, output, sources, *, optimization="-Oz", debug=True,
                   symbolic=True, extra_flags=()):
    command = [
        str(zig), "cc", "-target", TARGETS[arch], *codegen_flags(arch), optimization, *extra_flags,
        *(["-g"] if debug else []), "-shared", "-fPIC", "-ffreestanding",
        "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables", "-nostdlib",
        "-Wl,--no-undefined" + (",-Bsymbolic" if symbolic else ""),
        "-o", str(output), *map(str, sources),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
