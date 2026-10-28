"""Distinguish a decoded camera file error from an unknown USB transfer."""
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from desktopapp import usbcheck
from looktool.devicesession import modules
from test_usb_stability import Camera,Clock,load

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture(params=('camera_runtime','fl23'))
def transport(request,monkeypatch):
    runtime,_=modules()
    if request.param=='camera_runtime':return runtime
    monkeypatch.syspath_prepend(str(ROOT/'src/fl23'))
    spec=importlib.util.spec_from_file_location('legacy_jiritsu_status',ROOT/'src/fl23/transport.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def session(transport,response=0,payload=None):
    value=transport.Session.__new__(transport.Session)
    value.channel=SimpleNamespace(sendSenserPacket=Mock())
    value.call=Mock(return_value=(response,payload if payload is not None else struct.pack('<I',0x10000004)))
    value.mutating=False
    return value


def test_decoded_error_retains_status_and_command_without_replaying(transport):
    value=session(transport)
    with pytest.raises(transport.JiritsuError) as caught:value.jiritsu(17,b'\0\xff\0')
    assert caught.value.jiritsu_status==0x10000004 and caught.value.command==17
    assert caught.value.request_mode==0
    assert isinstance(caught.value,RuntimeError)
    value.call.assert_called_once()


def test_missing_file_option_does_not_swallow_a_mount_failure(transport):
    value=session(transport)
    with pytest.raises(transport.JiritsuError):value.jiritsu(17,b'\0\xff\0',missing=True)
    value.call.return_value=(0,struct.pack('<I',0x10000006))
    assert value.jiritsu(17,b'\0\xff\0',missing=True) is None


@pytest.mark.parametrize('response,payload',[(1,bytes(4)),(0,b'\0\0')])
def test_malformed_reply_is_not_classified_as_a_known_camera_error(transport,response,payload):
    with pytest.raises(RuntimeError) as caught:session(transport,response,payload).jiritsu(17)
    assert not isinstance(caught.value,transport.JiritsuError)


@pytest.mark.parametrize('status,kind',[(0x10000004,'camera-staging-mount'),(0x10000006,'camera-file-command')])
def test_usb_test_reports_camera_failure_and_stops_once(transport,tmp_path,status,kind):
    clock=Clock();original=transport.JiritsuError(status,17,0)
    camera=Camera([original],clock)
    with pytest.raises(RuntimeError) as caught:usbcheck.run(tmp_path,factory=lambda:camera,clock=clock)
    assert caught.value.__cause__ is original
    assert '请换线' not in str(caught.value)
    report=load(tmp_path)
    assert report['failure_kind']==kind and report['jiritsu_status']==hex(status)
    assert report['jiritsu_command']==17 and report['failed_path']==usbcheck.PATHS[0]
    assert report['jiritsu_mode']==0
    assert report['rounds']==[] and len(camera.calls)==1
    assert not report['camera_firmware_written'] and not report['camera_settings_written']
    camera.mark_unknown.assert_not_called()


@pytest.mark.parametrize('command,mode',[(17,1),(17,None),(15,0),(16,0)])
def test_mount_interpretation_requires_the_observed_read_command_and_mode(transport,tmp_path,command,mode):
    clock=Clock();camera=Camera([transport.JiritsuError(0x10000004,command,mode)],clock)
    with pytest.raises(RuntimeError):usbcheck.run(tmp_path,factory=lambda:camera,clock=clock)
    assert load(tmp_path)['failure_kind']=='camera-file-command'
