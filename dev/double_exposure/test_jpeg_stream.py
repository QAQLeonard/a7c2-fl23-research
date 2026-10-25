"""Native stream-core tests with short/failing callbacks and a synthetic MPR.

Set A7C2_STREAM_LIBRARY to the host's built stream library. No live SDK calls.
"""
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import io
import os
import unittest

READ = C.CFUNCTYPE(C.c_int64, C.c_void_p, C.c_void_p, C.c_size_t)
WRITE = C.CFUNCTYPE(C.c_int64, C.c_void_p, C.c_void_p, C.c_size_t)
CANCEL = C.CFUNCTYPE(C.c_int, C.c_void_p)


class Input(C.Structure):
    _fields_ = [('context', C.c_void_p), ('length', C.c_uint64), ('read', READ)]


class Output(C.Structure):
    _fields_ = [('context', C.c_void_p), ('write', WRITE)]


class Control(C.Structure):
    _fields_ = [('context', C.c_void_p), ('cancelled', CANCEL)]


class Result(C.Structure):
    _fields_ = [('width', C.c_uint32), ('height', C.c_uint32), ('orientation', C.c_uint32),
                ('status', C.c_int32), ('io_error', C.c_int64), ('input_bytes', C.c_uint64 * 2),
                ('output_bytes', C.c_uint64), ('message', C.c_char * 512)]


OPEN = C.CFUNCTYPE(C.c_int32, C.c_char_p, C.c_uint32, C.POINTER(C.c_uint64))
MREAD = C.CFUNCTYPE(C.c_int32, C.c_char, C.c_uint64, C.c_void_p, C.c_uint32)
MWRITE = C.CFUNCTYPE(C.c_int32, C.c_char, C.c_uint64, C.c_void_p, C.c_uint32)
CLOSE = C.CFUNCTYPE(C.c_int32, C.c_char, C.c_uint64)
STAT = C.CFUNCTYPE(C.c_int32, C.c_char_p, C.POINTER(C.c_uint64))
FLUSH = C.CFUNCTYPE(C.c_int32, C.c_uint64)


class Api(C.Structure):
    _fields_ = [('open', OPEN), ('read', MREAD), ('write', MWRITE), ('close', CLOSE),
                ('stat', STAT), ('flush', FLUSH)]


class MprStream(C.Structure):
    _fields_ = [('api', Api), ('handle', C.c_uint64), ('length', C.c_uint64),
                ('phase', C.c_uint32), ('owned', C.c_uint32), ('close_attempted', C.c_uint32),
                ('last_error', C.c_int32), ('last_native_result', C.c_int32),
                ('close_error', C.c_int32), ('path', C.c_char * 512)]


NATIVE_ERROR = C.c_int32(0x80000010).value


def jpeg(color):
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (37, 29), color).save(output, format='JPEG', quality=100, subsampling=0)
    return output.getvalue()


class MemoryIo:
    def __init__(self, data, *, chunk=1 << 30, error=None, overread=False, zero=False):
        self.data = bytearray(data)
        self.at, self.calls = 0, 0
        self.chunk, self.error, self.overread, self.zero = chunk, error, overread, zero
        self.read_cb = READ(self.read)
        self.write_cb = WRITE(self.write)

    def read(self, context, buffer, size):
        self.calls += 1
        if self.error is not None: return self.error
        if self.overread: return size + 1
        count = min(size, self.chunk, len(self.data) - self.at)
        if count: C.memmove(buffer, bytes(self.data[self.at:self.at + count]), count)
        self.at += count
        return count

    def write(self, context, buffer, size):
        self.calls += 1
        if self.error is not None and self.calls > 1: return self.error
        if self.zero: return 0
        if self.overread: return size + 1
        count = min(size, self.chunk)
        self.data.extend(C.string_at(buffer, count))
        return count

    def input(self): return Input(None, len(self.data), self.read_cb)
    def output(self): return Output(None, self.write_cb)


class FakeMpr:
    def __init__(self, first, second, *, fault=None, chunk=1 << 30):
        self.files = {b'A:/first.jpg': first, b'A:/second.jpg': second}
        self.handles = {0x100000001: [first, 0], 0x100000002: [second, 0]}
        self.output_handle = 0x100000003
        self.data, self.events, self.fault, self.chunk = bytearray(), [], fault, chunk
        self.open_cb, self.read_cb = OPEN(self.open), MREAD(self.read)
        self.write_cb, self.close_cb = MWRITE(self.write), CLOSE(self.close)
        self.stat_cb, self.flush_cb = STAT(self.stat), FLUSH(self.flush)
        self.api = Api(self.open_cb, self.read_cb, self.write_cb, self.close_cb,
                       self.stat_cb, self.flush_cb)

    def open(self, path, flags, handle):
        self.events.append(('open', path, flags))
        if self.fault == 'partial-open':
            handle[0] = 0x100000099; return NATIVE_ERROR
        if self.fault == 'open': return NATIVE_ERROR
        if path not in self.files or flags != 1: return NATIVE_ERROR
        handle[0] = 0x100000001 if path == b'A:/first.jpg' else 0x100000002
        return 0

    def read(self, drive, handle, buffer, size):
        self.events.append(('read', drive, handle, size))
        if self.fault == 'read': return NATIVE_ERROR
        if handle not in self.handles or drive != b'A': return NATIVE_ERROR
        data, at = self.handles[handle]
        count = min(size, self.chunk, len(data) - at)
        if count: C.memmove(buffer, data[at:at + count], count)
        self.handles[handle][1] += count
        return count

    def write(self, drive, handle, buffer, size):
        self.events.append(('write', drive, handle, size))
        if self.fault == 'write': return NATIVE_ERROR
        if drive != b'A' or handle != self.output_handle: return NATIVE_ERROR
        count = min(size, self.chunk)
        self.data.extend(C.string_at(buffer, count)); return count

    def close(self, drive, handle):
        self.events.append(('close', drive, handle))
        return NATIVE_ERROR if self.fault == 'close' else 0

    def stat(self, path, length):
        self.events.append(('stat', path))
        if self.fault == 'stat': return NATIVE_ERROR
        length[0] = 0 if self.fault == 'length' else len(self.files[path])
        return 0

    def flush(self, handle):
        self.events.append(('flush', handle))
        return NATIVE_ERROR if self.fault == 'flush' else 0


@unittest.skipUnless(os.environ.get('A7C2_STREAM_LIBRARY'), 'Set A7C2_STREAM_LIBRARY to a host library')
class JpegStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = C.CDLL(os.environ['A7C2_STREAM_LIBRARY'])
        cls.lib.a7_jpeg_mean.argtypes = [C.POINTER(Input), C.POINTER(Input), C.POINTER(Output),
                                        C.POINTER(Control), C.POINTER(Result)]
        cls.lib.a7_jpeg_mean.restype = C.c_int
        for name in ('a7_mpr_open_reader', 'a7_mpr_attach_writer'):
            fn = getattr(cls.lib, name)
            fn.argtypes = [C.POINTER(MprStream), C.POINTER(Api), C.c_char_p] + (
                [C.c_uint64] if name.endswith('writer') else [])
            fn.restype = C.c_int
        cls.lib.a7_mpr_get_input.argtypes = [C.POINTER(MprStream), C.POINTER(Input)]
        cls.lib.a7_mpr_get_output.argtypes = [C.POINTER(MprStream), C.POINTER(Output)]
        for name in ('a7_mpr_close', 'a7_mpr_flush_writer'):
            getattr(cls.lib, name).argtypes = [C.POINTER(MprStream)]
            getattr(cls.lib, name).restype = C.c_int

    def run_mean(self, a, b, output, control=None):
        left, right, dest, result = a.input(), b.input(), output.output(), Result()
        status = self.lib.a7_jpeg_mean(C.byref(left), C.byref(right), C.byref(dest),
                                       C.byref(control) if control is not None else None, C.byref(result))
        self.assertEqual(status, result.status)
        return result

    def test_short_reads_and_writes_produce_same_jpeg(self):
        first, second = jpeg((20, 40, 60)), jpeg((220, 180, 120))
        normal, short = MemoryIo(b''), MemoryIo(b'', chunk=7)
        self.assertEqual(self.run_mean(MemoryIo(first), MemoryIo(second), normal).status, 0)
        result = self.run_mean(MemoryIo(first, chunk=3), MemoryIo(second, chunk=11), short)
        self.assertEqual(result.status, 0, result.message)
        self.assertEqual(short.data, normal.data)
        self.assertEqual(result.output_bytes, len(short.data))
        from PIL import Image
        with Image.open(io.BytesIO(short.data)) as image:
            self.assertTrue(all(abs(x - y) <= 3 for x, y in zip(image.getpixel((0, 0)), (120, 110, 90))))

    def test_native_read_error_is_preserved_and_not_retried(self):
        left, right, out = MemoryIo(jpeg('red'), error=NATIVE_ERROR), MemoryIo(jpeg('blue')), MemoryIo(b'')
        result = self.run_mean(left, right, out)
        self.assertEqual((result.status, result.io_error), (-2, NATIVE_ERROR))
        self.assertEqual((left.calls, right.calls, out.calls), (1, 0, 0))

    def test_error_after_known_short_write_does_not_repeat_prefix(self):
        output = MemoryIo(b'', chunk=11, error=NATIVE_ERROR)
        result = self.run_mean(MemoryIo(jpeg('red')), MemoryIo(jpeg('blue')), output)
        self.assertEqual((result.status, result.io_error), (-2, NATIVE_ERROR))
        self.assertEqual((output.calls, result.output_bytes, len(output.data)), (2, 11, 11))

    def test_zero_and_overreported_callback_results_fail(self):
        for fault in ('zero', 'overread'):
            with self.subTest(fault=fault):
                output = MemoryIo(b'', **{fault: True})
                result = self.run_mean(MemoryIo(jpeg('red')), MemoryIo(jpeg('blue')), output)
                self.assertEqual(result.status, -2)
                self.assertEqual(output.calls, 1)
        left = MemoryIo(jpeg('red'), overread=True)
        self.assertEqual(self.run_mean(left, MemoryIo(jpeg('blue')), MemoryIo(b'')).status, -2)
        self.assertEqual(left.calls, 1)

    def test_declared_length_and_early_eof_are_enforced(self):
        a, b, out, result = MemoryIo(jpeg('red')), MemoryIo(jpeg('blue')), MemoryIo(b''), Result()
        left, right, dest = a.input(), b.input(), out.output()
        for length in (0, 96 * 1024 * 1024 + 1):
            left.length = length
            self.assertEqual(self.lib.a7_jpeg_mean(C.byref(left), C.byref(right), C.byref(dest),
                                                  None, C.byref(result)), -1)
            self.assertEqual(a.calls, 0)
        left.length = len(a.data) + 100
        a.data = a.data[:-2]
        self.assertEqual(self.lib.a7_jpeg_mean(C.byref(left), C.byref(right), C.byref(dest),
                                              None, C.byref(result)), -3)

    def test_cancel_is_per_job_and_does_not_affect_concurrent_job(self):
        first, second = jpeg('red'), jpeg('blue')
        cancel = CANCEL(lambda _: 1)
        control = Control(None, cancel)
        with ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(self.run_mean, MemoryIo(first), MemoryIo(second), MemoryIo(b''), control)
            saved = pool.submit(self.run_mean, MemoryIo(first), MemoryIo(second), MemoryIo(b''))
            self.assertEqual(failed.result().status, -4)
            self.assertEqual(saved.result().status, 0)

    def test_mpr_reader_to_stream_core_keeps_read_only_flags_and_64_bit_handles(self):
        backend = FakeMpr(jpeg('red'), jpeg('blue'), chunk=7)
        a, b, out = MprStream(), MprStream(), MprStream()
        for state, path in ((a, b'A:/first.jpg'), (b, b'A:/second.jpg')):
            self.assertEqual(self.lib.a7_mpr_open_reader(C.byref(state), C.byref(backend.api), path), 0)
        self.assertEqual(self.lib.a7_mpr_attach_writer(C.byref(out), C.byref(backend.api),
                                                     b'A:/owned.tmp', backend.output_handle), 0)
        left, right, dest, result = Input(), Input(), Output(), Result()
        self.assertEqual(self.lib.a7_mpr_get_input(C.byref(a), C.byref(left)), 0)
        self.assertEqual(self.lib.a7_mpr_get_input(C.byref(b), C.byref(right)), 0)
        self.assertEqual(self.lib.a7_mpr_get_output(C.byref(out), C.byref(dest)), 0)
        self.assertEqual(self.lib.a7_jpeg_mean(C.byref(left), C.byref(right), C.byref(dest),
                                              None, C.byref(result)), 0, result.message)
        self.assertEqual([e[2] for e in backend.events if e[0] == 'open'], [1, 1])
        self.assertEqual({e[2] for e in backend.events if e[0] == 'read'}, {0x100000001, 0x100000002})
        self.assertFalse(any(e[0] == 'flush' for e in backend.events))
        self.assertEqual(self.lib.a7_mpr_flush_writer(C.byref(out)), 0)
        for state in (a, b, out):
            self.assertEqual(self.lib.a7_mpr_close(C.byref(state)), 0)
            self.assertEqual(self.lib.a7_mpr_close(C.byref(state)), -10003)
        self.assertEqual(len([e for e in backend.events if e[0] == 'close']), 3)
        from PIL import Image
        with Image.open(io.BytesIO(backend.data)) as image: image.load()

    def test_mpr_failed_or_partial_open_is_not_used_or_closed_as_success(self):
        for fault, phase in (('open', 3), ('partial-open', 5)):
            with self.subTest(fault=fault):
                backend, state = FakeMpr(jpeg('red'), jpeg('blue'), fault=fault), MprStream()
                self.assertEqual(self.lib.a7_mpr_open_reader(C.byref(state), C.byref(backend.api),
                                                            b'A:/first.jpg'), NATIVE_ERROR)
                self.assertEqual(state.phase, phase)
                self.assertEqual(self.lib.a7_mpr_close(C.byref(state)), -10003)
                self.assertEqual([e[0] for e in backend.events], ['open'])

    def test_mpr_bad_stat_or_length_closes_owned_reader_once(self):
        for fault, error in (('stat', NATIVE_ERROR), ('length', -10002)):
            with self.subTest(fault=fault):
                backend, state = FakeMpr(jpeg('red'), jpeg('blue'), fault=fault), MprStream()
                self.assertEqual(self.lib.a7_mpr_open_reader(C.byref(state), C.byref(backend.api),
                                                            b'A:/first.jpg'), error)
                self.assertEqual(state.phase, 4)
                self.assertEqual(self.lib.a7_mpr_close(C.byref(state)), -10003)
                self.assertEqual(len([e for e in backend.events if e[0] == 'close']), 1)

    def test_mpr_close_and_flush_errors_preserve_context_without_retry(self):
        backend, state = FakeMpr(jpeg('red'), jpeg('blue')), MprStream()
        self.assertEqual(self.lib.a7_mpr_open_reader(C.byref(state), C.byref(backend.api), b'A:/first.jpg'), 0)
        backend.fault = 'close'
        self.assertEqual(self.lib.a7_mpr_close(C.byref(state)), NATIVE_ERROR)
        self.assertEqual((state.phase, state.owned, state.close_attempted), (5, 1, 1))
        self.assertEqual(self.lib.a7_mpr_close(C.byref(state)), -10003)
        self.assertEqual(self.lib.a7_mpr_open_reader(C.byref(state), C.byref(backend.api), b'A:/first.jpg'), -10003)
        writer = MprStream(); backend.fault = 'flush'
        self.assertEqual(self.lib.a7_mpr_attach_writer(C.byref(writer), C.byref(backend.api),
                                                     b'A:/owned.tmp', backend.output_handle), 0)
        self.assertEqual(self.lib.a7_mpr_flush_writer(C.byref(writer)), NATIVE_ERROR)
        self.assertEqual(self.lib.a7_mpr_flush_writer(C.byref(writer)), -10003)
        self.assertEqual(writer.last_error, NATIVE_ERROR)


if __name__ == '__main__':
    unittest.main()
