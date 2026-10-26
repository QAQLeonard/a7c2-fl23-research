"""Actual production ELF constructor; isolated Linux paths, no SDK/device access."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from entry_protocol import device_request, receipt
from staging_model import CHUNK_BYTES, Plan
from staging_protocol import CREATE, PUT, ASSEMBLE, QUERY, request


@unittest.skipUnless(os.environ.get('A7C2_FILE_ENTRY_CONSTRUCTOR_COMMAND'),
                     'Set the isolated Linux constructor runner argv')
class NativeEntryConstructor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a7c2-constructor-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'.a7c2-constructor-fixture').write_bytes(b'offline-only')
        self.identity = b'INSTANCE-0000001'
        self.stage = self.root / ('a7c2-dex-' + self.identity.hex())
        self.data = bytes(range(256)) * 601
        self.plan = Plan.from_bytes(self.data)

    def invoke(self, wire, payload=None, mode='once', remove=True):
        (self.root/'a7c2.dex.request').write_bytes(wire)
        if payload is not None: (self.root/'a7c2.dex.payload').write_bytes(payload)
        command = json.loads(os.environ['A7C2_FILE_ENTRY_CONSTRUCTOR_COMMAND'])
        run = subprocess.run(command + [str(self.root), mode], capture_output=True, timeout=40)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors='replace'))
        result = json.loads(run.stdout)
        self.assertTrue(result['constructor_checked'])
        self.assertFalse(result['explicit_entry_call']); self.assertFalse(result['camera_io'])
        path = self.root/('first.receipt' if mode == 'retained' else 'a7c2.dex.result')
        out = receipt(path.read_bytes(), wire)
        if remove: path.unlink()
        return out

    def stage_core(self):
        self.assertEqual(self.invoke(request(self.plan, self.identity, CREATE))['status'], 0)
        for index, offset in enumerate(range(0, len(self.data), CHUNK_BYTES)):
            out = self.invoke(request(self.plan, self.identity, PUT, index), self.data[offset:offset+CHUNK_BYTES])
            self.assertEqual(out['completed_chunks'], index + 1)
        self.assertEqual(self.invoke(request(self.plan, self.identity, ASSEMBLE))['phase'], 2)

    def test_production_constructor_receives_chunks_assembles_and_queries(self):
        self.stage_core()
        self.assertEqual((self.stage/'core.so').read_bytes(), self.data)
        self.assertEqual(self.invoke(request(self.plan, self.identity, QUERY))['phase'], 2)

    def test_retained_loader_handle_does_not_run_constructor_twice(self):
        self.assertEqual(self.invoke(request(self.plan, self.identity, CREATE), mode='retained')['status'], 0)
        self.assertFalse((self.root/'a7c2.dex.result').exists())
        self.assertEqual({p.name for p in self.stage.iterdir()}, {'plan.bin'})

    def test_unload_reload_reexecutes_entry_and_rejects_old_create(self):
        wire = request(self.plan, self.identity, CREATE)
        self.assertEqual(self.invoke(wire, mode='reload')['status'], -13002)
        self.assertEqual(receipt((self.root/'first.receipt').read_bytes(), wire)['status'], 0)
        self.assertEqual((self.stage/'plan.bin').read_bytes(), wire)

    def test_existing_receipt_blocks_constructor_replay_without_overwrite(self):
        wire = request(self.plan, self.identity, CREATE)
        self.invoke(wire, remove=False)
        original = (self.root/'a7c2.dex.result').read_bytes()
        self.invoke(wire, remove=False)
        self.assertEqual((self.root/'a7c2.dex.result').read_bytes(), original)
        self.assertEqual({p.name for p in self.stage.iterdir()}, {'plan.bin'})

    def test_query_and_disable_do_not_load_absent_core(self):
        for op in (3, 4):
            with self.subTest(operation=op):
                out = self.invoke(device_request(self.identity, op, op))
                self.assertEqual(out['status'], -12002)
                self.assertFalse(out['photo_complete'])
                self.assertFalse(self.stage.exists())

    @unittest.skipUnless(os.environ.get('A7C2_STAGE_CORE'), 'Set actual ARM64 core path')
    def test_constructor_loads_real_core_and_retains_missing_sdk_failure(self):
        self.data = Path(os.environ['A7C2_STAGE_CORE']).read_bytes()
        self.plan = Plan.from_bytes(self.data)
        self.stage_core()
        digest = hashlib.sha256(self.data).digest()
        out = self.invoke(device_request(self.identity, 1, 1, epoch=1, generation=1), remove=False)
        self.assertEqual(out['status'], -11001)
        self.assertFalse(out['photo_complete'])
        self.assertEqual(hashlib.sha256((self.stage/'core.so').read_bytes()).digest(), digest)
        self.assertFalse((self.root/('a7c2-dex-run-' + self.identity.hex())).exists())
