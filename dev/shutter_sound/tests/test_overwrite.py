"""Resource-only sound replacement and direct same-setting sound switches."""
import json
from pathlib import Path
import sys
from unittest.mock import patch,Mock
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import boot_trial,boot_sound,files_worker,sound_cli,trial


@pytest.mark.parametrize('name',['custom-shutter.bin','custom-shutter-a.bin','custom-shutter-b.bin'])
def test_supported_current_csv_maps_to_fixed_audio_slots(name):
    csv=boot_sound.CSV.replace(b'custom-shutter.bin',name.encode()).replace(b'0xEC0',b'0x80')
    assert boot_trial.current_sound(csv)==('/usr/share/avsystemsound/'+name,128)


def test_foreign_csv_is_not_used_as_a_path():
    with pytest.raises(ValueError):boot_trial.current_sound(boot_sound.CSV.replace(b'custom-shutter.bin',b'../../foreign'))


@pytest.mark.parametrize('same',[False,True])
@pytest.mark.parametrize('upgrade',[False,True])
def test_existing_hook_is_kept_and_audio_publication_precedes_csv(tmp_path,same,upgrade):
    root=tmp_path/'job';root.mkdir()
    old=bytes(64);payload=old if same else bytes([0,1])*64
    csv=boot_sound.CSV.replace(b'0xEC0',b'0x40')
    files={'/usr/lib/appFw.so':b'after-code','/cp/cpapp-b.bin':b'unchanged',
           boot_trial.PATHS[0]:old,boot_trial.PATHS[1]:csv}
    camera=Mock();camera.read.side_effect=lambda path,missing=False:files.get(path)
    before={'appFw.so':files['/usr/lib/appFw.so'],'cpapp-b.bin':files['/cp/cpapp-b.bin']}
    state={'identity':{},'journal':[]};events=[];workers={}
    def prepare(ap,cp,raw,output,zig):
        output.mkdir();audio=output/'audio';text=output/'csv';audio.write_bytes(raw);text.write_bytes(b'initial')
        target=dict(before,**({'cpapp-b.bin':b'new-selector'} if upgrade else {}))
        cp_windows=[dict(offset=100,before_hex=b'old'.hex(),after_hex=b'new'.hex())] if upgrade else []
        return target,dict(audio=str(audio),csv=str(text),probe='probe',wbi='wbi',windows=[],cp_windows=cp_windows)
    def build(audio,csv,path,zig=None,**kwargs):
        workers[str(path)]=(audio,csv,kwargs);return str(path)
    def invoke(camera,root,state,worker,mode):
        events.append(('files',mode))
        if mode:
            audio,csv,options=workers[str(worker)]
            assert files[boot_trial.PATHS[1]]!=csv
            files[options['audio_path']]=audio
            # At the publish point both the old and new referenced audio exist.
            assert files[boot_trial.PATHS[0]]==old
            files[boot_trial.PATHS[1]]=csv
    def native_call(camera,root,state,worker,kind,mode=0,plan=None):
        events.append((kind,mode))
        if kind=='program' and mode:
            files['/cp/cpapp-b.bin']=b'new-selector'
    with patch.object(boot_sound,'expected_windows',return_value=[]),patch.object(boot_sound,'patch',return_value=b'stock'), \
         patch.object(boot_trial,'prepare',side_effect=prepare),patch.object(boot_trial,'probe',return_value={'image_mode':'0'}), \
         patch.object(files_worker,'build',side_effect=build),patch.object(boot_trial,'invoke_files',side_effect=invoke), \
         patch.object(boot_trial,'check_settings'),patch.object(trial,'backup',return_value='small-backup'), \
         patch.object(boot_trial,'program_worker',return_value=dict(path='selector',windows=1,sizes=[10,10])), \
         patch.object(trial,'run_native',side_effect=native_call) as native:
        result=boot_trial.replace_connected(camera,before,root,tmp_path/'backup',state,payload,None)
    assert result['phase']=='installed_cold_test_pending' and result['camera_firmware_written']==upgrade
    assert files['/usr/lib/appFw.so']==before['appFw.so']
    assert files['/cp/cpapp-b.bin']==(b'new-selector' if upgrade else before['cpapp-b.bin'])
    if not upgrade:native.assert_not_called()
    assert events==([('program',0)] if upgrade else [])+([] if same else [('files',0),('files',1)])+([('program',1)] if upgrade else [])


def test_second_save_does_not_require_restoring_previous_persistent_sound(tmp_path):
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    native=root/'native';native.mkdir();trial.save(native,dict(phase='written',identity={},complete_readback_and_settings_verified=True,electronic_only_gate=True))
    old=root/'old';old.mkdir();trial.save(old,dict(phase='installed_cold_test_pending'))
    converted=root/'converted';converted.mkdir();(converted/'custom-native.private.bin').write_bytes(bytes(64))
    state.update(native_job=str(native),boot_job=str(old),conversion=str(converted))
    def adopt(job,*args,**kwargs):
        value=dict(phase='written',identity={},complete_readback_and_settings_verified=True,adopted_existing_enabled=True)
        Path(job).mkdir(parents=True);trial.save(job,value);return value
    with patch.object(trial,'preflight',side_effect=adopt),patch.object(boot_trial,'install',return_value=dict(phase='installed_cold_test_pending')) as install:
        assert sound_cli.install(root,state,None,power_confirmed=True)['phase']=='installed_cold_test_pending'
    install.assert_called_once()


@pytest.mark.parametrize('enabled',[False,True])
def test_sound_switch_plan_is_repeatable_and_preserves_other_bytes(enabled):
    from looktool import direct
    import candidate
    ap=b'unchanged-app';cp=bytearray(candidate.OFFSET+32)
    cp[candidate.SELECTOR_TABLE:candidate.SELECTOR_TABLE+5]=candidate.TABLE_BEFORE
    cp[candidate.GATE:candidate.GATE+20]=candidate.LEGACY_GATE if enabled else candidate.CONTEXT
    before={'appFw.so':ap,'cpapp-b.bin':bytes(cp)}
    with patch.object(candidate,'guard'):
        target,settings,_=direct.plan(before,[{},{}],'sound_enable')
        repeated,_,_=direct.plan(target,[{},{}],'sound_enable')
        off,_,_=direct.plan(repeated,[{},{}],'sound_disable')
        off_again,_,_=direct.plan(off,[{},{}],'sound_disable')
    assert target==repeated and off==off_again
    assert all(v=={} for v in settings)
    assert target['appFw.so']==off['appFw.so']==ap
    allowed={at+i for at,old,_ in candidate.WINDOWS for i in range(len(old))}
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(target['cpapp-b.bin'],before['cpapp-b.bin'])))
    assert candidate.sound_state(off['cpapp-b.bin'])=='mechanical_only'
