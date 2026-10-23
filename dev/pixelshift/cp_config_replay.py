"""Replay native mode dispatch and its later native capture-configuration copy.

The same emulator RAM carries the dispatched mode into the original snapshot
routine and ARM memcpy. Other LiRo fields, capture ID and snapshot arguments are
synthetic. The scheduler/caller between these entries is NOT executed. No driver,
positioning, capture, saved setting or hardware completion is emulated.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_dispatch_replay import _dispatch, profile as dispatch_profile
from trinity_replay import configure


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, dispatcher = dispatch_profile(directory)
    target = dispatcher['dispatcher'] == 0x35cf70
    entry = 0xb0e074 if target else 0xb0ded2
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    code = list(md.disasm(data[entry - 0x108000:entry - 0x108000 + 0xc4], entry))
    low = next(i for i in code if i.mnemonic == 'movw' and i.op_str.startswith('r4, #'))
    high = next(i for i in code if i.mnemonic == 'movt' and i.op_str.startswith('r4, #'))
    root = int(low.op_str.split('#')[1], 0) | (int(high.op_str.split('#')[1], 0) << 16)
    calls = [int(i.op_str.lstrip('#'), 0) for i in code if i.mnemonic in ('bl', 'blx')]
    if len(calls) != 4 or calls[0] != dispatcher['trace']:
        raise ValueError('Native capture configuration snapshot routine changed')
    if not any(i.mnemonic == 'movw' and i.op_str == 'r2, #0xd64' for i in code):
        raise ValueError('Native capture configuration copy length changed')
    return data, dict(entry=entry, root=root, copy=calls[1], predicates=calls[2:])


def _snapshot(directory, *, mode, test=0, seed=0, source_initializer=None, snapshot_runner=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
    packet = configure(directory, mode=mode, test=test)['packet']
    cpu, d, dispatch_result = _dispatch(directory, packet, source_id=0x80020002)
    data, p = profile(directory)
    root, source = p['root'], d['parameter'] - 0x180
    mapped = {page for begin, end, _ in cpu.mem_regions() for page in range(begin, end + 1, 4096)}
    for begin, end in ((source, source + 0xd64), (root, root + 0xe00)):
        for page in range(begin & ~4095, (end + 4095) & ~4095, 4096):
            if page not in mapped:
                cpu.mem_map(page, 4096)
                mapped.add(page)
    # Initialize unrelated synthetic fields, leaving the handler-written mode
    # bytes untouched. No second host assignment supplies the propagated mode.
    synthetic = bytes((index * 37 + seed) & 255 for index in range(0xd64))
    cpu.mem_write(source, synthetic[:0x180])
    cpu.mem_write(source + 0x184, synthetic[0x184:])
    if source_initializer is not None:
        source_initializer(cpu, p, d, source)
    before = bytes(cpu.mem_read(source, 0xd64))
    capture_id = 0x12345678
    cpu.mem_write(root, b'\xa5' * 0xe00)
    cpu.mem_write(root, struct.pack('<I', capture_id))
    stack, finish = 0x3000f000, 0x30002000
    cpu.mem_write(stack, struct.pack('<II', 4, 0x87654321))
    cpu.reg_write(UC_ARM_REG_R0, capture_id)
    cpu.reg_write(UC_ARM_REG_R1, source)
    cpu.reg_write(UC_ARM_REG_R2, 1 if snapshot_runner is None else 0xa5a5a5a5)
    cpu.reg_write(UC_ARM_REG_R3, 0)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    result = dict(native_copy_executed=False, mode_dispatch=dispatch_result,
                  scheduler_between_entries_executed=False,
                  unrelated_configuration_synthetic=True, capture_executed=False,
                  physical_shift_verified=False)
    regions = [(p['entry'], p['entry'] + 0xc4), (p['copy'], p['copy'] + 0x300),
               (p['predicates'][0], p['predicates'][0] + 0x22),
               (p['predicates'][1], p['predicates'][1] + 0x30)]

    def hook(uc, address, size, unused):
        if snapshot_runner is None and not any(begin <= address < end for begin, end in regions):
            raise ValueError('Snapshot routine reached unhandled native code: ' + hex(address))
        if address == p['copy']:
            if (uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1), uc.reg_read(UC_ARM_REG_R2)) != (root + 0x28, source, 0xd64):
                raise ValueError('Unexpected native memcpy arguments')
            result['native_copy_executed'] = True

    def write_hook(uc, access, address, size, value, unused):
        if snapshot_runner is not None:
            return  # The original-caller continuation owns its inspected write boundaries.
        if 0x30008000 <= address and address + size <= stack:
            return
        if root + 0x28 <= address and address + size <= root + 0xd8c:
            return
        if root + 0xd90 <= address and address + size <= root + 0xd9d:
            return
        raise ValueError('Snapshot routine changed unrelated state: ' + hex(address))

    code_hook = cpu.hook_add(UC_HOOK_CODE, hook)
    memory_hook = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    stop = finish
    if snapshot_runner is None:
        cpu.emu_start(p['entry'] | 1, finish, count=10000)
    else:
        stop = snapshot_runner(cpu, p, d, source, capture_id, stack)
    if (cpu.reg_read(UC_ARM_REG_PC) != stop or not result['native_copy_executed']
            or bytes(cpu.mem_read(root + 0x28, 0xd64)) != before
            or bytes(cpu.mem_read(source, 0xd64)) != before
            or bytes(cpu.mem_read(root + 4, 0x24)) != b'\xa5' * 0x24
            or bytes(cpu.mem_read(root + 0xd8c, 4)) != b'\xa5' * 4):
        raise ValueError('Native snapshot copy failed its byte comparison')
    propagated = struct.unpack('<I', cpu.mem_read(root + 8 + 0x1a0, 4))[0]
    if propagated != dispatch_result['mode']:
        raise ValueError('Capture configuration did not retain the dispatched TRINITY mode')
    cpu.hook_del(code_hook)
    cpu.hook_del(memory_hook)
    return cpu, p, d, dict(result, copied_bytes=0xd64, capture_configuration_trinity=propagated,
                           source_field='0x180', destination_field='0x1a0', configuration_snapshot_equal=True)


def snapshot(directory, *, mode, test=0, seed=0):
    return _snapshot(directory, mode=mode, test=test, seed=seed)[3]


def compare(c2, reference):
    cases = []
    for args in (dict(mode=0), dict(mode=1), dict(mode=2), dict(mode=1, test=1)):
        for seed in (0, 255):
            values = dict(args, seed=seed)
            a, b = snapshot(c2, **values), snapshot(reference, **values)
            if a != b:
                raise ValueError('C2/A7CR native mode-to-configuration copy differs')
            cases.append(dict(input=values, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-config/1', camera_io=False, installable=False,
                physical_shift_verified=False, paired_cases=len(cases), cases=cases)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
