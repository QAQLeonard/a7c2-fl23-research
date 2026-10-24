"""All desktop sound buttons act on current data, not old task eligibility."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import re
import sys

import pytest
from desktopapp import worker
from desktopapp.actions import sound_state
from looktool import direct,checkpointworker

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src/shutter_sound'))
import boot_sound,boot_trial,sound_cli


@pytest.fixture(scope='module')
def stock_ap():
    ap=bytearray(boot_sound.PATH+len(boot_sound.OLD_PATH)+8)
    for at,old,new in boot_sound.expected_windows():ap[at:at+len(old)]=old
    ap[-1]=71
    return bytes(ap)


@pytest.mark.parametrize('kind',['stock','installed','partial'])
def test_restore_sound_reconstructs_only_owned_ap_windows_from_current_bytes(stock_ap,kind):
    current=bytearray(stock_ap)
    for i,(at,old,new) in enumerate(boot_sound.expected_windows()):
        if kind=='installed' or kind=='partial' and i%2:current[at:at+len(new)]=new
    before={'appFw.so':bytes(current),'cpapp-b.bin':b'current switch and unrelated CP bytes'}
    target,wanted,names=direct.plan(before,[{},{}],'sound_restore')
    assert target['appFw.so']==stock_ap and target['cpapp-b.bin']==before['cpapp-b.bin']
    assert wanted==[{},{}] and names is None


def test_restore_disables_boot_call_before_restoring_reader_windows(stock_ap,tmp_path):
    before={'appFw.so':boot_sound.patch(stock_ap,boot_sound.expected_windows()),'cpapp-b.bin':b'keep'}
    target={'appFw.so':stock_ap,'cpapp-b.bin':b'keep'}
    def compile(source,header,path,*args,**kwargs):Path(path).write_bytes(b'compiled')
    with patch.object(checkpointworker,'compile_worker',side_effect=compile):
        checkpointworker.build_programs(before,target,tmp_path,window_priority=boot_sound.restore_priority)
    text=(tmp_path/'program-0.private.h').read_text()
    rows=re.search(r'windows\[\]=\{(.*?)\};',text).group(1)
    offsets=[int(n) for n in re.findall(r'\{(\d+)UL,',rows)]
    assert boot_sound.BOOT<=offsets[0]<boot_sound.BOOT+16


@pytest.mark.parametrize('custom',[False,True])
def test_current_state_probe_compiles_and_reads_stock_or_custom_without_a_job(stock_ap,tmp_path,custom):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'shutter_sound'))
    from verify_probe import execute
    ap=boot_sound.patch(stock_ap,boot_sound.expected_windows()) if custom else stock_ap
    path=boot_trial.current_probe(ap,tmp_path/'probe')
    headers={at:ap[at:at+len(old)] for at,old,new in boot_sound.expected_windows()}
    result=execute(path,ap,extra_headers=headers,decode=boot_trial.candidate.parse_probe)
    assert result['model_index']==16


@pytest.mark.parametrize('action,mode',[('sound_on','sound_enable'),('sound_off','sound_disable'),('sound_restore_sound','sound_reset')])
def test_desktop_switch_and_restore_ignore_missing_or_unreadable_old_job(tmp_path,action,mode):
    root=tmp_path/'sound';root.mkdir();(root/'sound.private.json').write_text('unreadable old state')
    job=tmp_path/'run';job.mkdir()
    with patch.object(direct.DirectJob,'run_direct',return_value=dict(mode=mode,phase='AWAITING_RELOAD')) as run:
        result=worker.run(action,dict(workspace=str(root),firmware='2.01',power_confirmed=True),job)
    assert run.call_args.args[0]==mode and result['reload_required']
    assert (root/'sound.private.json').read_text()=='unreadable old state'
    if action=='sound_restore_sound':assert result['phase']=='restored_cold_test_pending'


def test_current_verify_uses_no_saved_installation_record(tmp_path):
    root=tmp_path/'sound';root.mkdir();(root/'sound.private.json').write_text('unreadable old state')
    class Camera:
        identity=dict(model='ILCE-7CM2',serial_sha256='fixture')
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,path,missing=False):return None if missing else b'current program'
        def temp_read(self,name,missing=False):return None
    path=tmp_path/'probe';path.write_bytes(b'read-only probe')
    with patch('trial.factory',return_value=Camera()),patch('candidate.is_enabled',return_value=False), \
         patch('candidate.guard'),patch('candidate.sound_state',return_value='off'),patch('candidate.require_registry'),patch('boot_sound.installed',return_value=False), \
         patch('boot_trial.current_probe',return_value=path),patch('looktool.devicesession.invoke',return_value={}), \
         patch.object(sound_cli,'verify',side_effect=AssertionError('No old-job verifier')):
        result=worker.run('sound_verify',dict(workspace=str(root),accepted=False),tmp_path)
    assert result['loaded_code_and_current_descriptor_verified'] and not result['camera_firmware_written']
    assert (root/'sound.private.json').read_text()=='unreadable old state'


@pytest.mark.parametrize('options',[['--decibels','3'],['--decibels','-3'],['--reset']])
def test_volume_buttons_ignore_unresolved_camera_tasks(tmp_path,options):
    import native_codec
    source=tmp_path/'sound.wav'
    native_codec.write_wav(source,[0,3000,-3000,6000]*600,24000)
    root=tmp_path/'sound';sound_cli.import_audio(root,None,source,duration=.08)
    state=dict(schema=sound_cli.SCHEMA,pending=dict(command='install',job='missing-old-job'),history=[])
    sound_cli.save(root,state);before=(root/'sound.private.json').read_bytes();reports=[]
    assert sound_cli.main(['volume','--workspace',str(root),*options],report=reports.append)==0
    assert reports[0]['camera_io'] is False and (root/'sound.private.json').read_bytes()==before


@pytest.mark.parametrize('command',['audio','recovery'])
def test_optional_confirmation_does_not_require_a_previous_task(tmp_path,command):
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    state.update(audio_job=str(root/'missing'),pending=dict(command='old',job='missing'))
    result=(sound_cli.confirm_audio(root,state,'correct') if command=='audio' else sound_cli.confirm_recovery(root,state))
    assert result['camera_io'] is False and state['pending'] is None
