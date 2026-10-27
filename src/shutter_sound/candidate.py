"""Narrow, offline-only CP sound trial and native-worker construction.

No USB imports. Physical preflight and writing are separate explicit commands
in trial.py. No donor firmware or sound resources are distributed.
"""
import argparse
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/looks'))
OFFSET = 0x3935ca
BEFORE, AFTER = bytes.fromhex('0021'), bytes.fromhex('0321')
START = 0x3935bc
CONTEXT = bytes.fromhex('dbf33afc0321002845f61c4018bf002121502044')
# The context is read from the actual stock instructions when authored below;
# this explicit literal is checked independently, not a firmware SHA gate.

# Classify the real per-capture electronic flag written by 8b8004..8b8014.
# Reuse existing native mode blocks; no added executable storage.
SELECTOR_TABLE = 0x393570
TABLE_BEFORE = bytes.fromhex('1b26034403')
TABLE_AFTER = bytes.fromhex('4426444444')
# Preserve the original mechanical/front-policy selection and its guards.
TABLE_SPLIT = TABLE_BEFORE
TABLE_ELECTRONIC = bytes.fromhex('4426034403')
GATE = START
GATE_AFTER = bytes.fromhex('dcf3a1fa41f21901415c012916d1e0e700bf00bf')
GATE_MUTED = GATE_AFTER[:14] + bytes.fromhex('15e0') + GATE_AFTER[16:]
# Read the same native per-capture flag at +0x1019. Mechanical uses mode1
# (native kind1 KA / kind2 SHA); electronic uses mode3 (kind3, customizable).
GATE_BOTH = bytes.fromhex('dcf3a1fa41f21901415c4900013145f61c40f2e7')
GATE_MECHANICAL = bytes.fromhex('dcf3a1fa41f21901415cb9b945f61c40204410e0')
GATE_ELECTRONIC = bytes.fromhex('dcf3a1fa41f21901415cb9b145f61c400321f2e7')
FRONT = 0x39358e
FRONT_BEFORE, FRONT_AFTER = bytes.fromhex('45f6'), bytes.fromhex('15e0')
MECHANICAL = 0x3935aa
MECHANICAL_BEFORE, MECHANICAL_AFTER = bytes.fromhex('0321'), bytes.fromhex('0121')
LEGACY_GATE = CONTEXT[:OFFSET - START] + AFTER + CONTEXT[OFFSET - START + 2:]
WINDOWS = ((SELECTOR_TABLE, TABLE_BEFORE, TABLE_AFTER), (GATE, CONTEXT, GATE_ELECTRONIC),
           (FRONT, FRONT_BEFORE, FRONT_AFTER), (MECHANICAL, MECHANICAL_BEFORE, MECHANICAL_AFTER))
CP_GUARDS = (
    (0x39356c, bytes.fromhex('dfe801f0')),
    (0x393590, bytes.fromhex('1c4003210fe0')),
    (0x3935a6, bytes.fromhex('94f8d709')),
    (0x3935ac, bytes.fromhex('002845f61c4018bf0221')),
    (0x3935b6, bytes.fromhex('215020440ae0')),
    (0x3935d0, bytes.fromhex('b1b1')),
    (0x3935f8, bytes.fromhex('45f61c4000212150')),
    (0x76fb02, bytes.fromhex('4af6d070c0f201207047')),
    (0x7b0004, bytes.fromhex('d0f8c85441f21901012d18bf0025049c6554')),
)


def sound_state(cp):
    table = cp[SELECTOR_TABLE:SELECTOR_TABLE + len(TABLE_BEFORE)]
    gate = cp[GATE:GATE + len(CONTEXT)]
    if table == TABLE_BEFORE and gate == CONTEXT:
        return 'off'
    if table == TABLE_BEFORE and gate == LEGACY_GATE:
        return 'legacy'
    if table == TABLE_AFTER and gate in (GATE_AFTER, GATE_ELECTRONIC):
        return 'electronic_only'
    if table == TABLE_ELECTRONIC and gate == GATE_ELECTRONIC:
        return 'electronic_only'
    if table == TABLE_AFTER and gate == GATE_MUTED:
        return 'muted'
    if table == TABLE_SPLIT and gate == GATE_BOTH:
        return 'both'
    if table == TABLE_SPLIT and gate == GATE_MECHANICAL:
        return 'mechanical_only'
    if table in (TABLE_BEFORE, TABLE_AFTER) and gate in (CONTEXT, LEGACY_GATE, GATE_AFTER, GATE_MUTED):
        return 'partial'
    raise ValueError('Sound-selector context differs from supported 2.01 instructions')


def is_enabled(cp):
    return sound_state(cp) not in ('off', 'muted', 'mechanical_only')


def is_current(cp):
    return sound_state(cp) in ('electronic_only', 'both')


def switches(cp):
    state = sound_state(cp)
    return dict(mechanical=state in ('off', 'legacy', 'both', 'mechanical_only'),
                electronic=is_enabled(cp))


def is_legacy(cp):
    return (cp[SELECTOR_TABLE:SELECTOR_TABLE+len(TABLE_BEFORE)]==TABLE_BEFORE
            and cp[GATE:GATE+len(LEGACY_GATE)]==LEGACY_GATE)


def guard(ap, cp, *, installed=False):
    if ap[:4] != b'\x7fELF' or len(ap) < 0x288549c:
        raise ValueError('Expected the A7C II 2.01 AArch64 AP')
    if is_enabled(cp) != installed:
        raise ValueError('Sound trial instruction conflicts; no write planned')
    for at, code in CP_GUARDS:
        if cp[at:at + len(code)] != code:
            raise ValueError('CP per-capture electronic-flag source differs from 2.01')
    for at, before, after in WINDOWS[2:]:
        if cp[at:at+len(before)] not in (before,after):
            raise ValueError('CP native mechanical sound context differs from 2.01')
    getters = ((0x286cde8, bytes.fromhex('20af029000601391008c409100800391c0035fd6')),
               (0x2885488, bytes.fromhex('40ae02f0006013910004429100002f91c0035fd6')))
    for at, code in getters:
        if ap[at:at + 20] != code:
            raise ValueError('AP sound getter conflicts; no native access planned')


def patch(ap, cp, *, restore=False, mechanical=None, electronic=True):
    guard(ap, cp, installed=is_enabled(cp))
    if mechanical is None:mechanical=switches(cp)['mechanical']
    if restore:
        table, gate = TABLE_BEFORE, CONTEXT
    elif mechanical:
        table, gate = TABLE_SPLIT, GATE_BOTH if electronic else GATE_MECHANICAL
    else:
        table, gate = (TABLE_ELECTRONIC,GATE_ELECTRONIC) if electronic else (TABLE_AFTER,GATE_MUTED)
    out = bytearray(cp)
    out[SELECTOR_TABLE:SELECTOR_TABLE+len(table)] = table
    out[GATE:GATE+len(gate)] = gate
    for at, before, after in WINDOWS[2:]:out[at:at+len(before)] = before if restore else after
    return {'appFw.so': ap, 'cpapp-b.bin': bytes(out)}


def disable(ap, cp):
    return patch(ap, cp, electronic=False)


def mechanical(ap, cp, enabled):
    return patch(ap, cp, mechanical=enabled, electronic=switches(cp)['electronic'])


def build(ap, cp, out, zig=None, *, restore=False):
    from looktool import nativebuild
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    target = patch(ap, cp, restore=restore)
    cbytes = lambda b: '{' + ','.join(map(str, b)) + '}'
    program_header = out / 'program.private.h'
    lines = ['#define BYTE_WINDOWS_ONLY 1']
    rows = []
    for i, (at, before, after) in enumerate(WINDOWS):
        old, new = cp[at:at + len(before)], target['cpapp-b.bin'][at:at + len(before)]
        lines += ['static const u8 old_' + str(i) + '[]=' + cbytes(old) + ';',
                  'static const u8 new_' + str(i) + '[]=' + cbytes(new) + ';']
        rows.append('{%dUL,%d,1,old_%d,new_%d}' % (at, len(old), i, i))
    program_header.write_text('\n'.join(lines + [
        'static const struct Window windows[]={' + ','.join(rows) + '};',
        'static const u32 window_count=' + str(len(rows)) + ';',
        'static const u64 file_sizes[]={' + str(len(ap)) + 'UL,' + str(len(cp)) + 'UL};',
    ]) + '\n', encoding='ascii')
    nativebuild.compile_worker(ROOT / 'src/fl23/native/installer.c', program_header,
                               out / 'program.so', zig, fingerprints=False)
    program = {'path': str(out / 'program.so'), 'windows': len(rows), 'sizes': [len(ap), len(cp)]}
    lines = []
    for name, at in (('audio_getter', 0x286cde8), ('table_getter', 0x2885488)):
        lines.append('static const u8 ' + name + '[]={' + ','.join(map(str, ap[at:at + 20])) + '};')
    header = out / 'probe.private.h'
    header.write_text('\n'.join(lines) + '\n', encoding='ascii')
    nativebuild.compile_worker((Path(__file__).parent / 'native/sound_probe.c'), header,
                               out / 'probe.so', zig, fingerprints=False)
    nativebuild.compile_worker(ROOT / 'src/fl23/native/wbi.c', header,
                               out / 'wbi.so', zig, fingerprints=False)
    plan = {'schema': 'a7c2-shutter-trial/1', 'model': 'ILCE-7CM2', 'firmware': '2.01',
            'offset': OFFSET, 'before': cp[OFFSET:OFFSET+2].hex(),
            'after': target['cpapp-b.bin'][OFFSET:OFFSET+2].hex(),
            'windows': [dict(offset=at,before_hex=cp[at:at+len(old)].hex(),
                             after_hex=target['cpapp-b.bin'][at:at+len(old)].hex())
                        for at,old,_ in WINDOWS],
            'bytes': sum(len(before) for _, before, _ in WINDOWS),
            'electronic_only_gate': not restore,
            'sound_switches': switches(target['cpapp-b.bin']),
            'native_program': program, 'restore': restore,
            'camera_io': False, 'physical_sound_verified': False,
            'native_registry_preflight_required': True}
    (out / 'plan.private.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return plan, target


def parse_probe(raw):
    if len(raw) not in (1256,4456):
        raise ValueError('Incomplete sound preflight report')
    magic, version, index, status, base, audio, reserved = struct.unpack_from('<8sIIqQII', raw)
    if (magic, version, index, status, reserved) != (b'A7SND001', 1, 16, 0, 0):
        raise ValueError('Sound preflight failed: ' + repr((version, index, status)))
    entries = []
    stride=176 if len(raw)==4456 else 48
    for i in range(25):
        entry = raw[40 + i * stride:40 + (i + 1) * stride]
        entries.append({'slot': i, 'priority': entry[0], 'kind': entry[1],
                        'first_length': struct.unpack_from('<I', entry, 4)[0],
                        'loop_length': struct.unpack_from('<I', entry, 8)[0],
                        'length': struct.unpack_from('<Q', entry, 16)[0],
                        'offset': struct.unpack_from('<Q', entry, 24)[0],
                        'address': struct.unpack_from('<Q', entry, 32)[0],
                        'native_handle': struct.unpack_from('<I', entry, 40)[0],
                        'filename_prefix': entry[44:48].split(b'\0', 1)[0].decode('ascii', errors='replace')})
        if stride==176:entries[-1]['filename']=entry[44:172].split(b'\0',1)[0].decode('ascii',errors='strict')
    image_mode = raw[40+25*stride:].split(b'\0')[0].decode('ascii').strip()
    return {'model_index': index, 'audio_signals': audio, 'entries': entries,
            'image_mode': image_mode, 'camera_firmware_or_settings_written': False}


def require_registry(probe):
    # Original CP mode3 sends kind3. Stock AP run() unregisters indices0..5
    # for Audio Signals enum1 (Off); confirm kind3 belongs to that group.
    for kind in (1, 2, 3):  # counter-limited KA/SHA pair and ordinary KASHA
        selected = [e for e in probe['entries'][:6] if e['kind'] == kind]
        if not selected or any(not e['address'] or not e['length'] for e in selected):
            raise ValueError('Live shutter registration does not match kind' + str(kind) + '; stop at read-only preflight')
    if probe['image_mode'] not in ('0', '2'):
        raise ValueError('Unrecognized retained-image mode; stop at read-only preflight')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap', required=True, type=Path)
    p.add_argument('--cp', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--zig')
    p.add_argument('--restore', action='store_true')
    a = p.parse_args()
    if a.output.exists():
        raise ValueError('Use a new private candidate directory')
    plan, target = build(a.ap.read_bytes(), a.cp.read_bytes(), a.output, a.zig, restore=a.restore)
    (a.output / 'cpapp-b.candidate.private.bin').write_bytes(target['cpapp-b.bin'])
    print(json.dumps({k: plan[k] for k in ('bytes', 'offset', 'before', 'after', 'camera_io')}))


if __name__ == '__main__':
    main()
