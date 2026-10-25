"""Run the compiled ARM64 capture coordinator with reordered/failing events.

All capture/media notifications are synthetic. No camera hook is installed.
"""
import ctypes as C
import os
from pathlib import Path
import struct
import tempfile
import unittest
from build_average import build, ROOT

U64 = C.c_uint64
U32 = C.c_uint32
NO_CONTENT = (1 << 64) - 1
IDLE, COLLECTING, READY, PROCESSING, ENCODED, REGISTERING, VERIFYING, COMPLETE, FAILED, REVIEW, CANCELLING, CANCELLED = range(12)
OK, IGNORED, INVALID, BUSY, CONFLICT = 0, 1, -1, -2, -3
SUCCESS, NO_CHANGE, UNKNOWN = range(3)


class Shot(C.Structure):
    _fields_ = [('capture_id', U64), ('content_id', U64), ('started', U32),
                ('complete', U32), ('path', C.c_char * 512)]


class Session(C.Structure):
    _fields_ = [('phase', U32), ('media_id', U32), ('media_generation', U64),
                ('epoch', U64), ('shots', Shot * 2), ('staging', C.c_char * 512),
                ('result', C.c_char * 512), ('result_id', U64)]


class Job(C.Structure):
    _fields_ = [('epoch', U64), ('media_generation', U64), ('media_id', U32),
                ('reserved', U32), ('shots', Shot * 2), ('staging', C.c_char * 512)]


class CaptureIdentity(C.Structure):
    _fields_ = [('media_id', U32), ('content_id', U32),
                ('directory_number', C.c_uint16), ('file_number', C.c_uint16)]


class CapturePair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='a7c2-pair-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.library = build(Path(cls.temp.name) / 'pair.so',
                            source=ROOT / 'src/double_exposure/native/capture_pair.c',
                            entry='a7_pair_arm')

    def setUp(self):
        from elftools.elf.elffile import ELFFile
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_INTR
        from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1
        self.cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.base, self.stop = 0x10000000, 0x70000000
        self.state, self.job, self.strings = 0x20000000, 0x21000000, 0x30000000
        self.entries = {}
        with self.library.open('rb') as stream:
            elf = ELFFile(stream)
            segments = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
            end = max(s['p_vaddr'] + s['p_memsz'] for s in segments)
            self.cpu.mem_map(self.base, (end + 4095) & ~4095)
            for segment in segments:
                self.cpu.mem_write(self.base + segment['p_vaddr'], segment.data())
            for symbol in elf.get_section_by_name('.dynsym').iter_symbols():
                if symbol['st_info']['type'] == 'STT_FUNC':
                    self.entries[symbol.name] = self.base + symbol['st_value']
        for pointer in (self.state, self.job, self.strings, self.stop, 0x60000000):
            self.cpu.mem_map(pointer, 0x10000 if pointer == 0x60000000 else 4096)
        self.cpu.reg_write(UC_ARM64_REG_CPACR_EL1, 0x300000)
        self.cpu.hook_add(UC_HOOK_INTR, lambda *_: self.fail('Coordinator performed a syscall'))
        self.assertEqual(self.call('session_size'), C.sizeof(Session))

    def call(self, name, *args):
        from unicorn import arm64_const as R
        for index, value in enumerate(args):
            self.cpu.reg_write(getattr(R, 'UC_ARM64_REG_X' + str(index)), value)
        self.cpu.reg_write(R.UC_ARM64_REG_SP, 0x6000f000)
        self.cpu.reg_write(R.UC_ARM64_REG_LR, self.stop)
        self.cpu.emu_start(self.entries['a7_pair_' + name], self.stop, count=1000000)
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_PC), self.stop)
        value = self.cpu.reg_read(R.UC_ARM64_REG_X0)
        return value if name == 'session_size' else C.c_int32(value).value

    def text(self, value, offset=0):
        raw = value if isinstance(value, bytes) else value.encode()
        self.cpu.mem_write(self.strings + offset, raw + b'\0')
        return self.strings + offset

    def snapshot(self):
        return bytes(self.cpu.mem_read(self.state, C.sizeof(Session)))

    @property
    def current(self):
        return Session.from_buffer_copy(self.snapshot())

    def arm(self):
        self.assertEqual(self.call('arm', self.state, 10, 7, 100), OK)

    def saved(self, capture, uid, path, *, epoch=10, media=7, generation=100, outcome=SUCCESS):
        return self.call('saved', self.state, epoch, capture, media, generation, uid,
                         self.text(path), outcome)

    def ready(self):
        self.arm()
        for capture in (101, 102):
            self.assertEqual(self.call('begin', self.state, 10, capture), OK)
        self.assertEqual(self.saved(102, 20, '/card/b.jpg'), OK)
        self.assertEqual(self.current.phase, COLLECTING)
        self.assertEqual(self.saved(101, 10, '/card/a.jpg'), OK)
        self.assertEqual(self.current.phase, READY)

    def processing(self):
        self.ready()
        self.assertEqual(self.call('take', self.state, 10, self.text('/work/mean.jpg'), self.job), OK)

    def registering(self):
        self.processing()
        self.assertEqual(self.call('encoded', self.state, 10, SUCCESS), OK)
        self.assertEqual(self.call('register', self.state, 10, 7, 100), OK)

    def verifying(self):
        self.registering()
        self.assertEqual(self.call('registered', self.state, 10, SUCCESS, 30,
                                   self.text('/card/result.jpg')), OK)

    def test_reordered_completions_preserve_capture_order_and_single_job(self):
        self.processing()
        job = Job.from_buffer_copy(bytes(self.cpu.mem_read(self.job, C.sizeof(Job))))
        self.assertEqual([s.capture_id for s in job.shots], [101, 102])
        self.assertEqual([s.path for s in job.shots], [b'/card/a.jpg', b'/card/b.jpg'])
        self.assertEqual(job.staging, b'/work/mean.jpg')
        # Notification buffers may be reused immediately after returning.
        self.text('/different.jpg')
        self.assertEqual(self.current.shots[0].path, b'/card/a.jpg')
        self.assertEqual(self.call('take', self.state, 10, self.text('/work/again.jpg'), self.job), BUSY)
        self.assertEqual(self.call('arm', self.state, 11, 7, 100), BUSY)

    def test_old_or_unstarted_events_never_count_as_a_photo(self):
        self.arm()
        before = self.snapshot()
        self.assertEqual(self.saved(999, 10, '/old.jpg'), IGNORED)
        self.assertEqual(self.saved(101, 10, '/old.jpg', epoch=9), IGNORED)
        self.assertEqual(self.call('begin', self.state, 9, 101), IGNORED)
        self.assertEqual(self.snapshot(), before)

    def test_duplicates_do_not_fill_second_slot_or_rewrite_identity(self):
        self.arm()
        self.assertEqual(self.call('begin', self.state, 10, 101), OK)
        self.assertEqual(self.call('begin', self.state, 10, 101), IGNORED)
        self.assertEqual(self.saved(101, 10, '/card/a.jpg'), OK)
        before = self.snapshot()
        self.assertEqual(self.saved(101, 10, '/card/a.jpg'), IGNORED)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.current.shots[1].started)
        self.assertEqual(self.saved(101, 11, '/card/changed.jpg'), CONFLICT)
        self.assertEqual(self.current.phase, REVIEW)

    def test_same_content_or_path_cannot_be_two_exposures(self):
        for uid, path in ((10, '/card/b.jpg'), (20, '/card/a.jpg')):
            with self.subTest(uid=uid, path=path):
                self.setUp(); self.arm()
                for capture in (101, 102): self.call('begin', self.state, 10, capture)
                self.saved(101, 10, '/card/a.jpg')
                self.assertEqual(self.saved(102, uid, path), CONFLICT)
                self.assertEqual(self.current.phase, REVIEW)

    def test_media_change_and_unknown_capture_stop_pairing(self):
        for media, generation, outcome in ((8, 100, SUCCESS), (7, 101, SUCCESS), (7, 100, UNKNOWN)):
            with self.subTest(media=media, generation=generation, outcome=outcome):
                self.setUp(); self.arm(); self.call('begin', self.state, 10, 101)
                self.assertEqual(self.saved(101, 10, '/card/a.jpg', media=media,
                                            generation=generation, outcome=outcome), CONFLICT)
                self.assertEqual(self.current.phase, REVIEW)
                self.assertEqual(self.call('arm', self.state, 11, 7, 101), BUSY)

    def test_invalid_paths_and_source_as_output_do_not_schedule(self):
        self.ready()
        for path in ('/', 'relative.jpg', '/bad\nname.jpg', b'/' + b'a' * 511, '/card/a.jpg'):
            with self.subTest(path=str(path)[:30]):
                before = self.snapshot()
                self.assertEqual(self.call('take', self.state, 10, self.text(path), self.job), INVALID)
                self.assertEqual(self.snapshot(), before)

    def test_native_drive_sources_are_retained_and_staging_stays_posix(self):
        self.arm()
        for capture in (101, 102): self.call('begin', self.state, 10, capture)
        self.assertEqual(self.saved(101, 10, 'A:/DCIM/100MSDCF/DSC00001.JPG'), OK)
        self.assertEqual(self.saved(102, 20, 'A:/DCIM/100MSDCF/DSC00002.JPG'), OK)
        self.assertEqual(self.call('take', self.state, 10, self.text('A:/mean.jpg'), self.job), INVALID)
        self.assertEqual(self.call('take', self.state, 10, self.text('/tmp/mean.jpg'), self.job), OK)
        job = Job.from_buffer_copy(bytes(self.cpu.mem_read(self.job, C.sizeof(Job))))
        self.assertEqual(job.shots[0].path, b'A:/DCIM/100MSDCF/DSC00001.JPG')
        self.assertEqual(job.shots[1].path, b'A:/DCIM/100MSDCF/DSC00002.JPG')

    def test_native_drive_case_alias_is_one_source(self):
        self.arm()
        for capture in (101, 102): self.call('begin', self.state, 10, capture)
        self.saved(101, 10, 'A:/DCIM/100MSDCF/DSC00001.JPG')
        self.assertEqual(self.saved(102, 20, 'a:/dcim/100msdcf/dsc00001.jpg'), CONFLICT)
        self.assertEqual(self.current.phase, REVIEW)

    def test_encoding_unknown_retains_work_and_forbids_registration(self):
        self.processing()
        self.assertEqual(self.call('encoded', self.state, 10, UNKNOWN), CONFLICT)
        self.assertEqual(self.current.staging, b'/work/mean.jpg')
        self.assertEqual(self.call('register', self.state, 10, 7, 100), BUSY)
        self.assertEqual(self.current.phase, REVIEW)

    def test_registration_is_claimed_once_and_requires_catalog_confirmation(self):
        self.verifying()
        self.assertEqual(self.current.phase, VERIFYING)
        self.assertEqual(self.call('register', self.state, 10, 7, 100), BUSY)
        self.assertEqual(self.call('verified', self.state, 10, 7, 100, 30,
                                   self.text('/card/result.jpg')), OK)
        self.assertEqual(self.current.phase, COMPLETE)
        self.assertEqual(self.call('arm', self.state, 10, 7, 100), INVALID)
        self.assertEqual(self.call('arm', self.state, 11, 7, 100), OK)
        self.assertEqual(self.saved(101, 10, '/card/a.jpg', epoch=10), IGNORED)

    def test_zero_content_id_is_valid_and_result_cannot_be_a_source(self):
        self.registering()
        self.assertEqual(self.call('registered', self.state, 10, SUCCESS, 0,
                                   self.text('/card/result.jpg')), OK)
        self.assertEqual(self.call('verified', self.state, 10, 7, 100, 0,
                                   self.text('/card/result.jpg')), OK)
        for uid, path in ((10, '/card/result.jpg'), (30, '/card/a.jpg'),
                          (30, '/work/mean.jpg'), (NO_CONTENT, '/card/result.jpg')):
            with self.subTest(uid=uid, path=path):
                self.setUp(); self.registering()
                self.assertEqual(self.call('registered', self.state, 10, SUCCESS, uid,
                                           self.text(path)), CONFLICT)
                self.assertEqual(self.current.phase, REVIEW)

    def test_unknown_publication_never_retries_or_claims_complete(self):
        self.registering()
        self.assertEqual(self.call('registered', self.state, 10, UNKNOWN, NO_CONTENT, 0), CONFLICT)
        self.assertEqual(self.current.phase, REVIEW)
        self.assertEqual(self.call('register', self.state, 10, 7, 100), BUSY)
        self.assertEqual(self.call('arm', self.state, 11, 7, 100), BUSY)

    def test_catalog_mismatch_retains_result_for_review(self):
        for media, generation, uid, path in ((8, 100, 30, '/card/result.jpg'),
                                             (7, 101, 30, '/card/result.jpg'),
                                             (7, 100, 31, '/card/result.jpg'),
                                             (7, 100, 30, '/card/other.jpg')):
            with self.subTest(media=media, generation=generation, uid=uid, path=path):
                self.setUp(); self.verifying()
                self.assertEqual(self.call('verified', self.state, 10, media, generation,
                                           uid, self.text(path)), CONFLICT)
                self.assertEqual(self.current.result, b'/card/result.jpg')
                self.assertEqual(self.current.phase, REVIEW)

    def test_cancel_waits_for_running_worker_and_does_not_interrupt_registration(self):
        self.arm()
        self.assertEqual(self.call('cancel', self.state, 10), OK)
        self.assertEqual(self.current.phase, CANCELLED)
        self.setUp(); self.processing()
        self.assertEqual(self.call('cancel', self.state, 10), OK)
        self.assertEqual(self.current.phase, CANCELLING)
        self.assertEqual(self.call('arm', self.state, 11, 7, 100), BUSY)
        self.assertEqual(self.call('encoded', self.state, 10, SUCCESS), OK)
        self.assertEqual(self.current.phase, CANCELLED)
        self.setUp(); self.registering()
        self.assertEqual(self.call('cancel', self.state, 10), BUSY)
        self.assertEqual(self.current.phase, REGISTERING)

    def test_known_prepublication_failures_can_start_fresh_epoch(self):
        for step in ('capture', 'encode', 'register'):
            with self.subTest(step=step):
                self.setUp()
                if step == 'capture':
                    self.arm(); self.call('begin', self.state, 10, 101)
                    self.saved(101, NO_CONTENT, '', outcome=NO_CHANGE)
                elif step == 'encode':
                    self.processing(); self.call('encoded', self.state, 10, NO_CHANGE)
                else:
                    self.registering(); self.call('registered', self.state, 10, NO_CHANGE, NO_CONTENT, 0)
                self.assertEqual(self.current.phase, FAILED)
                self.assertEqual(self.call('arm', self.state, 11, 7, 100), OK)

    def result_bytes(self, records, error=0):
        raw = bytearray(56)
        struct.pack_into('<II', raw, 0, error, len(records))
        for index, (media, uid, directory, file) in enumerate(records):
            struct.pack_into('<I', raw, 8 + index * 4, media)
            struct.pack_into('<I', raw, 24 + index * 4, uid)
            struct.pack_into('<H', raw, 40 + index * 2, directory)
            struct.pack_into('<H', raw, 48 + index * 2, file)
        return bytes(raw)

    def decode(self, raw, media):
        self.cpu.mem_write(self.strings, raw)
        self.cpu.mem_write(self.job, b'\xa5' * C.sizeof(CaptureIdentity))
        status = self.call('decode_capture_result', self.strings, len(raw), media, self.job)
        result = bytes(self.cpu.mem_read(self.job, C.sizeof(CaptureIdentity)))
        if status != OK:
            self.assertEqual(result, b'\xa5' * C.sizeof(CaptureIdentity))
        return status, CaptureIdentity.from_buffer_copy(result)

    def test_capture_result_selects_media_without_truncating_content_id(self):
        raw = self.result_bytes([(7, 0, 100, 1), (8, 0x81234567, 123, 9876),
                                 (9, 44, 105, 42), (10, 55, 106, 43)])
        status, result = self.decode(raw, 8)
        self.assertEqual(status, OK)
        self.assertEqual((result.media_id, result.content_id, result.directory_number,
                          result.file_number), (8, 0x81234567, 123, 9876))
        self.assertEqual(self.decode(raw, 7)[1].content_id, 0)
        self.assertEqual(self.decode(raw, 99)[0], IGNORED)

    def test_capture_result_rejects_ambiguous_failed_or_short_records(self):
        raw = self.result_bytes([(7, 11, 100, 1)])
        self.assertEqual(self.decode(raw[:-1], 7)[0], INVALID)
        self.assertEqual(self.decode(raw + b'\0', 7)[0], INVALID)
        self.assertEqual(self.decode(self.result_bytes([], error=0), 7)[0], IGNORED)
        self.assertEqual(self.decode(self.result_bytes([(7, 11, 100, 1)], error=1), 7)[0], IGNORED)
        bad = bytearray(raw); struct.pack_into('<I', bad, 4, 5)
        self.assertEqual(self.decode(bytes(bad), 7)[0], INVALID)
        duplicate = self.result_bytes([(7, 11, 100, 1), (7, 12, 100, 2)])
        self.assertEqual(self.decode(duplicate, 7)[0], CONFLICT)

    @unittest.skipUnless(os.environ.get('A7C2_CAPTURE_AP'), 'Optional original 2.01 AP fixture')
    def test_decoded_numbers_match_original_native_auto_review_reader(self):
        from elftools.elf.elffile import ELFFile
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
        from unicorn import arm64_const as R
        # Execute the original AP control flow. String/model helper calls are
        # intercepted; the requested directory/file values are observed at
        # the native integer-to-string boundary, not injected into registers.
        entry, size, convert = 0x349e5e0, 0x23c, 0x2551df8
        with Path(os.environ['A7C2_CAPTURE_AP']).open('rb') as source:
            elf = ELFFile(source)
            segment = next(s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD' and
                           s['p_vaddr'] <= entry < s['p_vaddr'] + s['p_filesz'])
            source.seek(segment['p_offset'] + entry - segment['p_vaddr'])
            code = source.read(size)
        instructions = list(Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN).disasm(code, entry))
        targets = {int(i.op_str.lstrip('#'), 0) for i in instructions if i.mnemonic == 'bl'}
        self.assertIn(convert, targets)
        for records, slot, media in [([(7, 0, 100, 1)], 0, 7),
                                     ([(7, 10, 100, 12), (8, 20, 123, 9876)], 0, 7),
                                     ([(7, 10, 100, 12), (8, 20, 123, 9876)], 1, 8)]:
            with self.subTest(slot=slot, records=len(records)):
                raw = self.result_bytes(records)
                status, decoded = self.decode(raw, media)
                self.assertEqual(status, OK)
                cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
                pages = {entry & ~4095, (entry + size - 1) & ~4095}
                pages.update(t & ~4095 for t in targets)
                for page in pages: cpu.mem_map(page, 4096)
                cpu.mem_write(entry, code)
                for target in targets: cpu.mem_write(target, b'\xc0\x03\x5f\xd6')
                for pointer, length in ((0x40000000, 8192), (0x50000000, 4096),
                                        (0x60000000, 65536), (self.stop, 4096)):
                    cpu.mem_map(pointer, length)
                cpu.mem_write(0x50000000, raw)
                cpu.mem_write(0x40000e50, struct.pack('<I', 7))
                cpu.mem_write(0x40000ec0, struct.pack('<I', 8))
                cpu.mem_write(0x40000100, struct.pack('<I', slot))
                observed = []
                def hook(uc, address, size, user):
                    if address not in targets: return
                    # The C++ string result uses hidden sret X8; the integer
                    # input is W0, despite the decompiler showing a first
                    # explicit output-pointer parameter.
                    if address == convert: observed.append(uc.reg_read(R.UC_ARM64_REG_X0) & 0xffff)
                    if address == 0x28783b8: uc.reg_write(R.UC_ARM64_REG_X0, 0x40000100)
                    uc.reg_write(R.UC_ARM64_REG_PC, uc.reg_read(R.UC_ARM64_REG_LR))
                cpu.hook_add(UC_HOOK_CODE, hook)
                cpu.reg_write(R.UC_ARM64_REG_SP, 0x6000f000)
                cpu.reg_write(R.UC_ARM64_REG_LR, self.stop)
                cpu.reg_write(R.UC_ARM64_REG_X0, 0x40000000)
                cpu.reg_write(R.UC_ARM64_REG_X1, 0x50000000)
                cpu.emu_start(entry, self.stop, count=100000)
                self.assertEqual(cpu.reg_read(R.UC_ARM64_REG_PC), self.stop)
                self.assertEqual(observed, [decoded.directory_number, decoded.file_number])


if __name__ == '__main__':
    unittest.main()
