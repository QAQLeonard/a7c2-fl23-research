"""Collect native A7CR reference files and optional read-only settings snapshots.

File commands use only Python's standard library and the adjacent raw_group.py.
USB access is lazy and explicit; no camera is contacted by init/check/pack.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import zipfile

from raw_group import inspect, validate

VERSION = '1.1'
ROLES = ('before', 'four-shot', 'four-shot-repeat', 'after')
STAGES = ('off-before', 'four-selected', 'off-after')
EVIDENCE_TYPES = {'.jpg', '.jpeg', '.png', '.txt', '.arq'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def initialize(root, *, firmware, lens='', interval='1 s'):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    for folder in ROLES + ('evidence', 'runtime'):
        (root / folder).mkdir()
    session = dict(schema='a7cr-reference-session/1', collector_version=VERSION,
        model='ILCE-7CR', firmware_user_reported=firmware, lens=lens,
        four_shot_interval_user_reported=interval,
        same_camera_and_static_scene_user_confirmed=False,
        exposure_focus_white_balance_fixed_user_confirmed=False,
        notes='Record any changed setting, restart, error, or movement here.')
    (root / 'session.json').write_text(json.dumps(session, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return session


def contained(root, path):
    path = Path(path)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError('A selected file points outside the collection directory') from None
    return path


def check(root):
    root = Path(root).resolve()
    session = json.loads(contained(root, root/'session.json').read_text(encoding='utf-8'))
    if session.get('schema') != 'a7cr-reference-session/1' or session.get('model') != 'ILCE-7CR':
        raise ValueError('Choose an A7CR reference session created by init')
    errors, warnings, records, selected, groups = [], [], {}, [root/'session.json'], {}
    for role in ROLES:
        folder = contained(root, root/role)
        paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.arw')
        rows = []
        for path in paths:
            contained(root, path)
            relative = path.relative_to(root).as_posix()
            try:
                row = inspect(path)
                row['file'] = relative
                rows.append(row)
                if row['model'] != 'ILCE-7CR':
                    errors.append(relative+': expected ILCE-7CR')
            except (ValueError, KeyError, UnicodeError, OSError) as exc:
                errors.append(relative+': RAW metadata could not be read ('+type(exc).__name__+')')
            selected.append(path)
        records[role] = rows
        if role in ('before', 'after'):
            if len(paths) != 1:
                errors.append(role+': need exactly one ordinary RAW with Pixel Shift OFF')
            if any(row['pixel_shift'] is not None for row in rows):
                errors.append(role+': expected an ordinary RAW, not a Pixel Shift source')
        elif role == 'four-shot-repeat' and not paths:
            warnings.append('Optional second four-shot group was not supplied')
        else:
            try:
                groups[role] = validate(rows)
            except ValueError as exc:
                errors.append(role+': '+str(exc))
    exposures = [row['exposure_fields'] for rows in records.values() for row in rows]
    if exposures and any(row != exposures[0] for row in exposures[1:]):
        errors.append('Shutter/aperture/ISO metadata differs across the comparison set')
    if exposures and any(not all(str(k) in row for k in (33434, 33437, 34855)) for row in exposures):
        errors.append('Missing shutter/aperture/ISO metadata')
    if all(records.get(role) for role in ('four-shot', 'four-shot-repeat')):
        first = records['four-shot'][0]['pixel_shift']
        second = records['four-shot-repeat'][0]['pixel_shift']
        if first and second and first['group_id'] == second['group_id']:
            warnings.append('Both groups have the same group ID; confirm that the repeat is a new capture')
    if not session.get('firmware_user_reported'):
        warnings.append('Camera firmware version was not recorded')
    for field in ('same_camera_and_static_scene_user_confirmed',
                  'exposure_focus_white_balance_fixed_user_confirmed'):
        if not session.get(field):
            warnings.append(field+': not confirmed in session.json')
    evidence = contained(root, root/'evidence')
    for path in sorted(evidence.rglob('*')):
        if path.is_file() and path.suffix.lower() in EVIDENCE_TYPES:
            selected.append(contained(root, path))
    snapshots = []
    runtime = contained(root, root/'runtime')
    for folder in sorted(runtime.iterdir()):
        if not folder.is_dir():
            continue
        contained(root, folder)
        report_path = folder/'snapshot.json'
        if not report_path.is_file():
            continue
        contained(root, report_path)
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('schema') != 'a7cr-readonly-settings/1':
            continue
        snapshots.append(dict(label=report.get('label'), complete=report.get('complete', False),
            settings_ram_captured=report.get('settings_ram_captured', False),
            cp_execution_ram_captured=False))
        selected.append(report_path)
        for name in report.get('files', []):
            if Path(name).name != name or not name.endswith('.bin'):
                raise ValueError('Unexpected snapshot member name')
            selected.append(contained(root, folder/name))
    completed = {row['label'] for row in snapshots if row['complete']}
    if not set(STAGES) <= completed:
        warnings.append('Optional USB snapshots missing: '+', '.join(stage for stage in STAGES if stage not in completed))
    report = dict(schema='a7cr-reference-validation/1', collector_version=VERSION,
        created_utc=now(), status='READY' if not errors else 'INCOMPLETE',
        errors=errors, warnings=warnings, session=session, raw_files=records,
        groups=groups, runtime_snapshots=snapshots,
        camera_io=False, originals_modified=False, physical_shift_verified=False,
        centering_verified=False, settling_verified=False,
        limits=['RAW metadata is not proof of sensor motion or settling',
                'USB settings snapshots are not CP execution memory or per-exposure traces',
                'USB connection can change the observed camera state',
                'Original files and settings may contain private camera/owner information'])
    return report, selected


def pack(root, *, output=None, allow_partial=False):
    root = Path(root).resolve()
    report, files = check(root)
    if report['errors'] and not allow_partial:
        raise ValueError('Collection incomplete:\n'+'\n'.join(report['errors']))
    output = Path(output) if output else root.parent/(root.name+'.private.zip')
    if output.exists():
        raise FileExistsError('Output already exists; choose a new --output path')
    with zipfile.ZipFile(output, 'x', allowZip64=True) as archive:
        archive.writestr('validation.json', json.dumps(report, ensure_ascii=False, indent=2)+'\n',
                         compress_type=zipfile.ZIP_DEFLATED)
        for path in files:
            kind = zipfile.ZIP_DEFLATED if path.suffix.lower() in ('.json', '.txt', '.bin') else zipfile.ZIP_STORED
            archive.write(path, path.relative_to(root).as_posix(), compress_type=kind)
    return report, output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='Create folders and a session notes template; no USB')
    init.add_argument('folder', type=Path)
    init.add_argument('--firmware', required=True, help='Actual version shown by the camera; no downgrade required')
    init.add_argument('--lens', default='')
    init.add_argument('--interval', default='1 s')
    for name in ('check', 'pack'):
        command = sub.add_parser(name, help='Inspect original files without changing them; no USB')
        command.add_argument('folder', type=Path)
        if name == 'pack':
            command.add_argument('--output', type=Path)
            command.add_argument('--allow-partial', action='store_true', help='Include an explicit INCOMPLETE report')
    usb = sub.add_parser('usb', help='Explicit, read-only service settings collection; optional dependencies required')
    usb.add_argument('folder', type=Path)
    usb.add_argument('--label', required=True, choices=STAGES)
    usb.add_argument('--cp-shadows', action='store_true', help='Also read the nineteen native CP backup-shadow units')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            initialize(args.folder, firmware=args.firmware, lens=args.lens, interval=args.interval)
            print('Created '+str(args.folder)+'. Follow the collection guide; USB has not been accessed.')
        elif args.command == 'usb':
            from cr_usb_readonly import collect
            result = collect(args.folder, label=args.label, cp_shadows=args.cp_shadows)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            report, result = (pack(args.folder, output=args.output, allow_partial=args.allow_partial)
                              if args.command == 'pack' else check(args.folder))
            print(json.dumps({key: report[key] for key in ('status', 'errors', 'warnings')}, ensure_ascii=False, indent=2))
            if args.command == 'pack':
                print('Private archive: '+str(result))
            return 0 if not report['errors'] else 2
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print('Stopped: '+str(exc))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
