"""Factory recovery frees independent portrait resources before voice copying."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import pytest
from looktool import verticalresources,verticalpersist,direct,checkpointjob,resourceworker
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src/vertical'))


@pytest.mark.parametrize('failure',[False,True])
def test_native_portrait_release_saves_off_then_stops_runtime_before_delete(tmp_path,failure):
    from verticaltool import device,nativeportrait
    events=[];owner=MagicMock();targets=[b'body0',b'body1',b'body2']
    camera=MagicMock()
    camera.read.side_effect=lambda path,missing=False:targets[device.ALIASES.index(path)] if path in device.ALIASES else b'horizontal'
    camera.snapshot.side_effect=lambda memory:b'after-ram' if memory else b'after-saved'
    camera.records.return_value=[{},{}]
    current={'appFw.so':b'AP','settings-ram.bin':b'before-ram','settings-saved.bin':b'before-saved'}
    worker=MagicMock();worker.probe.return_value={'value':0}
    worker.ram.side_effect=lambda value:events.append(('running',value))
    def remove(obj):
        events.append(('delete',))
        if failure:raise OSError('read-only remount failed')
    with patch.object(nativeportrait,'owned',return_value=True), \
         patch.object(nativeportrait,'targets',return_value=targets), \
         patch.object(verticalpersist,'field',return_value={verticalpersist.SETTING:b'\1'}), \
         patch.object(direct.DirectJob,'settings',return_value='prepared'), \
         patch.object(checkpointjob.Rollback,'restore_settings',side_effect=lambda *args:events.append(('save-off',))), \
         patch.object(device,'Workers',return_value=worker), \
         patch.object(resourceworker.Resources,'delete',remove):
        if failure:
            with pytest.raises(OSError):verticalresources.release(camera,owner,current)
        else:
            assert verticalresources.release(camera,owner,current)
            assert current['settings-ram.bin']==b'after-ram'
    assert events==[('save-off',),('running',1),('delete',)]


def test_foreign_portrait_file_is_preserved_before_settings_change():
    from verticaltool import nativeportrait
    camera=MagicMock();camera.read.return_value=b'foreign';owner=MagicMock()
    with patch.object(nativeportrait,'owned',return_value=True), \
         patch.object(nativeportrait,'targets',return_value=[b'expected']*3), \
         patch.object(checkpointjob.Rollback,'restore_settings') as write:
        with pytest.raises(ValueError,match='Unaccounted'):verticalresources.release(camera,owner,{})
    write.assert_not_called()


@pytest.mark.parametrize('wrong_body',[False,True])
def test_voice_source_is_validated_before_releasing_any_portrait_space(wrong_body):
    from desktopapp import screenreader
    from looktool import checkpoint
    events=[];camera=SimpleNamespace(identity={'model':'ILCE-7CM2'})
    def match(*args):
        events.append('validate-body')
        if wrong_body:raise ValueError('different body')
    with patch.object(screenreader,'load',return_value={'identity':camera.identity,'files':{}}), \
         patch.object(checkpoint,'same_body',side_effect=match), \
         patch.object(resourceworker.Resources,'restore',side_effect=lambda *args:events.append('copy-voice')):
        if wrong_body:
            with pytest.raises(ValueError):resourceworker.restore_voice(camera,None,'source',before_restore=lambda:events.append('release-space'))
            assert events==['validate-body']
        else:
            resourceworker.restore_voice(camera,None,'source',before_restore=lambda:events.append('release-space'))
            assert events==['validate-body','release-space','copy-voice']
