"""Fault-injected execution of the compiled fixed sound-file worker, offline.

File/mount/model state is synthetic. These cases verify transaction ordering,
owned-file rollback and read-only remount; no live disk or firmware is touched.
"""
import argparse
import json
from pathlib import Path
import struct

from files_worker import parse
from verify_probe import execute


PATHS = ('/usr/share/avsystemsound/custom-shutter.bin',
         '/usr/share/avsystemsound/custom.txt')
DIRECTORY = '/usr/share/avsystemsound'
REQUEST = '/tmp/jiritsu/a7c2.install.request'


def case(worker, ap, audio, csv, mode, fault='none'):
    data = {p: bytes(b) for p, b in zip(PATHS, (audio, csv))} if mode == 2 else {}
    untouched = b'UNRELATED_NATIVE_SOUND'
    data[DIRECTORY + '/SysSound.bin'] = untouched
    if fault == 'conflict':
        data[PATHS[0]] = b'EXISTING_USER_FILE'
    inodes = {p: 100 + i for i, p in enumerate(data)}
    handles, events, injected = {}, [], set()
    readonly = [fault != 'initial_rw']
    request = struct.pack('<8sII', b'A7SFQ001', mode, 0)
    if fault == 'long_request':
        request += b'X'

    def string(cpu, at):
        return bytes(cpu.mem_read(at, 256)).split(b'\0', 1)[0].decode()

    def syscall(cpu, no, a):
        if no == 56:
            path, flags = string(cpu, a[1]), a[2]
            if path not in (*PATHS, DIRECTORY, REQUEST, '/proc/mounts'):
                return None
            if path in PATHS and flags == 0x880c1:
                assert not readonly[0]
                if fault in ('create_second', 'rollback_unlink', 'foreign_inode') and path == PATHS[1]:
                    if fault == 'foreign_inode':
                        inodes[PATHS[0]] += 999
                    return -13
                if path in data:
                    return -17
                data[path] = b''
                inodes[path] = 500 + len(inodes)
                events.append(['create', path])
            elif path in PATHS:
                assert flags == 0x88000
                if path not in data:
                    return -2
            elif path == DIRECTORY:
                assert flags == 0x8c000
            else:
                assert not flags
            fd = 1000 + len(handles)
            handles[fd] = {'path': path, 'position': 0, 'closed': False, 'flags': flags}
            return fd
        if no == 40:
            assert string(cpu, a[1]) == '/usr'
            wanted_ro = bool(a[3] & 1)
            readonly[0] = wanted_ro
            events.append(['remount', 'ro' if wanted_ro else 'rw'])
            if fault == 'mount_rw' and not wanted_ro:
                return -5
            if fault == 'mount_ro' and wanted_ro:
                return -5
            return 0
        if no == 35:
            path = string(cpu, a[1])
            if path not in PATHS:
                return None
            assert not readonly[0]
            if fault == 'rollback_unlink':
                return -5
            if path not in data:
                return -2
            del data[path]
            events.append(['unlink', path])
            return 0
        if not a or a[0] not in handles:
            return None
        h = handles[a[0]]
        assert not h['closed']
        path = h['path']
        if no == 57:
            h['closed'] = True
            return 0
        if no == 80:
            st = bytearray(128)
            struct.pack_into('<QQI', st, 0, 15, inodes[path], 0o100644)
            struct.pack_into('<q', st, 48, len(data[path]))
            cpu.mem_write(a[1], bytes(st))
            return 0
        if no == 63:
            if path == REQUEST:
                value = request
            elif path == '/proc/mounts':
                value = b'/dev/nflasha15 /usr ext2 ' + (b'ro' if readonly[0] else b'rw') + b',sync 0 0\n'
            else:
                value = data[path]
            value = value[h['position']:h['position'] + a[2]]
            h['position'] += len(value)
            if fault == 'readback' and path in PATHS and value and 'readback' not in injected:
                value = bytes([value[0] ^ 1]) + value[1:]
                injected.add('readback')
            cpu.mem_write(a[1], value)
            return len(value)
        if no == 64:
            assert path in PATHS and not readonly[0] and h['flags'] == 0x880c1
            count = a[2]
            if fault == 'partial_write':
                if 'short' in injected:
                    return -5
                injected.add('short')
                count //= 2
            value = bytes(cpu.mem_read(a[1], count))
            pos = h['position']
            data[path] = data[path][:pos] + value + data[path][pos + count:]
            h['position'] += count
            events.append(['write', path, count])
            return count
        if no == 82:
            if fault == 'fsync' and path in PATHS and 'fsync' not in injected:
                injected.add('fsync')
                return -5
            return 0
        raise ValueError('Unexpected sound-file syscall ' + str(no))

    result = execute(worker, ap, 'model' if fault == 'model' else 'none',
                     decode=parse, extra_syscall=syscall)
    assert all(h['closed'] for h in handles.values())
    assert data[DIRECTORY + '/SysSound.bin'] == untouched
    expected_success = fault == 'none'
    if result['native_success'] != expected_success:
        raise ValueError('Native worker promoted a failed sound-file transaction')
    if expected_success:
        assert readonly[0]
        for path, value in zip(PATHS, (audio, csv)):
            assert data.get(path) == (value if mode == 1 else None)
        if mode == 2:
            assert [e[1] for e in events if e[0] == 'unlink'] == [PATHS[1], PATHS[0]]
    elif fault in ('conflict', 'model', 'long_request', 'initial_rw'):
        assert not events
    elif fault not in ('rollback_unlink', 'foreign_inode', 'mount_ro'):
        assert readonly[0] and not any(p in data for p in PATHS)
    if fault == 'foreign_inode':
        assert PATHS[0] in data and result['rollback'] == -116
    if fault == 'rollback_unlink':
        assert PATHS[0] in data and result['rollback'] == -5
    return {'mode': mode, 'fault': fault, 'result': result,
            'events': events, 'final_usr_readonly': readonly[0]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker', type=Path, required=True)
    p.add_argument('--ap', type=Path, required=True)
    p.add_argument('--native-bin', type=Path, required=True)
    p.add_argument('--csv', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    ap, audio, csv = a.ap.read_bytes(), a.native_bin.read_bytes(), a.csv.read_bytes()
    jobs = [(mode, 'none') for mode in (0, 1, 2)] + [(1, fault) for fault in
        ('conflict', 'create_second', 'partial_write', 'readback', 'fsync', 'mount_rw',
         'mount_ro', 'rollback_unlink', 'foreign_inode', 'model', 'initial_rw', 'long_request')]
    results = [case(a.worker, ap, audio, csv, mode, fault) for mode, fault in jobs]
    with a.output.open('x', encoding='utf-8') as f:
        json.dump({'compiled_sound_files_cases': len(results), 'camera_io': False, 'cases': results}, f, indent=2)
        f.write('\n')
    print('Compiled sound-file transaction:', len(results), 'offline cases passed')


if __name__ == '__main__':
    main()
