"""Native portrait migration must finish resources before saving ON."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import pytest
from desktopapp import vertical_native
from looktool import direct,portraitjob,resourceworker,requestcleanup,verticalpersist
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src/vertical'))


@pytest.mark.parametrize('waiting',[False,True])
def test_legacy_cold_reload_boundary_precedes_all_resource_copies(tmp_path,waiting):
    camera=MagicMock();camera.identity={};camera.identity_pending=False
    camera.read.return_value=None
    camera.records.return_value=[{verticalpersist.SETTING:SimpleNamespace(data=b'\1')},{}]
    factory=MagicMock();factory.return_value.__enter__.return_value=camera
    with patch.object(requestcleanup,'supersede_temporary'), \
         patch.object(portraitjob.PortraitJob,'run_frames',return_value=dict(phase='AWAITING_RELOAD' if waiting else 'LOADED')), \
         patch('verticaltool.nativeportrait.targets',return_value=[b'bank0',b'bank1',b'bank2']), \
         patch.object(resourceworker,'Resources') as resources, \
         patch.object(vertical_native,'enable_current',return_value=dict(phase='AWAITING_RELOAD',native_portrait=True)) as enable:
        result=vertical_native.run(dict(workspace=str(tmp_path/'work'),firmware='2.01',power_confirmed=True),tmp_path,factory=factory)
    if waiting:
        assert result['migration_pending'];resources.assert_not_called();enable.assert_not_called()
    else:
        resources.return_value.restore.assert_called_once();enable.assert_called_once()


def test_failed_resource_copy_never_saves_vertical_on(tmp_path):
    camera=MagicMock();camera.identity={};camera.identity_pending=False;camera.read.return_value=None
    camera.records.return_value=[{verticalpersist.SETTING:SimpleNamespace(data=b'\1')},{}]
    factory=MagicMock();factory.return_value.__enter__.return_value=camera
    with patch.object(requestcleanup,'supersede_temporary'), \
         patch.object(portraitjob.PortraitJob,'run_frames',return_value=dict(phase='LOADED')), \
         patch('verticaltool.nativeportrait.targets',return_value=[b'0',b'1',b'2']), \
         patch.object(resourceworker.Resources,'restore',side_effect=OSError('ENOSPC')), \
         patch.object(vertical_native,'enable_current') as enable:
        with pytest.raises(OSError):vertical_native.run(dict(workspace=str(tmp_path/'work'),firmware='2.01',power_confirmed=True),tmp_path,factory=factory)
    enable.assert_not_called()


def test_native_switch_uses_existing_save_checks_without_names_or_program_writes(tmp_path):
    from test_checkpoint import Camera,Prop,values
    from test_direct import SimDirect
    from verticaltool import device
    camera=Camera(values())
    camera.ram[0][verticalpersist.SETTING]=Prop(b'\1',64)
    camera.saved[0][verticalpersist.SETTING]=Prop(b'\1',64)
    owner=SimDirect(tmp_path/'switch',factory=lambda:camera)
    owner.root.mkdir();owner.state=dict(mode='vertical_enable',journal=[],phase='READING')
    workers=MagicMock();workers.probe.return_value={'value':1}
    with patch.object(verticalpersist,'field',return_value={verticalpersist.SETTING:b'\0'}), \
         patch.object(device,'Workers',return_value=workers), \
         patch.object(resourceworker.Resources,'inspect',return_value={}), \
         patch.object(camera,'read',wraps=camera.read) as reads:
        result=vertical_native.enable_current(camera,owner,tmp_path)
        assert result['phase']=='AWAITING_RELOAD'
        assert camera.saved[0][verticalpersist.SETTING].data==b'\0'
        assert all('string_' not in call.args[0] for call in reads.call_args_list)
        assert all(kind not in ('program','names') for kind,mode in camera.native_calls)
        writes=list(camera.saves);workers.probe.return_value={'value':0}
        assert vertical_native.enable_current(camera,owner,tmp_path)['phase']=='LOADED'
        assert camera.saves==writes
