"""Prepare voice resources from a user's Sony update; no USB or camera writes.

This is a local restoration source, never an application asset. Preparing it
does not restore a camera or authorize removing its voice-guide disable guard.
"""
from hashlib import sha256
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import uuid
from . import official
from .paths import data_root, write_json

SCHEMA = 'a7c2-screenreader-source/1'
LANGUAGES = ('english', 'french', 'german', 'italian', 'japanese', 'korean',
             'portuguese', 'simplifiedchinese', 'spanish', 'traditionalchinese')
NAMES = tuple(name + suffix for name in LANGUAGES for suffix in ('.bin', '_info.txt'))
SOURCE_ROOT = '/share/screenreader/'
CAMERA_ROOT = '/usr/share/screenreader/'
DOWNLOAD_URL = 'https://www.sony.com.hk/en/electronics/support/software/00301104'


def extract(entries, output):
    """Extract only the twenty regular files in the supported /usr image."""
    output = Path(output)
    rows = {}
    for entry in entries:
        if not entry.path.startswith(SOURCE_ROOT):
            continue
        name = entry.path[len(SOURCE_ROOT):]
        if name not in NAMES:
            continue
        if name in rows or not stat.S_ISREG(entry.mode) or not 0 < entry.size <= 40 * 1024 * 1024:
            raise ValueError('Invalid or duplicate voice resource: ' + name)
        entry.contents.seek(0)
        size, digest = 0, sha256()
        with (output / name).open('xb') as stream:
            while block := entry.contents.read(1024 * 1024):
                size += len(block)
                if size > entry.size:
                    raise ValueError('Voice resource exceeds its declared size: ' + name)
                stream.write(block)
                digest.update(block)
        if size != entry.size:
            raise ValueError('Incomplete voice resource: ' + name)
        rows[name] = dict(bytes=size, sha256=digest.hexdigest(), camera_path=CAMERA_ROOT + name)
    if set(rows) != set(NAMES):
        raise ValueError('Sony 2.01 voice resources are incomplete: ' + ', '.join(sorted(set(NAMES) - set(rows))))
    return rows


def prepare(source, cache=None):
    """Validate the model/version and prepare a complete local restore source."""
    source = Path(source).expanduser().resolve(strict=True)
    cache = Path(cache or data_root() / 'screenreader-source')
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / ('sony-2.01-' + uuid.uuid4().hex[:12])
    with tempfile.TemporaryDirectory(prefix='preparing-', dir=cache) as temporary:
        folder = Path(temporary)
        with official.firmware(source) as (contents, decoder):
            from fwtool.archive import ext2
            with tarfile.open(fileobj=contents.firmware, mode='r:') as archive:
                image = archive.extractfile('0700_part_image/dev/nflasha15')
                if image is None or not ext2.isExt2(image):
                    raise ValueError('Sony update lacks the supported /usr filesystem')
                rows = extract(ext2.readExt2(image), folder)
        manifest = dict(schema=SCHEMA, model='ILCE-7CM2', version='2.01', decoder=decoder,
                        files=rows, camera_io=False, camera_restored=False)
        write_json(folder / 'source.private.json', manifest)
        load(folder)
        folder.rename(target)
    return dict(source=str(target), files=len(rows), bytes=sum(r['bytes'] for r in rows.values()),
                camera_io=False, camera_restored=False)


def load(folder):
    """Check a prepared source before any future restore can start."""
    folder = Path(folder)
    manifest = json.loads((folder / 'source.private.json').read_text(encoding='utf-8'))
    if (manifest.get('schema'), manifest.get('model'), manifest.get('version')) != (SCHEMA, 'ILCE-7CM2', '2.01'):
        raise ValueError('Expected original ILCE-7CM2 2.01 voice resources')
    if set(manifest['files']) != set(NAMES):
        raise ValueError('Incomplete voice resource source')
    for name, row in manifest['files'].items():
        path = folder / name
        if row['camera_path'] != CAMERA_ROOT + name or path.stat().st_size != row['bytes']:
            raise ValueError('Voice resource path/size differs: ' + name)
        with path.open('rb') as stream:
            digest = sha256()
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != row['sha256']:
            raise ValueError('Voice resource contents differ: ' + name)
    return manifest
