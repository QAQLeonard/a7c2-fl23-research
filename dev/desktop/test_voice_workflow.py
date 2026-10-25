"""Ordering and interruption boundaries for the optional voice resource workflow."""
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import pytest
from desktopapp import voicespace,screenreader
from looktool import direct,voicelock,resourceworker


@pytest.mark.parametrize('action',['voice_cleanup'])
def test_first_disable_phase_never_touches_voice_files(tmp_path,action):
    args=dict(workspace=str(tmp_path),firmware='2.01',power_confirmed=True,sony_firmware='user.DAT')
    with patch.object(screenreader,'restore_source',return_value='source'), \
         patch.object(screenreader,'load',return_value={}), \
         patch.object(direct.DirectJob,'run_direct',return_value=dict(phase='AWAITING_RELOAD')), \
         patch.object(resourceworker,'Resources') as resource:
        result=voicespace.run(action,args,tmp_path,factory=MagicMock())
    assert result['phase']=='AWAITING_RELOAD' and result['mode']=='voice_disable'
    resource.assert_not_called()


@pytest.mark.parametrize('failure',[False,True])
def test_cleanup_waits_for_disabled_settings_and_preserves_failure(tmp_path,failure):
    events=[]
    class Camera:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def snapshot(self,memory):return memory
        def records(self,raw):return [{voicelock.SETTING:SimpleNamespace(data=b'\1'),
                                     voicelock.TRIGGER:SimpleNamespace(data=b'\0')},{}]
    def run(owner,mode,**kwargs):
        events.append(mode);owner.state=dict(phase='LOADED',mode=mode,journal=[])
        return dict(phase='LOADED' if mode=='voice_disable' else 'AWAITING_RELOAD',identity={})
    def remove(resource):
        events.append('delete_files')
        if failure:raise TimeoutError('deletion interrupted')
    with patch.object(direct.DirectJob,'run_direct',run), \
         patch.object(resourceworker.Resources,'delete',remove):
        if failure:
            with pytest.raises(TimeoutError):voicespace.run('voice_cleanup',dict(workspace=str(tmp_path),firmware='2.01',power_confirmed=True),tmp_path,factory=Camera)
        else:
            result=voicespace.run('voice_cleanup',dict(workspace=str(tmp_path),firmware='2.01',power_confirmed=True),tmp_path,factory=Camera)
            assert result['voice_audio_removed'] and result['voice_menu_flags_verified']
    assert events==['voice_disable','delete_files']
