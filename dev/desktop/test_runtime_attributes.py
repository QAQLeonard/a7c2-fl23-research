"""Native look setting copies are selected settings, not arbitrary exceptions."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import json
import struct

import pytest

from looktool import devicesettings,direct,runtimebindings,settingsresume
from looktool.devicesession import modules
from test_checkpoint import Prop,Camera,KEYS,values
from test_direct import SimDirect


def record_fixture(key=0x02cf1287,value=10):
    return [{key:Prop(bytes([value]),0x60),key+1:Prop(bytes(13),0xc0),
             0x02cf4000:Prop(b'\x03',0x40)},
            {key:Prop(b'\x07',8) for key in devicesettings.PROTECTED}]


@pytest.mark.parametrize('key,value',[(0x02cf1287,10),(0x02cf1289,11),
    *[(0x02cf0cd0+2*i,0) for i in range(6)]])
def test_only_selected_setting_copies_can_take_the_selected_value(key,value):
    before=record_fixture(key,value)
    if value==0:before[0][key+1]=Prop(bytes([8])*13,0xc0)
    after=deepcopy(before);data=bytearray(after[0][key+1].data)
    data[0]=data[5]=value;after[0][key+1]=Prop(bytes(data),0xc0)
    core=modules()[1]
    with pytest.raises(ValueError,match='額外設定變動'):
        devicesettings.compare(before,after,{},core)
    changes=runtimebindings.setting_array_changes(before,after,{key:value})
    assert changes=={key+1:bytes(data)}
    devicesettings.compare(before,after,{k:v.hex() for k,v in changes.items()},core)
    assert bytes(data)[1:5]==before[0][key+1].data[1:5]


@pytest.mark.parametrize('fault',['wrong_value','size','attr','unselected','calibration'])
def test_other_values_other_slots_and_calibration_still_fail(fault):
    key=0x02cf1287;before=record_fixture();after=deepcopy(before)
    if fault=='wrong_value':after[0][key+1]=Prop(b'\x0b'+bytes(12),0xc0)
    elif fault=='size':after[0][key+1]=Prop(b'\x0a'+bytes(11),0xc0)
    elif fault=='attr':after[0][key+1]=Prop(b'\x0a'+bytes(12),0x40)
    elif fault=='unselected':after[0][0x02cf4000]=Prop(b'\x04',0x40)
    else:after[1][devicesettings.PROTECTED[0]]=Prop(b'\x08',8)
    with pytest.raises(ValueError):
        changes=runtimebindings.setting_array_changes(before,after,{key:10})
        devicesettings.compare(before,after,{k:v.hex() for k,v in changes.items()},modules()[1])


def test_outer_settings_verification_accepts_the_same_owned_copies(tmp_path):
    key=0x02cf1287;before=record_fixture();after=deepcopy(before)
    after[0][key+1]=Prop(b'\x0a'+bytes(12),0xc0)
    job=direct.DirectJob(tmp_path)
    expected={(0,key):b'\x0a'}
    with pytest.raises(ValueError):
        modules()[1].verify_preservation(before,after,job.settings_readback_expected(before,after,expected))
    job._synced_look_bases={key:10}
    allowed=job.settings_readback_expected(before,after,expected)
    assert allowed[(0,key+1)]==b'\x0a'+bytes(12)
    modules()[1].verify_preservation(before,after,allowed)


@pytest.mark.parametrize('saved_changes',[False,True])
def test_sync_accepts_only_owned_array_updates_in_both_backup_views(tmp_path,saved_changes):
    key=0x02cf1287;initial=record_fixture();actual=[deepcopy(initial),deepcopy(initial)]
    owner=SimpleNamespace(root=tmp_path,zig=None,state={'journal':[]},_runtime_binding_ap=b'fixture',
        record=lambda *args,**kwargs:None,raw=lambda *args:None)
    camera=SimpleNamespace(property_read=lambda key:b'\x0a',snapshot=lambda memory:actual[0 if memory else 1],
        records=lambda raw:raw,core=modules()[1])
    selected=[dict(key=key,index=16,value=10)]
    def build(*args):
        blob=tmp_path/'native.so';blob.write_bytes(b'synthetic-worker');return dict(path=str(blob))
    def invoke(*args,**kwargs):
        actual[0][0][key+1]=Prop(b'\x0a'+bytes(12),0xc0)
        if saved_changes:actual[1][0][key+1]=Prop(b'\x0a'+bytes(12),0xc0)
        return dict(targets=selected)
    with patch.object(runtimebindings,'targets',return_value=selected),patch.object(runtimebindings,'build',side_effect=build),\
            patch.object(runtimebindings,'invoke',side_effect=invoke):
        result=runtimebindings.sync(camera,owner,{key:b'\x0a'},expected=(initial,initial))
    assert owner._synced_look_bases=={key:10}
    assert result['setting_array_updates'][0]['keys']==[hex(key+1)]
    assert result['setting_array_updates'][1]['keys']==([hex(key+1)] if saved_changes else [])


def completed_array_failure():
    before=list(range(10))+[0]*8;after=before[:];after[16]=10;after[17]=11
    result=dict(before=before,after=after,current=13,changed_mask=(1<<16)|(1<<17),
        targets=[dict(key=0x02cf1287,index=16,value=10),dict(key=0x02cf1289,index=17,value=11)])
    tail=[dict(event=e,stage='lut-runtime-staged.so',mode=1) for e in [
        'native_stage_intent','native_intent','native_extra_result','native_result_verified','native_cleanup_verified']]
    tail[3]['result']=result
    return dict(schema='a7c2-direct-job/1',mode='install_all',phase='NEEDS_REVIEW',
        failed_during='RESTORING_SETTINGS',error='發現額外設定變動：chip0/0x2cf1288，請保存紀錄後檢查',
        program_builds=[dict(windows=65),dict(windows=47)],bundle_options={},identity={'model':'ILCE-7CM2'},
        journal=[dict(event='native_result_verified',stage='checkpoint.staged.so',mode=1,result=dict(windows=n))
                 for n in [65,47]]+[dict(event='complete_program_and_name_bytes_verified')]+tail)


@pytest.mark.parametrize('fault',['none','no_readback','no_cleanup','unknown_after','wrong_report',
                                 'unrelated_key','program_incomplete','wrong_mode'])
def test_only_the_completed_72_failure_can_continue(fault):
    state=completed_array_failure()
    if fault=='no_readback':state['journal']=[e for e in state['journal'] if e['event']!='complete_program_and_name_bytes_verified']
    if fault=='no_cleanup':state['journal'].pop()
    if fault=='unknown_after':state['journal'].append(dict(event='native_intent',mode=1))
    if fault=='wrong_report':state['journal'][-2]['result']={}
    if fault=='unrelated_key':state['error']='chip0/0x2cf4000'
    if fault=='program_incomplete':state['program_builds'].append(dict(windows=3))
    if fault=='wrong_mode':state['mode']='factory_reset'
    assert settingsresume.eligible(state)==(fault=='none')


@pytest.mark.parametrize('changed',['none','program','name'])
@pytest.mark.parametrize('cleanup_pending',[False,True])
@pytest.mark.parametrize('rejected_key',[0x02cf1288,0x02cf191c,0x02cf191d,0x02cf196f,0x02cf1970,
    0x02cf1492,0x02cf1494,0x02cf1496,0x02cf1498,0x02cf149a,0x02cf149c])
def test_settings_continuation_cannot_invoke_program_or_name_writers(tmp_path,changed,cleanup_pending,rejected_key):
    old=tmp_path/'old';old.mkdir();state=completed_array_failure()
    state['error']='發現額外設定變動：chip0/'+hex(rejected_key)
    if cleanup_pending:
        state.update(names_cleanup_pending=True,forward_name_build={'marker':'previous-name-transaction'})
        (old/'names').mkdir();(old/'names/names.private.h').write_bytes(b'private-native-header')
    camera=Camera(values());state['identity']=camera.identity
    (old/'direct.private.json').write_text(json.dumps(state))
    class Job(SimDirect):
        def native(self,camera,kind,mode,build=None):
            assert kind not in ('program','names','purge')
            return super().native(camera,kind,mode,build)
    job=Job(tmp_path/'continue',factory=lambda expected=None:camera)
    before=deepcopy(camera.files)
    def plan(current,records,options,rows):
        target=dict(current)
        if changed=='program':target['appFw.so']=b'X'+current['appFw.so'][1:]
        if changed=='name':
            name=next(n for n in current if n.startswith('resources/'));target[name]=b'changed'
        return target,[{KEYS[2]:b'\x03'},{}],None
    with patch('looktool.bundle.documents',return_value=({},[])),patch('looktool.bundle.plan',side_effect=plan):
        if changed=='none':
            result=job.resume_install_settings(old,power_confirmed=True)
            assert result['phase']=='AWAITING_RELOAD'
            assert camera.ram[0][KEYS[2]].data==b'\x03'
            if cleanup_pending:
                assert result['names_cleanup_pending'] is True
                assert (job.root/'names/names.private.h').read_bytes()==b'private-native-header'
        else:
            with pytest.raises(direct.ContentChanged):job.resume_install_settings(old,power_confirmed=True)
            assert not camera.saves and camera.native_calls==[]
    assert camera.files==before


def test_one_click_routes_72_to_settings_only_and_keeps_original_job(tmp_path):
    from desktopapp import allinone
    root=tmp_path/'setup';old=root/'install';old.mkdir(parents=True)
    state=completed_array_failure();path=old/'direct.private.json';path.write_text(json.dumps(state));original=path.read_bytes()
    (root/'setup.private.json').write_text(json.dumps(dict(schema='a7c2-one-click/1',phase='NEEDS_REVIEW',
        options={},install_workspace=str(old),completed_steps=['drivers'])))
    calls=[]
    def dispatch(action,args,step):
        calls.append(action)
        assert action=='direct_resume_settings'
        assert args['failed_workspace']==str(old)
        return dict(workspace=args['workspace'],phase='AWAITING_RELOAD',mode='install_all')
    result=allinone.run(dict(workspace=str(root),firmware='2.01',power_confirmed=True),dispatch=dispatch)
    assert result['phase']=='WAIT_RELOAD' and calls==['direct_resume_settings']
    assert path.read_bytes()==original


def test_one_click_can_retry_when_settings_dispatch_never_created_its_child(tmp_path):
    from desktopapp import allinone
    root=tmp_path/'setup';old=root/'install';old.mkdir(parents=True)
    (old/'direct.private.json').write_text(json.dumps(completed_array_failure()))
    (root/'setup.private.json').write_text(json.dumps(dict(schema='a7c2-one-click/1',phase='NEEDS_REVIEW',
        options={},install_workspace=str(old),completed_steps=['drivers'])))
    args=dict(workspace=str(root),firmware='2.01',power_confirmed=True)
    with pytest.raises(OSError):allinone.run(args,dispatch=lambda *a:(_ for _ in ()).throw(OSError('launch failed')))
    calls=[]
    def dispatch(action,arguments,folder):
        calls.append(action);assert arguments['failed_workspace']==str(old)
        return dict(workspace=arguments['workspace'],phase='AWAITING_RELOAD')
    assert allinone.run(args,dispatch=dispatch)['phase']=='WAIT_RELOAD'
    assert calls==['direct_resume_settings']


def test_changed_body_in_settings_continuation_never_falls_back_to_reinstall(tmp_path):
    from desktopapp import allinone
    root=tmp_path/'setup';child=root/'install-settings-1';child.mkdir(parents=True)
    (child/'direct.private.json').write_text(json.dumps(dict(schema='a7c2-direct-job/1',mode='install_all',
        phase='NEEDS_REVIEW',failed_during='READING',settings_resume_from=str(root/'install'),
        error='Saved install programs changed',journal=[])))
    (root/'setup.private.json').write_text(json.dumps(dict(schema='a7c2-one-click/1',phase='NEEDS_REVIEW',
        options={},install_workspace=str(child),resume_settings_from=str(root/'install'),completed_steps=['drivers'])))
    calls=[]
    with pytest.raises(ValueError):
        allinone.run(dict(workspace=str(root),firmware='2.01',power_confirmed=True),
            dispatch=lambda *args:calls.append(args))
    assert calls==[]
