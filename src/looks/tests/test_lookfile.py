"""Compiled-file boundary: exact coefficients, no refitting, no hidden stages."""
import json
from pathlib import Path
import tempfile
import unittest
import math
from unittest.mock import patch
from looktool import lookfile, devicejob, devicecli, photoformat


class MemoryCamera:
    def __call__(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class PreparedJob(devicejob.Job):
    def _prepare(self, camera, name, slot, second, raw):
        self.received = raw
        self.save('PREFLIGHT_VERIFIED')


class CompiledLookTests(unittest.TestCase):
    def test_invalid_metrics_leave_no_partial_output(self):
        output=self.folder/'bad-metrics.a7look'
        with self.assertRaises(ValueError):
            lookfile.write(output,'Invalid report',self.raw,method='test',attribution='test',
                metrics={'error':math.nan})
        self.assertFalse(output.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'test.a7look'
        self.raw = bytes((j % 128 - 64) % 256 for j in range(1215))
        self.document = lookfile.write(self.source, 'Classic Neg.', self.raw,
            method='synthetic-test', attribution='Synthetic data only',
            metrics={'heldout_MAE': 4.5})

    def test_roundtrip_keeps_exact_planar_coefficients_and_explicit_evidence(self):
        value = lookfile.read(self.source)
        self.assertEqual(lookfile.writer_table(value), self.raw)
        inventory = lookfile.inventory(value)
        self.assertFalse(inventory['validation']['camera_photos_and_preview_verified'])
        self.assertEqual(inventory['validation']['metrics']['heldout_MAE'], 4.5)
        self.assertNotIn('table_base64', inventory)
        self.assertFalse(inventory['camera_io'])

    def test_prepared_job_uses_compiled_bytes_without_calibration_or_fitting(self):
        job = PreparedJob(self.folder / 'job', factory=MemoryCamera())
        with patch.object(devicejob.native, 'fit_reference', side_effect=AssertionError('Refit must not run')), \
             patch.object(devicejob.calibration, 'validate', side_effect=AssertionError('Calibration is not needed')):
            state = job.create(self.source, 'Imported', 5, None, self.folder / 'backup')
        self.assertEqual(state['phase'], 'PREFLIGHT_VERIFIED')
        self.assertEqual(job.received, self.raw)
        self.assertEqual((job.root / 'candidate/slot5.bin').read_bytes(), self.raw)
        report = json.loads((job.root / 'candidate/fit.private.json').read_text(encoding='utf-8'))
        self.assertFalse(report['refitted'])

    def test_unknown_native_photo_stages_stop_before_device_or_job_creation(self):
        path = self.folder / 'future.a7look'
        from test_photoformat import curve
        bank = photoformat.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        lookfile.write(path, 'Future', self.raw, method='synthetic-test', attribution='Synthetic',
            native_photo=photoformat.difference(bank, bank.perturb(curve_gain=.01)))
        def no_camera():
            self.fail('Unsupported stages must stop before USB')
        job = devicejob.Job(self.folder / 'future-job', factory=no_camera)
        with self.assertRaisesRegex(ValueError, 'supported native integer basis'):
            job.create(path, 'Future', 1, None, self.folder / 'future-backup')
        self.assertFalse(job.root.exists())

    def test_supported_native_basis_is_frozen_with_the_compiled_table(self):
        from test_photoformat import curve
        from looktool import photobasis
        bank=photoformat.PhotoBank(curve(),curve(),bytes(576),bytes(64))
        _,delta=photobasis.pack(bank,tone=[16,0,0])
        path=self.folder/'native.a7look'
        lookfile.write(path,'Native',self.raw,method='test',attribution='Synthetic',native_photo=delta)
        job=PreparedJob(self.folder/'native-job',factory=MemoryCamera())
        state=job.create(path,'Native',1,None,self.folder/'native-backup')
        self.assertEqual(state['native_photo_binding'],delta)
        self.assertTrue(state['byte_checks'])
        self.assertEqual(job.received,self.raw)

    def test_cli_uses_packaged_name_without_a_calibration_option(self):
        state = {'phase': 'PREFLIGHT_VERIFIED', 'slot': 5, 'name': self.document['name']}
        with patch.object(devicecli, 'settings', return_value={}), \
             patch.object(devicecli.Job, 'create', return_value=state) as create:
            code = devicecli.main(['import', str(self.source), '--slot', '5',
                '--work-dir', str(self.folder / 'cli-job'), '--backup-dir', str(self.folder / 'cli-backup')])
        self.assertEqual(code, 0)
        self.assertEqual(create.call_args.args[1:3], ('Classic Neg.', 5))


if __name__ == '__main__':
    unittest.main()
