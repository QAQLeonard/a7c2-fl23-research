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
import base64
import zlib
from hashlib import sha256
from .paths import ROOT, data_root, write_json

MODEL = 0x20030014
FILES = ('appFw.so', 'cpapp-b.bin', 'CX89700_ALLLANG.bin')


def load(folder=None):
    if folder is None or str(folder) == 'builtin':
        raise ValueError('请提供本地原厂恢复来源；软件不再内置原厂恢复字节')
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


def layout():
    return json.loads((ROOT/'src/looks/assets/factory-layout-2.01.json').read_text(encoding='utf-8'))


def regions(values,*,identity=None,settings=None):
    """Take only declared original regions from a user-provided local source."""
    from looktool.devicesession import modules
    result=layout();result['schema']='a7c2-factory-regions/1'
    def fill(rows,raw):
        for row in rows:
            value=raw[row['offset']:row['offset']+row['bytes']]
            if len(value)!=row['bytes'] or sha256(value).hexdigest()!=row['sha256']:
                raise ValueError('恢复来源不是可用的原厂区域，请选择官方 2.01 固件；普通当前状态备份不一定可用。')
            row['zlib_base64']=base64.b64encode(zlib.compress(value,9)).decode('ascii')
    for name,spec in result['programs'].items():
        if len(values[name])!=spec['bytes']:raise ValueError('Original program size differs: '+name)
        fill(spec['regions'],values[name])
    records=modules()[1].backup_records(settings if settings is not None else values['CX89700_ALLLANG.bin'])
    for key,rows in result['color_units'].items():fill(rows,records[1][int(key)].data)
    if identity:result['source_identity']=identity
    return result


def load_restore(path):
    path=Path(path)
    if path.is_file() and path.suffix.lower()=='.json':
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('schema')!='a7c2-factory-regions/1':raise ValueError('Invalid local recovery reference')
        expected=layout()
        if (value.get('model'),value.get('version'))!=(expected['model'],expected['version']):
            raise ValueError('Local recovery source model/version differs')
        pairs=[(value['programs'][name]['regions'],spec['regions']) for name,spec in expected['programs'].items()]
        pairs.extend((value['color_units'][key],rows) for key,rows in expected['color_units'].items())
        for actual,rows in pairs:
            if len(actual)!=len(rows):raise ValueError('Local recovery source layout differs')
            for row,wanted in zip(actual,rows):
                raw=zlib.decompress(base64.b64decode(row['zlib_base64']))
                if (row['offset'],row['bytes'])!=(wanted['offset'],wanted['bytes']) or len(raw)!=wanted['bytes'] or sha256(raw).hexdigest()!=wanted['sha256']:
                    raise ValueError('Local recovery source contents differ')
        return value
    return regions(load(path))


def prepare_restore(arguments):
    """Prepare all recovery inputs before opening USB; never bundle originals."""
    from . import screenreader
    source=arguments.get('sony_firmware')
    backup=arguments.get('backup')
    if source:
        cache=prepare(source)['cache'];value=regions(load(cache))
        voice=screenreader.prepare(source)['source'] if arguments.get('restore_voice',True) else None
    elif backup:
        from looktool import checkpoint
        manifest,values=checkpoint.load_target(backup)
        value=regions(values,identity=manifest['identity'],settings=values['settings-saved.bin'])
        voice=screenreader.restore_source(dict(backup=backup)) if arguments.get('restore_voice',True) else None
        if arguments.get('restore_voice',True) and not voice:
            raise ValueError('所选备份没有语音包。请选择官方固件、带语音 ZIP 的同机原始备份，或取消勾选“同时恢复语音包”。')
    elif arguments.get('factory') and arguments['factory']!='builtin':
        value=load_restore(arguments['factory']);voice=None
    else:
        raise ValueError('一键恢复需要原厂恢复来源。请选择官方 ILCE-7CM2 2.01 BODYDATA.DAT，或可用同机原始备份；安装不要求预先提供。')
    folder=data_root()/'recovery-sources'/uuid.uuid4().hex;folder.mkdir(parents=True)
    path=folder/'reference.private.json';write_json(path,value)
    return value,str(path),voice


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
