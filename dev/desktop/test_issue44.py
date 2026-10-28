"""Issue44 host persistence and precisely scoped session-field accounting."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import pytest
from desktopapp import jobs,paths
from looktool import backupstore,devicesession
import test_device_components as component_fixture

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture(params=('camera_runtime','fl23'))
def core(request):
    spec=importlib.util.spec_from_file_location('issue44_'+request.param,ROOT/'src'/request.param/'core.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize('key',(0x02cf191c,0x02cf191d,0x02cf196f,0x02cf1970))
def test_only_the_reported_32bit_session_fields_are_accounted_for(core,key):
    a=SimpleNamespace(attr=0,data=bytes(4));b=SimpleNamespace(attr=0,data=b'\xa1\1\0\0')
    assert core.verify_preservation([{key:a},{}],[{key:b},{}],{})['runtime_counters']==[hex(key)]
    for chip,other,a2,b2 in ((1,key,a,b),(0,0x02cf191e,a,b),
            (0,key,a,SimpleNamespace(attr=1,data=b.data)),
            (0,key,SimpleNamespace(attr=0,data=bytes(8)),SimpleNamespace(attr=0,data=bytes([1])*8))):
        assert not core.runtime_counter(chip,other,a2,b2)
    with pytest.raises(ValueError,match='目標設定讀回不符'):
        core.verify_preservation([{key:a},{}],[{key:b},{}],{(0,key):bytes(4)})


def test_known_runtime_counters_do_not_have_an_arbitrary_delta_limit(core):
    old=SimpleNamespace(attr=0,data=(9_000_000).to_bytes(8,'little'))
    reset=SimpleNamespace(attr=0,data=bytes(8))
    assert core.runtime_counter(0,0x01070000,old,reset)
    large=SimpleNamespace(attr=0,data=(20_000_000).to_bytes(8,'little'))
    assert core.runtime_counter(0,0x01070000,old,large)
    a=bytearray(256);b=bytearray(a);a[24:28]=b'\xff'*4
    assert core.runtime_counter(0,0x02780000,SimpleNamespace(attr=0,data=bytes(a)),SimpleNamespace(attr=0,data=bytes(b)))
    b[23]=1
    assert not core.runtime_counter(0,0x02780000,SimpleNamespace(attr=0,data=bytes(a)),SimpleNamespace(attr=0,data=bytes(b)))


@pytest.mark.parametrize('writer',(backupstore.write_json,paths.write_json))
def test_transient_host_replace_retries_the_same_complete_file(tmp_path,writer):
    path=tmp_path/'state.private.json';writer(path,{'phase':'old'})
    original=os.replace;attempts=[]
    def replace(source,target):
        attempts.append((Path(source),Path(target)))
        if len(attempts)<3:raise PermissionError(13,'temporary sharing denial')
        return original(source,target)
    with patch('os.replace',side_effect=replace),patch('time.sleep') as sleep:
        writer(path,{'phase':'new','中文':'完整'})
    assert len(attempts)==3 and len({p for p,_ in attempts})==1
    assert json.loads(path.read_text(encoding='utf-8'))['中文']=='完整'
    assert [call.args[0] for call in sleep.call_args_list]==[.05,.1]
    assert not list(tmp_path.glob('*.new'))


@pytest.mark.parametrize('writer',(backupstore.write_json,paths.write_json))
def test_persistent_host_denial_keeps_old_record_and_unpublished_evidence(tmp_path,writer):
    path=tmp_path/'state.private.json';writer(path,{'phase':'old'})
    with patch('os.replace',side_effect=PermissionError(13,'persistent denial')) as replace,patch('time.sleep'):
        with pytest.raises(PermissionError):writer(path,{'phase':'new'})
    assert replace.call_count==6
    assert json.loads(path.read_text(encoding='utf-8'))['phase']=='old'
    assert json.loads(next(tmp_path.glob('*.new')).read_text(encoding='utf-8'))['phase']=='new'


@pytest.mark.parametrize('published',[False,True])
def test_diagnostics_preserve_filtered_unpublished_journals(tmp_path,published):
    job=tmp_path/'job';job.mkdir();work=tmp_path/'work';work.mkdir()
    (job/'request.private.json').write_text(json.dumps(dict(action='direct_factory_reset',arguments=dict(workspace=str(work)))),encoding='utf-8')
    if published:(work/'direct.private.json').write_text(json.dumps(dict(phase='WRITING',journal=[])))
    pending=dict(phase='NEEDS_REVIEW',program_bytes='NEVER_EXPORT',journal=[dict(event='native_result_verified',mode=1,result=dict(windows=3,raw_program='NEVER_EXPORT'))])
    (work/'direct.private.json.unpublished.new').write_text(json.dumps(pending))
    values=jobs.transaction_summaries(job)
    row=next(value for name,value in values.items() if name.startswith('direct-pending-'))
    assert row['record_status']=='unpublished-host-journal'
    assert row['journal'][0]['mode']==1 and row['journal'][0]['result']['windows']==3
    assert 'NEVER_EXPORT' not in json.dumps(values)


def test_unconfirmed_model_probe_uses_only_its_actual_binary(tmp_path):
    assets=tmp_path/'assets';assets.mkdir();(assets/'runtime.so').write_bytes(b'read-only probe')
    camera=devicesession.Camera();camera.programs_pinned=True;camera.service_only=False;camera.identity_pending=True
    camera.core=SimpleNamespace(BASE=tmp_path,assets=Mock(side_effect=AssertionError('No unrelated manifest scan')))
    camera.link=Mock()
    camera.temp_write('lut-runtime-staged.so',b'read-only probe')
    assert camera.link.jiritsu.call_count==1
    for name,data in (('lut-runtime-staged.so',b'other worker'),('a7c2.install.request',b'read-only probe')):
        with pytest.raises(ValueError,match='pinned read-only'):camera.temp_write(name,data)
    assert camera.link.jiritsu.call_count==1


@pytest.mark.parametrize('persistent',[False,True])
def test_journal_lock_after_native_result_does_not_relaunch_the_device(tmp_path,persistent):
    camera=component_fixture.NativeInvocationTests.Camera()
    state=dict(journal=[]);raw=[];original=os.replace;locked=[0]
    def record(event,**values):
        state['journal'].append(dict(event=event,**values))
        backupstore.write_json(tmp_path/'direct.private.json',state)
    def replace(source,target):
        saved=json.loads(Path(source).read_text(encoding='utf-8'))
        if saved['journal'][-1]['event']=='native_result_verified' and (persistent or locked[0]<2):
            locked[0]+=1;raise PermissionError(13,'host journal lock')
        return original(source,target)
    def run():
        return devicesession.invoke(camera,b'worker',stage='lut-program-staged.so',request='a7c2.install.request',
            result='a7c2.install.result',contents=b'request',mode=1,decode=lambda data:dict(windows=2),record=record,save_raw=raw.append)
    with patch('os.replace',side_effect=replace),patch('time.sleep'):
        if persistent:
            with pytest.raises(PermissionError):run()
            assert not camera.healthy and 'a7c2.install.result' in camera.files
            assert list(tmp_path.glob('*.new'))
        else:
            assert run()['windows']==2
            assert camera.healthy and not camera.files
            assert state['journal'][-1]['event']=='native_cleanup_verified'
    assert camera.writes.count('libJit.so')==1 and raw==[b'valid report']
