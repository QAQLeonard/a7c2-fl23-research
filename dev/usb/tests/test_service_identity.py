"""Active service-first sessions: old bindings, failed entry and no MSC gate."""
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'src/fl23'),str(ROOT/'src/fl23/vendor')]
spec=importlib.util.spec_from_file_location('service_first_transport',ROOT/'src/fl23/transport.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)

class SessionTests(unittest.TestCase):
    def setUp(self):
        self._get_device_original=t.get_device
        self.events=[];self.clock=0;self.product='ILCE-7CM2'
        self.normal=SimpleNamespace(iProduct=2,pid=0x0e8a)
        self.service=SimpleNamespace(pid=0x0336)
        self.serial=bytes.fromhex('00a1b2ff')
        self.camera=Mock()
        self.camera.getBackupPresetData.side_effect=self.snapshot
        self.failure=None;self.missing_service=False
        owner=self
        class Backend:
            def __init__(self,device,budget=180):self.device=device
            def reset(self):owner.events.append(('reset',self.device.pid))
        class Auth:
            def __init__(self,driver):self.driver=driver
            def start(self):owner.events.append(('start',self.driver.device.pid))
            def authenticate(self):
                owner.events.append(('auth',self.driver.device.pid))
                if owner.failure==self.driver.device.pid:raise TimeoutError('unknown auth')
            def stop(self):owner.events.append(('stop',self.driver.device.pid))
        patches=[patch.object(t,'get_device',side_effect=self.device),
            patch.object(t.usbdev,'find',side_effect=self.device),
            patch.object(t.usb.util,'get_string',side_effect=lambda *args:self.product),
            patch.object(t.usb.util,'dispose_resources',side_effect=lambda d:self.events.append(('dispose',d.pid))),
            patch.object(t,'Bounded',Backend),patch.object(t,'GenericUsbDriver',side_effect=lambda b:b),
            patch.object(t,'SonySenserAuthDevice',Auth),patch.object(t,'SonySenserDevice',side_effect=lambda d:d),
            patch.object(t,'SonySenserCamera',return_value=self.camera),
            patch.object(t.core,'backup_records',side_effect=lambda raw:[{0x00e70003:SimpleNamespace(data=self.serial)},{}]),
            patch.object(t,'identity',side_effect=AssertionError('Application query must not gate service')),
            patch.object(t,'MscDevice',side_effect=AssertionError('No TUR/INQUIRY in Session')),
            patch.object(t,'SonyExtCmdCamera',side_effect=AssertionError('No GetModelInfo in Session')),
            patch.object(t.time,'sleep',side_effect=self.sleep),patch.object(t.time,'monotonic',side_effect=lambda:self.clock)]
        for p in patches:p.start();self.addCleanup(p.stop)
    def device(self,pid,timeout=0):
        self.events.append(('device',pid))
        if pid==0x0336 and self.missing_service:return None
        return self.normal if pid==0x0e8a else self.service
    def snapshot(self,from_memory):
        self.events.append(('snapshot',from_memory));return b'backup'
    def sleep(self,seconds):self.clock+=seconds
    def expected(self):
        return {'model':'ILCE-7CM2','serial_sha256':hashlib.sha256(b'00a1b2ff').hexdigest()}
    def test_busy_msc_and_info_are_not_called_and_old_binding_matches(self):
        with t.Session(self.expected()) as link:
            self.assertEqual(link.identity,self.expected())
        self.assertEqual([e for e in self.events if e[0]=='auth'],[('auth',0x0e8a),('auth',0x0336)])
        self.assertGreater(self.events.index(('snapshot',True)),self.events.index(('auth',0x0336)))
        self.assertIn(('stop',0x0336),self.events)
        self.camera.readHasp.assert_not_called();self.camera.writeBackup.assert_not_called()
        self.camera.saveBackup.assert_not_called()
    def test_prepare_without_existing_binding_uses_same_serial_format(self):
        with t.Session() as link:self.assertEqual(link.identity,self.expected())
    def test_wrong_body_stops_and_exits_service_before_any_settings_write(self):
        expected=self.expected();expected['serial_sha256']='other'
        with self.assertRaisesRegex(RuntimeError,'备份的机身不同'):t.Session(expected).__enter__()
        self.assertIn(('stop',0x0336),self.events);self.camera.writeBackup.assert_not_called()
    def test_wrong_usb_model_does_not_authenticate(self):
        self.product='ILCE-7CR'
        with self.assertRaisesRegex(RuntimeError,'USB 型号不符'):t.Session().__enter__()
        self.assertFalse(any(e[0]=='auth' for e in self.events))
    def test_missing_serial_exits_service_without_writes(self):
        self.serial=b'bad'
        with self.assertRaisesRegex(RuntimeError,'序列号属性'):t.Session().__enter__()
        self.assertIn(('stop',0x0336),self.events);self.camera.writeBackup.assert_not_called()
    def test_snapshot_timeout_stops_commands_and_does_not_repeat_auth(self):
        for error in (TimeoutError('unknown read'),KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.events.clear();self.camera.getBackupPresetData.reset_mock()
                self.camera.getBackupPresetData.side_effect=error
                with self.assertRaises(type(error)):t.Session().__enter__()
                self.assertFalse(any(e[0]=='stop' for e in self.events))
                self.assertEqual(self.camera.getBackupPresetData.call_count,1)
    def test_normal_auth_timeout_is_never_repeated(self):
        self.failure=0x0e8a
        with self.assertRaises(TimeoutError):t.Session().__enter__()
        self.assertEqual([e for e in self.events if e[0]=='auth'],[('auth',0x0e8a)])
        self.assertNotIn(('device',0x0336),self.events)
        self.assertFalse(any(e[0]=='stop' for e in self.events))
    def test_service_auth_timeout_sends_no_stop_or_snapshot(self):
        self.failure=0x0336
        with self.assertRaises(TimeoutError):t.Session().__enter__()
        self.assertFalse(any(e[0] in ('stop','snapshot') for e in self.events))
    def test_missing_service_identity_has_bounded_wait(self):
        self.missing_service=True
        with self.assertRaisesRegex(RuntimeError,'服务身份未出现'):t.Session(service_timeout=3).__enter__()
        self.assertEqual(self.clock,3)
        self.assertEqual([e for e in self.events if e[0]=='auth'],[('auth',0x0e8a)])

    def test_ambiguous_service_devices_are_not_retried(self):
        with patch.object(t.usbdev,'find',side_effect=RuntimeError('multiple devices')) as find:
            with self.assertRaisesRegex(RuntimeError,'multiple devices'):t.Session().__enter__()
        find.assert_called_once_with(0x0336)
        self.assertFalse(any(e[0]=='stop' for e in self.events))

    def test_interrupted_command_marks_session_unknown_and_sends_no_stop(self):
        with self.assertRaises(KeyboardInterrupt):
            with t.Session() as link:
                link.call(Mock(side_effect=KeyboardInterrupt()))
        self.assertFalse(link.healthy)
        self.assertFalse(any(e[0]=='stop' for e in self.events))

    def test_get_device_preserves_shared_backend_and_single_device_guard(self):
        # Exercise the real compatibility entry, not the session's fake getter.
        with patch.object(t.usbdev,'require',return_value=self.normal) as require:
            original_getter=self._get_device_original
            self.assertIs(original_getter(0x0e8a,timeout=15),self.normal)
        require.assert_called_once_with(0x0e8a,timeout=15)

if __name__=='__main__':unittest.main()
