"""Run compiled sound preflight ELF against synthetic AP process memory.

Only read syscalls to fixed process sources and writes to its two temporary
reports are allowed. This tests the compiled reader, not live AP table contents.
"""
import argparse
import json
from pathlib import Path
import struct

from candidate import parse_probe, require_registry
from verify_worker import load


def execute(worker, ap, fault='none', *, extra_headers=None, setup_native=None,
            decode=None, extra_syscall=None, allow_device_mapping=False,
            extra_outputs=None, result_path='/tmp/jiritsu/shutter.probe.result'):
    from unicorn import UC_HOOK_INTR
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X8, UC_ARM64_REG_PC
    cpu, start, end = load(worker)
    base = 0x400000000
    maps = (f'{base:x}-{base + 0x51a7000:x} r-xp 00000000 00:01 1 /usr/lib/appFw.so\n'
            f'{base + 0x51b7000:x}-{base + 0x9800000:x} rw-p 051a7000 00:01 1 /usr/lib/appFw.so\n').encode()
    files = {'/proc/self/maps': maps, '/proc/mounts': b'/dev/nflasha15 /usr ext2 ro,sync 0 0\n',
             '/proc/self/cmdline': b'/usr/bin/app\0', '/sys/power/image_mode': b'2\n',
             '/tmp/jiritsu/libJit.so': b'owned'}
    headers = {0x286cde8: ap[0x286cde8:0x286cdfc], 0x2885488: ap[0x2885488:0x288549c],
               0x5bc35b0: struct.pack('<I', 0 if fault == 'model' else 16),
               0x7e735b8: struct.pack('<I', 0)}
    for i in range(25):
        row = bytearray(176); row[0] = 6; row[1] = i + 1 if i < 3 else 4
        struct.pack_into('<Q', row, 16, 1216)
        struct.pack_into('<Q', row, 32, 0x405000000)
        headers[0x7ed2098 + 176 * i] = bytes(row)
    if fault == 'getter': headers[0x2885488] = bytes(20)
    if extra_headers:
        headers.update(extra_headers)
    if fault == 'kind':
        row = bytearray(headers[0x7ed2098 + 176 * 2]); row[1] = 4
        headers[0x7ed2098 + 176 * 2] = bytes(row)
    handles, reads = {}, []
    outputs = ('/tmp/jiritsu/a7c2.probe.result', '/tmp/jiritsu/shutter.probe.result')
    output_flags = dict.fromkeys(outputs, 0x241)
    output_flags.update(extra_outputs or {})
    def string(at):
        out = bytearray()
        for i in range(1024):
            v = bytes(cpu.mem_read(at + i, 1))
            if v == b'\0': return out.decode('ascii')
            out += v
        raise AssertionError('Unterminated path')
    def syscall(uc, number, user):
        no = uc.reg_read(UC_ARM64_REG_X8)
        a = [uc.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3)]
        result = 0
        supplied = extra_syscall(uc, no, a) if extra_syscall else None
        if supplied is not None: result = supplied
        elif no == 175: result = 1000 if fault == 'nonroot' else 0
        elif no == 172: result = 45
        elif no == 35:
            assert string(a[1]) == '/tmp/jiritsu/libJit.so'
            files.pop('/tmp/jiritsu/libJit.so')
        elif no == 56:
            path, flags = string(a[1]), a[2]
            if path in output_flags:
                assert flags == output_flags[path]; files[path] = bytearray()
            elif allow_device_mapping and path == '/dev/mem': assert flags == 0x101002
            else: assert flags == 0 and path in (*files, '/proc/self/mem')
            result = 10 + len(handles); handles[result] = [path, 0, False]
        elif no in (63, 67):
            path, pos, closed = handles[a[0]]; assert not closed
            if path == '/proc/self/mem':
                assert no == 67 and a[3] >= base
                at = a[3] - base; assert at in headers
                data = headers[at]; assert 0 < a[2] <= len(data);data=data[:a[2]]
                reads.append(at)
                if fault == 'short' and at == 0x7e735b8: data = data[:-1]
            else:
                assert no == 63; data = files[path][pos:pos + a[2]]
                handles[a[0]][1] += len(data)
            uc.mem_write(a[1], bytes(data)); result = len(data)
        elif no == 64:
            path, _, closed = handles[a[0]]; assert path in output_flags and not closed
            files[path].extend(bytes(uc.mem_read(a[1], a[2]))); result = a[2]
        elif no == 82: assert handles[a[0]][0] in output_flags
        elif no == 57: handles[a[0]][2] = True
        else: raise AssertionError('Forbidden read-only-probe syscall: ' + str(no))
        uc.reg_write(UC_ARM64_REG_X0, result & ((1 << 64) - 1))
    cpu.hook_add(UC_HOOK_INTR, syscall)
    if setup_native:
        setup_native(cpu, base)
    cpu.emu_start(start, end, count=4000000)
    assert cpu.reg_read(UC_ARM64_REG_PC) == end
    assert all(h[2] for h in handles.values())
    raw = bytes(files[result_path])
    if decode:
        return decode(raw)
    if fault in ('none', 'kind'):
        result = parse_probe(raw)
        if fault == 'kind':
            try: require_registry(result)
            except ValueError: pass
            else: raise AssertionError('Wrong registry binding accepted')
        else: require_registry(result)
    else:
        try: parse_probe(raw)
        except ValueError: pass
        else: raise AssertionError('Failed native reader accepted')
        assert not any(at >= 0x7ed2098 for at in reads)
    return {'fault': fault, 'native_status': struct.unpack_from('<q', raw, 16)[0], 'fixed_memory_reads': len(reads)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker', required=True, type=Path)
    p.add_argument('--ap', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    ap = a.ap.read_bytes()
    rows = [execute(a.worker, ap, fault) for fault in ('none', 'model', 'getter', 'short', 'nonroot', 'kind')]
    result = {'compiled_reader_cases': len(rows), 'camera_io': False,
              'actual_loaded_sound_registry_tested': False, 'cases': rows}
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2); f.write('\n')
    print('Compiled read-only preflight:', len(rows), 'offline cases passed')


if __name__ == '__main__': main()
