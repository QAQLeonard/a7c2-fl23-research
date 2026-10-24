"""Fix SciPy arm64 zero-fill section offsets before final app signing.

SciPy 1.16.3 PROPACK wheels have nonzero __thread_bss file offsets rejected
by recent dyld. Zero-fill sections have no file payload. Only offset fields
change; section addresses/sizes, code and numerical data are preserved.
"""
from pathlib import Path
import struct
import subprocess

ZERO_FILL = {0x01, 0x0c, 0x12}


def normalize(data):
    """Return corrected Mach-O 64 little-endian bytes and changed sections."""
    if len(data) < 32 or data[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('Expected a little-endian Mach-O 64 library')
    commands, command_bytes = struct.unpack_from('<II', data, 16)
    end = 32 + command_bytes
    if end > len(data) or commands > command_bytes // 8:
        raise ValueError('Invalid Mach-O load-command extent')
    patches = []
    offset = 32
    for _ in range(commands):
        if offset + 8 > end:
            raise ValueError('Truncated Mach-O load command')
        command, size = struct.unpack_from('<II', data, offset)
        if size < 8 or offset + size > end:
            raise ValueError('Invalid Mach-O load-command size')
        if command == 0x19:
            if size < 72:
                raise ValueError('Truncated Mach-O segment')
            sections = struct.unpack_from('<I', data, offset + 64)[0]
            if 72 + sections * 80 > size:
                raise ValueError('Truncated Mach-O section table')
            for index in range(sections):
                section = offset + 72 + index * 80
                kind = struct.unpack_from('<I', data, section + 64)[0] & 0xff
                file_offset = struct.unpack_from('<I', data, section + 48)[0]
                if kind in ZERO_FILL and file_offset:
                    name = data[section:section+16].split(b'\0')[0].decode('ascii')
                    segment = data[section+16:section+32].split(b'\0')[0].decode('ascii')
                    patches.append(dict(field=section+48, section=segment+'/'+name,
                                        old_offset=file_offset, section_type=kind))
        offset += size
    if offset != end:
        raise ValueError('Mach-O load-command count/extent differs')
    result = bytearray(data)
    for patch in patches:
        struct.pack_into('<I', result, patch['field'], 0)
    return bytes(result), patches


def prepare_scipy(app):
    """Repair affected extensions, re-sign them and then re-sign the app."""
    app = Path(app)
    libraries = sorted((app/'Contents/Frameworks/scipy').rglob('*.so'))
    if not libraries:
        raise ValueError('Bundled SciPy native extensions were not found')
    changed = []
    for library in libraries:
        after, patches = normalize(library.read_bytes())
        if patches:
            library.write_bytes(after)
            subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(library)],check=True)
            changed.append(dict(path=library.relative_to(app).as_posix(),sections=patches))
    if changed:
        subprocess.run(['codesign','--force','--deep','--sign','-','--timestamp=none',str(app)],check=True)
    for library in libraries:
        if normalize(library.read_bytes())[1]:
            raise ValueError('Invalid zero-fill section remains: '+str(library))
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    return dict(native_libraries_checked=len(libraries),repaired=changed)
