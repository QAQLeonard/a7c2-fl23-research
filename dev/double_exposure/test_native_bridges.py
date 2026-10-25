"""Native DCF/delegate bridge contracts with local SDK-shaped callbacks."""
import ctypes as C
import hashlib
import os
import threading
import unittest
from test_capture_pair import Job
from test_jpeg_stream import Api, OPEN, MREAD, MWRITE, CLOSE, STAT, FLUSH
from test_output_reservation import MKDIR
from test_pipeline import Publication

FIRST = C.CFUNCTYPE(C.c_int32, C.c_char_p, C.c_uint8, C.c_void_p)
NEXT = C.CFUNCTYPE(C.c_int32, C.c_void_p)
MOVE = C.CFUNCTYPE(C.c_int32, C.c_char_p, C.c_char_p)


class DcfState(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('phase', 'directory_owned', 'close_attempted', 'handle_owned')] + [
        ('native_error', C.c_int32), ('close_error', C.c_int32), ('bytes', C.c_uint64), ('pending_handle', C.c_uint64),
        ('staging', C.c_char * 512), ('directory', C.c_char * 512), ('path', C.c_char * 512), ('checksum', C.c_uint8 * 32)]


DCF_SAVE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(DcfState))
CACHE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.c_uint16, C.c_char_p)


class DcfApi(C.Structure):
    _fields_ = [('context', C.c_void_p), ('first', FIRST), ('next', NEXT), ('mkdir', MKDIR),
                ('move', MOVE), ('files', Api), ('save', DCF_SAVE), ('cache_context', C.c_void_p),
                ('reserve', CACHE), ('ready', CACHE)]


class DcfFixture:
    TEMP = b'A:/DCIM/100MSDCF/A7000001/MEAN.TMP'
    def __init__(self, fault=None, full=False):
        self.fault, self.calls, self.positions, self.handles = fault, [], {}, {}
        self.data = bytes(range(256)) * 257
        self.contents = {self.TEMP: self.data}
        if fault == 'staging-tamper': self.contents[self.TEMP] = b'X' + self.data[1:]
        names = [f'{i:03}OTHER' for i in range(100, 1000)] if full else ['100MSDCF', '101OTHER', '101ALIAS']
        self.names = [C.create_string_buffer(name.encode()) for name in names]
        self.index = 0
        self.callbacks = [FIRST(self.first), NEXT(self.next), MKDIR(self.mkdir), MOVE(self.move),
                          OPEN(self.open), MREAD(self.read), MWRITE(lambda *args: -1),
                          CLOSE(self.close), STAT(self.stat), FLUSH(lambda _: 0), DCF_SAVE(self.save)]
        self.cache_callbacks = [CACHE(self.reserve), CACHE(self.ready)]
        self.api = DcfApi(None, *self.callbacks[:4], Api(*self.callbacks[4:10]), self.callbacks[10], None, *self.cache_callbacks)

    def first(self, pattern, flags, find):
        self.calls.append(('first', pattern, flags)); self.index = 0
        C.c_void_p.from_address(find).value = C.addressof(self.names[0]); return 0
    def next(self, find):
        self.index += 1
        if self.fault == 'scan': return -7
        if self.index == len(self.names): return 2
        C.c_void_p.from_address(find).value = C.addressof(self.names[self.index]); return 0
    def mkdir(self, path):
        self.calls.append(('mkdir', path))
        if self.fault == 'mkdir': return -8
        self.names.append(C.create_string_buffer(path.rsplit(b'/', 1)[1]))
        if self.fault == 'numeric-race': self.names.append(C.create_string_buffer(b'102OTHER'))
        return 0
    def reserve(self, _, media, number, name):
        self.calls.append(('reserve', number, name)); return -14 if self.fault == 'cache-busy' else 0
    def ready(self, _, media, number, name):
        self.calls.append(('ready', number, name)); return -15 if self.fault == 'cache-ready' else 0
    def move(self, a, b):
        self.calls.append(('move', a, b))
        if self.fault == 'move': return -9
        self.contents[b] = self.contents.pop(a)
        if self.fault == 'tamper': self.contents[b] = b'X' + self.contents[b][1:]
        return 0
    def open(self, path, flags, handle):
        self.calls.append(('open', path, flags))
        if flags != 1 or path not in self.contents: return -10
        identifier = 0x100000001 + len(self.handles)
        self.handles[identifier] = path
        self.positions[identifier] = 0; handle[0] = identifier; return 0
    def read(self, drive, handle, buffer, size):
        if self.fault == 'read': return -11
        data = self.contents[self.handles[handle]]; at = self.positions[handle]
        count = min(size, 13, len(data) - at)
        if count: C.memmove(buffer, data[at:at + count], count)
        self.positions[handle] += count; return count
    def close(self, drive, handle): self.calls.append(('close', handle)); return -12 if self.fault == 'close' else 0
    def stat(self, path, size): size[0] = len(self.contents[path]); return 0
    def save(self, _, state):
        self.calls.append(('save', state.contents.phase))
        return -13 if self.fault == 'journal' and state.contents.phase == 4 else 0


@unittest.skipUnless(os.environ.get('A7C2_PIPELINE_LIBRARY'), 'Set A7C2_PIPELINE_LIBRARY')
class DcfPublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = C.CDLL(os.environ['A7C2_PIPELINE_LIBRARY'])
        cls.lib.a7_dcf_publish.argtypes = [C.POINTER(DcfState), C.POINTER(DcfApi), C.POINTER(Job),
                                         C.c_char_p, C.c_uint64, C.c_char_p, C.POINTER(Publication)]

    def run_fixture(self, fault=None, full=False):
        fixture, state, job, out = DcfFixture(fault, full), DcfState(), Job(), Publication()
        job.epoch = job.media_generation = 1
        job.shots[0].path = b'A:/DCIM/100MSDCF/DSC00001.JPG'
        job.shots[1].path = b'A:/DCIM/100MSDCF/DSC00002.JPG'
        status = self.lib.a7_dcf_publish(C.byref(state), C.byref(fixture.api), C.byref(job),
                                        fixture.TEMP, len(fixture.data), hashlib.sha256(fixture.data).digest(), C.byref(out))
        return fixture, state, job, out, status

    def test_numeric_aliases_are_skipped_and_full_bytes_verified(self):
        fixture, state, job, out, status = self.run_fixture()
        self.assertEqual(status, 0)
        self.assertEqual((state.phase, out.owned, out.distinct), (6, 1, 1))
        self.assertEqual(out.path, b'A:/DCIM/102A7AVG/A7AV0001.JPG')
        self.assertEqual(fixture.contents[out.path], fixture.data)
        self.assertIn(('save', 2), fixture.calls)
        self.assertIn(('save', 4), fixture.calls)

    def test_all_numbers_occupied_never_mutates(self):
        fixture, state, _, out, status = self.run_fixture(full=True)
        self.assertLess(status, 0); self.assertEqual(state.phase, 7)
        self.assertFalse(any(row[0] in ('mkdir', 'move', 'open') for row in fixture.calls))

    def test_scan_error_never_creates_directory(self):
        fixture, state, _, _, status = self.run_fixture('scan')
        self.assertEqual(status, -7)
        self.assertFalse(any(row[0] == 'mkdir' for row in fixture.calls))

    def test_uncertain_mkdir_and_move_not_replayed(self):
        for fault, code in (('mkdir', -8), ('move', -9)):
            fixture, state, job, out, status = self.run_fixture(fault)
            self.assertEqual(status, code)
            before = list(fixture.calls)
            self.assertLess(self.lib.a7_dcf_publish(C.byref(state), C.byref(fixture.api), C.byref(job),
                fixture.TEMP, len(fixture.data), hashlib.sha256(fixture.data).digest(), C.byref(out)), 0)
            self.assertEqual(fixture.calls, before)

    def test_changed_destination_is_not_verified(self):
        fixture, state, _, out, status = self.run_fixture('tamper')
        self.assertLess(status, 0); self.assertEqual((state.phase, out.owned), (7, 0))
        self.assertTrue(state.directory_owned)

    def test_journal_failure_before_move_preserves_temporary(self):
        fixture, state, _, _, status = self.run_fixture('journal')
        self.assertEqual(status, -13)
        self.assertIn(fixture.TEMP, fixture.contents)
        self.assertFalse(any(row[0] == 'move' for row in fixture.calls))

    def test_read_and_close_errors_stop_before_mkdir(self):
        for fault in ('read', 'close'):
            fixture, state, _, _, status = self.run_fixture(fault)
            self.assertLess(status, 0)
            self.assertEqual(len([row for row in fixture.calls if row[0] == 'close']), 1)
            self.assertFalse(any(row[0] == 'mkdir' for row in fixture.calls))

    def test_native_number_reservation_precedes_directory_creation(self):
        fixture, _, _, _, status = self.run_fixture()
        self.assertEqual(status, 0)
        names = [row[0] for row in fixture.calls]
        self.assertLess(names.index('reserve'), names.index('mkdir'))
        self.assertLess(names.index('ready'), names.index('move'))

    def test_cache_conflict_never_creates_or_moves_files(self):
        fixture, _, _, _, status = self.run_fixture('cache-busy')
        self.assertEqual(status, -14)
        self.assertFalse(any(row[0] in ('mkdir', 'move') for row in fixture.calls))

    def test_numeric_alias_racing_directory_creation_stops_before_move(self):
        fixture, state, _, _, status = self.run_fixture('numeric-race')
        self.assertLess(status, 0)
        self.assertEqual(state.phase, 7)
        self.assertFalse(any(row[0] == 'move' for row in fixture.calls))

    def test_cache_confirmation_failure_does_not_move(self):
        fixture, _, _, _, status = self.run_fixture('cache-ready')
        self.assertEqual(status, -15)
        self.assertFalse(any(row[0] == 'move' for row in fixture.calls))

    def test_staging_must_match_encoder_digest_before_number_reservation(self):
        fixture, state, _, _, status = self.run_fixture('staging-tamper')
        self.assertLess(status, 0)
        self.assertEqual(state.phase, 7)
        self.assertFalse(any(row[0] in ('reserve', 'mkdir', 'move') for row in fixture.calls))


METHOD = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)
LOCK = C.CFUNCTYPE(C.c_int, C.c_void_p)
SINK = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)


class DelegateObject(C.Structure):
    _fields_ = [('vtable', C.POINTER(METHOD))]


class DelegateApi(C.Structure):
    _fields_ = [('context', C.c_void_p), ('slot', C.POINTER(C.c_void_p)), ('lock', LOCK), ('unlock', LOCK)]


@unittest.skipUnless(os.environ.get('A7C2_PIPELINE_LIBRARY'), 'Set A7C2_PIPELINE_LIBRARY')
class CaptureDelegate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = C.CDLL(os.environ['A7C2_PIPELINE_LIBRARY'])
        cls.lib.a7_capture_delegate_create.argtypes = [C.POINTER(DelegateApi), SINK, C.c_void_p]
        cls.lib.a7_capture_delegate_create.restype = C.c_void_p
        for name in ('attach', 'detach', 'destroy'):
            getattr(cls.lib, 'a7_capture_delegate_' + name).argtypes = [C.c_void_p]

    def setUp(self):
        self.mutex, self.seen, self.forwarded = threading.RLock(), [], []
        self.method = METHOD(self.original)
        self.table = (METHOD * 1)(self.method)
        self.object = DelegateObject(self.table)
        self.slot = C.c_void_p(C.addressof(self.object))
        self.callbacks = [LOCK(lambda _: (self.mutex.acquire() and 0)), LOCK(self.release), SINK(self.sink)]
        self.api = DelegateApi(None, C.pointer(self.slot), *self.callbacks[:2])
        self.bridge = self.lib.a7_capture_delegate_create(C.byref(self.api), self.callbacks[2], None)
        self.assertTrue(self.bridge)

    def release(self, _): self.mutex.release(); return 0
    def sink(self, _, payload): self.seen.append(C.string_at(payload, 20))
    def original(self, pointer, payload):
        self.forwarded.append((pointer, C.string_at(payload, 20)))
        C.memset(payload, 0, 20)  # native delegate owns/releases its notification
    def dispatch(self):
        payload = C.create_string_buffer(bytes(range(20)))
        with self.mutex:
            obj = C.cast(self.slot, C.POINTER(DelegateObject)).contents
            obj.vtable[0](self.slot, payload)

    def test_original_pointer_and_ownership_forwarded_and_copy_retained(self):
        self.assertEqual(self.lib.a7_capture_delegate_attach(self.bridge), 0)
        self.dispatch()
        self.assertEqual(self.seen, [bytes(range(20))])
        self.assertEqual(self.forwarded, [(C.addressof(self.object), bytes(range(20)))])
        self.assertEqual(self.lib.a7_capture_delegate_destroy(self.bridge), -1)
        self.assertEqual(self.lib.a7_capture_delegate_detach(self.bridge), 0)
        self.assertEqual(self.slot.value, C.addressof(self.object))
        self.assertEqual(self.lib.a7_capture_delegate_destroy(self.bridge), 0)

    def test_detach_waits_for_native_dispatcher_to_return(self):
        entered, release, detached = threading.Event(), threading.Event(), threading.Event()
        def blocking(_, payload):
            entered.set(); self.assertTrue(release.wait(5)); self.sink(_, payload)
        sink = SINK(blocking)
        self.assertEqual(self.lib.a7_capture_delegate_destroy(self.bridge), 0)
        self.bridge = self.lib.a7_capture_delegate_create(C.byref(self.api), sink, None)
        self.assertEqual(self.lib.a7_capture_delegate_attach(self.bridge), 0)
        first = threading.Thread(target=self.dispatch); first.start()
        self.assertTrue(entered.wait(5))
        result = []
        def detach(): result.append(self.lib.a7_capture_delegate_detach(self.bridge)); detached.set()
        second = threading.Thread(target=detach); second.start()
        self.assertFalse(detached.wait(.05)); release.set()
        first.join(5); second.join(5)
        self.assertFalse(first.is_alive() or second.is_alive()); self.assertEqual(result, [0])
        self.assertEqual(self.lib.a7_capture_delegate_destroy(self.bridge), 0)
