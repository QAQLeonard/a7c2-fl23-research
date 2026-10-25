"""Integrated request/callback/JPEG/catalog tests with synthetic SDK adapters."""
import ctypes as C
import io
import hashlib
import json
import os
import struct
import subprocess
import sys
import unittest
from test_ap_runtime import FakeLoader, Loader, Report, SYMBOLS
from test_capture_pair import Session, Job
from test_jpeg_stream import FakeMpr, jpeg
from test_output_reservation import MKDIR

CLEAR = C.CFUNCTYPE(None, C.c_void_p)
SELECT = C.CFUNCTYPE(C.c_int32, C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint8)
ISSUE = C.CFUNCTYPE(C.c_int32, C.c_uint32, C.POINTER(C.c_uint32), C.c_uint8)
UPDATE = C.CFUNCTYPE(C.c_int32, C.c_uint32, C.c_void_p, C.c_uint8, C.c_uint8)
MEDIA = C.CFUNCTYPE(C.c_int32, C.c_uint32, C.POINTER(C.c_uint32))
DBFLUSH = C.CFUNCTYPE(C.c_int32, C.c_uint32)


class CatalogApi(C.Structure):
    _fields_ = [('clear', CLEAR), ('select', SELECT), ('issue', ISSUE), ('update', UPDATE), ('media', MEDIA), ('flush', DBFLUSH)]


class Event(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ('epoch', 'capture', 'generation', 'content')] + [
        (n, C.c_uint32) for n in ('kind', 'media', 'outcome', 'reserved')] + [('path', C.c_char * 512)]


class Publication(C.Structure):
    _fields_ = [('bytes', C.c_uint64), ('owned', C.c_uint32), ('distinct', C.c_uint32), ('path', C.c_char * 512)]


class Snapshot(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('abi', 'step', 'intent', 'active', 'review', 'queued', 'processing', 'attached')] + [
        ('status', C.c_int32), ('backend_error', C.c_int32), ('sequence', C.c_uint64), ('pair', Session),
        ('output_phase', C.c_uint32), ('catalog_phase', C.c_uint32), ('pending_handle', C.c_uint64),
        ('output_bytes', C.c_uint64), ('publication', Publication),
        ('catalog_uid', C.c_uint32), ('catalog_uid_valid', C.c_uint32),
        ('catalog_error', C.c_int32), ('output_error', C.c_int32),
        ('input_handles', C.c_uint64 * 2), ('input_phases', C.c_uint32 * 2), ('encoded_digest', C.c_uint8 * 32)]


class DeviceReport(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('abi', 'operation', 'intent', 'review')] + [
        ('request_id', C.c_uint64), ('status', C.c_int32), ('journal_error', C.c_int32), ('pipeline', Snapshot)]


SINK = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(Event))
SAVE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(Snapshot))
ATTACH = C.CFUNCTYPE(C.c_int, C.c_void_p, SINK, C.c_void_p)
DETACH = C.CFUNCTYPE(C.c_int, C.c_void_p)
PUBLISH = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(Job), C.c_char_p, C.c_uint64, C.c_void_p, C.POINTER(Publication))
RESOLVE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(Event))
REQUEST_SAVE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(DeviceReport))


class Backend(C.Structure):
    _fields_ = [('context', C.c_void_p), ('save', SAVE), ('attach', ATTACH),
                ('detach', DETACH), ('publish', PUBLISH), ('resolve', RESOLVE), ('catalog', CatalogApi)]


class PipelineMpr(FakeMpr):
    PATHS = [b'A:/DCIM/100MSDCF/DSC00001.JPG', b'A:/DCIM/100MSDCF/DSC00002.JPG']
    def __init__(self, fault=None):
        super().__init__(jpeg((20, 40, 60)), jpeg((220, 180, 120)), fault=fault, chunk=17)
        self.files = dict(zip(self.PATHS, self.files.values()))
        self.directories = []
        self.mkdir_cb = MKDIR(self.mkdir)

    def open(self, path, flags, handle):
        self.events.append(('open', path, flags))
        if flags == 6:
            handle[0] = self.output_handle
            return -33 if self.fault == 'partial-output' else 0
        if flags != 1 or path not in self.PATHS: return -10
        handle[0] = 0x100000001 + self.PATHS.index(path)
        return 0

    def mkdir(self, path):
        self.events.append(('mkdir', path))
        self.directories.append(path)
        return -30 if self.fault == 'mkdir' else 0


class RuntimeLoader(FakeLoader):
    def __init__(self, mpr):
        super().__init__()
        self.symbol_addresses = [C.cast(getattr(mpr.api, name), C.c_void_p).value
                                 for name in ('open', 'read', 'write', 'close', 'stat', 'flush')]
        self.symbol_addresses.append(C.cast(mpr.mkdir_cb, C.c_void_p).value)

    def symbol(self, context, handle, name):
        return self.symbol_addresses[SYMBOLS.index(name)]

    def owner(self, context, address, module):
        index = self.symbol_addresses.index(address)
        return int(module == (b'libInfraFsys.so' if index >= 5 else b'libmpr.so'))


class Fixture:
    def __init__(self, fault):
        self.fault = fault
        self.mpr = PipelineMpr(fault)
        self.loader = RuntimeLoader(self.mpr)
        self.events, self.journal, self.requests, self.errors = [], [], [], []
        self.records = {}
        for uid, path in zip((0, 2), self.mpr.PATHS):
            record = bytearray(0x620)
            struct.pack_into('<II', record, 0, 1, uid)
            record[12:24] = bytes(range(12))
            record[0xc0] = 1; record[0xc1:0xc1 + len(path) + 1] = path + b'\0'
            record[0x24] = 1  # protected source must not mislabel a writable new file
            self.records[uid] = bytes(record)
        self.originals = dict(self.mpr.files)
        self.final = b'A:/DCIM/101A7AVG/A7AV0001.JPG'
        self.callbacks = [SAVE(self.save), ATTACH(self.attach), DETACH(self.detach), PUBLISH(self.publish),
                          CLEAR(self.clear), SELECT(self.select), ISSUE(self.issue), UPDATE(self.update), MEDIA(self.media),
                          DBFLUSH(self.db_flush), REQUEST_SAVE(self.save_request)]
        self.api = Backend(None, *self.callbacks[:4], RESOLVE(), CatalogApi(*self.callbacks[4:10]))

    def save(self, _, value):
        row = value.contents
        self.journal.append((row.step, row.intent, row.pair.phase))
        return -70 if self.fault == 'journal' and row.step == 5 and row.intent else 0

    def save_request(self, _, value):
        row = value.contents
        self.requests.append((row.operation, row.intent, row.request_id))
        return -71 if self.fault == 'request-journal' else 0

    def attach(self, _, sink, context):
        self.events.append('attach'); self.sink, self.sink_context = sink, context
        return -50 if self.fault == 'attach' else 0

    def detach(self, _):
        self.events.append('detach')
        return -51 if self.fault == 'detach' else 0

    def publish(self, _, job, staging, size, expected, out):
        self.events.append('publish')
        if C.string_at(expected, 32) != hashlib.sha256(self.mpr.data).digest():
            self.errors.append('encoded digest differs'); return -64
        if self.fault == 'publish': return -52
        out.contents.bytes, out.contents.owned, out.contents.distinct = size, 1, 1
        out.contents.path = self.final
        if self.fault == 'same-dcf': out.contents.distinct = 0
        return 0

    def clear(self, pointer): C.memset(pointer, 0, 0x620)

    def select(self, flags, uid, pointer, verbose):
        self.events.append(('select', uid))
        if self.fault == 'select' or uid not in self.records: return -60
        data = bytearray(self.records[uid])
        if uid == 9 and self.fault == 'verify': data[0xc1] = ord('B')
        C.memmove(pointer, bytes(data), len(data)); return 0

    def issue(self, media, pointer, verbose):
        self.events.append('issue'); pointer[0] = 9
        return -61 if self.fault == 'issue' else 0

    def update(self, flags, pointer, a, b):
        self.events.append('update')
        self.records[9] = C.string_at(pointer, 0x620)
        return -62 if self.fault == 'update' else 0

    def media(self, uid, out): out[0] = 1 if self.fault == 'media' else 0; return 0
    def db_flush(self, media): self.events.append('db-flush'); return -63 if self.fault == 'db-flush' else 0

    def notify(self, kind, capture, content=0, path=b'', generation=1, epoch=1):
        event = Event(epoch, capture, generation, content, kind, 0, 0, 0, path)
        self.sink(self.sink_context, C.byref(event))


def run_case(case):
    fixture = Fixture(case)
    lib = C.CDLL(os.environ['A7C2_PIPELINE_LIBRARY'])
    lib.a7_resident_abi.restype = C.c_uint64
    assert lib.a7_resident_abi() == (1 << 32) | C.sizeof(DeviceReport)
    lib.a7_ap_start.argtypes = [C.POINTER(Loader), C.POINTER(Report)]
    lib.a7_ap_query.argtypes = lib.a7_ap_retire.argtypes = [C.POINTER(Report)]
    lib.a7_device_create.argtypes = [C.c_void_p, C.POINTER(Backend), REQUEST_SAVE]
    lib.a7_device_create.restype = C.c_void_p
    lib.a7_device_execute.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(DeviceReport)]
    lib.a7_device_destroy.argtypes = [C.c_void_p]
    runtime = Report()
    assert lib.a7_ap_start(C.byref(fixture.loader.api), C.byref(runtime)) == 0
    identity = b'INSTANCE-0000001'
    device = lib.a7_device_create(identity, C.byref(fixture.api), fixture.callbacks[-1]); assert device
    def execute(operation, request_id, *, instance=identity, raw=None):
        wire = raw if raw is not None else struct.pack('<8sIIQQQII16s', b'A7DEX001', operation, 0,
            request_id, 1 if operation == 1 else 0, 1 if operation == 1 else 0, 0, 123 if operation == 1 else 0, instance)
        report = DeviceReport()
        status = lib.a7_device_execute(device, wire, len(wire), C.byref(report))
        assert status == report.status
        return status, report
    if case == 'invalid':
        for wire in (b'', b'X' * 64): assert execute(1, 1, raw=wire)[0] == -16001
        assert not fixture.requests and not fixture.events
        assert lib.a7_device_destroy(device) == 0
    elif case == 'cancel-rearm':
        assert execute(1, 1)[0] == 0
        status, report = execute(4, 2)
        assert status == 0 and not report.pipeline.active and report.pipeline.pair.phase == 11
        wire = struct.pack('<8sIIQQQII16s', b'A7DEX001', 1, 0, 3, 2, 1, 0, 124, identity)
        assert execute(1, 3, raw=wire)[0] == 0
        assert execute(4, 4)[0] == 0
        assert fixture.events.count('attach') == fixture.events.count('detach') == 2
        assert not fixture.mpr.events
        assert lib.a7_device_destroy(device) == 0
    else:
        status, report = execute(1, 1)
        if case in ('attach', 'request-journal'):
            assert status < 0 and report.review
            assert 'publish' not in fixture.events
        else:
            assert status == 0
            if case == 'replay':
                count = len(fixture.requests)
                assert execute(1, 1)[0] == 0
                assert fixture.events.count('attach') == 1 and len(fixture.requests) == count
                assert execute(4, 1)[0] == -16002
            fixture.notify(1, 101)
            fixture.notify(1, 102)
            if case == 'overflow':
                for _ in range(17): fixture.notify(1, 102)
            elif case == 'generation':
                fixture.notify(2, 101, 0, fixture.mpr.PATHS[0], generation=2)
            else:
                fixture.notify(2, 102, 2, fixture.mpr.PATHS[1])
                fixture.notify(2, 101, 0, fixture.mpr.PATHS[0])
            assert not fixture.mpr.events  # callbacks only copy; no codec/SDK I/O
            status, report = execute(2, 2)
            success = case in ('success', 'replay', 'detach')
            if success:
                assert status == 0, (status, report.pipeline.backend_error)
                assert report.pipeline.pair.phase == 7 and report.pipeline.catalog_phase == 6
                assert report.pipeline.pair.result_id == 9
                assert fixture.events.count('issue') == fixture.events.count('update') == 1
                assert fixture.events[-1] == ('select', 9)
                assert fixture.events.count('db-flush') == 1
                assert fixture.records[9][12:24] == bytes(range(12))
                assert fixture.records[9][0x24] == 0
                from PIL import Image
                with Image.open(io.BytesIO(fixture.mpr.data)) as image:
                    assert all(abs(a - b) <= 3 for a, b in zip(image.getpixel((0, 0)), (120, 110, 90)))
                old = len(fixture.events)
                assert execute(2, 2)[0] == 0 and len(fixture.events) == old
                status, report = execute(4, 3)
                if case == 'detach': assert status < 0 and report.review
                else:
                    assert status == 0 and not report.pipeline.active
                    assert lib.a7_device_destroy(device) == 0
            else:
                assert status < 0 and report.review, (case, status, report.pipeline.pair.phase)
                old = list(fixture.events)
                assert execute(2, 3)[0] == -16003 and fixture.events == old
                if case in ('overflow', 'generation', 'journal', 'mkdir', 'partial-output', 'read', 'flush', 'close'):
                    assert 'publish' not in fixture.events
                if case in ('publish', 'same-dcf', 'select', 'media'): assert 'issue' not in fixture.events
                if case == 'issue': assert fixture.events.count('issue') == 1 and 'update' not in fixture.events
                if case in ('update', 'verify', 'db-flush'): assert fixture.events.count('update') == 1
                if case == 'issue':
                    assert report.pipeline.catalog_uid == 9 and not report.pipeline.catalog_uid_valid
                    assert report.pipeline.catalog_error == -61
                if case == 'update':
                    assert report.pipeline.catalog_uid == 9 and report.pipeline.catalog_uid_valid
                    assert report.pipeline.catalog_error == -62
                if case == 'db-flush':
                    assert fixture.events.count('db-flush') == 1
                    assert report.pipeline.catalog_uid == 9 and report.pipeline.catalog_error == -63
                assert lib.a7_device_destroy(device) != 0
            assert fixture.mpr.files == fixture.originals
    lib.a7_ap_query(C.byref(runtime))
    assert not fixture.errors, fixture.errors
    if case in ('success', 'replay', 'invalid', 'cancel-rearm'):
        assert runtime.jobs == runtime.callbacks == 0
        assert lib.a7_ap_retire(C.byref(runtime)) == 0
        fixture.loader.close(None, runtime.release_handle)
    print(json.dumps({'case': case, 'verified': True, 'camera_io': False}))


@unittest.skipUnless(os.environ.get('A7C2_PIPELINE_LIBRARY'), 'Set A7C2_PIPELINE_LIBRARY to the integrated host core')
class IntegratedPipeline(unittest.TestCase):
    def test_request_callback_mean_and_independent_catalog_confirmation(self): self.run_case('success')
    def test_completed_request_replay_returns_cached_report(self): self.run_case('replay')
    def test_invalid_requests_do_not_start_or_persist(self): self.run_case('invalid')
    def test_callback_attach_unknown_keeps_module_reference(self): self.run_case('attach')
    def test_callback_rundown_failure_blocks_unload(self): self.run_case('detach')
    def test_request_intent_failure_does_not_attach(self): self.run_case('request-journal')
    def test_pipeline_journal_failure_stops_before_encoding(self): self.run_case('journal')
    def test_queue_overflow_stops_before_media_io(self): self.run_case('overflow')
    def test_media_generation_change_stops_pair(self): self.run_case('generation')
    def test_existing_or_uncertain_directory_not_replayed(self): self.run_case('mkdir')
    def test_partial_output_open_retains_pending_handle(self): self.run_case('partial-output')
    def test_native_read_error_does_not_publish(self): self.run_case('read')
    def test_native_flush_error_does_not_publish(self): self.run_case('flush')
    def test_native_close_error_does_not_publish(self): self.run_case('close')
    def test_unknown_publication_does_not_issue_uid(self): self.run_case('publish')
    def test_prefix_only_dcf_identity_not_accepted(self): self.run_case('same-dcf')
    def test_source_catalog_failure_does_not_issue_uid(self): self.run_case('select')
    def test_wrong_source_media_does_not_issue_uid(self): self.run_case('media')
    def test_uid_issue_unknown_not_repeated(self): self.run_case('issue')
    def test_catalog_update_unknown_not_repeated(self): self.run_case('update')
    def test_independent_catalog_mismatch_never_complete(self): self.run_case('verify')
    def test_catalog_flush_unknown_never_repeats_or_marks_complete(self): self.run_case('db-flush')
    def test_disable_before_capture_allows_a_fresh_epoch(self): self.run_case('cancel-rearm')

    def run_case(self, case):
        result = subprocess.run([sys.executable, __file__, case], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertTrue(json.loads(result.stdout)['verified'])


if __name__ == '__main__':
    if len(sys.argv) == 2 and not sys.argv[1].startswith('-'): run_case(sys.argv[1])
    else: unittest.main()
