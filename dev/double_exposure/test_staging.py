"""Local staging interruptions, corruption and ownership; never camera I/O."""
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from staging_model import CHUNK_BYTES, LocalStage, Plan, ReviewRequired, digest


class Staging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a7c2-staging-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'transaction'
        self.data = bytes(range(256)) * 1734  # larger than the 64 KiB transport
        self.plan = Plan.from_bytes(self.data)

    def complete_chunks(self, stage):
        for i in range(stage.state['completed'], len(self.plan.chunks)):
            stage.receive(i, self.data[i * CHUNK_BYTES:(i + 1) * CHUNK_BYTES])

    def test_chunked_core_roundtrip_and_verified_reopen(self):
        stage = LocalStage.create(self.root, self.plan)
        self.complete_chunks(stage)
        path = stage.assemble()
        self.assertEqual(path.read_bytes(), self.data)
        self.assertEqual(LocalStage.reopen(self.root, self.plan).state['phase'], 'READY')
        self.assertTrue(all(stage.plan.chunk_size(i) <= 65536 for i in range(len(self.plan.chunks))))
        with self.assertRaises(ValueError): stage.assemble()

    def test_acknowledged_prefix_can_resume_without_rewriting(self):
        stage = LocalStage.create(self.root, self.plan)
        stage.receive(0, self.data[:CHUNK_BYTES])
        first = stage._chunk(0).stat()
        stage = LocalStage.reopen(self.root, self.plan)
        self.complete_chunks(stage)
        self.assertEqual(stage._chunk(0).stat().st_mtime_ns, first.st_mtime_ns)
        self.assertEqual(stage.assemble().read_bytes(), self.data)

    def test_existing_directory_and_user_file_preserved(self):
        self.root.mkdir()
        (self.root / 'core.so').write_bytes(b'user data')
        with self.assertRaises(FileExistsError): LocalStage.create(self.root, self.plan)
        self.assertEqual((self.root / 'core.so').read_bytes(), b'user data')

    def test_bad_index_duplicate_order_and_hash_have_no_side_effects(self):
        stage = LocalStage.create(self.root, self.plan)
        original = (self.root / 'state.json').read_bytes()
        for index, data in ((True, b''), (-1, b''), (1, self.data[CHUNK_BYTES:2 * CHUNK_BYTES]),
                            (0, b'wrong'), (0, b'X' * CHUNK_BYTES)):
            with self.assertRaises(ValueError): stage.receive(index, data)
            self.assertEqual((self.root / 'state.json').read_bytes(), original)
        stage.receive(0, self.data[:CHUNK_BYTES])
        with self.assertRaises(ValueError): stage.receive(0, self.data[:CHUNK_BYTES])

    def test_corrupt_acknowledged_chunk_blocks_resume(self):
        stage = LocalStage.create(self.root, self.plan)
        stage.receive(0, self.data[:CHUNK_BYTES])
        stage._chunk(0).write_bytes(b'X' * CHUNK_BYTES)
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, self.plan)
        with self.assertRaises(ReviewRequired): stage.receive(1, self.data[CHUNK_BYTES:2 * CHUNK_BYTES])

    def test_unfinished_write_intent_is_retained_without_replay(self):
        stage = LocalStage.create(self.root, self.plan)
        with patch.object(stage, '_read_chunk', side_effect=OSError('lost acknowledgement')):
            with self.assertRaises(OSError): stage.receive(0, self.data[:CHUNK_BYTES])
        saved = (self.root / 'state.json').read_bytes()
        self.assertEqual(json.loads(saved)['intent']['operation'], 'WRITE_CHUNK')
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, self.plan)
        with self.assertRaises(ReviewRequired): stage.receive(0, self.data[:CHUNK_BYTES])
        self.assertEqual((self.root / 'state.json').read_bytes(), saved)
        self.assertEqual(stage._chunk(0).read_bytes(), self.data[:CHUNK_BYTES])

    def test_journal_failure_stops_same_instance(self):
        stage = LocalStage.create(self.root, self.plan)
        with patch('staging_model.os.replace', side_effect=OSError('journal unavailable')):
            with self.assertRaises(OSError): stage.receive(0, self.data[:CHUNK_BYTES])
        self.assertFalse(stage._chunk(0).exists())
        with self.assertRaises(ReviewRequired): stage.receive(0, self.data[:CHUNK_BYTES])
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, self.plan)

    def test_final_ack_failure_preserves_complete_file_without_reassembly(self):
        stage = LocalStage.create(self.root, self.plan)
        self.complete_chunks(stage)
        original = stage._save_state
        def fail_on_ready():
            if stage.state['phase'] == 'READY': raise OSError('lost final acknowledgement')
            original()
        with patch.object(stage, '_save_state', side_effect=fail_on_ready):
            with self.assertRaises(OSError): stage.assemble()
        self.assertEqual((self.root / 'core.so').read_bytes(), self.data)
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, self.plan)
        with self.assertRaises(ReviewRequired): stage.assemble()

    def test_whole_hash_is_independent_of_chunk_hashes(self):
        plan = dataclasses.replace(self.plan, sha256=digest(b'different core'))
        stage = LocalStage.create(self.root, plan)
        self.complete_chunks(stage)
        with self.assertRaises(ReviewRequired): stage.assemble()
        self.assertFalse((self.root / 'core.so').exists())
        self.assertTrue((self.root / 'assembling.tmp').exists())
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, plan)

    def test_foreign_output_cannot_be_overwritten(self):
        stage = LocalStage.create(self.root, self.plan)
        self.complete_chunks(stage)
        (self.root / 'core.so').write_bytes(b'user')
        with self.assertRaises(ReviewRequired): stage.assemble()
        self.assertEqual((self.root / 'core.so').read_bytes(), b'user')

    def test_publication_error_retains_intent_and_assembly(self):
        stage = LocalStage.create(self.root, self.plan)
        self.complete_chunks(stage)
        with patch('staging_model.os.link', side_effect=OSError('unknown publication outcome')):
            with self.assertRaises(OSError): stage.assemble()
        self.assertTrue((self.root / 'assembling.tmp').exists())
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, self.plan)

    def test_output_created_during_publication_is_not_replaced(self):
        import os
        stage = LocalStage.create(self.root, self.plan)
        self.complete_chunks(stage)
        original = os.link
        def collide(source, destination):
            destination.write_bytes(b'new user output')
            original(source, destination)
        with patch('staging_model.os.link', side_effect=collide):
            with self.assertRaises(FileExistsError): stage.assemble()
        self.assertEqual((self.root / 'core.so').read_bytes(), b'new user output')
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, self.plan)

    def test_completed_chunk_ack_failure_cannot_advance_same_instance(self):
        stage = LocalStage.create(self.root, self.plan)
        original = stage._save_state
        def fail_on_ack():
            if stage.state['completed']: raise OSError('lost chunk acknowledgement')
            original()
        with patch.object(stage, '_save_state', side_effect=fail_on_ack):
            with self.assertRaises(OSError): stage.receive(0, self.data[:CHUNK_BYTES])
        self.assertEqual(stage._chunk(0).read_bytes(), self.data[:CHUNK_BYTES])
        with self.assertRaises(ReviewRequired): stage.receive(1, self.data[CHUNK_BYTES:2 * CHUNK_BYTES])
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, self.plan)

    def test_changed_plan_and_invalid_sizes_rejected(self):
        LocalStage.create(self.root, self.plan)
        with self.assertRaises(ReviewRequired): LocalStage.reopen(self.root, Plan.from_bytes(b'other'))
        for data in (b'', b'x' * (8 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError): Plan.from_bytes(data)
        with self.assertRaises(ValueError): dataclasses.replace(self.plan, size=True)
        with self.assertRaises(ValueError): dataclasses.replace(self.plan, chunks=())


if __name__ == '__main__':
    unittest.main()
