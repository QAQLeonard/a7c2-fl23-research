"""Driver removal planning/ordering only; no real driver command is run."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from desktopapp.platforms import usb_drivers as drivers


class DriverUninstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'INF').mkdir()
        (self.root / 'INF/oem42.inf').write_text(
            '[Models]\nCamera=Install,USB\\VID_054C&PID_0E8A\n', encoding='utf-8')
        self.rows = [{'id': r'USB\VID_054C&PID_0E8A\CAMERA', 'inf': 'oem42.inf'}]

    def test_only_camera_oem_package_selected(self):
        self.assertEqual(drivers.uninstall_plan(self.rows, {'0e8a', '0336'}, self.root / 'INF'), ['oem42.inf'])
        self.assertFalse(drivers.is_camera_id(r'USB\VID_1234&PID_0E8A\OTHER', {'0e8a'}))
        self.assertFalse(drivers.is_camera_id(r'USB\VID_054C&PID_0E8A0\OTHER', {'0e8a'}))

    def test_compatible_drivers_skip_installer_and_elevation_with_visible_result(self):
        for pid,service in (('0e8a','WinUSB'),('0336','libusbK')):
            report=dict(devices=[dict(id='USB\\VID_054C&PID_'+pid.upper()+'\\Camera',service=service)])
            output=io.StringIO()
            with patch.object(drivers.sys,'platform','win32'),patch.object(drivers,'scan',return_value=report) as scan, \
                 patch.object(drivers,'installer') as install,patch.object(drivers,'elevate_request') as elevate,redirect_stdout(output):
                result=drivers.install({'pid':pid},self.root)
            self.assertFalse(result['driver_changed']);install.assert_not_called();elevate.assert_not_called()
            self.assertEqual(scan.call_count,1);self.assertIn('跳过驱动安装',output.getvalue())
            with patch.object(drivers.sys,'platform','win32'),patch.object(drivers,'scan') as scan:
                drivers.install({'pid':pid},self.root,report=report)
            scan.assert_not_called()

    def test_windows_native_driver_never_deleted(self):
        rows = [dict(self.rows[0], inf='usbstor.inf')]
        self.assertEqual(drivers.uninstall_plan(rows, {'0e8a'}, self.root / 'INF'), [])

    def test_shared_non_camera_package_is_not_removed(self):
        rows = self.rows + [{'id': r'USB\VID_1234&PID_5678\OTHER', 'inf': 'oem42.inf'}]
        with self.assertRaisesRegex(ValueError, 'shared'):
            drivers.uninstall_plan(rows, {'0e8a', '0336'}, self.root / 'INF')

    def test_inf_cannot_hide_other_supported_hardware_ids(self):
        with (self.root / 'INF/oem42.inf').open('a') as stream:
            stream.write('Other=Install,USB\\VID_1234&PID_5678\n')
        with self.assertRaisesRegex(ValueError, 'another device'):
            drivers.uninstall_plan(self.rows, {'0e8a', '0336'}, self.root / 'INF')

    def test_zadig_libusbk_string_reference_and_utf16(self):
        text = ('[Strings]\nDeviceID = "VID_054C&PID_0E8A"\nDeviceName="ILCE-7CM2"\n'
                '[Manufacturer]\n%VendorName%=LUsbK_DeviceGroup,NTX86,NTAMD64\n'
                '[LUsbK_DeviceGroup.NTAMD64]\n%DeviceName%=LUsbK_Device, USB\\%DeviceID%\n')
        (self.root / 'INF/oem42.inf').write_text(text, encoding='utf-16')
        self.assertEqual(drivers.uninstall_plan(self.rows, {'0e8a'}, self.root / 'INF'), ['oem42.inf'])

    def test_nested_case_insensitive_inf_variables_and_comments(self):
        text = ('[Strings]\nVendor="054C"\nDeviceID="VID_%vendor%&PID_0336"\n'
                '[Models]\nCamera=Install,USB\\%deviceid% ; example USB\\VID_1234&PID_5678\n')
        self.assertEqual(drivers.inf_hardware_ids(text), [('054C', '0336')])

    def test_other_device_hidden_in_variable_is_rejected(self):
        (self.root / 'INF/oem42.inf').write_text(
            '[Strings]\nDeviceID="VID_1234&PID_5678"\n[Models]\nCamera=Install,USB\\%DeviceID%\n')
        with self.assertRaisesRegex(ValueError, 'another device'):
            drivers.uninstall_plan(self.rows, {'0e8a'}, self.root / 'INF')

    def test_admin_error_is_not_replaced_with_generic_exit_code(self):
        (self.root / 'status.private.json').write_text(
            '{"phase":"FAILED","error":"Original driver error oem42.inf"}')
        with self.assertRaisesRegex(RuntimeError, '^Original driver error oem42.inf$'):
            drivers.elevated_result(self.root, 2)

    def test_admin_success_is_returned(self):
        (self.root / 'status.private.json').write_text(
            '{"phase":"SUCCEEDED","result":{"removed_packages":["oem42.inf"]}}')
        self.assertEqual(drivers.elevated_result(self.root, 0)['removed_packages'], ['oem42.inf'])

    def test_export_before_uninstall_then_rescan_no_force_or_reboot(self):
        commands = []
        fake = SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: True))
        with patch.object(drivers.sys, 'platform', 'win32'), \
             patch.object(drivers.ctypes, 'windll', fake, create=True), \
             patch.dict(os.environ, {'WINDIR': str(self.root)}), \
             patch.object(drivers, 'driver_inventory', side_effect=[self.rows, []]), \
             patch.object(drivers, 'run_pnputil', side_effect=lambda a, **kw: commands.append(a) or 0):
            result = drivers.uninstall({}, self.root / 'job')
        self.assertEqual([row[0] for row in commands], ['/export-driver', '/delete-driver', '/scan-devices'])
        self.assertEqual(commands[1], ['/delete-driver', 'oem42.inf', '/uninstall'])
        self.assertNotIn('/force', sum(([str(x) for x in row] for row in commands), []))
        self.assertFalse(result['camera_firmware_written'])

    def test_failed_export_prevents_deletion(self):
        fake = SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: True))
        with patch.object(drivers.sys, 'platform', 'win32'), \
             patch.object(drivers.ctypes, 'windll', fake, create=True), \
             patch.dict(os.environ, {'WINDIR': str(self.root)}), \
             patch.object(drivers, 'driver_inventory', return_value=self.rows), \
             patch.object(drivers, 'run_pnputil', side_effect=RuntimeError('export failed')) as command:
            with self.assertRaisesRegex(RuntimeError, 'export failed'):
                drivers.uninstall({}, self.root / 'job')
        self.assertEqual(command.call_count, 1)

    def test_elevation_routes_to_uninstall_not_install(self):
        fake = SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: False))
        with patch.object(drivers.sys, 'platform', 'win32'), \
             patch.object(drivers.ctypes, 'windll', fake, create=True), \
             patch.object(drivers, 'elevate_request', return_value={'ok': True}) as elevate:
            self.assertEqual(drivers.uninstall({}, self.root), {'ok': True})
        self.assertEqual(elevate.call_args.kwargs['action'], 'driver_uninstall')


if __name__ == '__main__':
    unittest.main()
