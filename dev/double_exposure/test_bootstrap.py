"""Control-helper fault injection, without loading any camera code."""
import ctypes as C
import os
from pathlib import Path
import tempfile
import unittest
from build_bootstrap import build
from test_ap_runtime import Report

OPEN = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_char_p, C.c_int)
SYMBOL = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_void_p, C.c_char_p)
OWNS = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p, C.c_void_p)
CLOSE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)
ABI = C.CFUNCTYPE(C.c_uint32)
START = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(Report))
CONTROL = C.CFUNCTYPE(C.c_int, C.POINTER(Report))
NAMES = [b'a7_ap_runtime_abi', b'a7_ap_start', b'a7_ap_query', b'a7_ap_retire']


class Loader(C.Structure):
    _fields_ = [('context', C.c_void_p), ('open', OPEN), ('symbol', SYMBOL),
                ('owns', OWNS), ('close', CLOSE)]


class BootReport(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('abi', 'operation', 'called', 'close_attempts')] + [
        ('status', C.c_int32), ('core_status', C.c_int32), ('close_error', C.c_int32),
        ('review', C.c_uint32), ('runtime', Report)]


class Backend:
    HANDLE = 0x1234

    def __init__(self, *, absent=False, missing=None, wrong=None, abi=1,
                 status=0, pin=False, phase=1, close_failure=0):
        self.events, self.bad = [], []
        self.absent, self.missing, self.wrong = absent, missing, wrong
        self.version, self.status, self.pin, self.phase = abi, status, pin, phase
        self.close_failure, self.closes, self.refs = close_failure, 0, 0
        self.calls = [ABI(lambda: self.version), START(lambda _, out: self.control(out)),
                      CONTROL(self.control), CONTROL(self.control)]
        self.addresses = [C.cast(call, C.c_void_p).value for call in self.calls]
        self.callbacks = [OPEN(self.open), SYMBOL(self.symbol), OWNS(self.owns), CLOSE(self.close)]
        self.loader = Loader(None, *self.callbacks)

    def open(self, _, path, flags):
        self.events.append(('open', path, flags))
        if self.absent: return 0
        self.refs += 1
        return self.HANDLE

    def symbol(self, _, module, name):
        index = NAMES.index(name)
        self.events.append(('symbol', index))
        return 0 if self.missing == index else self.addresses[index]

    def owns(self, _, module, address):
        return self.addresses.index(address) != self.wrong

    def control(self, out):
        self.events.append(('core',))
        out.contents.abi = 1
        out.contents.phase = self.phase
        out.contents.status = self.status
        if self.pin:
            self.refs += 1
            out.contents.release_handle = self.HANDLE
        return self.status

    def close(self, _, module):
        self.closes += 1
        self.events.append(('close', module))
        if self.closes == self.close_failure: return 37
        self.refs -= 1
        if self.refs < 0: self.bad.append('double release')
        return 0


@unittest.skipUnless(os.environ.get('A7C2_ZIG'), 'Set A7C2_ZIG for the control-helper tests')
class Bootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='a7c2-bootstrap-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.lib = C.CDLL(str(build(Path(cls.temp.name), target='host')))
        import _ctypes
        cls.addClassCleanup((_ctypes.FreeLibrary if os.name == 'nt' else _ctypes.dlclose), cls.lib._handle)
        cls.lib.a7_boot_dispatch.argtypes = [C.c_char_p, C.c_uint32, C.POINTER(Loader), C.POINTER(BootReport)]

    def dispatch(self, backend, operation=1, path=b'/owned/transaction/core.so'):
        report = BootReport()
        result = self.lib.a7_boot_dispatch(path, operation, C.byref(backend.loader), C.byref(report))
        self.assertEqual(result, report.status)
        self.assertEqual(report.abi, 1)
        self.assertIsNone(report.runtime.release_handle)
        self.assertEqual(backend.bad, [])
        return result, report

    def test_no_load_flags_for_query_and_retire(self):
        for operation, flags in ((1, 2), (2, 6), (3, 6)):
            with self.subTest(operation=operation):
                backend = Backend()
                result, report = self.dispatch(backend, operation)
                self.assertEqual(result, 0)
                self.assertEqual(backend.events[0][2], flags)
                self.assertEqual((report.called, report.close_attempts, backend.refs), (1, 2, 0))

    def test_invalid_requests_do_not_open(self):
        for path in (None, b'relative', b'/', b'/x//core.so', b'/x/../core.so',
                     b'/x/./core.so', b'/x/\ncore.so', b'/' + b'x' * 512, b'/x/'):
            backend = Backend()
            self.assertEqual(self.dispatch(backend, path=path)[0], -12001)
            self.assertEqual(backend.events, [])
        backend = Backend()
        self.assertEqual(self.dispatch(backend, operation=4)[0], -12001)
        self.assertEqual(backend.events, [])

    def test_absent_core_no_close_or_dispatch(self):
        for operation in (1, 2, 3):
            backend = Backend(absent=True)
            result, report = self.dispatch(backend, operation)
            self.assertEqual(result, -12003 if operation == 1 else -12002)
            self.assertEqual((report.called, backend.closes), (0, 0))

    def test_every_missing_or_imported_export_rejected_before_control(self):
        for i in range(4):
            for options, expected in (({'missing': i}, -12004), ({'wrong': i}, -12005)):
                with self.subTest(options=options):
                    backend = Backend(**options)
                    result, report = self.dispatch(backend)
                    self.assertEqual((result, report.called, backend.refs), (expected, 0, 0))

    def test_version_mismatch_balances_temp_reference(self):
        backend = Backend(abi=2)
        result, report = self.dispatch(backend)
        self.assertEqual((result, report.called, backend.refs), (-12006, 0, 0))

    def test_transferred_pin_closed_after_core_before_temporary_reference(self):
        backend = Backend(pin=True, status=-11001, phase=0)
        result, report = self.dispatch(backend)
        self.assertEqual((result, report.core_status, report.close_attempts, backend.refs), (-11001, -11001, 3, 0))
        self.assertEqual([e[0] for e in backend.events][-3:], ['core', 'close', 'close'])

    def test_busy_and_core_review_propagated(self):
        for status, phase, review in ((-11006, 1, 0), (-11008, 2, 1), (1, 1, 0)):
            backend = Backend(status=status, phase=phase)
            result, report = self.dispatch(backend, 3)
            self.assertEqual((result, report.core_status, report.review, backend.refs), (status, status, review, 0))

    def test_pin_close_failure_does_not_retry_or_close_temporary_reference(self):
        backend = Backend(pin=True, close_failure=1)
        result, report = self.dispatch(backend, 3)
        self.assertEqual((result, report.review, report.close_attempts, backend.closes), (-12007, 1, 1, 1))
        self.assertEqual(report.close_error, 37)

    def test_temporary_close_failure_preserves_primary_result(self):
        backend = Backend(pin=True, status=-11001, close_failure=2)
        result, report = self.dispatch(backend)
        self.assertEqual((result, report.core_status, report.close_attempts, report.review), (-12007, -11001, 3, 1))
        self.assertEqual(backend.closes, 2)


if __name__ == '__main__':
    unittest.main()
