"""Actual ARM64 helper/core loader, optionally after local chunk assembly."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from staging_model import CHUNK_BYTES, LocalStage, Plan


@unittest.skipUnless(os.environ.get('A7C2_BOOTSTRAP_COMMAND') and os.environ.get('A7C2_STAGE_CORE'),
                     'Set A7C2_BOOTSTRAP_COMMAND and A7C2_STAGE_CORE for ARM64 loader tests')
class NativeBootstrap(unittest.TestCase):
    def run_mode(self, mode, core=None):
        command = json.loads(os.environ['A7C2_BOOTSTRAP_COMMAND'])
        result = subprocess.run(command + [str(core or os.environ['A7C2_STAGE_CORE']), mode],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        report = json.loads(result.stdout)
        self.assertEqual(report['backend'], 'synthetic-sdk-libraries')
        self.assertFalse(report['camera_io'])
        self.assertTrue(report['control_verified'])

    def test_query_and_retire_do_not_load_absent_core(self):
        self.run_mode('absent')

    def test_failed_sdk_binding_drops_both_core_references(self):
        self.run_mode('missing-sdk')

    def test_start_query_retire_preserve_sdk_refs_and_unload_core(self):
        self.run_mode('lifetime')

    def test_jobs_and_callbacks_each_block_retirement(self):
        self.run_mode('busy')

    def test_actual_core_chunked_then_loaded_and_retired(self):
        data = Path(os.environ['A7C2_STAGE_CORE']).read_bytes()
        self.assertGreater(len(data), 65536)
        with tempfile.TemporaryDirectory(prefix='a7c2-staged-core-') as directory:
            stage = LocalStage.create(Path(directory) / 'transaction', Plan.from_bytes(data))
            for index, offset in enumerate(range(0, len(data), CHUNK_BYTES)):
                stage.receive(index, data[offset:offset + CHUNK_BYTES])
            core = stage.assemble()
            self.run_mode('lifetime', core)
            self.assertEqual(core.read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
