"""Body identity must survive sessions and reject a different device."""
import importlib.util,types,unittest
from unittest.mock import Mock,patch
from looktool import usbidentity,firmware
from looktool.devicesession import Camera

class IdentityTests(unittest.TestCase):
    def transport(self,serial,index=3):
        dev=types.SimpleNamespace(iSerialNumber=index)
        util=types.SimpleNamespace(get_string=Mock(return_value=serial),dispose_resources=Mock())
        return types.SimpleNamespace(get_device=Mock(return_value=dev),usb=types.SimpleNamespace(util=util)),dev
    def test_descriptor_hash_stable_and_raw_serial_not_returned(self):
        t,dev=self.transport('BODY01234567')
        first=usbidentity.capture(t);second=usbidentity.capture(t)
        self.assertEqual(first,second);self.assertEqual(first,firmware.sha(b'BODY01234567'))
        usbidentity.require_match({'usb_serial_sha256':first,'product_info_sha256':'old-session'},second)
        self.assertEqual(t.usb.util.dispose_resources.call_count,2)
    def test_wrong_body_and_unbound_legacy_job_stop(self):
        for expected in [{'usb_serial_sha256':firmware.sha(b'another-body')},{'product_sha256':'legacy-opaque-response'}]:
            with self.assertRaises(ValueError):usbidentity.require_match(expected,firmware.sha(b'BODY01234567'))
    def test_missing_or_generic_serial_and_descriptor_error_stop_with_cleanup(self):
        for serial in [None,'','000000000000','1234567890','unknown','ILCE-7CM2',' BODY01234567']:
            t,dev=self.transport(serial)
            with self.assertRaises(ValueError):usbidentity.capture(t)
            t.usb.util.dispose_resources.assert_called_once_with(dev)
        t,dev=self.transport('unused');t.usb.util.get_string.side_effect=TimeoutError('descriptor failed')
        with self.assertRaises(TimeoutError):usbidentity.capture(t)
        t.usb.util.dispose_resources.assert_called_once_with(dev)
    def test_connection_does_not_query_opaque_product_for_body_binding(self):
        token=firmware.sha(b'BODY01234567');expected={'model':'ILCE-7CM2','usb_serial_sha256':token}
        t,dev=self.transport('BODY01234567')
        link=Mock();link.identity={'model':'ILCE-7CM2'};link.call.side_effect=[b'a'*88,b'b'*88]
        link.__enter__=Mock(return_value=link);link.__exit__=Mock()
        t.Session=Mock(return_value=link)
        # Deliberately omit the removed libusb_package/readiness interfaces.
        with patch('looktool.devicesession.modules',return_value=(t,types.SimpleNamespace(MODEL='ILCE-7CM2'))):
            one=Camera(expected)._connect();two=Camera(expected)._connect()
            link.call.assert_not_called()
            self.assertEqual(one.identity['usb_serial_sha256'],two.identity['usb_serial_sha256'])
            t.Session.reset_mock()
            with self.assertRaises(ValueError):Camera(dict(expected,usb_serial_sha256='different-body'))._connect()
            t.Session.assert_not_called()

    def test_connection_timeout_does_not_retry_authentication(self):
        t,_=self.transport('BODY01234567')
        link=Mock();link.__enter__=Mock(side_effect=TimeoutError('unknown authentication'))
        t.Session=Mock(return_value=link)
        with patch('looktool.devicesession.modules',return_value=(t,types.SimpleNamespace(MODEL='ILCE-7CM2'))):
            with self.assertRaises(TimeoutError):Camera()._connect()
        t.Session.assert_called_once_with(None)
        link.__enter__.assert_called_once_with()

    def test_absent_normal_identity_stops_before_service_authentication(self):
        t,_=self.transport('BODY01234567')
        t.get_device.side_effect=RuntimeError('No normal device');t.Session=Mock()
        with patch('looktool.devicesession.modules',return_value=(t,types.SimpleNamespace(MODEL='ILCE-7CM2'))):
            with self.assertRaisesRegex(RuntimeError,'No normal device'):Camera()._connect()
        t.get_device.assert_called_once_with(0x0e8a,timeout=15)
        t.Session.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec('usb'),'Optional device dependencies required')
    def test_real_transport_interface_reaches_shared_session_without_usb(self):
        from looktool.devicesession import modules
        transport,core=modules()
        dev=types.SimpleNamespace(iSerialNumber=3)
        link=Mock();link.identity={'model':core.MODEL,'serial_sha256':'ap-body'}
        link.__enter__=Mock(return_value=link)
        with patch.object(transport.usbdev,'require',return_value=dev) as require, \
                patch.object(transport.usb.util,'get_string',return_value='BODY01234567'), \
                patch.object(transport.usb.util,'dispose_resources'), \
                patch.object(transport,'Session',return_value=link) as session:
            camera=Camera()._connect()
        require.assert_called_once_with(0x0e8a,timeout=15)
        session.assert_called_once_with(None)
        self.assertEqual(camera.identity['serial_sha256'],'ap-body')
        self.assertEqual(camera.identity['usb_serial_sha256'],firmware.sha(b'BODY01234567'))
        self.assertFalse(camera.programs_pinned)

if __name__=='__main__':unittest.main()
