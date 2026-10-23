"""Fresh RPC-context generated-code MODELS. No camera or native send.

Models transport syscalls and remote outcomes explicitly; a modeled accepting
gate is not live scheduling/lifetime admission. Uses original allocator header
bytes and independent AArch64 ABI extraction.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.aarch64_abi import context_abi
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP
from support.uipc import original_header

STATE, WORK, SCALL, IOCTL, GATE = MEM, MEM+0x400, 0x22000000, 0x21000000, 0x23000000
SHARED, MESSAGE, NONCE = 0x60000000, 0x60001040, 0x73693203
CONTEXT_BYTES, RESULT_BYTES = 248, 360


def model(elf, header, abi, kind):
    # Page-aligned map can overlap only the RPC tail, leaving the old
    # 248-byte context untouched. Exercise the complete 360-byte extent.
    STATE = MEM+0xf00 if kind == 'rpc-tail-map-overlap' else MEM
    u, symbols = image_loader(elf, 'aarch64', ('precapture_rpc_context_once',))
    if kind == 'rpc-tail-map-overlap': u.mem_map(MEM+0x1000, 4096)
    for at in (SCALL, IOCTL, GATE):
        u.mem_map(at, 4096)
    u.mem_write(STATE, bytes(RESULT_BYTES))
    u.mem_write(WORK, b'\xa5'*256)
    if kind == 'used-context': u.mem_write(STATE+247, b'\1')
    if kind == 'used-rpc': u.mem_write(STATE+359, b'\1')
    initial = bytes(u.mem_read(STATE, RESULT_BYTES))
    calls, gates, source = [], [], 0x803f6112
    if kind == 'different-fresh-source': source = 0x803f6223
    if kind == 'invalid-source': source = 0x80020005
    if kind == 'zero-source': source = 0
    mapped = False

    def word(at): return struct.unpack('<I', bytes(u.mem_read(at, 4)))[0]
    def ret(value):
        for i in range(1, 18): u.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), 0xde000000+i)
        u.reg_write(R.UC_ARM64_REG_X0, value & ((1 << 64)-1))
        u.reg_write(R.UC_ARM64_REG_PC, u.reg_read(R.UC_ARM64_REG_LR))
    def text(p): return bytes(u.mem_read(p, 160)).split(b'\0', 1)[0].decode()
    def stat(p):
        raw = bytearray(abi['stat_bytes'])
        for name, value, size in (('mode_offset', abi['char_type']|0o600, 4),
                ('dev_offset', 11, 8), ('inode_offset', 22, 8), ('rdev_offset', 33, 8)):
            struct.pack_into('<I' if size == 4 else '<Q', raw, abi[name], value)
        u.mem_write(p, bytes(raw))
    def hook(cpu, at, size, _):
        nonlocal mapped
        if at not in (SCALL, IOCTL, GATE): return
        if at == GATE:
            stage, context = (u.reg_read(r) for r in (R.UC_ARM64_REG_X0, R.UC_ARM64_REG_X1))
            assert context == WORK+0x200 and stage == len(gates)+1
            assert word(STATE+4) == 2 and word(STATE+44) == 1
            assert word(STATE+248+100) == source
            gates.append(stage)
            if stage == 2:
                assert bytes(u.mem_read(MESSAGE-16, 44)) == header[48:92]
            ret(-117 if kind == f'gate-{stage}-unknown' else
                -95 if kind == f'deny-{stage}' or kind == 'deny-cancel-error' and stage == 2 else 0)
            return
        if at == SCALL:
            assert word(STATE+4) == 2 and word(STATE+44) == 1
            nr, *a = [u.reg_read(getattr(R, f'UC_ARM64_REG_X{i}')) for i in range(7)]
            calls.append(('sys', nr))
            assert nr in [abi[k] for k in ('nr_statat','nr_openat','nr_stat','nr_mmap','nr_munmap','nr_close')]
            if nr == abi['nr_statat']:
                assert a[0] == (-100 & ((1 << 64)-1)) and text(a[1]) == '/dev/uipc'
                assert a[2:] == [WORK, abi['at_nofollow'], 0, 0]
                if kind == 'path-error': ret(-2); return
                stat(a[2]); ret(0)
            elif nr == abi['nr_openat']:
                assert text(a[1]) == '/dev/uipc' and a[2:] == [abi['rdwr_flags'], 0, 0, 0]
                ret(-13 if kind == 'open-error' else 77)
            elif nr == abi['nr_stat']:
                assert a == [77, WORK+128, 0, 0, 0, 0]
                stat(a[1]); ret(-5 if kind == 'fd-error' else 0)
            elif nr == abi['nr_mmap']:
                assert a == [0, 0x200000, abi['prot_rw'], abi['map_shared'], 77, 0]
                if kind == 'map-error': ret(-12); return
                if kind == 'rpc-tail-map-overlap': ret(MEM+0x1000); return
                u.mem_map(SHARED, 0x200000); mapped = True
                u.mem_write(MESSAGE-64, header)
                if kind == 'bad-header': u.mem_write(MESSAGE-8, struct.pack('<I', 23))
                ret(SHARED)
            elif nr == abi['nr_munmap']:
                assert a == [SHARED, 0x200000, 0, 0, 0, 0] and mapped
                assert word(STATE+248+12) == 0
                if kind == 'unmap-error': ret(-22); return
                u.mem_unmap(SHARED, 0x200000); mapped = False; ret(0)
            else:
                assert nr == abi['nr_close'] and a == [77, 0, 0, 0, 0, 0]
                assert not mapped
                ret(-4 if kind == 'close-error' else 0)
            return
        fd, command, arg = [u.reg_read(r) for r in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
        calls.append(('ioctl', command)); assert fd == 77
        route, pad, ptr = struct.unpack('<IIQ', bytes(u.mem_read(arg, 16))); assert pad == 0
        if command == 0x80000010:
            assert route == 0 and ptr == STATE+152
            if kind == 'query-error': ret(-1021); return
            u.mem_write(ptr, struct.pack('<4I', 0x200000, 0x80000, 0x20000, source)); ret(0)
        elif command == 0x8000000a:
            assert route == 0x908f084b and gates == [1]
            output, count, wait = struct.unpack('<QII', bytes(u.mem_read(ptr, 16)))
            assert (count, wait) == (24, 0)
            if kind == 'allocate-rejected': ret(-1023); return
            u.mem_write(output, struct.pack('<Q', MESSAGE))
            ret(-5 if kind == 'allocate-unknown' else 0)
        elif command == 0x80000005:
            assert route == 0x908f084b and gates == [1, 2]
            message, callback, context = struct.unpack('<3Q', bytes(u.mem_read(ptr, 24)))
            assert (message, callback, context) == (MESSAGE, 0, 0)
            expected = bytearray(24); expected[0] = 0xe1; struct.pack_into('<I', expected, 20, NONCE)
            assert bytes(u.mem_read(MESSAGE, 24)) == expected and word(MESSAGE-12) == source
            assert word(STATE+248+24) == 1
            if kind != 'unchanged-reply':
                expected[1] = 0x80
                if kind == 'bad-reply': expected[12] = 1
                u.mem_write(MESSAGE, bytes(expected))
            if kind == 'callback': u.mem_write(ptr+8, struct.pack('<Q', 0x1234))
            ret(-5 if kind == 'send-error' else 0)
        else:
            assert command == 0x8000000b and route == 0x908f084b and ptr == MESSAGE
            if kind in ('deny-2', 'deny-cancel-error'):
                assert bytes(u.mem_read(MESSAGE-16, 44)) == header[48:92]
                assert word(STATE+248+24) == 0
            ret(-5 if kind in ('release-error', 'deny-cancel-error') else 0)

    u.hook_add(UC_HOOK_CODE, hook)
    args = [STATE, WORK, NONCE, SCALL, IOCTL, GATE, WORK+0x200]
    invalid = {'null-result': (0, 0), 'null-work': (1, 0), 'tail-work-overlap': (1, STATE+248),
        'zero-nonce': (2, 0), 'null-syscall': (3, 0), 'null-ioctl': (4, 0),
        'null-gate': (5, 0), 'null-gate-context': (6, 0)}
    if kind in invalid: i, value = invalid[kind]; args[i] = value
    def run():
        for i, value in enumerate(args): u.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
        u.reg_write(R.UC_ARM64_REG_SP, STACK+0x3000); u.reg_write(R.UC_ARM64_REG_LR, STOP)
        u.emu_start(symbols['precapture_rpc_context_once'], STOP, count=100000)
        assert u.reg_read(R.UC_ARM64_REG_PC) == STOP
        return u.reg_read(R.UC_ARM64_REG_X0) & 0xffffffff
    status = run(); raw = bytes(u.mem_read(STATE, RESULT_BYTES))
    if kind in invalid or kind.startswith('used-'):
        assert not calls and not gates and raw == initial
        assert status == (-16 if kind.startswith('used-') else -22) & 0xffffffff
    else:
        assert word(STATE+4) == 2 and word(STATE+44) == 1
        unknowns = ('rpc-tail-map-overlap','allocate-unknown','bad-header','send-error',
            'unchanged-reply','bad-reply','callback','release-error','deny-cancel-error','unmap-error','close-error',
            'gate-1-unknown','gate-2-unknown')
        if kind in unknowns:
            assert status == (-5 & 0xffffffff) and word(STATE+8) == 11 and word(STATE+12) == 3
            if kind not in ('unmap-error','close-error'):
                assert word(STATE+36) == 0 and word(STATE+40) == 0
        else:
            assert word(STATE+12) == 0 and not mapped
            expected = {'deny-1': -95, 'deny-2': -95, 'invalid-source': -84, 'zero-source': -84,
                'path-error': -2, 'open-error': -13, 'fd-error': -5, 'query-error': -1021,
                'map-error': -12, 'allocate-rejected': -5}.get(kind, 0)
            assert status == expected & 0xffffffff
            assert word(STATE+8) == (10 if expected else 9)
        if kind in ('deny-1','invalid-source','zero-source'): assert not word(STATE+248+20)
        if kind in ('deny-1','deny-2','deny-cancel-error','invalid-source','zero-source'):
            assert not word(STATE+248+24)
        if kind in ('default-reply','different-fresh-source'):
            assert word(STATE+248+100) == source and word(STATE+248+24) == 1
        before = list(calls), list(gates)
        assert run() == (-16 & 0xffffffff) and (calls, gates) == before
        assert bytes(u.mem_read(STATE, RESULT_BYTES)) == raw
    return dict(case=kind, calls=calls, gates=gates, status=status, models_only=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('zig','uipc-kernel','uipc','output'): p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=False)
    abi = context_abi(a.zig, a.output/'target-ABI')
    header, _ = original_header(a.uipc_kernel.read_bytes(), a.uipc.read_bytes(), payload_bytes=24)
    root = Path(__file__).parent
    sources = [root/name for name in ('ap_rpc_context.c','ap_rpc_probe_once.c')]
    elf = a.output/'NOT-INSTALLABLE-rpc-context.elf'
    compile_shared(a.zig, 'aarch64', elf, sources)
    kinds = ['default-reply','different-fresh-source','deny-1','deny-2','deny-cancel-error','gate-1-unknown','gate-2-unknown',
        'invalid-source','zero-source','path-error','open-error','fd-error','query-error','map-error',
        'rpc-tail-map-overlap','allocate-rejected','allocate-unknown','bad-header','send-error',
        'unchanged-reply','bad-reply','callback','release-error','unmap-error','close-error',
        'null-result','null-work','tail-work-overlap','zero-nonce','null-syscall','null-ioctl',
        'null-gate','null-gate-context','used-context','used-rpc']
    cases = [model(elf, header, abi, kind) for kind in kinds]
    pins = [*sources, root/'ap_rpc_context.h', root/'ap_ipc_transport.h', root/'ap_ipc_context.h',
            root/'ap_binding_guard.h', root/'ap_rpc_probe_once.h', Path(__file__)]
    report = dict(schema='OFFLINE_FRESH_RPC_CONTEXT_MODELS/1', cases=cases, camera_IO=False,
        live_gate=False, physical_send=False, source_from_fresh_info3=True, ABI=abi,
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in pins})
    (a.output/'report.private.json').write_text(json.dumps(report, indent=2)+'\n')
    print(len(cases), 'fresh RPC context models; no live gate or camera send')


if __name__ == '__main__': main()
