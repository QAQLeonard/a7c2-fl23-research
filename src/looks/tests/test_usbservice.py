"""No USB: busy-only service acquisition and deferred model guards."""
import types,unittest,tempfile
from pathlib import Path
from unittest.mock import Mock,patch
from looktool import usbservice
from looktool.devicesession import Camera

class ReadinessFailure(RuntimeError):pass
class SonyBusyFailure(RuntimeError):pass

class ServiceTests(unittest.TestCase):
    def transport(self,manufacturer='Sony',failure=None):
        events=[]
        class Auth:
            def __init__(self,driver):self.driver=driver
            def start(self):events.append(('start',self.driver))
            def authenticate(self):
                events.append(('authenticate',self.driver))
                if failure:raise failure
        def get_device(pid):events.append(('device',pid));return pid
        t=types.SimpleNamespace(ReadinessFailure=ReadinessFailure,SonyBusyFailure=SonyBusyFailure,
            get_device=get_device,usb=types.SimpleNamespace(util=types.SimpleNamespace(dispose_resources=lambda d:events.append(('dispose',d)))),
            MscBbbDriver=lambda x:x,_InitialBackend=lambda d,r:d,
            MscDevice=lambda d:types.SimpleNamespace(getDeviceInfo=lambda:types.SimpleNamespace(manufacturer=manufacturer)),
            GenericUsbDriver=lambda d:d,Bounded=lambda d,budget=180:d,SonySenserAuthDevice=Auth,
            Session=lambda:types.SimpleNamespace(healthy=True),SonySenserDevice=lambda d:d,SonySenserCamera=lambda d:d)
        return t,events
    def test_fallback_is_only_known_initial_busy_not_unknown_or_timeout(self):
        t,_=self.transport()
        self.assertTrue(usbservice.allowed_initial_busy(t,ReadinessFailure('Camera did not become ready; Sony query was not started.')))
        self.assertTrue(usbservice.allowed_initial_busy(t,ReadinessFailure('Camera is not ready; sense=02/3a/00. Stopped.')))
        self.assertTrue(usbservice.allowed_initial_busy(t,SonyBusyFailure('Camera remained busy after readiness passed; query stopped.')))
        for error in [ReadinessFailure('Camera is not ready; sense=05/20/00. Stopped.'),TimeoutError('timeout'),ValueError('wrong camera')]:
            self.assertFalse(usbservice.allowed_initial_busy(t,error))
    def test_known_protocol_switches_once_and_keeps_model_unconfirmed(self):
        t,events=self.transport()
        with patch.object(usbservice.time,'sleep'):link=usbservice.open_service(t)
        self.assertIsNone(link.identity['model'])
        self.assertEqual([e for e in events if e[0]=='authenticate'],[('authenticate',0x0e8a),('authenticate',0x0336)])
    def test_wrong_manufacturer_and_ambiguous_auth_never_advance(self):
        t,events=self.transport('Other')
        with self.assertRaises(ValueError):usbservice.open_service(t)
        self.assertFalse(any(e[0]=='authenticate' for e in events))
        t,events=self.transport(failure=TimeoutError('unknown'))
        with self.assertRaises(TimeoutError):usbservice.open_service(t)
        self.assertNotIn(('device',0x0336),events)
        self.assertEqual([e for e in events if e[0]=='authenticate'],[('authenticate',0x0e8a)])
    def test_unconfirmed_identity_only_allows_pinned_readonly_probe(self):
        camera=Camera();camera.identity_pending=True;camera.programs_pinned=True;camera.service_only=False
        camera.identity={'model':None};camera.link=Mock();blob=b'only-readonly-runtime'
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        base=Path(temporary.name);(base/'assets').mkdir();(base/'assets/runtime.so').write_bytes(blob)
        camera.core=types.SimpleNamespace(MODEL='ILCE-7CM2',BASE=base)
        for stage,data in [('lut-program-staged.so',blob),('lut-runtime-staged.so',b'other'),('libJit.so',b'other')]:
            with self.assertRaises(ValueError):camera.temp_write(stage,data)
        with self.assertRaises(ValueError):camera.property_write(0x02cf0001,b'\0',{0x02cf0001})
        camera.link.call.assert_not_called();camera.link.select.assert_not_called()
        camera.temp_write('lut-runtime-staged.so',blob)
        with self.assertRaises(ValueError):camera.confirm_identity({'model_index':17})
        camera.confirm_identity({'model_index':16})
        self.assertFalse(camera.identity_pending);self.assertEqual(camera.identity['model'],'ILCE-7CM2')

if __name__=='__main__':unittest.main()
