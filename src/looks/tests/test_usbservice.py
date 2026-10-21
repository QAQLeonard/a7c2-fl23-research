"""Shared service entry and deferred model guards, with no USB access."""
import types
import unittest
from unittest.mock import Mock
from looktool import usbservice, firmware
from looktool.devicesession import Camera


class ServiceTests(unittest.TestCase):
    def test_service_entry_uses_expected_identity_once(self):
        expected={'model':'ILCE-7CM2','serial_sha256':'body'}
        link=Mock();link.__enter__=Mock(return_value=link)
        transport=types.SimpleNamespace(Session=Mock(return_value=link))
        self.assertIs(usbservice.open_service(transport,expected),link)
        transport.Session.assert_called_once_with(expected)
        link.__enter__.assert_called_once_with()

    def test_failed_or_interrupted_entry_never_retries_or_sends_cleanup(self):
        for error in (TimeoutError('unknown'),KeyboardInterrupt(),ValueError('wrong body')):
            with self.subTest(error=type(error).__name__):
                link=Mock();link.__enter__=Mock(side_effect=error);link.__exit__=Mock()
                transport=types.SimpleNamespace(Session=Mock(return_value=link))
                with self.assertRaises(type(error)):usbservice.open_service(transport)
                transport.Session.assert_called_once_with(None)
                link.__enter__.assert_called_once_with()
                link.__exit__.assert_not_called()

    def test_unconfirmed_identity_only_allows_pinned_readonly_probe(self):
        camera=Camera();camera.identity_pending=True;camera.programs_pinned=True;camera.service_only=False
        camera.identity={'model':None};camera.link=Mock();blob=b'only-readonly-runtime'
        camera.core=types.SimpleNamespace(MODEL='ILCE-7CM2',assets=lambda:{'files':{'runtime.so':firmware.sha(blob)}})
        for stage,data in [('lut-program-staged.so',blob),('lut-runtime-staged.so',b'other'),('libJit.so',b'other')]:
            with self.assertRaises(ValueError):camera.temp_write(stage,data)
        with self.assertRaises(ValueError):camera.property_write(0x02cf0001,b'\0',{0x02cf0001})
        camera.link.call.assert_not_called();camera.link.select.assert_not_called()
        camera.temp_write('lut-runtime-staged.so',blob)
        with self.assertRaises(ValueError):camera.confirm_identity({'model_index':17})
        camera.confirm_identity({'model_index':16})
        self.assertFalse(camera.identity_pending);self.assertEqual(camera.identity['model'],'ILCE-7CM2')


if __name__=='__main__':unittest.main()
