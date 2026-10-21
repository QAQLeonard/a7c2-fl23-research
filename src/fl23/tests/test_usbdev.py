"""usbdev 的离线回归测试。

曾经的线上错误：

    File "...\\usb\\util.py", line 231, in dispose_resources
        device._ctx.dispose(device)
    AttributeError: 'list' object has no attribute '_ctx'

原因是 ``find()`` 在等不到设备时返回 ``[]``（空列表），而
``usb.util.dispose_resources()`` 只接受单个 Device。这里用假设备锁住
「未找到返回 None」「dispose 对任何非设备对象都安静返回」这两条约定。
"""
import sys
import types
import unittest
from unittest.mock import Mock,patch
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

import usbdev

USB_KEYS = ('usb', 'usb.core', 'usb.util')


class FakeDevice:
    """带 ``_ctx`` 的假设备，用来确认 dispose 真的调用了 pyusb。"""

    def __init__(self, tag='dev'):
        self.tag = tag
        self._ctx = types.SimpleNamespace(dispose=lambda _d: None)


class UsbStub:
    """把 ``usb`` / ``usb.core`` / ``usb.util`` 换成可控的假模块。

    ``import usb.core`` 要求 ``usb`` 是 package（有 ``__path__``），
    所以这里三个条目都塞进 ``sys.modules``。
    """

    def __init__(self, devices=(), dispose_hook=None):
        self.devices = list(devices)
        self.dispose_hook = dispose_hook
        self.calls = []
        self.saved = {}

    def __enter__(self):
        for key in USB_KEYS:
            self.saved[key] = sys.modules.get(key, None)
        usb = types.ModuleType('usb')
        usb.__path__ = []

        core = types.ModuleType('usb.core')

        def find(find_all=False, idVendor=None, idProduct=None, backend=None):
            self.calls.append({'find_all': find_all, 'idVendor': idVendor,
                               'idProduct': idProduct, 'backend': backend})
            return iter(self.devices)

        core.find = find

        util = types.ModuleType('usb.util')
        if self.dispose_hook is None:
            util.dispose_resources = lambda device: self.calls.append(
                {'disposed': device})
        else:
            util.dispose_resources = self.dispose_hook

        sys.modules['usb'] = usb
        sys.modules['usb.core'] = core
        sys.modules['usb.util'] = util
        usb.core = core
        usb.util = util
        return self

    def __exit__(self, *_exc):
        for key, value in self.saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


class FindTests(unittest.TestCase):
    def setUp(self):
        self._backend = usbdev.backend
        usbdev.backend = lambda: 'fake-backend'

    def tearDown(self):
        usbdev.backend = self._backend

    def test_absent_returns_none_not_list(self):
        """等不到设备必须返回 None；返回 [] 会让 dispose_resources 崩。"""
        with UsbStub() as stub:
            self.assertIsNone(usbdev.find(usbdev.PID_MSC))
            self.assertEqual(stub.calls[0], {'find_all': True, 'idVendor': usbdev.VID,
                                             'idProduct': usbdev.PID_MSC,
                                             'backend': 'fake-backend'})

    def test_present_returns_the_single_device(self):
        only = FakeDevice()
        with UsbStub([only]):
            self.assertIs(usbdev.find(usbdev.PID_SERVICE), only)

    def test_two_devices_is_rejected(self):
        with UsbStub([FakeDevice('a'), FakeDevice('b')]):
            with self.assertRaises(RuntimeError) as ctx:
                usbdev.find(usbdev.PID_MSC)
            self.assertIn('需要且只能连接一台', str(ctx.exception))

    def test_require_raises_a_displayable_message(self):
        with UsbStub():
            with self.assertRaises(RuntimeError) as ctx:
                usbdev.require(usbdev.PID_MSC)
            self.assertIn('没有找到', str(ctx.exception))
            self.assertIn('0e8a', str(ctx.exception))

    def test_require_returns_the_device_when_present(self):
        only = FakeDevice()
        with UsbStub([only]):
            self.assertIs(usbdev.require(usbdev.PID_MSC), only)


class DisposeTests(unittest.TestCase):
    def test_none_is_ignored(self):
        usbdev.dispose(None)          # 不能抛

    def test_list_is_ignored(self):
        """这正是当初的崩溃现场：dispose([]) / dispose([dev])。"""
        usbdev.dispose([])
        usbdev.dispose([FakeDevice()])
        usbdev.dispose((FakeDevice(),))
        usbdev.dispose({FakeDevice()})

    def test_plain_object_without_ctx_is_ignored(self):
        usbdev.dispose(object())
        usbdev.dispose('not-a-device')
        usbdev.dispose(0)

    def test_device_is_forwarded_to_pyusb(self):
        dev = FakeDevice()
        with UsbStub() as stub:
            usbdev.dispose(dev)
        disposed = [c['disposed'] for c in stub.calls if 'disposed' in c]
        self.assertEqual(disposed, [dev])

    def test_pyusb_failure_is_swallowed(self):
        def boom(_device):
            raise RuntimeError('backend already gone')

        with UsbStub(dispose_hook=boom):
            usbdev.dispose(FakeDevice())      # 不能抛


class DriverReportTests(unittest.TestCase):
    """复现崩溃现场：拿不到系统驱动信息、又没连相机时的回退分支。"""

    def setUp(self):
        self._backend = usbdev.backend
        self._services = usbdev._windows_services
        usbdev.backend = lambda: 'fake-backend'
        usbdev._windows_services = lambda: None

    def tearDown(self):
        usbdev.backend = self._backend
        usbdev._windows_services = self._services

    def test_fallback_branch_does_not_crash(self):
        with UsbStub():
            report = usbdev.driver_report()
        self.assertFalse(report['ok'])
        for key in ('0e8a', '0336'):
            item = report[key]
            self.assertFalse(item['present'])
            self.assertFalse(item['reachable'])
            self.assertFalse(item['driver_ok'])
            self.assertIn('没有找到', item['detail'])

    def test_fallback_branch_reports_a_connected_device(self):
        only = FakeDevice()
        with UsbStub([only]):
            report = usbdev.driver_report()
        for key in ('0e8a', '0336'):
            item = report[key]
            self.assertTrue(item['present'])
            self.assertTrue(item['reachable'])
            self.assertTrue(item['driver_ok'])


class RequestServiceModeTests(unittest.TestCase):
    """用户点击“检查”时的真实崩溃路径。

    旧版在 ``finally: usb.util.dispose_resources(dev)`` 里释放，而 ``finally``
    抛出的 AttributeError 不会被外层的 ``except`` 接住，于是直接冒到界面上。
    """

    def setUp(self):
        self._backend = usbdev.backend
        usbdev.backend = lambda: 'fake-backend'

    def tearDown(self):
        usbdev.backend = self._backend

    def test_no_device_returns_a_message_instead_of_crashing(self):
        with UsbStub():
            result = usbdev.request_service_mode()
        self.assertFalse(result['switched'])
        self.assertIn('没有找到', result['detail'])

    def test_unknown_authentication_sends_no_stop_or_second_authentication(self):
        import transport
        from pmca.usb import sony
        dev=FakeDevice()
        for error in (TimeoutError('unknown'),KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                auth=Mock();auth.authenticate.side_effect=error
                with patch.object(usbdev,'find',return_value=dev) as find, \
                        patch.object(usbdev,'dispose') as dispose, \
                        patch.object(transport,'Bounded'), \
                        patch('pmca.usb.driver.generic.GenericUsbDriver'), \
                        patch.object(sony,'SonySenserAuthDevice',return_value=auth):
                    with self.assertRaises(type(error)):usbdev.request_service_mode()
                find.assert_called_once_with(usbdev.PID_MSC)
                auth.authenticate.assert_called_once_with()
                auth.stop.assert_not_called()
                dispose.assert_called_once_with(dev)

    def test_multiple_service_devices_stop_instead_of_waiting_or_reauthenticating(self):
        import transport
        from pmca.usb import sony
        auth=Mock();dev=FakeDevice()
        with patch.object(usbdev,'find',side_effect=[dev,RuntimeError('multiple cameras')]) as find, \
                patch.object(usbdev,'dispose'),patch.object(transport,'Bounded'), \
                patch('pmca.usb.driver.generic.GenericUsbDriver'), \
                patch.object(sony,'SonySenserAuthDevice',return_value=auth):
            with self.assertRaisesRegex(RuntimeError,'multiple cameras'):usbdev.request_service_mode()
        self.assertEqual(find.call_count,2)
        auth.authenticate.assert_called_once_with()
        auth.stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
