"""Native archive composition without PyInstaller, signing tools or USB."""
import importlib.util
import io
from pathlib import Path
from unittest.mock import patch
import zipfile
import pytest
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'dev/desktop'))
import profilepack


def library_fixture(root):
    from test_compile_dcp_offline import dcp
    from looktool import lookfile,rawidentity
    library=root/'desktop-assets/profile-library-v1';rows=[]
    for group,stem in profilepack.PAIRS:
        source=library/group/(stem+'.dcp');source.parent.mkdir(parents=True,exist_ok=True)
        dcp(source)
        output=source.with_suffix('.a7look')
        lookfile.write(output,'Fixture',bytes(1215),method='fixture',attribution='test',
            raw_profile=rawidentity.descriptor(source))
        rows.append(dict(dcp=source.relative_to(library).as_posix(),a7look=output.relative_to(library).as_posix(),
            independent_prediction=dict(RGB_MAE_8bit=0,RGB_P95_8bit=0)))
    import json
    (library/'catalog.json').write_text(json.dumps(dict(profiles=rows)))
    return library


def module(name):
    spec=importlib.util.spec_from_file_location('desktop_'+name,ROOT/('dev/desktop/'+name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


assets=module('prepare_assets')
build=module('build')


def test_pack_export_import_preserves_six_files_and_notices(tmp_path):
    before=tmp_path/'before';folder=before/'desktop-assets/presets/default-six-v1';folder.mkdir(parents=True)
    for name in assets.PRESET_NAMES:(folder/name).write_bytes(name.encode())
    library_fixture(before)
    (folder/'private-photo.ARW').write_bytes(b'not-distributable')
    archive=assets.export_presets(tmp_path/'presets.zip',before)
    after=assets.import_presets(archive,tmp_path/'after')
    assert sorted(p.name for p in after.iterdir())==sorted(assets.PRESET_NAMES)
    for name in assets.PRESET_NAMES:assert (after/name).read_bytes()==(folder/name).read_bytes()
    assert len(profilepack.files(tmp_path/'after'))==37


def test_existing_windows_zip_extracts_data_only(tmp_path):
    library_fixture(tmp_path/'fixture')
    source=io.BytesIO()
    with zipfile.ZipFile(source,'w') as z:
        for name in assets.PRESET_NAMES:z.writestr('A7C2Tools/_internal/desktop-assets/presets/default-six-v1/'+name,b'asset')
        z.writestr('A7C2Tools/A7C2Tools.exe',b'windows-executable')
        z.writestr('../../outside',b'not-data')
        for name,path in profilepack.files(tmp_path/'fixture').items():z.write(path,'A7C2Tools/Profiles/'+name)
    source.seek(0)
    target=assets.import_presets(source,tmp_path)
    assert len(list(target.iterdir()))==len(assets.PRESET_NAMES)
    assert not list(tmp_path.rglob('*.exe'))


def test_legacy_pack_license_is_optional_but_preserved_when_present(tmp_path):
    before=tmp_path/'before';folder=before/'desktop-assets/presets/default-six-v1'
    folder.mkdir(parents=True)
    for name in assets.PRESET_NAMES:(folder/name).write_bytes(name.encode())
    library_fixture(before)
    legacy=assets.OPTIONAL_PRESET_NAMES[0]
    (folder/legacy).write_bytes(b'original legacy license')
    archive=assets.export_presets(tmp_path/'presets.zip',before)
    after=assets.import_presets(archive,tmp_path/'after')
    assert (after/legacy).read_bytes()==b'original legacy license'


def test_missing_pack_notice_does_not_replace_existing_assets(tmp_path):
    target=tmp_path/'desktop-assets/presets/default-six-v1';target.mkdir(parents=True)
    (target/'slot1.a7look').write_bytes(b'existing')
    source=io.BytesIO()
    with zipfile.ZipFile(source,'w') as z:z.writestr('default-six-v1/slot1.a7look',b'incomplete')
    source.seek(0)
    with pytest.raises(KeyError):assets.import_presets(source,tmp_path)
    assert (target/'slot1.a7look').read_bytes()==b'existing'


def test_windows_output_path_unchanged(tmp_path):
    fixture=tmp_path/'fixture';library_fixture(fixture)
    exe=tmp_path/'A7C2Tools/A7C2Tools.exe';exe.parent.mkdir();exe.write_bytes(b'test')
    (exe.parent/'a7c2-diagnostics.zip').write_bytes(b'private local diagnostic')
    with patch.object(build,'profile_files',side_effect=lambda:profilepack.files(fixture)):
        result=build.make_windows_zip(tmp_path)
    assert result.name=='A7C2Tools-Windows-x64.zip'
    with zipfile.ZipFile(result) as z:
        assert z.read('A7C2Tools/A7C2Tools.exe')==b'test'
        assert len([n for n in z.namelist() if n.endswith('.dcp')])==18
        assert len([n for n in z.namelist() if n.startswith('A7C2Tools/Profiles/') and n.endswith('.a7look')])==18
        assert not any('diagnostics' in n for n in z.namelist())


def test_build_library_rejects_missing_or_mismatched_pair(tmp_path):
    library=library_fixture(tmp_path)
    row=profilepack.PAIRS[0];source=library/row[0]/(row[1]+'.dcp')
    original=source.read_bytes();source.write_bytes(b'wrong DCP')
    with pytest.raises(ValueError,match='source differs'):profilepack.files(tmp_path)
    source.write_bytes(original);source.with_suffix('.a7look').unlink()
    with pytest.raises(FileNotFoundError):profilepack.files(tmp_path)


def test_mono_pairs_are_excluded_as_pairs_when_quality_is_insufficient(tmp_path):
    import json
    library=library_fixture(tmp_path);catalog=library/'catalog.json'
    doc=json.loads(catalog.read_text())
    mono=next(r for r in doc['profiles'] if (r['dcp'],r['a7look']) in profilepack.OPTIONAL)
    mono['independent_prediction']['RGB_MAE_8bit']=8.6
    catalog.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='Monochrome profile'):profilepack.files(tmp_path)
    doc['profiles']=[r for r in doc['profiles'] if (r['dcp'],r['a7look']) not in profilepack.OPTIONAL]
    catalog.write_text(json.dumps(doc))
    files=profilepack.files(tmp_path)
    assert len([name for name in files if name.endswith('.dcp')])==15
    assert len([name for name in files if name.endswith('.a7look')])==15


def test_dmg_has_fresh_staging_and_arch_specific_filename(tmp_path):
    app=tmp_path/'A7C2Tools.app';app.mkdir();(app/'file').write_bytes(b'app')
    old=tmp_path/'dmg-contents';old.mkdir();(old/'stale').write_bytes(b'stale')
    def command(args,**kwargs):
        if args[:2]==['hdiutil','create']:
            stage=Path(args[args.index('-srcfolder')+1])
            assert sorted(p.name for p in stage.iterdir())==['A7C2Tools.app','Applications']
            Path(args[-1]).write_bytes(b'dmg')
    def symlink(path,target,**kwargs):path.write_text(str(target))
    with patch.object(build.platform,'machine',return_value='arm64'), \
            patch.object(build.subprocess,'run',side_effect=command) as run, \
            patch.object(Path,'symlink_to',symlink):
        result=build.make_dmg(tmp_path)
    assert result.name=='A7C2Tools-macOS-arm64.dmg'
    assert not list(tmp_path.glob('a7c2-dmg-*'))
    assert run.call_args.args[0]==['hdiutil','verify',str(result)]
