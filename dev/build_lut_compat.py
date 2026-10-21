"""Reproduce the current FL23/LUT adapter from local official 2.01 components.

No USB access. Full firmware stays outside the repository; the output contains
only public patch-window differences and derived program fingerprints.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/fl23'), str(ROOT / 'src/looks')]
import core
from looktool import checkpointworker, device_layout


def apply_windows(source, windows):
    result = bytearray(source)
    for row in windows:
        at = row['offset']
        before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
        if len(before) != len(after) or result[at:at+len(before)] != before:
            raise ValueError(f'Bootstrap conflict at {at:#x}')
        result[at:at+len(after)] = after
    return bytes(result)


def build(components):
    sources = [(Path(components) / name).read_bytes() for name in core.PROGRAMS]
    if [core.sha(data) for data in sources] != core.ORIGINAL:
        raise ValueError('Exact official A7C II 2.01 components required')
    old = json.loads((ROOT / 'src/looks/assets/runtime-v1.json').read_text(encoding='utf-8'))
    stock = next(s for s in old['cp_sources'] if s['kind'] == 'stock')
    fl23 = next(s for s in old['cp_sources'] if s['kind'] == 'fl23')
    legacy = apply_windows(sources[1], stock['windows'])
    if core.sha(legacy) != old['cp_zero_tables_sha256']:
        raise ValueError('Legacy runtime reconstruction differs')
    current_fl23 = core.patch_program(sources[1], 1)
    merged = apply_windows(current_fl23, fl23['windows'])
    windows = [{'offset': at, 'before': a.hex(), 'after': b.hex()}
               for at, a, b in checkpointworker.differences(legacy, merged)]
    patches = core.read_json(core.BASE / 'assets/patches.json')[1]['writes']
    # The LUT's larger loaded range and gamma dispatch wrappers must survive.
    protected = {0x20140, 0x323172, 0x323298}
    allowed = [(int(w['file_offset'], 16), len(bytes.fromhex(w['after_hex'])))
               for w in patches if int(w['file_offset'], 16) not in protected]
    for row in windows:
        start, end = row['offset'], row['offset'] + len(bytes.fromhex(row['after']))
        if not any(at <= start and end <= at+n for at, n in allowed):
            raise ValueError(f'Unreviewed runtime difference at {start:#x}')
    if apply_windows(legacy, windows) != merged:
        raise ValueError('Runtime merge is not reproducible')
    return {
        'schema': 'a7c2-lut-fl23-current/1',
        'physical_first_install_tested': False,
        'fl23_cp_sha256': core.sha(current_fl23),
        'cp_bytes': len(merged),
        'cp_zero_tables_sha256': core.sha(merged),
        'cp_code_sha256': device_layout.code_hash(merged),
        'legacy_cp_zero_tables_sha256': core.sha(legacy),
        'legacy_cp_code_sha256': device_layout.code_hash(legacy),
        'upgrade_windows': windows,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.components)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'upgrade_windows'}, indent=2))
    print('Upgrade windows:', len(result['upgrade_windows']))
