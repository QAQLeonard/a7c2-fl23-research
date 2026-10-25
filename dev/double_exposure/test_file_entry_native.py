"""ARM64 one-shot request entry on synthetic local files; never camera USB."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from entry_protocol import device_request, receipt
from staging_model import CHUNK_BYTES, Plan
from staging_protocol import CREATE, PUT, ASSEMBLE, QUERY, request


@unittest.skipUnless(os.environ.get('A7C2_FILE_ENTRY_COMMAND'), 'Set A7C2_FILE_ENTRY_COMMAND to file entry runner argv')
class NativeFileEntry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a7c2-file-entry-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = b'INSTANCE-0000001'
        self.stage = self.root / ('a7c2-dex-' + self.identity.hex())
        self.data = bytes(range(256)) * 601
        self.plan = Plan.from_bytes(self.data)

    def invoke(self, wire, payload=None, *, remove=True):
        (self.root/'a7c2.dex.request').write_bytes(wire)
        if payload is not None: (self.root/'a7c2.dex.payload').write_bytes(payload)
        command = json.loads(os.environ['A7C2_FILE_ENTRY_COMMAND'])
        result = subprocess.run(command + [str(self.root)], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        status = json.loads(result.stdout)['status']
        path = self.root/'a7c2.dex.result'
        report = receipt(path.read_bytes(), wire)
        self.assertEqual(status, report['status'])
        if remove: path.unlink()  # only a fully verified, test-owned receipt
        return report

    def stage_core(self):
        self.assertEqual(self.invoke(request(self.plan, self.identity, CREATE))['status'], 0)
        for index, offset in enumerate(range(0, len(self.data), CHUNK_BYTES)):
            out = self.invoke(request(self.plan, self.identity, PUT, index), self.data[offset:offset+CHUNK_BYTES])
            self.assertEqual((out['status'], out['completed_chunks']), (0, index+1))
        out = self.invoke(request(self.plan, self.identity, ASSEMBLE))
        self.assertEqual((out['status'], out['phase']), (0, 2))

    def test_request_entry_receives_assembles_and_queries(self):
        self.stage_core()
        self.assertEqual((self.stage/'core.so').read_bytes(), self.data)
        self.assertEqual(self.invoke(request(self.plan, self.identity, QUERY))['phase'], 2)

    def test_existing_receipt_blocks_execution_and_is_preserved(self):
        wire = request(self.plan, self.identity, CREATE)
        self.invoke(wire, remove=False)
        result_file = self.root/'a7c2.dex.result'
        original = result_file.read_bytes()
        command = json.loads(os.environ['A7C2_FILE_ENTRY_COMMAND'])
        result = subprocess.run(command + [str(self.root)], capture_output=True, timeout=30)
        self.assertEqual(json.loads(result.stdout)['status'], -17003)
        self.assertEqual(result_file.read_bytes(), original)
        self.assertEqual({p.name for p in self.stage.iterdir()}, {'plan.bin'})

    def test_invalid_request_has_failure_receipt_without_staging(self):
        self.assertEqual(self.invoke(b'invalid')['status'], -17001)
        self.assertFalse(self.stage.exists())

    def test_partial_chunk_is_retained_without_replay(self):
        self.invoke(request(self.plan, self.identity, CREATE))
        self.assertEqual(self.invoke(request(self.plan, self.identity, PUT, 0), b'bad')['status'], -13001)
        self.assertEqual({p.name for p in self.stage.iterdir()}, {'plan.bin'})

    def test_query_and_disable_never_load_an_absent_core(self):
        # Bytes are deliberately not ELF. QUERY/DISABLE must still return
        # NOT_RESIDENT rather than trying to load the staged file.
        self.stage_core()
        for operation in (3, 4):
            report = self.invoke(device_request(self.identity, operation, operation))
            self.assertEqual(report['status'], -12002)
            self.assertFalse(report['photo_complete'])

    def test_arm_requires_completed_core_staging(self):
        self.invoke(request(self.plan, self.identity, CREATE))
        report = self.invoke(device_request(self.identity, 1, 1, epoch=1, generation=1))
        self.assertEqual(report['status'], -17001)
        self.assertFalse((self.root/('a7c2-dex-run-' + self.identity.hex())).exists())

    def test_malformed_control_is_rejected_before_loading(self):
        wire = bytearray(device_request(self.identity, 1, 1, epoch=1, generation=1))
        wire[12] = 1
        self.assertEqual(self.invoke(bytes(wire))['status'], -17001)
        self.assertFalse(self.stage.exists())

    @unittest.skipUnless(os.environ.get('A7C2_STAGE_CORE'), 'Set actual ARM64 core path')
    def test_real_core_missing_sdk_stops_before_callback_installation(self):
        self.data = Path(os.environ['A7C2_STAGE_CORE']).read_bytes()
        self.plan = Plan.from_bytes(self.data)
        self.stage_core()
        report = self.invoke(device_request(self.identity, 1, 1, epoch=1, generation=1))
        self.assertEqual(report['status'], -11001)
        self.assertFalse(report['photo_complete'])
        self.assertFalse((self.root/('a7c2-dex-run-' + self.identity.hex())).exists())
        self.assertEqual((self.stage/'core.so').read_bytes(), self.data)
