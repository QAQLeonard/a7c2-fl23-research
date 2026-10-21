"""Reviewed gamma-data merge; retain LUT dispatch and loaded text extents."""
import json
from pathlib import Path


def runtime():
    path = Path(__file__).resolve().parents[1] / 'assets/runtime-fl23-current.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['schema'] != 'a7c2-lut-fl23-current/1':
        raise ValueError('Unknown FL23/LUT compatibility schema')
    return data


def transform(cp, *, reverse=False):
    spec = runtime()
    if len(cp) != spec['cp_bytes']:
        raise ValueError('FL23/LUT CP length differs')
    result = bytearray(cp)
    for row in spec['upgrade_windows']:
        at = row['offset']
        old, new = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
        before, after = (new, old) if reverse else (old, new)
        actual = cp[at:at+len(before)]
        if not before or len(before) != len(after):
            raise ValueError('Invalid FL23/LUT merge window')
        # Reverse normalization proves a complete known legacy code identity;
        # it must not hide a partly applied or unrelated edit.
        if actual != before and (reverse or actual != after):
            raise ValueError(f'FL23/LUT gamma conflict at {at:#x}')
        result[at:at+len(after)] = after
    return bytes(result)


def preserve_lut_dispatch(cp):
    expected = {
        0x20140: 'a02f1400',
        0x323172: '04f0c5d900bf00bf',
        0x323298: '04f032d900bf00bf',
    }
    for at, value in expected.items():
        raw = bytes.fromhex(value)
        if cp[at:at+len(raw)] != raw:
            raise ValueError(f'LUT dispatch/loaded extent conflict at {at:#x}')
    return set(expected)
