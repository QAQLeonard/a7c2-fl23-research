"""User-supplied voice restoration source; synthetic files and no camera I/O."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import stat
import tarfile
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from desktopapp import official, screenreader


def entries():
    return [SimpleNamespace(path=screenreader.SOURCE_ROOT+name, size=len(name),
                            mode=stat.S_IFREG|0o644, contents=BytesIO(name.encode()))
            for name in screenreader.NAMES]


def manifest(tmp_path):
    rows=screenreader.extract(entries(),tmp_path)
    value=dict(schema=screenreader.SCHEMA,model='ILCE-7CM2',version='2.01',files=rows)
    (tmp_path/'source.private.json').write_text(json.dumps(value))
    return value


def test_complete_source_preserves_bytes_and_contains_no_programs(tmp_path):
    value=manifest(tmp_path)
    assert screenreader.load(tmp_path)==value
    assert len(value['files'])==20
    assert {p.name for p in tmp_path.iterdir()}==set(screenreader.NAMES)|{'source.private.json'}
    for name in screenreader.NAMES:
        assert (tmp_path/name).read_bytes()==name.encode()


@pytest.mark.parametrize('fault',['missing','symlink','duplicate','truncated','oversized','traversal'])
def test_bad_source_never_becomes_complete(tmp_path,fault):
    rows=entries()
    if fault=='missing':rows.pop()
    elif fault=='symlink':rows[0].mode=stat.S_IFLNK|0o777
    elif fault=='duplicate':rows.append(rows[0])
    elif fault=='truncated':rows[0].size+=1
    elif fault=='oversized':rows[0].size=41*1024*1024
    else:rows[0].path=screenreader.SOURCE_ROOT+'../english.bin'
    with pytest.raises(ValueError):screenreader.extract(rows,tmp_path)
    assert not (tmp_path.parent/'english.bin').exists()


@pytest.mark.parametrize('fault',['model','version','file','path'])
def test_changed_cache_is_rejected_before_restore(tmp_path,fault):
    value=manifest(tmp_path)
    if fault=='model':value['model']='ILCE-7CR'
    elif fault=='version':value['version']='2.00'
    elif fault=='file':(tmp_path/screenreader.NAMES[0]).write_bytes(b'changed')
    else:value['files'][screenreader.NAMES[0]]['camera_path']='/usr/lib/appFw.so'
    (tmp_path/'source.private.json').write_text(json.dumps(value))
    with pytest.raises(ValueError):screenreader.load(tmp_path)


def test_failed_preparation_preserves_old_source_and_input(tmp_path):
    source=tmp_path/'BODYDATA.DAT';source.write_bytes(b'user original')
    cache=tmp_path/'cache';cache.mkdir();old=cache/'old-source';old.mkdir()
    (old/'original').write_bytes(b'keep')
    @contextmanager
    def wrong_file(path):
        raise ValueError('Wrong Sony model or version')
        yield
    with patch.object(official,'firmware',wrong_file),pytest.raises(ValueError):
        screenreader.prepare(source,cache)
    assert source.read_bytes()==b'user original'
    assert list(cache.iterdir())==[old]
    assert (old/'original').read_bytes()==b'keep'


def test_preparation_publishes_only_complete_local_resources(tmp_path):
    source=tmp_path/'BODYDATA.DAT';source.write_bytes(b'user original')
    archive=BytesIO()
    with tarfile.open(fileobj=archive,mode='w') as stream:
        member=tarfile.TarInfo('0700_part_image/dev/nflasha15');member.size=4
        stream.addfile(member,BytesIO(b'ext2'))
    @contextmanager
    def firmware(path):
        archive.seek(0)
        yield SimpleNamespace(firmware=archive),'test-decoder'
    # Real extraction, publication and local readback; only the filesystem parser is substituted.
    import sys
    sys.path.insert(0,str(official.ROOT/'src/desktopapp/vendor'))
    from fwtool.archive import ext2
    with patch.object(official,'firmware',firmware),patch.object(ext2,'isExt2',return_value=True), \
         patch.object(ext2,'readExt2',return_value=entries()):
        result=screenreader.prepare(source,tmp_path/'cache')
    assert result['files']==20 and not result['camera_io'] and not result['camera_restored']
    folder=Path(result['source'])
    assert screenreader.load(folder)['decoder']=='test-decoder'
    assert list((tmp_path/'cache').iterdir())==[folder]
    assert source.read_bytes()==b'user original'


@pytest.mark.parametrize('model,version',[(0x20030015,'2.01'),(official.MODEL,'2.00')])
def test_wrong_firmware_stops_before_reading_voice_files(tmp_path,model,version):
    import sys
    sys.path.insert(0,str(official.ROOT/'src/desktopapp/vendor'))
    from fwtool.sony import fdat
    source=tmp_path/'decoded.bin';source.write_bytes(fdat.fdatHeaderMagic+b'header')
    with patch.object(fdat,'readFdat',return_value=SimpleNamespace(model=model,version=version)):
        with pytest.raises(ValueError,match='Wrong Sony model or version'):
            screenreader.prepare(source,tmp_path/'cache')
    assert list((tmp_path/'cache').iterdir())==[]
