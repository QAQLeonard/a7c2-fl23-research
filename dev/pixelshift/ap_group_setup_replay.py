"""Native AP group-count/interval selection and TRINITY argument propagation.

Cached parameter inputs and post-admission caller objects are fixtures. Original
snapshot fragments, first-ordinal initialization, count/interval selection and
sequence-run argument packing execute. Actual argument bytes cross an explicit
dispatcher fixture into the existing original formatter and CP dispatcher.
No four-frame scheduler, saved-setting transaction, exposure or camera access.
"""
from functools import lru_cache
import argparse
import json
from pathlib import Path
import struct

from audit import audit
from native_replay import source
from trinity_replay import configure_arguments
from cp_dispatch_replay import _dispatch


@lru_cache(maxsize=2)
def profile(directory):
    image, info = source(directory)
    report = audit(directory)
    names = [r for r in report['debug_string_references'] if 'sequence_still_record::pixel_shift_multi_shoot_start_proc' in r['name']]
    if len(names) != 1 or not names[0]['code_references']:
        raise ValueError('Native start-procedure references are unavailable')
    reference = min(int(v, 16) for v in names[0]['code_references'])
    p = dict(cache=reference-0xbc, cache_end=reference-0x8c, first_ordinal=reference-0x84,
        select=reference+0x44, before_setup=reference+0x124)

    def branch(at):
        row = image.instructions(at, 4)[0]
        if not row.mnemonic.startswith('b'):
            raise ValueError('Native AP group branch changed')
        return int(row.op_str.lstrip('#'), 0)

    triples = image.instructions(p['cache'], 0x30)
    p['getters'] = []
    for index, field in enumerate((0xcd0, 0xcd4, 0xcd8, 0xcdc)):
        call, load, store = triples[index*3:index*3+3]
        if (call.mnemonic != 'bl' or load.op_str != 'w0, [x0]'
                or store.op_str != 'w0, [x19, #'+hex(field)+']'):
            raise ValueError('Original cached setting snapshot no longer matches the group selection')
        p['getters'].append(int(call.op_str.lstrip('#'), 0))
    rows = image.instructions(p['select'], 20)
    if rows[0].op_str != 'w0, [x19, #0xcd0]' or rows[1].op_str != 'w0, #1' or rows[3].op_str != 'w0, #2':
        raise ValueError('Original AP group mode selection changed')
    p['four'], p['sixteen'] = branch(p['select']+8), branch(p['select']+16)
    p['invalid_mode'] = p['select']+20
    p['invalid_intervals'] = [branch(p[key]+8) for key in ('four', 'sixteen')]
    if image.instructions(p['before_setup'], 4)[0].mnemonic != 'bl':
        raise ValueError('Native group setup boundary changed')

    # Find the same four cached values in the set-TRINITY sequence's snapshot.
    pattern = struct.pack('<II', 0xb9400000, 0xb9001a60)
    matches, start = [], 0
    while True:
        offset = image.data.find(pattern, start)
        if offset < 0:
            break
        start = offset+4
        try:
            at = image.address(offset)-4
            block = image.instructions(at, 0x30)
        except ValueError:
            continue
        if (block[0].mnemonic == 'bl' and int(block[0].op_str.lstrip('#'), 0) == p['getters'][0]
                and all(block[n*3].mnemonic == 'bl'
                    and int(block[n*3].op_str.lstrip('#'), 0) == getter
                    and block[n*3+2].op_str == 'w0, [x19, #'+hex(0x18+4*n)+']'
                    for n, getter in enumerate(p['getters']))):
            matches.append(at)
    if len(matches) != 1:
        raise ValueError('Native TRINITY cached-argument snapshot is not unique')
    p['argument_snapshot'] = matches[0]
    name = image.address(image.data.find(b'N5model25sequence_set_trinity_modeE\0'))
    runners = []
    for nref in image.data_references(name):
        for ref in image.data_references(nref-8):
            if image.qword(ref-8) == 0:
                run = image.qword(ref+8+16)
                if image.text_address(run):
                    runners.append(run)
    if len(runners) != 1:
        raise ValueError('Original set-TRINITY sequence runner is not unique')
    p['run'] = runners[0]
    calls = [r for r in image.instructions(p['run'], 0x38) if r.mnemonic == 'bl']
    if len(calls) != 1:
        raise ValueError('Original runner dispatcher boundary changed')
    p['run_dispatch'] = int(calls[0].op_str.lstrip('#'), 0)
    p['regions'] = [(p['cache'], p['cache_end']), (p['first_ordinal'], p['first_ordinal']+12),
        (p['select'], max(p['invalid_intervals'])+4),
        (p['argument_snapshot'], p['argument_snapshot']+0x30), (p['run'], calls[0].address+4)]
    p['regions'] += [(at, at+20) for at in p['getters']]
    return image, p


def replay(directory, *, mode=1, interval=1, companion=0, inactive=0xffffffff):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as arm
    image, p = profile(directory)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    mapped = set()

    def load(page):
        if page in mapped:
            return
        if not page or not any(s['p_vaddr'] <= page and page+4096 <= s['p_vaddr']+s['p_memsz'] for s in image.segments):
            raise ValueError('Native AP setup accessed a non-module address: '+hex(page))
        cpu.mem_map(page, 4096)
        try:
            offset = image.offset(page, 4096)
        except ValueError:
            pass  # Uninitialized module data, not an API return.
        else:
            cpu.mem_write(page, image.data[offset:offset+4096])
        mapped.add(page)

    def unmapped(uc, access, address, size, value, unused):
        load(address & ~4095)
        return True

    cpu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
    cpu.mem_map(0x10000000, 0x10000)
    group, sequence, stack, finish = 0x10004010, 0x10006010, 0x1000f000, 0x10002000
    cpu.mem_write(group-4, b'\x6b'*0xe08)
    cpu.mem_write(sequence-4, b'\x6b'*0x38)
    before_group = bytes(cpu.mem_read(group-4, 0xe08))
    before_sequence = bytes(cpu.mem_read(sequence-4, 0x38))
    phase, boundary, arguments = 'source-getters', None, None
    slots = []
    regions = p['regions']

    def hook(uc, address, size, unused):
        nonlocal boundary, arguments
        if phase == 'group-select' and address in [p['invalid_mode'], *p['invalid_intervals']]:
            boundary = 'unsupported_mode' if address == p['invalid_mode'] else 'unsupported_interval'
            uc.emu_stop()
            return
        if phase == 'sequence-run' and address == p['run_dispatch']:
            arguments = bytes(uc.mem_read(uc.reg_read(arm.UC_ARM64_REG_X0), 20))
            uc.emu_stop()
            return
        if not any(lo <= address and address+size <= hi for lo, hi in regions):
            raise ValueError('Native AP setup entered an unresolved dependency: '+hex(address))

    def write_hook(uc, access, address, size, value, unused):
        spans = [(stack-4096, 4096), (group+0xcd0, 16), (group+0xd08, 16),
                 (group+0xd22, 1), (sequence+0x18, 16)]
        if not any(lo <= address and address+size <= lo+n for lo, n in spans):
            raise ValueError('Native AP setup changed unrelated state: '+hex(address))

    def execute(entry, end=finish):
        cpu.reg_write(arm.UC_ARM64_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM64_REG_LR, finish)
        cpu.emu_start(entry, end, count=3000)

    ch = cpu.hook_add(UC_HOOK_CODE, hook)
    for getter in p['getters']:
        execute(getter)
        if cpu.reg_read(arm.UC_ARM64_REG_PC) != finish:
            raise ValueError('Original cached-setting getter did not return')
        slots.append(cpu.reg_read(arm.UC_ARM64_REG_X0))
    values = (mode, interval if mode == 1 else inactive, interval if mode == 2 else inactive, companion)
    for slot, value in zip(slots, values):
        load(slot & ~4095)
        cpu.mem_write(slot, struct.pack('<I', value))
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        phase = 'group-snapshot'
        cpu.reg_write(arm.UC_ARM64_REG_X19, group)
        execute(p['cache'], p['cache_end'])
        phase = 'first-ordinal'
        execute(p['first_ordinal'], p['first_ordinal']+12)
        phase = 'group-select'
        execute(p['select'], p['before_setup'])
        selected = boundary is None
        count = struct.unpack('<I', cpu.mem_read(group+0xd08, 4))[0] if selected else None
        interval_value = struct.unpack('<Q', cpu.mem_read(group+0xd10, 8))[0] if selected else None
        phase = 'argument-snapshot'
        cpu.reg_write(arm.UC_ARM64_REG_X19, sequence)
        execute(p['argument_snapshot'], p['argument_snapshot']+0x30)
        cpu.hook_del(wh)
        cpu.mem_write(sequence+0x14, struct.pack('<I', 0x12345678))  # Opaque source identifier fixture.
        wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        phase = 'sequence-run'
        cpu.reg_write(arm.UC_ARM64_REG_X0, sequence)
        execute(p['run'])
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    expected_args = struct.pack('<5I', 0x12345678, *values)
    if arguments != expected_args or struct.unpack('<I', cpu.mem_read(group+0xd0c, 4))[0] != 1:
        raise ValueError('Original AP cached arguments or first ordinal differ')
    expected_group = bytearray(before_group)
    expected_group[4+0xcd0:4+0xce0] = struct.pack('<4I', *values)
    expected_group[4+0xd0c:4+0xd10] = struct.pack('<I', 1)
    expected_group[4+0xd22] = 0
    if selected:
        intervals = (500, 1000, 2000, 3000, 4000, 5000, 10000, 15000, 30000)
        if count != (4 if mode == 1 else 16) or interval_value != intervals[interval]:
            raise ValueError('Native AP count/interval result differs from independent expectations')
        expected_group[4+0xd08:4+0xd0c] = struct.pack('<I', count)
        expected_group[4+0xd10:4+0xd18] = struct.pack('<Q', interval_value)
    expected_sequence = bytearray(before_sequence)
    expected_sequence[4+0x14:4+0x28] = expected_args
    if (bytes(cpu.mem_read(group-4, len(expected_group))) != bytes(expected_group)
            or bytes(cpu.mem_read(sequence-4, len(expected_sequence))) != bytes(expected_sequence)):
        raise ValueError('Native AP snapshots/count setup changed neighboring object fields')
    formatted = None
    cp_value = None
    if companion == 1 or mode in (0, 1, 2) and (mode == 0 or interval <= 8):
        formatted = configure_arguments(directory, arguments)
        raw = bytes.fromhex(formatted['packet'])
        cpcpu, cpp, _ = _dispatch(directory, formatted['packet'], source_id=0x80020002)
        cp_value = struct.unpack('<I', cpcpu.mem_read(cpp['parameter'], 4))[0]
        expected_enable = int(companion == 1 or mode != 0)
        expected_packet_count = 1 if companion else (4 if mode == 1 else 16 if mode == 2 else 0)
        if cp_value != expected_enable or list(raw[8:10]) != [expected_enable, expected_packet_count]:
            raise ValueError('Native AP formatter/CP enable assignment differs from cached input semantics')
    return dict(native_group_selected=selected, boundary=boundary or 'before_group_setup_call',
        native_ap_group_count=count, native_interval_value=interval_value, native_first_ap_ordinal=1,
        native_argument_bytes_preserved=True, native_object_neighbors_preserved=True,
        native_cp_enable=cp_value, native_packet_count=bytes.fromhex(formatted['packet'])[9] if formatted else None,
        companion_overrides_off=mode == 0 and companion == 1 and cp_value == 1,
        host_assigned_group_count_or_first_ordinal=False, api_results_replaced=False,
        cached_settings_source_identifier_and_stage_handoffs_are_fixtures=True,
        dispatcher_and_transport_bridge_is_explicit=True, admission_mutex_and_full_start_proc_executed=False,
        cp_total_count_source_producer_executed=False, four_frame_scheduler_executed=False,
        saved_off_setting_executed=False, exposure_or_centering_executed=False, camera_io=False, installable=False)


def compare(c2, reference):
    cases = [dict(mode=mode, interval=interval, companion=flag)
             for mode in (1, 2) for interval in range(9) for flag in (0, 1)]
    cases += [dict(mode=mode, interval=interval, companion=flag)
              for mode, interval in ((0, 0), (3, 0), (1, 9), (2, 9)) for flag in (0, 1)]
    rows = []
    for values in cases:
        x, y = replay(c2, **values), replay(reference, **values)
        if x != y:
            raise ValueError('Original AP group/argument/CP enable setup differs between C2 and CR')
        rows.append(dict(input=values, target=x, reference=y))
    return dict(schema='a7c2-native-ap-group-setup/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({key: result[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
