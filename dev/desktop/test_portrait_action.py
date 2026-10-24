"""The explicit portrait test actions share power, driver and reload plumbing."""
from unittest.mock import patch,MagicMock
import pytest

from desktopapp import worker,jobs,reloadguide


@pytest.mark.parametrize('action,enabled',[('vertical_enable',True),('vertical_disable',False)])
def test_portrait_dispatch_prepares_drivers_and_uses_fresh_job(tmp_path,action,enabled):
    from looktool.portraitjob import PortraitJob
    from desktopapp import vertical_native
    from desktopapp.platforms import usb_drivers
    with patch.object(usb_drivers,'prepare',return_value={'camera_firmware_written':False}) as driver, \
         patch.object(PortraitJob,'run_frames',return_value={'phase':'AWAITING_RELOAD'}) as run, \
         patch.object(vertical_native,'run',return_value={'phase':'AWAITING_RELOAD'}) as native:
        result=worker.run(action,dict(workspace=str(tmp_path/'frames'),firmware='2.01',power_confirmed=True),tmp_path)
    driver.assert_called_once_with(tmp_path)
    if enabled:
        native.assert_called_once();run.assert_not_called()
    else:
        assert run.call_args.args==(enabled,)
        assert run.call_args.kwargs==dict(version='2.01',power_confirmed=True)
    assert action in jobs.CAMERA_ACTIONS and action in jobs.POWER_ACTIONS
    assert reloadguide.required(action,result)
    assert 'Fn' in reloadguide.text(mode='vertical_enable')


def test_frame_actions_require_power_before_driver_or_camera(tmp_path):
    from desktopapp.platforms import usb_drivers
    with patch.object(usb_drivers,'prepare') as driver,pytest.raises(ValueError):
        worker.run('vertical_enable',dict(workspace=str(tmp_path),firmware='2.01'),tmp_path)
    driver.assert_not_called()
