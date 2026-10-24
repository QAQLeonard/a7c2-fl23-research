"""Prepare a model/version-checked Sony reference locally. Never opens USB."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import uuid
from .paths import ROOT, data_root, write_json

MODEL = 0x20030014
FILES = ('appFw.so', 'cpapp-b.bin', 'CX89700_ALLLANG.bin')


def load(folder=None):
    if folder is None or str(folder) == 'builtin':
        return builtin()
    folder = Path(folder or data_root() / 'factory-2.01')
    pointer = folder / 'current.json'
    if pointer.is_file():
        folder = folder / json.loads(pointer.read_text(encoding='utf-8'))['generation']
    report = json.loads((folder / 'reference.json').read_text(encoding='utf-8'))
    if report.get('model_code') != MODEL or report.get('version') != '2.01':
        raise ValueError('Select original ILCE-7CM2 firmware 2.01')
    values = {name: (folder / name).read_bytes() for name in FILES}
    if any(len(values[name]) != report['sizes'][name] for name in FILES):
        raise ValueError('Incomplete original firmware cache; prepare the Sony file again')
    if values['appFw.so'][:4] != b'\x7fELF' or values['appFw.so'][18:20] != b'\xb7\x00':
        raise ValueError('Original application must be AArch64 ELF')
    return values


def builtin():
    return json.loads((ROOT / 'src/looks/assets/factory-regions-2.01.json').read_text(encoding='utf-8'))


@contextmanager
def firmware(source):
    """Open a user-supplied official file locally; never download or contact USB."""
    sys.path.insert(0, str(ROOT / 'src/desktopapp/vendor'))
    from fwtool.sony import dat, fdat
    print('正在解码原厂文件，仅操作电脑文件…', flush=True)
    with source.open('rb') as stream, tempfile.TemporaryFile() as decoded:
        if stream.read(8) == fdat.fdatHeaderMagic:
            stream.seek(0)
            contents = fdat.readFdat(stream)
            cipher = 'decrypted-FDAT'
            plain = stream
        else:
            stream.seek(0)
            outer = dat.readDat(stream)
            cipher, plain = fdat.decryptFdat(outer.firmwareData)
            header = fdat.FdatHeader.unpack(plain)
            contents = type('Header', (), {'model': header.model,
                'version': '%x.%02x' % (header.versionMajor, header.versionMinor)})()
        if contents.model != MODEL or contents.version != '2.01':
            raise ValueError('Wrong Sony model or version; expected ILCE-7CM2 2.01')
        # Keep streams seekable for the nested tar/filesystem readers.
        plain.seek(0)
        count, last = 0, time.monotonic()
        while block := plain.read(4 * 1024 * 1024):
            decoded.write(block)
            count += len(block)
            if time.monotonic() - last >= 5:
                print('原厂文件已解码 %.0f MiB' % (count / 1048576), flush=True)
                last = time.monotonic()
        decoded.seek(0)
        contents = fdat.readFdat(decoded)
        yield contents, cipher


def prepare(source, cache=None):
    source = Path(source).expanduser().resolve()
    cache = Path(cache or data_root() / 'factory-2.01')
    if source.is_dir():
        load(source)
        return {'cache': str(source), 'camera_io': False}
    sys.path.insert(0, str(ROOT / 'src/desktopapp/vendor'))
    from fwtool.archive import ext2, fat
    cache.mkdir(parents=True, exist_ok=True)
    generation = 'sony-2.01-' + uuid.uuid4().hex[:12]
    folder = cache / generation
    folder.mkdir()
    with firmware(source) as (contents, cipher):
        with tarfile.open(fileobj=contents.firmware, mode='r:') as archive:
            for member in archive:
                if not member.isfile():
                    continue
                base = member.name.rsplit('/', 1)[-1]
                if base in FILES:
                    with (folder / base).open('wb') as out:
                        shutil.copyfileobj(archive.extractfile(member), out)
                elif member.name.startswith('0700_part_image/') and member.size:
                    image = archive.extractfile(member)
                    reader = ext2.readExt2 if ext2.isExt2(image) else fat.readFat if fat.isFat(image) else None
                    if reader:
                        for entry in reader(image):
                            name = entry.path.rsplit('/', 1)[-1]
                            if stat.S_ISREG(entry.mode) and name in FILES:
                                with (folder / name).open('wb') as out:
                                    entry.contents.seek(0)
                                    shutil.copyfileobj(entry.contents, out)
                if all((folder / name).is_file() for name in FILES):
                    break
    if not all((folder / name).is_file() for name in FILES):
        raise ValueError('Sony archive lacks required original programs/settings')
    report = {'model_code': MODEL, 'version': '2.01', 'decoder': cipher,
              'sizes': {name: (folder / name).stat().st_size for name in FILES}}
    write_json(folder / 'reference.json', report)
    load(folder)
    write_json(cache / 'current.json', {'generation': generation})
    return {'cache': str(cache), 'model': 'ILCE-7CM2', 'firmware': '2.01', 'camera_io': False}
