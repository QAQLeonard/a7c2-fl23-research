"""Isolated native-runtime binding/refcount tests using loader callbacks only."""
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from test_jpeg_stream import Api

OPEN = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_char_p, C.c_int)
SYMBOL = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_void_p, C.c_char_p)
CLOSE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)
OWNER = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p, C.c_char_p)
PIN = C.CFUNCTYPE(C.c_void_p, C.c_void_p)
ERROR = C.CFUNCTYPE(C.c_void_p, C.c_void_p)
SYMBOLS = [b'_ZN3mpr4file4OpenEPcNS0_8OpenFlagEPm', b'_ZN3mpr4file4ReadEcmPvj',
           b'_ZN3mpr4file5WriteEcmPvj', b'_ZN3mpr4file5CloseEcm',
           b'_ZN3mpr4file4StatEPcPm', b'Fsys_Flush', b'Fsys_Mkdir']


class Loader(C.Structure):
    _fields_ = [('context', C.c_void_p), ('open', OPEN), ('symbol', SYMBOL), ('close', CLOSE),
                ('owner', OWNER), ('pin_self', PIN), ('error', ERROR)]


class Report(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ('abi', 'phase', 'bound_mask', 'jobs', 'callbacks', 'owned_sdk_mask',
                 'failed_symbol', 'close_attempts')] + [
        ('status', C.c_int32), ('close_error', C.c_int32), ('primary_status', C.c_int32),
        ('reserved', C.c_int32), ('generation', C.c_uint64), ('release_handle', C.c_void_p),
        ('message', C.c_char * 256)]


class Lease(C.Structure):
    _fields_ = [('generation', C.c_uint64), ('token', C.c_uint64),
                ('kind', C.c_uint32), ('reserved', C.c_uint32), ('api', Api), ('mkdir', C.c_void_p)]


class FakeLoader:
    MPR, FSYS, SELF = 0x1001, 0x2002, 0x3003

    def __init__(self, *, missing=None, symbol=None, owner=None, pin=False, close=None):
        self.missing, self.missing_symbol, self.wrong_owner = missing, symbol, owner
        self.pin_failure, self.close_failure = pin, close
        self.refs = {self.MPR: 0 if missing == b'libmpr.so' else 1,
                     self.FSYS: 0 if missing == b'libInfraFsys.so' else 1, self.SELF: 0}
        self.baseline = dict(self.refs)
        self.events, self.bad = [], []
        self.message = C.create_string_buffer(b'synthetic loader detail')
        self.callbacks = [OPEN(self.open), SYMBOL(self.symbol), CLOSE(self.close),
                          OWNER(self.owner), PIN(self.pin), ERROR(lambda _: C.addressof(self.message))]
        self.api = Loader(None, *self.callbacks)

    def open(self, context, name, flags):
        self.events.append(('open', name, flags))
        if flags != 6: self.bad.append('SDK force-load flag'); return 0
        if name == self.missing: return 0
        handle = self.MPR if name == b'libmpr.so' else self.FSYS if name == b'libInfraFsys.so' else 0
        if not handle: self.bad.append('Unexpected module'); return 0
        self.refs[handle] += 1; return handle

    def symbol(self, context, handle, name):
        self.events.append(('symbol', handle, name))
        if name not in SYMBOLS: self.bad.append('Unexpected SDK symbol'); return 0
        index = SYMBOLS.index(name)
        if handle != (self.FSYS if index >= 5 else self.MPR): self.bad.append('Wrong SDK module'); return 0
        return 0 if self.missing_symbol == index else 0x10000000 + index * 0x100

    def owner(self, context, symbol, module):
        index = (symbol - 0x10000000) // 0x100
        expected = b'libInfraFsys.so' if index >= 5 else b'libmpr.so'
        if module != expected: self.bad.append('Wrong module-owner request')
        return 0 if self.wrong_owner == index else 1

    def close(self, context, handle):
        self.events.append(('close', handle))
        if handle == self.close_failure: return 7
        if self.refs.get(handle, 0) <= 0: self.bad.append('Reference released twice'); return 9
        self.refs[handle] -= 1; return 0

    def pin(self, context):
        self.events.append(('pin',))
        if self.pin_failure: return 0
        self.refs[self.SELF] += 1; return self.SELF


def library():
    lib = C.CDLL(os.environ['A7C2_STREAM_LIBRARY'])
    lib.a7_ap_start.argtypes = [C.POINTER(Loader), C.POINTER(Report)]
    lib.a7_ap_query.argtypes = [C.POINTER(Report)]
    lib.a7_ap_retire.argtypes = [C.POINTER(Report)]
    lib.a7_ap_acquire.argtypes = [C.c_uint32, C.POINTER(Lease), C.POINTER(Report)]
    lib.a7_ap_release.argtypes = [C.POINTER(Lease), C.POINTER(Report)]
    lib.a7_ap_runtime_abi.restype = C.c_uint32
    assert lib.a7_ap_runtime_abi() == 1
    return lib


def run_case(case):
    lib, report = library(), Report()
    if case in ('missing-mpr', 'missing-fsys', 'pin', 'missing-symbol', 'owner'):
        indexes = range(7) if case in ('missing-symbol', 'owner') else [None]
        for index in indexes:
            backend = FakeLoader(missing=b'libmpr.so' if case == 'missing-mpr' else
                                 b'libInfraFsys.so' if case == 'missing-fsys' else None,
                                 symbol=index if case == 'missing-symbol' else None,
                                 owner=index if case == 'owner' else None, pin=case == 'pin')
            expected = {'missing-mpr': -11001, 'missing-fsys': -11002,
                        'pin': -11005, 'missing-symbol': -11003, 'owner': -11004}[case]
            assert lib.a7_ap_start(C.byref(backend.api), C.byref(report)) == expected
            assert report.phase == 0 and report.owned_sdk_mask == 0 and not backend.bad
            if index is not None: assert report.failed_symbol == index
            if report.release_handle: assert backend.close(None, report.release_handle) == 0
            assert backend.refs == backend.baseline
            assert lib.a7_ap_query(C.byref(report)) == 0 and not report.release_handle
        return
    if case == 'cleanup-review':
        backend = FakeLoader(missing=b'libInfraFsys.so', close=FakeLoader.MPR)
        assert lib.a7_ap_start(C.byref(backend.api), C.byref(report)) == -11008
        assert (report.phase, report.primary_status, report.close_error) == (2, -11002, 7)
        assert not report.release_handle and backend.refs[backend.SELF] == 1
        before = list(backend.events)
        assert lib.a7_ap_retire(C.byref(report)) == -11008
        assert lib.a7_ap_start(C.byref(backend.api), C.byref(report)) == -11008
        assert backend.events == before
        return
    backend = FakeLoader()
    assert lib.a7_ap_start(C.byref(backend.api), C.byref(report)) == 0
    assert (report.abi, report.phase, report.bound_mask, report.owned_sdk_mask) == (1, 1, 127, 3)
    assert not report.release_handle and backend.refs[backend.SELF] == 1
    if case == 'already':
        before = list(backend.events)
        assert lib.a7_ap_start(C.byref(backend.api), C.byref(report)) == 1
        assert backend.events == before
    elif case in ('job', 'callback', 'stale', 'duplicate'):
        lease = Lease(); kind = 2 if case == 'callback' else 1
        assert lib.a7_ap_acquire(kind, C.byref(lease), C.byref(report)) == 0
        assert (report.jobs, report.callbacks) == ((0, 1) if kind == 2 else (1, 0))
        assert C.cast(lease.api.open, C.c_void_p).value == 0x10000000
        assert C.cast(lease.api.flush, C.c_void_p).value == 0x10000500
        assert lease.mkdir == (0x10000600 if kind == 1 else None)
        copy = Lease.from_buffer_copy(bytes(lease)); before = list(backend.events)
        if case == 'job':
            token = lease.token
            assert lib.a7_ap_acquire(1, C.byref(lease), C.byref(report)) == -11007
            assert lease.token == token and report.jobs == 1
        assert lib.a7_ap_retire(C.byref(report)) == -11006 and not report.release_handle
        assert backend.events == before
        assert lib.a7_ap_release(C.byref(lease), C.byref(report)) == 0
        assert bytes(lease) == bytes(C.sizeof(Lease))
        assert lib.a7_ap_release(C.byref(copy), C.byref(report)) == -11007
        if case == 'stale':
            assert lib.a7_ap_retire(C.byref(report)) == 0
            assert backend.close(None, report.release_handle) == 0
            assert lib.a7_ap_start(C.byref(backend.api), C.byref(report)) == 0
            fresh = Lease(); assert lib.a7_ap_acquire(1, C.byref(fresh), C.byref(report)) == 0
            assert fresh.generation != copy.generation
            assert lib.a7_ap_release(C.byref(copy), C.byref(report)) == -11007
            assert report.jobs == 1
            assert lib.a7_ap_release(C.byref(fresh), C.byref(report)) == 0
    elif case == 'capacity':
        leases = [Lease() for _ in range(33)]
        for lease in leases[:32]: assert lib.a7_ap_acquire(1, C.byref(lease), C.byref(report)) == 0
        assert lib.a7_ap_acquire(1, C.byref(leases[32]), C.byref(report)) == -11006
        assert not leases[32].token and report.jobs == 32
        for lease in leases[:32]: assert lib.a7_ap_release(C.byref(lease), C.byref(report)) == 0
    elif case == 'concurrent':
        callback = Lease()
        assert lib.a7_ap_acquire(2, C.byref(callback), C.byref(report)) == 0
        def jobs():
            for _ in range(100):
                lease, local_report = Lease(), Report()
                assert lib.a7_ap_acquire(1, C.byref(lease), C.byref(local_report)) == 0
                assert lib.a7_ap_release(C.byref(lease), C.byref(local_report)) == 0
        def retire_busy():
            for _ in range(100):
                local_report = Report()
                assert lib.a7_ap_retire(C.byref(local_report)) == -11006
                assert not local_report.release_handle
        with ThreadPoolExecutor(max_workers=5) as pool:
            work = [pool.submit(jobs) for _ in range(4)] + [pool.submit(retire_busy)]
            for task in work: task.result()
        assert lib.a7_ap_query(C.byref(report)) == 0
        assert (report.jobs, report.callbacks) == (0, 1)
        assert lib.a7_ap_release(C.byref(callback), C.byref(report)) == 0
    elif case == 'close-review':
        backend.close_failure = backend.FSYS
        assert lib.a7_ap_retire(C.byref(report)) == -11008
        assert (report.phase, report.close_error, report.owned_sdk_mask) == (2, 7, 3)
        assert not report.release_handle and backend.refs[backend.SELF] == 1
        before = list(backend.events)
        assert lib.a7_ap_retire(C.byref(report)) == -11008
        assert backend.events == before
        return
    assert lib.a7_ap_retire(C.byref(report)) == 0
    assert report.phase == 0 and not report.owned_sdk_mask and report.release_handle == backend.SELF
    # The caller, outside the native runtime, drops the transferred self pin.
    assert backend.close(None, report.release_handle) == 0
    assert backend.refs == backend.baseline and not backend.bad


@unittest.skipUnless(os.environ.get('A7C2_STREAM_LIBRARY'), 'Set A7C2_STREAM_LIBRARY to a host library')
class ApRuntime(unittest.TestCase):
    def worker(self, name):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--case', name],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertEqual(json.loads(result.stdout)['case'], name)

    def test_missing_mpr_is_not_force_loaded(self): self.worker('missing-mpr')
    def test_missing_fsys_balances_partial_references(self): self.worker('missing-fsys')
    def test_pin_failure_does_not_touch_sdk(self): self.worker('pin')
    def test_missing_exports_balance_references(self): self.worker('missing-symbol')
    def test_wrong_export_owner_rejected(self): self.worker('owner')
    def test_cleanup_error_retains_pin_without_retry(self): self.worker('cleanup-review')
    def test_already_started_does_not_pin_twice(self): self.worker('already')
    def test_job_lease_blocks_retire(self): self.worker('job')
    def test_callback_lease_blocks_retire(self): self.worker('callback')
    def test_copied_lease_cannot_release_twice(self): self.worker('duplicate')
    def test_stale_lease_cannot_release_new_generation(self): self.worker('stale')
    def test_bounded_lease_capacity(self): self.worker('capacity')
    def test_concurrent_jobs_and_retire_preserve_callback_reference(self): self.worker('concurrent')
    def test_close_failure_keeps_owned_modules_for_review(self): self.worker('close-review')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--case':
        run_case(sys.argv[2]); print(json.dumps({'case': sys.argv[2], 'passed': True}))
    else:
        unittest.main()
