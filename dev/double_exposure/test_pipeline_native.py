"""Actual ARM64 asynchronous pipeline and AP-shaped delegate, synthetic SDK."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('A7C2_PIPELINE_COMMAND'), 'Set A7C2_PIPELINE_COMMAND to native harness argv')
class NativePipeline(unittest.TestCase):
    def run_mode(self, mode):
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='a7c2-pipeline-') as directory:
            root = Path(directory)
            left, right = root/'first.jpg', root/'second.jpg'
            Image.new('RGB', (117, 89), (20, 40, 60)).save(left, quality=100, subsampling=0)
            Image.new('RGB', (117, 89), (220, 180, 120)).save(right, quality=100, subsampling=0)
            originals = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (left, right)]
            command = json.loads(os.environ['A7C2_PIPELINE_COMMAND'])
            result = subprocess.run(command + [str(left), str(right), str(root), mode], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            report = json.loads(result.stdout)
            self.assertEqual(report['backend'], 'synthetic-sdk-and-ap')
            self.assertTrue(report['verified']); self.assertFalse(report['camera_io'])
            self.assertEqual(originals, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (left, right)])
            if mode in ('success', 'detach-error', 'queued-disable', 'sdk-forward', 'sdk-auto'):
                with Image.open(root/'A7AV0001.JPG') as image:
                    self.assertTrue(all(abs(a-b) <= 3 for a,b in zip(image.getpixel((0,0)),(120,110,90))))
            return report

    def test_async_request_through_real_codec_and_catalog_query(self): self.run_mode('success')
    def test_uid_error_is_not_repeated(self): self.run_mode('issue-error')
    def test_update_error_is_not_repeated(self): self.run_mode('update-error')
    def test_independent_catalog_query_mismatch_is_not_complete(self): self.run_mode('verify-error')
    def test_publication_unknown_does_not_register(self): self.run_mode('publish-error')
    def test_journal_failure_retains_handles_before_encoding(self): self.run_mode('journal-error')
    def test_native_context_rundown_failure_keeps_module_lease(self): self.run_mode('detach-error')
    def test_disable_queues_behind_running_encoder_and_drains_once(self): self.run_mode('queued-disable')
    def test_sdk_forwarding_preserves_native_registry_and_survives_context_destruction(self): self.run_mode('sdk-forward')
    def test_sdk_error_stops_io_and_quiets_review_worker(self): self.run_mode('sdk-fault')
    def test_catalog_flush_failure_retains_uid_and_never_completes(self): self.run_mode('flush-error')
    def test_auto_media_uses_native_event_id_instead_of_assuming_slot_zero(self): self.run_mode('sdk-auto')
    def test_acknowledged_corrupt_write_fails_full_readback_before_publication(self): self.run_mode('corrupt-write')
