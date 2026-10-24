"""Find initial checkpoints locally and restore using one body-bound session.

Discovery reads ZIP metadata, not whole firmware files. The existing rollback
backend validates the selected archive and performs full byte readback. Nothing
here treats an official update package as a checkpoint or attempts a downgrade.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from zipfile import ZipFile

from .paths import data_root, write_json


def describe(path):
    from looktool import checkpoint
    archive = checkpoint.archive_path(path).resolve()
    with ZipFile(archive) as stream:
        info = stream.getinfo('manifest.json')
        manifest = json.loads(stream.read(info))
        if manifest.get('schema') != checkpoint.SCHEMA or manifest.get('version') != '2.01':
            raise ValueError('Not a supported initial checkpoint')
        expected = checkpoint.inventory()
        if set(manifest.get('files', [])) != expected or set(stream.namelist()) != expected | {'manifest.json'}:
            raise ValueError('Incomplete checkpoint')
        checkpoint.same_body(manifest['identity'], manifest['identity'])
        captured = datetime(*info.date_time).astimezone().isoformat()
    return {'path': str(archive), 'identity': manifest['identity'],
            'captured_at': captured, 'scope': manifest.get('scope', ''),
            'provenance': manifest.get('provenance', {}),
            'limitations': manifest.get('limitations', [])}


def register(path):
    """Remember an original point, retaining its first recorded creation time."""
    from looktool.devicelock import DeviceLock
    row = describe(path)
    row['registered_at'] = datetime.now(timezone.utc).isoformat()
    registry = data_root() / 'recovery-index.private.json'
    with DeviceLock(registry.with_suffix('.lock')):
        rows = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else []
        if not any(Path(item['path']) == Path(row['path']) for item in rows):
            rows.append(row)
            write_json(registry, rows)
    return row


def discover(roots=()):
    """Only scan configured backup locations, never the user's entire drive."""
    registry = data_root() / 'recovery-index.private.json'
    rows = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else []
    paths = [Path(row['path']) for row in rows]
    for root in roots:
        root = Path(root).expanduser()
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            for pattern in ('checkpoint.private.zip', '*/checkpoint.private.zip',
                            '*/*/checkpoint.private.zip', '*/*/*/checkpoint.private.zip'):
                paths.extend(root.glob(pattern))
    result, seen = [], set()
    for path in paths:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            row = describe(path)
            if row['provenance'].get('type') in ('before-full-rollback', 'rollback-target', 'current-project-backup'):
                continue
            result.append(row)
        except Exception as exc:
            print('Skipped recovery candidate:', path, repr(exc), flush=True)
    return sorted(result, key=lambda row: (row['captured_at'], row['path']))


def select(rows, identity):
    from looktool import checkpoint
    matching = []
    for row in rows:
        try:
            checkpoint.same_body(row['identity'], identity)
        except ValueError:
            continue
        matching.append(row)
    if not matching:
        raise ValueError('No complete initial backup for this connected body was found. Select its original backup directory or ZIP manually.')
    return min(matching, key=lambda row: (row['captured_at'], row['path']))


def restore_auto(arguments, job, *, factory=None, rollback_type=None):
    from looktool.checkpointjob import CheckpointCamera, Rollback
    from looktool.power import require_power
    require_power(arguments.get('battery'), confirmed=arguments.get('power_confirmed', False))
    if arguments['firmware'] != '2.01':
        raise ValueError('Confirm firmware 2.01')
    rows = discover(arguments.get('roots', []))
    if not rows:
        raise ValueError('No complete initial backup found. Select the original backup manually.')
    with (factory or CheckpointCamera)() as camera:
        row = select(rows, camera.identity)
        write_json(job / 'recovery-selection.private.json', row)
        print('Selected earliest available same-body checkpoint:', row['path'], flush=True)
        for limitation in row['limitations']:
            print('Backup limitation:', limitation, flush=True)

        @contextmanager
        def reuse(expected):
            from looktool import checkpoint
            checkpoint.same_body(expected, camera.identity)
            yield camera

        obj = (rollback_type or Rollback)(Path(arguments['workspace']), factory=reuse)
        options = {'power_confirmed': True} if arguments.get('power_confirmed') else {}
        result = obj.run(row['path'], arguments.get('battery'), arguments['firmware'], **options)
    return {'workspace': str(obj.root), 'backup': row['path'], 'phase': result['phase']}
