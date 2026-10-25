"""Owned-directory output reservation, with a deliberately non-exclusive Open."""
import ctypes as C
import io
import os
import unittest
from test_jpeg_stream import (Api, MprStream, FakeMpr, NATIVE_ERROR, Input, Output, Result, jpeg)

MKDIR = C.CFUNCTYPE(C.c_int32, C.c_char_p)
EXISTS = C.c_int32(0x80000022).value


class Reservation(C.Structure):
    _fields_ = [('epoch', C.c_uint64), ('pending_handle', C.c_uint64), ('encoded_bytes', C.c_uint64),
                ('phase', C.c_uint32), ('directory_owned', C.c_uint32), ('file_owned', C.c_uint32),
                ('native_error', C.c_int32), ('directory', C.c_char * 512), ('path', C.c_char * 512),
                ('writer', MprStream)]


class OutputBackend(FakeMpr):
    def __init__(self, *, fault=None):
        super().__init__(jpeg('red'), jpeg('blue'))
        self.fault = fault
        self.directories, self.contents = set(), {}
        self.mkdir_cb = MKDIR(self.mkdir)

    def mkdir(self, path):
        self.events.append(('mkdir', path))
        if path.lower() in {p.lower() for p in self.directories}: return EXISTS
        self.directories.add(path)
        return NATIVE_ERROR if self.fault == 'mkdir' else 0

    def open(self, path, flags, handle):
        if flags == 1: return super().open(path, flags, handle)
        self.events.append(('open', path, flags))
        if flags != 6 or path.rsplit(b'/', 1)[0] not in self.directories: return NATIVE_ERROR
        handle[0] = self.output_handle
        if self.fault == 'output-open': return NATIVE_ERROR
        # Native write|create can open an existing file without establishing
        # ownership. The reservation must never get here for an old directory.
        if path in self.contents: self.data = self.contents[path]
        else: self.contents[path] = self.data
        return 0


@unittest.skipUnless(os.environ.get('A7C2_STREAM_LIBRARY'), 'Set A7C2_STREAM_LIBRARY to a host library')
class OutputReservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = C.CDLL(os.environ['A7C2_STREAM_LIBRARY'])
        cls.lib.a7_output_plan.argtypes = [C.POINTER(Reservation), C.c_uint64, C.c_char_p, C.c_uint32]
        for name in ('a7_output_prepare_mkdir', 'a7_output_prepare_open'):
            getattr(cls.lib, name).argtypes = [C.POINTER(Reservation), C.c_uint64]
        cls.lib.a7_output_create_dir.argtypes = [C.POINTER(Reservation), C.c_uint64, MKDIR]
        cls.lib.a7_output_open_temp.argtypes = [C.POINTER(Reservation), C.c_uint64, C.POINTER(Api)]
        cls.lib.a7_output_note_closed.argtypes = [C.POINTER(Reservation), C.c_uint64, C.c_uint64]
        cls.lib.a7_mpr_open_reader.argtypes = [C.POINTER(MprStream), C.POINTER(Api), C.c_char_p]
        cls.lib.a7_mpr_get_input.argtypes = [C.POINTER(MprStream), C.POINTER(Input)]
        cls.lib.a7_mpr_get_output.argtypes = [C.POINTER(MprStream), C.POINTER(Output)]
        cls.lib.a7_mpr_flush_writer.argtypes = [C.POINTER(MprStream)]
        cls.lib.a7_mpr_close.argtypes = [C.POINTER(MprStream)]
        cls.lib.a7_jpeg_mean.argtypes = [C.POINTER(Input), C.POINTER(Input), C.POINTER(Output),
                                        C.c_void_p, C.POINTER(Result)]

    def setUp(self):
        self.backend, self.state = OutputBackend(), Reservation()
        self.assertEqual(self.lib.a7_output_plan(C.byref(self.state), 10, b'A:/DCIM/100MSDCF', 123), 0)

    def directory(self):
        self.assertEqual(self.lib.a7_output_prepare_mkdir(C.byref(self.state), 10), 0)
        self.assertEqual(self.lib.a7_output_create_dir(C.byref(self.state), 10, self.backend.mkdir_cb), 0)

    def opened(self):
        self.directory()
        self.assertEqual(self.lib.a7_output_prepare_open(C.byref(self.state), 10), 0)
        self.assertEqual(self.lib.a7_output_open_temp(C.byref(self.state), 10, C.byref(self.backend.api)), 0)

    def test_planning_has_no_sdk_side_effects_and_stays_under_photo_parent(self):
        self.assertEqual(self.backend.events, [])
        self.assertEqual(self.state.directory, b'A:/DCIM/100MSDCF/A700007B')
        self.assertEqual(self.state.path, b'A:/DCIM/100MSDCF/A700007B/MEAN.TMP')
        self.assertEqual(self.state.phase, 1)
        for path in (b'/usr', b'A:/PRIVATE', b'A:/DCIM/100MSDCF/..',
                     b'A:/DCIM/100MSDCF/child', b'A:/x/../DCIM/100MSDCF', b'A:/DCIM/100MSDCF\n'):
            state = Reservation()
            self.assertEqual(self.lib.a7_output_plan(C.byref(state), 10, path, 123), -12001)
            self.assertEqual(bytes(state), bytes(C.sizeof(state)))

    def test_explicit_intents_are_required_and_operations_claim_once(self):
        self.assertEqual(self.lib.a7_output_create_dir(C.byref(self.state), 10, self.backend.mkdir_cb), -12002)
        self.assertEqual(self.lib.a7_output_open_temp(C.byref(self.state), 10, C.byref(self.backend.api)), -12002)
        self.assertEqual(self.backend.events, [])
        self.opened()
        before = list(self.backend.events)
        self.assertEqual(self.lib.a7_output_create_dir(C.byref(self.state), 10, self.backend.mkdir_cb), -12002)
        self.assertEqual(self.lib.a7_output_open_temp(C.byref(self.state), 10, C.byref(self.backend.api)), -12002)
        self.assertEqual(self.backend.events, before)
        self.assertEqual((self.state.directory_owned, self.state.file_owned), (1, 1))
        self.assertEqual(self.backend.events[-1][2], 6)

    def test_existing_directory_and_user_file_are_never_opened_as_owned(self):
        self.backend.directories.add(self.state.directory)
        self.backend.contents[self.state.path] = bytearray(b'original user bytes')
        self.lib.a7_output_prepare_mkdir(C.byref(self.state), 10)
        self.assertEqual(self.lib.a7_output_create_dir(C.byref(self.state), 10, self.backend.mkdir_cb), -12003)
        self.assertEqual(self.state.native_error, EXISTS)
        self.assertEqual((self.state.directory_owned, self.state.file_owned), (0, 0))
        self.assertEqual(self.backend.contents[self.state.path], b'original user bytes')
        self.assertFalse(any(e[0] == 'open' for e in self.backend.events))

    def test_uncertain_mkdir_and_partial_open_are_retained_without_retry(self):
        self.backend.fault = 'mkdir'
        self.lib.a7_output_prepare_mkdir(C.byref(self.state), 10)
        self.assertEqual(self.lib.a7_output_create_dir(C.byref(self.state), 10, self.backend.mkdir_cb), -12003)
        self.assertEqual((self.state.phase, self.state.directory_owned), (9, 0))
        self.assertIn(self.state.directory, self.backend.directories)
        before = list(self.backend.events)
        self.assertEqual(self.lib.a7_output_create_dir(C.byref(self.state), 10, self.backend.mkdir_cb), -12002)
        self.assertEqual(self.backend.events, before)
        self.setUp(); self.directory(); self.backend.fault = 'output-open'
        self.lib.a7_output_prepare_open(C.byref(self.state), 10)
        self.assertEqual(self.lib.a7_output_open_temp(C.byref(self.state), 10, C.byref(self.backend.api)), -12003)
        self.assertEqual((self.state.phase, self.state.directory_owned, self.state.file_owned), (9, 1, 0))
        self.assertEqual(self.state.pending_handle, self.backend.output_handle)
        self.assertFalse(any(e[0] == 'close' for e in self.backend.events))

    def test_old_epoch_and_encoded_bytes_do_not_bypass_handle_close(self):
        before = bytes(self.state)
        self.assertEqual(self.lib.a7_output_prepare_mkdir(C.byref(self.state), 9), -12004)
        self.assertEqual(bytes(self.state), before)
        self.opened()
        self.assertEqual(self.lib.a7_output_note_closed(C.byref(self.state), 10, 123), -12002)
        self.assertEqual(self.state.phase, 9)

    def test_reserved_stream_can_encode_flush_close_without_publication(self):
        self.opened()
        a, b, left, right, dest, result = MprStream(), MprStream(), Input(), Input(), Output(), Result()
        for state, path in ((a, b'A:/first.jpg'), (b, b'A:/second.jpg')):
            self.assertEqual(self.lib.a7_mpr_open_reader(C.byref(state), C.byref(self.backend.api), path), 0)
        self.lib.a7_mpr_get_input(C.byref(a), C.byref(left))
        self.lib.a7_mpr_get_input(C.byref(b), C.byref(right))
        self.lib.a7_mpr_get_output(C.byref(self.state.writer), C.byref(dest))
        self.assertEqual(self.lib.a7_jpeg_mean(C.byref(left), C.byref(right), C.byref(dest),
                                              None, C.byref(result)), 0, result.message)
        self.assertEqual(self.lib.a7_mpr_flush_writer(C.byref(self.state.writer)), 0)
        for stream in (a, b, self.state.writer): self.assertEqual(self.lib.a7_mpr_close(C.byref(stream)), 0)
        self.assertEqual(self.lib.a7_output_note_closed(C.byref(self.state), 10, result.output_bytes), 0)
        self.assertEqual((self.state.phase, self.state.encoded_bytes), (8, len(self.backend.data)))
        from PIL import Image
        with Image.open(io.BytesIO(self.backend.data)) as image: image.load()
        self.assertFalse(any(e[0] in ('move', 'remove', 'register') for e in self.backend.events))


if __name__ == '__main__':
    unittest.main()
