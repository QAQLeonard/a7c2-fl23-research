"""Linux/ARM64 POSIX receiver tests; temporary local fixtures only."""
from concurrent.futures import ThreadPoolExecutor
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import uuid
from staging_model import CHUNK_BYTES, MAX_BYTES, Plan
from staging_protocol import CREATE, PUT, ASSEMBLE, QUERY, request


@unittest.skipUnless(os.environ.get('A7C2_STAGING_COMMAND') and os.name != 'nt',
                     'Set A7C2_STAGING_COMMAND to the Linux native staging runner argv')
class NativeStaging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a7c2-native-staging-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'transaction'
        self.data = bytes(range(256)) * 385
        self.plan = Plan.from_bytes(self.data)
        self.identity = b'TRANSACTION-0001'

    def call(self, operation, index=0, payload=None, *, plan=None, identity=None,
             wire=None, root=None, fault=None, crash=False, close_error=0):
        token = uuid.uuid4().hex
        wire_path = self.base / (token + '.wire')
        wire_path.write_bytes(wire if wire is not None else request(
            plan or self.plan, identity or self.identity, operation, index))
        command = json.loads(os.environ['A7C2_STAGING_FAULT_COMMAND' if fault else 'A7C2_STAGING_COMMAND'])
        command += [str(root or self.root), str(wire_path)]
        if payload is not None:
            path = self.base / (token + '.payload')
            path.write_bytes(payload)
            command.append(str(path))
        environment = os.environ.copy()
        environment.pop('A7_STAGE_FAULT', None)
        if fault: environment['A7_STAGE_FAULT'] = fault
        result = subprocess.run(command, capture_output=True, timeout=30, env=environment)
        if crash:
            self.assertEqual(result.returncode, 73, result.stderr.decode(errors='replace'))
            return
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        report = json.loads(result.stdout)
        self.assertFalse(report['camera_io'])
        self.assertEqual(report['close_error'], close_error)
        return report

    def create(self, **kwargs):
        report = self.call(CREATE, **kwargs)
        self.assertEqual((report['status'], report['phase']), (0, 1))

    def put_all(self, *, plan=None, root=None):
        for i, offset in enumerate(range(0, len(self.data), CHUNK_BYTES)):
            report = self.call(PUT, i, self.data[offset:offset + CHUNK_BYTES], plan=plan, root=root)
            self.assertEqual((report['status'], report['completed']), (0, i + 1))

    def snapshot(self, root=None):
        return {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in (root or self.root).iterdir()
                if p.is_file() and not p.is_symlink()}

    def assert_review_unchanged(self, operation=QUERY, **kwargs):
        before = self.snapshot()
        report = self.call(operation, **kwargs)
        self.assertLess(report['status'], 0)
        self.assertEqual((report['phase'], report['mutated']), (3, 0))
        self.assertEqual(self.snapshot(), before)

    def test_native_chunk_roundtrip_reopens_each_request(self):
        self.create()
        self.put_all()
        report = self.call(ASSEMBLE)
        self.assertEqual((report['status'], report['phase'], report['published']), (0, 2, 1))
        self.assertEqual((self.root / 'core.so').read_bytes(), self.data)
        before = self.snapshot()
        self.assertEqual(self.call(QUERY)['phase'], 2)
        duplicate = self.call(ASSEMBLE)
        self.assertEqual((duplicate['status'], duplicate['mutated']), (-13005, 0))
        self.assertEqual(self.snapshot(), before)

    def test_sha256_matches_independent_hashlib_at_padding_boundaries(self):
        for size in (1, 55, 56, 63, 64, 65, 4097, CHUNK_BYTES, CHUNK_BYTES + 1):
            with self.subTest(size=size):
                self.data = (bytes(range(256)) * ((size + 255) // 256))[:size]
                self.plan = Plan.from_bytes(self.data)
                root = self.base / f'transaction-{size}'
                self.create(root=root)
                self.put_all(root=root)
                self.assertEqual(self.call(ASSEMBLE, root=root)['status'], 0)
                self.assertEqual(hashlib.sha256((root / 'core.so').read_bytes()).hexdigest(), self.plan.sha256)

    def test_invalid_envelopes_do_not_create_a_directory(self):
        good = request(self.plan, self.identity, CREATE)
        variants = [b'', good[:-1], good + b'X', b'INVALID!' + good[8:]]
        for offset, fmt, value in ((8, '<I', 0), (12, '<I', 1), (32, '<Q', 0),
                                   (32, '<Q', MAX_BYTES + 1), (40, '<I', 0), (44, '<I', 1)):
            wire = bytearray(good)
            struct.pack_into(fmt, wire, offset, value)
            variants.append(bytes(wire))
        wire = bytearray(good); wire[16:32] = b'\0' * 16; variants.append(bytes(wire))
        for wire in variants:
            report = self.call(CREATE, wire=wire)
            self.assertEqual((report['status'], report['mutated']), (-13001, 0))
            self.assertFalse(self.root.exists())
        for root in ('relative', str(self.base / '..' / 'bad'), str(self.base) + '//bad'):
            self.assertEqual(self.call(CREATE, root=root)['status'], -13001)
        self.assertEqual(self.call(CREATE, payload=b'unexpected')['status'], -13001)

    def test_maximum_plan_is_bounded_and_zero_size_is_not_admitted(self):
        plan = Plan.from_bytes(b'X' * MAX_BYTES)
        self.assertLess(len(request(plan, self.identity, CREATE)), 65536)
        self.create(plan=plan)
        report = self.call(QUERY, plan=plan)
        self.assertEqual((report['status'], report['completed'], report['chunks']), (0, 0, len(plan.chunks)))

    def test_existing_directory_and_user_file_not_changed(self):
        self.root.mkdir()
        (self.root / 'core.so').write_bytes(b'user data')
        before = self.snapshot()
        report = self.call(CREATE)
        self.assertEqual((report['status'], report['mutated']), (-13002, 0))
        self.assertEqual(self.snapshot(), before)

    def test_wrong_transaction_or_plan_does_not_write(self):
        self.create()
        before = self.snapshot()
        for kwargs in ({'identity': b'OTHER-TRANSACT01'},
                       {'plan': dataclasses.replace(self.plan, sha256='ab' * 32)},
                       {'plan': Plan.from_bytes(b'other size and count')}):
            report = self.call(QUERY, **kwargs)
            self.assertEqual((report['status'], report['mutated']), (-13004, 0))
            self.assertEqual(self.snapshot(), before)

    def test_out_of_order_duplicate_and_short_payload_do_not_write(self):
        self.create()
        before = self.snapshot()
        report = self.call(PUT, 1, self.data[CHUNK_BYTES:2 * CHUNK_BYTES])
        self.assertEqual((report['status'], report['mutated']), (-13005, 0))
        self.assertEqual(self.call(PUT, 0, b'wrong length')['status'], -13001)
        self.assertEqual(self.call(PUT, 0, b'X' * CHUNK_BYTES)['status'], -13006)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.call(PUT, 0, self.data[:CHUNK_BYTES])['status'], 0)
        before = self.snapshot()
        self.assertEqual(self.call(PUT, 0, self.data[:CHUNK_BYTES])['status'], -13005)
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_acknowledged_chunk_stops_query_and_next_put(self):
        self.create()
        self.call(PUT, 0, self.data[:CHUNK_BYTES])
        (self.root / '0000.chunk').write_bytes(b'X' * CHUNK_BYTES)
        self.assert_review_unchanged()
        self.assert_review_unchanged(PUT, index=1, payload=self.data[CHUNK_BYTES:2 * CHUNK_BYTES])

    def test_torn_or_stale_confirmation_is_not_accepted(self):
        self.create()
        self.call(PUT, 0, self.data[:CHUNK_BYTES])
        path = self.root / '0000.done'
        original = path.read_bytes()
        for content in (original[:17], original[:16] + b'OTHER-TRANSACT01' + original[32:]):
            path.write_bytes(content)
            self.assert_review_unchanged()

    def test_foreign_file_prevents_next_write(self):
        self.create()
        (self.root / 'foreign.txt').write_bytes(b'keep')
        self.assert_review_unchanged(PUT, index=0, payload=self.data[:CHUNK_BYTES])
        self.assertFalse((self.root / '0000.intent').exists())

    def test_symlink_fifo_and_hardlink_are_not_regular_owned_chunks(self):
        foreign = self.base / 'foreign'
        foreign.write_bytes(self.data[:CHUNK_BYTES])
        self.create()
        self.call(PUT, 0, self.data[:CHUNK_BYTES])
        chunk = self.root / '0000.chunk'
        chunk.unlink()
        chunk.symlink_to(foreign)
        self.assert_review_unchanged()
        chunk.unlink()
        os.mkfifo(chunk)
        self.assert_review_unchanged()
        chunk.unlink()
        os.link(foreign, chunk)
        self.assert_review_unchanged()
        self.assertEqual(foreign.read_bytes(), self.data[:CHUNK_BYTES])

    def test_root_symlink_is_not_followed(self):
        foreign = self.base / 'foreign-directory'
        foreign.mkdir()
        (foreign / 'plan.bin').write_bytes(b'keep')
        self.root.symlink_to(foreign, target_is_directory=True)
        self.assertLess(self.call(QUERY)['status'], 0)
        self.assertEqual(self.call(CREATE)['status'], -13002)
        self.assertEqual((foreign / 'plan.bin').read_bytes(), b'keep')

    def test_directory_lock_serializes_cooperating_processes(self):
        import fcntl
        self.create()
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            report = self.call(QUERY)
            self.assertEqual((report['status'], report['mutated'], report['locked']), (-13008, 0, 0))
        finally:
            os.close(descriptor)
        self.assertEqual(self.call(QUERY)['status'], 0)

    def test_competing_puts_have_one_success_and_no_rewrite(self):
        self.create()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.call, PUT, 0, self.data[:CHUNK_BYTES]) for _ in range(2)]
            reports = [future.result() for future in futures]
        statuses = [row['status'] for row in reports]
        self.assertEqual(statuses.count(0), 1)
        self.assertTrue(set(statuses) <= {0, -13005, -13008})
        self.assertEqual(self.call(QUERY)['completed'], 1)

    def test_whole_core_hash_is_checked_independently(self):
        plan = dataclasses.replace(self.plan, sha256='ab' * 32)
        self.create(plan=plan)
        self.put_all(plan=plan)
        report = self.call(ASSEMBLE, plan=plan)
        self.assertEqual((report['status'], report['phase']), (-13006, 3))
        self.assertFalse((self.root / 'core.so').exists())
        self.assertTrue((self.root / 'assembling.tmp').exists())
        self.assert_review_unchanged(plan=plan)

    def test_published_core_tampering_is_not_ready(self):
        self.create()
        self.put_all()
        self.call(ASSEMBLE)
        (self.root / 'core.so').write_bytes(b'changed')
        self.assert_review_unchanged()

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_lost_create_ack_can_only_be_reconciled_by_query(self):
        self.call(CREATE, fault='plan-done', crash=True)
        self.assertEqual(self.call(QUERY)['status'], 0)
        self.assertEqual(self.call(CREATE)['status'], -13002)

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_unfinished_chunk_intents_are_preserved_without_replay(self):
        for point in ('chunk-intent', 'chunk-data'):
            with self.subTest(point=point):
                self.root = self.base / point
                self.create()
                self.call(PUT, 0, self.data[:CHUNK_BYTES], fault=point, crash=True)
                self.assert_review_unchanged()
                self.assert_review_unchanged(PUT, index=0, payload=self.data[:CHUNK_BYTES])

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_lost_chunk_ack_does_not_require_or_allow_duplicate_put(self):
        self.create()
        self.call(PUT, 0, self.data[:CHUNK_BYTES], fault='chunk-done', crash=True)
        self.assertEqual(self.call(QUERY)['completed'], 1)
        before = self.snapshot()
        self.assertEqual(self.call(PUT, 0, self.data[:CHUNK_BYTES])['status'], -13005)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_unfinished_assembly_never_replays_or_discards_evidence(self):
        for point in ('assemble-intent', 'assembly-data', 'published', 'temp-removed'):
            with self.subTest(point=point):
                self.root = self.base / point
                self.create()
                self.put_all()
                self.call(ASSEMBLE, fault=point, crash=True)
                self.assert_review_unchanged()
                self.assert_review_unchanged(ASSEMBLE)

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_lost_final_ack_is_reconciled_without_reassembly(self):
        self.create()
        self.put_all()
        self.call(ASSEMBLE, fault='assemble-done', crash=True)
        before = self.snapshot()
        self.assertEqual(self.call(QUERY)['phase'], 2)
        self.assertEqual(self.call(ASSEMBLE)['status'], -13005)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_collision_at_publication_keeps_both_files(self):
        self.create()
        self.put_all()
        report = self.call(ASSEMBLE, fault='collision')
        self.assertLess(report['status'], 0)
        self.assertEqual(report['phase'], 3)
        self.assertEqual((self.root / 'core.so').read_bytes(), b'user output')
        self.assertEqual((self.root / 'assembling.tmp').read_bytes(), self.data)
        self.assert_review_unchanged()

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_positive_short_writes_continue_only_the_remaining_bytes(self):
        self.create()
        report = self.call(PUT, 0, self.data[:CHUNK_BYTES], fault='short-write')
        self.assertEqual((report['status'], report['completed']), (0, 1))
        self.assertEqual((self.root / '0000.chunk').read_bytes(), self.data[:CHUNK_BYTES])
        self.assertEqual(self.call(QUERY)['completed'], 1)

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_write_error_preserves_known_prefix_without_retry(self):
        self.create()
        report = self.call(PUT, 0, self.data[:CHUNK_BYTES], fault='write-prefix-error')
        self.assertEqual((report['status'], report['phase'], report['io_error']), (-13003, 3, 5))
        self.assertEqual((self.root / '0000.chunk').read_bytes(), self.data[:7])
        self.assertFalse((self.root / '0000.done').exists())
        self.assert_review_unchanged()

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_zero_write_is_an_io_error_without_stale_errno(self):
        self.create()
        report = self.call(PUT, 0, self.data[:CHUNK_BYTES], fault='write-zero')
        self.assertEqual((report['status'], report['io_error'], report['phase']), (-13003, 5, 3))
        self.assertEqual((self.root / '0000.chunk').read_bytes(), b'')
        self.assert_review_unchanged()

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_uncertain_fsync_is_not_repeated_or_acknowledged(self):
        self.create()
        report = self.call(PUT, 0, self.data[:CHUNK_BYTES], fault='fsync-error')
        self.assertEqual((report['status'], report['io_error'], report['phase']), (-13003, 5, 3))
        self.assertEqual((self.root / '0000.chunk').read_bytes(), self.data[:CHUNK_BYTES])
        self.assertFalse((self.root / '0000.done').exists())
        self.assert_review_unchanged()

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_uncertain_close_is_not_repeated_or_acknowledged(self):
        self.create()
        report = self.call(PUT, 0, self.data[:CHUNK_BYTES], fault='close-error', close_error=5)
        self.assertEqual((report['status'], report['phase']), (-13007, 3))
        self.assertFalse((self.root / '0000.done').exists())
        self.assert_review_unchanged()

    @unittest.skipUnless(os.environ.get('A7C2_STAGING_FAULT_COMMAND'), 'Set fault harness argv')
    def test_readback_error_does_not_acknowledge_or_repeat_write(self):
        self.create()
        report = self.call(PUT, 0, self.data[:CHUNK_BYTES], fault='read-error')
        self.assertEqual((report['status'], report['io_error'], report['phase']), (-13003, 5, 3))
        self.assertEqual((self.root / '0000.chunk').read_bytes(), self.data[:CHUNK_BYTES])
        self.assertFalse((self.root / '0000.done').exists())
        self.assert_review_unchanged()

    @unittest.skipUnless(os.environ.get('A7C2_BOOTSTRAP_COMMAND') and os.environ.get('A7C2_STAGE_CORE'),
                         'Set bootstrap command and core for integrated local staging/loading')
    def test_actual_core_received_then_loaded_and_retired_offline(self):
        self.data = Path(os.environ['A7C2_STAGE_CORE']).read_bytes()
        self.plan = Plan.from_bytes(self.data)
        self.create()
        self.put_all()
        self.assertEqual(self.call(ASSEMBLE)['phase'], 2)
        command = json.loads(os.environ['A7C2_BOOTSTRAP_COMMAND'])
        result = subprocess.run(command + [str(self.root / 'core.so'), 'lifetime'], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertTrue(json.loads(result.stdout)['control_verified'])
        self.assertEqual((self.root / 'core.so').read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
