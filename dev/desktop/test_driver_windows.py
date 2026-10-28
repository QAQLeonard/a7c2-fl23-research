"""Driver preparation timing, early elevation and PnP-only arrivals; no USB."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from desktopapp.platforms import usb_drivers as drivers,windows_pnp
from looktool import devicesession

transport,_=devicesession.modules()


def clock(monkeypatch):
    now=[0.0]
    monkeypatch.setattr(transport.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(transport.time,'sleep',lambda seconds:now.__setitem__(0,now[0]+seconds))
    monkeypatch.setattr(transport,'SERVICE_DRIVER_PRESENT',None)
    return now


def test_driver_installation_does_not_exhaust_the_rebind_budget(monkeypatch):
    now=clock(monkeypatch);device=object();attempts=[]
    monkeypatch.setattr(transport,'_sony_pids',lambda:['0336'])
    def setup():now[0]+=30
    def open_device(pid):
        attempts.append(now[0])
        if now[0]<31:raise RuntimeError('rebinding')
        return device
    monkeypatch.setattr(transport,'get_device',open_device)
    assert transport._wait_for(0x0336,20,[],prepare=setup) is device
    assert attempts[0]==30 and attempts[-1]>=31


def test_windows_pnp_can_trigger_setup_before_libusb_can_open(monkeypatch):
    clock(monkeypatch);ready=[False];device=object();seen=[]
    monkeypatch.setattr(transport,'_sony_pids',lambda:[])
    monkeypatch.setattr(transport,'SERVICE_DRIVER_PRESENT',lambda:True)
    def setup():ready[0]=True
    def open_device(pid):
        if not ready[0]:raise RuntimeError('missing binding')
        return device
    monkeypatch.setattr(transport,'get_device',open_device)
    assert transport._wait_for(0x0336,20,seen,prepare=setup) is device
    assert seen==['0336']


@pytest.mark.parametrize('error,recovers',[(-4,True),(-9,False)])
def test_only_device_disappearance_is_waited_through_during_reenumeration(monkeypatch,error,recovers):
    clock(monkeypatch);device=object()
    monkeypatch.setattr(transport,'_sony_pids',lambda:['0336'])
    opened=Mock(side_effect=[transport.usb.core.USBError('enumeration error',error),device])
    monkeypatch.setattr(transport,'get_device',opened)
    if recovers:
        assert transport._wait_for(0x0336,20,[]) is device
        assert opened.call_count==2
    else:
        with pytest.raises(transport.usb.core.USBError):transport._wait_for(0x0336,20,[])
        assert opened.call_count==1


def test_late_service_arrival_is_waited_for_without_another_authentication(monkeypatch):
    now=clock(monkeypatch);device=object()
    monkeypatch.setattr(transport,'_sony_pids',lambda:['0d68'] if now[0]<95 else ['0336'])
    def open_device(pid):
        if now[0]<95:raise RuntimeError('still switching')
        return device
    monkeypatch.setattr(transport,'get_device',open_device)
    seen=[]
    assert transport._wait_for(0x0336,transport.SERVICE_WAIT,seen) is device
    assert now[0]==95 and seen==['0d68','0336']


def test_admin_prompt_happens_before_any_camera_transition(monkeypatch,tmp_path):
    monkeypatch.setattr(drivers.sys,'platform','win32');monkeypatch.setattr(drivers,'is_admin',lambda:False)
    elevated=Mock(return_value=dict(service_connected=True));install=Mock();camera=Mock()
    monkeypatch.setattr(drivers,'elevate_request',elevated);monkeypatch.setattr(drivers,'install',install)
    monkeypatch.setattr(devicesession,'Camera',camera)
    assert drivers.prepare(tmp_path)['service_connected']
    elevated.assert_called_once_with({},tmp_path,action='usb_prepare')
    install.assert_not_called();camera.assert_not_called()


def test_installer_is_prepared_before_auth_and_pnp_snapshot_is_reused(monkeypatch,tmp_path):
    monkeypatch.setattr(drivers.sys,'platform','win32');monkeypatch.setattr(drivers,'is_admin',lambda:True)
    events=[];rows=[dict(id='USB\\VID_054C&PID_0336')]
    monkeypatch.setattr(drivers,'installer',lambda:events.append('installer-ready'))
    monkeypatch.setattr(windows_pnp,'devices',lambda:rows)
    def install(args,job,**kwargs):
        if args['pid']=='0336':assert kwargs['report']['devices']==rows
        events.append(args['pid']);return dict(driver_changed=False)
    monkeypatch.setattr(drivers,'install',install)
    @contextmanager
    def camera():
        events.append('auth')
        assert transport.SERVICE_DRIVER_PRESENT()
        transport.SERVICE_DRIVER_SETUP()
        yield SimpleNamespace(identity=dict(model='ILCE-7CM2'))
    monkeypatch.setattr(devicesession,'Camera',camera)
    drivers.prepare(tmp_path)
    assert events==['installer-ready','0e8a','auth','0336']
    assert transport.SERVICE_DRIVER_SETUP is None and transport.SERVICE_DRIVER_PRESENT is None
