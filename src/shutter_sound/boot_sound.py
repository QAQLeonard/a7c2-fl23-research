"""Offline persistent-sound candidate using the original boot file-loader.

No installer or camera access. A four-instruction boot log block instead calls
the original single-row CSV reader on kind3's existing descriptor. The native
file-loader then owns AP/CP allocation, transfer and lifetime as usual. Missing
CSV returns without changing that descriptor. Hardware codec/rate, physical
boot, missing/corrupt audio-file behavior and live installation remain untested.
"""
import argparse
import json
from pathlib import Path
import struct

from verify_beeplist import CSV, execute

BOOT = 0x3060a24
OLD_PATH = b'/usr/share/avsystemsound/beeplist.txt\0'
NEW_PATH = b'/usr/share/avsystemsound/custom.txt\0'
PATH = 0x48cfa83
MISSING = 0x2759b3c


def branch(at, target, link=False):
    delta = target - at
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError('AArch64 branch target outside range')
    return struct.pack('<I', (0x94000000 if link else 0x14000000) | ((delta // 4) & 0x3ffffff))


def adrp(at, target, register):
    delta = ((target & ~4095) - (at & ~4095)) // 4096
    if not -(1 << 20) <= delta < (1 << 20):
        raise ValueError('AArch64 page target outside range')
    return struct.pack('<I', 0x90000000 | ((delta & 3) << 29) |
                       (((delta >> 2) & 0x7ffff) << 5) | register)


def expected_windows():
    # Derive the exact original BL-to-logger bytes from the documented native
    # targets, without accepting arbitrary instructions supplied as a source.
    original_boot = adrp(BOOT, 0x4c14000, 0) + bytes.fromhex('b53f40f9000c2b91') + branch(BOOT + 12, 0x36804c8, True)
    # This is the first instruction of the original fopen-failure fatal path.
    # Reuse its own clean return epilogue at 2759bc8; no new code storage.
    original_missing = adrp(MISSING, 0x48cf000, 20)
    new_boot = (branch(BOOT, 0x2885488, True) + bytes.fromhex('00800591') +
                branch(BOOT + 8, 0x2759ae8, True) + bytes.fromhex('b53f40f9'))
    edits = [(MISSING, original_missing, branch(MISSING, 0x2759bc8))]
    # The original generic reader reserves 30KiB for its CSV. Our fixed one-row
    # file needs <2KiB. Keep all x29-relative locals and remove the matching 7-page
    # prologue/epilogue adjustment; reduce memset/fread/limit consistently.
    for at, old, new in (
        (0x2759ae8, 'ff1f40d1', '1f2003d5'),
        (0x2759be4, 'ff1f4091', '1f2003d5'),
        (0x2759af4, '02008fd2', '020081d2'),
        (0x2759bfc, '02008fd2', '020081d2'),
        (0x2759c0c, 'e0ff8ed2', 'e0ff80d2')):
        edits.append((at,bytes.fromhex(old),bytes.fromhex(new)))
    # Oversized CSV: the original path has just fclose'd at c24. Return using
    # its clean epilogue, preserving the stock descriptor instead of asserting.
    too_large = 0x2759c28
    before = bytes.fromhex('949a2991')
    edits.append((too_large, before, branch(too_large, 0x2759bc8)))
    edits.append((PATH, OLD_PATH, NEW_PATH.ljust(len(OLD_PATH), b'\0')))
    # Prepare the reader and private path before enabling the boot call. The
    # inverse must use reverse order, removing the call before its prerequisites.
    edits.append((BOOT, original_boot, new_boot))
    return edits


def windows(ap):
    edits=expected_windows()
    for at,old,new in edits:
        if ap[at:at+len(old)]!=old:
            raise ValueError('Original boot-sound instruction differs at '+hex(at))
    return edits


def installed(ap):
    import targeted_sound
    if targeted_sound.sparse(ap):
        edits=targeted_sound.windows(ap)
        if all(ap[at:at+len(new)]==new for at,old,new in edits):return True
        raise ValueError('Targeted sound reader contains an incomplete modification')
    edits=expected_windows()
    if all(ap[at:at+len(old)]==old for at,old,new in edits):return False
    if all(ap[at:at+len(new)]==new for at,old,new in edits):return True
    raise ValueError('Boot-sound regions contain an incomplete or different modification')


def patch(ap, edits, reverse=False):
    result = bytearray(ap)
    for at, old, new in edits:
        before, after = (new, old) if reverse else (old, new)
        if result[at:at + len(before)] != before or len(before) != len(after):
            raise ValueError('Boot-sound edited bytes conflict')
        result[at:at + len(after)] = after
    return bytes(result)


def restore_plan(ap):
    """Restore only known boot-sound windows from CURRENT bytes, no old job."""
    edits=[]
    for at,old,new in reversed(current_windows(ap)):
        actual=ap[at:at+len(old)]
        if actual not in (old,new):raise ValueError('Current sound-hook bytes conflict at '+hex(at))
        if actual!=old:edits.append((at,actual,old))
    target=patch(ap,edits)
    if patch(target,edits,reverse=True)!=ap:raise ValueError('Sound restore inverse differs')
    return target,edits


def current_windows(ap):
    """Original/current owned windows, including either boot-hook revision."""
    import targeted_sound
    if targeted_sound.sparse(ap):return targeted_sound.windows(ap)
    return expected_windows()


def restore_priority(row):
    chip,at,old,_=row
    return (0 if chip==0 and at<BOOT+16 and at+len(old)>BOOT else 1,chip,at)


def plan(ap,raw,*,current=False):
    """Pure byte planning; no native emulator/JIT is used by camera actions."""
    if not raw or len(raw)>51200 or len(raw) % 64 or any(raw[n] > 8 for n in range(0, len(raw), 32)):
        raise ValueError('Use a complete filter0 native-codec research candidate')
    csv = CSV.replace(b'0xEC0', ('0x%X' % len(raw)).encode())
    if current:
        edits=[]
        for at,old,new in expected_windows():
            actual=ap[at:at+len(old)]
            if actual not in (old,new):raise ValueError('Current sound-hook bytes conflict at '+hex(at))
            if actual!=new:edits.append((at,actual,new))
    else:edits=windows(ap)
    target = patch(ap, edits)
    if patch(target, edits, True) != ap:
        raise ValueError('Boot-sound inverse differs')
    report=dict(schema='a7c2-native-boot-sound-plan/1',camera_io=False,
        edited_bytes=sum(len(old) for _,old,_ in edits),inverse_byte_equal=True,
        native_file_loader_reused=True,emulator_executed=False)
    return target,csv,edits,report


def verify(ap, raw):
    target,csv,edits,_=plan(ap,raw)
    cases = []
    for scenario in ('valid', 'missing', 'oversized'):
        result = execute(target, csv if scenario != 'oversized' else csv.ljust(2048, b' '),
                         missing=scenario == 'missing', boot_block=True,
                         expected_path=NEW_PATH[:-1], csv_limit=2048)
        if scenario != 'valid':
            if result['output_changed'] or result['returned'] != 0:
                raise ValueError('Missing CSV changed the original descriptor')
        elif (result['priority'], result['kind'], result['bytes'], result['filename']) != (
                6, 3, len(raw), '/usr/share/avsystemsound/custom-shutter.bin'):
            raise ValueError('Original reader did not prepare the selected sound file')
        if result['maximum_native_reader_stack_bytes'] > 0xa90:
            raise ValueError('Reader exceeded its reduced native stack frame')
        cases.append(dict(scenario=scenario, **result))
    report = {'schema': 'a7c2-native-boot-sound-offline/1', 'camera_io': False,
              'edited_bytes': sum(len(old) for _, old, _ in edits),
              'boot_block_bytes': 16, 'trampoline_or_new_code_storage': False,
              'inverse_byte_equal': True, 'reader_cases': cases,
              'native_file_loader_reused': True, 'camera_boot_verified': False,
              'hardware_codec_or_rate_verified': False,
              'no_installer_or_write_authorization_implied': True}
    return target, csv, edits, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap', type=Path, required=True)
    p.add_argument('--native-bin', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    raw = a.native_bin.read_bytes()
    target, csv, edits, report = verify(a.ap.read_bytes(), raw)
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / 'appFw.candidate.private.so').write_bytes(target)
    (a.output / 'custom.txt').write_bytes(csv)
    (a.output / 'custom-shutter.bin').write_bytes(raw)
    (a.output / 'windows.private.json').write_text(json.dumps([
        {'offset': at, 'before_hex': old.hex(), 'after_hex': new.hex()}
        for at, old, new in edits], indent=2) + '\n', encoding='utf-8')
    (a.output / 'report.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
