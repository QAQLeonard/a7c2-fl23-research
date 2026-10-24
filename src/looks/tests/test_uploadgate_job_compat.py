"""Old-job verification and fresh slot restoration, using public synthetic data.

Job verification, resource comparisons and restoration eligibility checks are
real. Camera transport, archive loading and independent runtime/settings evidence
are simulated. Restoration stops at a preparation hook that runs the real
planner and checks its inverse; no native worker is compiled or executed.
"""
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from looktool import device_layout, devicejob, devicesession, devicesettings
from looktool import firmware, nameworker, photobasis, photoformat, photoio
from looktool import resources, six, uploadgate
from looktool.checkpointworker import differences
from test_device_components import resource_fixture
from test_photoformat import curve
from test_uploadgate_layout import AP, synthetic_layout


def legacy_identity(_):
    return {'kind': 'legacy-six', 'mask': 63,
            'label_ids': list(resources.LABEL_IDS)}


def replace_table(cp, slot, raw):
    result = bytearray(cp)
    at = six.TABLE_FILE + 32 + (slot - 1) * six.TABLE_BYTES
    result[at:at + six.TABLE_BYTES] = raw
    struct.pack_into('<I', result, six.TABLE_FILE + 8 + (slot - 1) * 4,
                     six.fnv(raw))
    return bytes(result)


def transition(before, after):
    regions = {name: [(at, len(old)) for at, old, _ in
                      differences(before[name], after[name])]
               for name in devicejob.PROGRAM_PATHS}
    return firmware.transition(before, after, regions)


class HostCamera:
    """Only the read-only interface exercised by verify/restore guards."""
    identity = {'model': 'ILCE-7CM2', 'serial': 'SYNTHETIC'}

    def __init__(self, programs, names):
        self.files = {path: programs[name] for name, path in
                      devicejob.PROGRAM_PATHS.items()}
        self.files.update({'/usr/share/app/' + name: names
                           for name in nameworker.filenames()})
        self.settings = [{}, {key: types.SimpleNamespace(
            data=b'UNCHANGED SYNTHETIC RECORD', attr=0)
            for key in devicesettings.PROTECTED}]

    def __call__(self, identity):
        if identity != self.identity:
            raise ValueError('Wrong synthetic body')
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, path):
        return self.files[path]

    def snapshot(self, memory):
        return b'SYNTHETIC SETTINGS'

    def records(self, raw):
        return self.settings


class UploadGateJobCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = photoformat.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        cls.before_delta = photobasis.pack(cls.bank, tone=(8, 0, 0))[1]
        cls.imported_delta = photobasis.pack(cls.bank, tone=(16, 0, 0))[1]
        cls.other_delta = photobasis.pack(cls.bank, tone=(-16, 8, 0))[1]
        cls.hash_before = {'appFw.so': AP,
                           'cpapp-b.bin': synthetic_layout(device_layout.runtime())}
        cls.hash_target = dict(cls.hash_before, **{'cpapp-b.bin': replace_table(
            cls.hash_before['cpapp-b.bin'], 1, bytes([8]) * six.TABLE_BYTES)})
        cls.hash_upgraded = dict(cls.hash_target, **{'cpapp-b.bin':
            uploadgate.restore(cls.hash_target['cpapp-b.bin'])})
        cp = photoio.update(cls.hash_before['cpapp-b.bin'],
                            {1: cls.before_delta, 6: cls.other_delta}, cls.bank,
                            allocation_proved=True)
        cls.before = {'appFw.so': AP, 'cpapp-b.bin': cp}
        # Model the stored result of an actual pre-migration slot-1 job. Its
        # table and native parameters changed while its shared gate stayed A.
        cp = replace_table(cp, 1, bytes([8]) * six.TABLE_BYTES)
        cp = photoio.update(cp, {1: cls.imported_delta}, cls.bank)
        cls.old_target = {'appFw.so': AP, 'cpapp-b.bin': cp}
        cls.old_forward = transition(cls.before, cls.old_target)
        cls.old_reverse = transition(cls.old_target, cls.before)
        with patch.object(device_layout, 'structural_ap',
                          side_effect=legacy_identity):
            cls.later_forward, cls.later_reverse, cls.later_target = (
                device_layout.replace(AP, cp, {6: bytes([7]) * six.TABLE_BYTES},
                                      hash_checks=False,
                                      native_photo={6: cls.other_delta},
                                      native_bank=cls.bank))
        cls.before_names = resource_fixture()
        cls.imported_name = 'Slot one imported'
        cls.old_names = resources.rename(cls.before_names,
                                        {1: cls.imported_name})[0]
        cls.later_names = resources.rename(cls.old_names, {6: 'Later six'})[0]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='upload-gate-job-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # FL23 is unchanged in this scenario. Do not import/open transport to
        # evaluate its independent transformation on the synthetic short AP.
        compat = types.ModuleType('compat')
        compat.plan = lambda ap, cp, **kwargs: (
            {}, True, {'appFw.so': ap, 'cpapp-b.bin': cp}, None, None)
        for guard in (patch.object(devicesession, 'modules'),
                      patch.dict(sys.modules, {'compat': compat}),
                      patch.object(device_layout, 'structural_ap',
                                   side_effect=legacy_identity)):
            guard.start()
            self.addCleanup(guard.stop)

    def old_job(self, label='old', *, actual=None, expected=None, source=None,
                byte_checks=True, names=None):
        source = self.before if source is None else source
        expected = self.old_target if expected is None else expected
        camera = HostCamera(self.later_target if actual is None else actual,
                            self.later_names if names is None else names)
        job = devicejob.Job(self.root / label, factory=camera)
        (job.root / 'transition').mkdir(parents=True)
        (job.root / 'candidate').mkdir()
        (job.root / 'candidate/slot1.bin').write_bytes(
            device_layout.tables(expected['cpapp-b.bin'])[0])
        forward, reverse = transition(source, expected), transition(expected, source)
        for name, manifest in (('forward', forward), ('reverse', reverse)):
            (job.root / ('transition/' + name + '.private.json')).write_text(
                json.dumps(manifest), encoding='utf-8')
        archived = dict(source, **{'settings-ram.bin': b'SYNTHETIC SETTINGS',
                                  'settings-saved.bin': b'SYNTHETIC SETTINGS'})
        archived.update({'resources/' + name: self.before_names
                         for name in nameworker.filenames()})
        job.source = Mock(side_effect=archived.__getitem__)
        # The fixture owns no body backup store. Keep load/recipe extraction
        # independent of the real readback and restoration eligibility paths.
        job.load = Mock(return_value=job)
        job._planned_settings = Mock(return_value=[])
        job._invoke = Mock(return_value={
            'boot_id': 'new-boot', 'spans': [{'offset': 0, 'length': len(AP),
                                          'memory': AP.hex(), 'disk': AP.hex()}]})
        job.state = {
            'schema': 'a7c2-lut-device-job/1', 'phase': 'COMPLETE',
            'identity': camera.identity, 'byte_checks': byte_checks, 'slot': 1,
            'job_id': 'old-forced-entry-slot-1', 'name': self.imported_name,
            'layout': {'label_ids': list(resources.LABEL_IDS)},
            'source_hashes': {name: firmware.sha(raw) for name, raw in source.items()},
            'target_hashes': {name: firmware.sha(raw) for name, raw in expected.items()},
            'journal': [], 'reload_before_boot_id': 'old-boot', 'settings_plan': [],
            'reload_before_boot_id_sha256': firmware.sha(b'old-boot'),
            'name_build': {'files': [dict(
                file=name, before_bytes=len(self.before_names),
                after_bytes=len(self.old_names),
                before_sha256=firmware.sha(self.before_names),
                after_sha256=firmware.sha(self.old_names))
                for name in nameworker.filenames()]}}
        return job, camera, archived

    def evidence(self, job):
        return {str(path.relative_to(job.root)): path.read_bytes()
                for folder in ('transition', 'candidate')
                for path in (job.root / folder).iterdir()}

    def assert_rejected(self, label, actual, *, expected=None, source=None,
                        byte_checks=True):
        job, _, archived = self.old_job(label, actual=actual,
                                        expected=expected, source=source,
                                        byte_checks=byte_checks, names=self.old_names)
        evidence = self.evidence(job)
        original = archived['cpapp-b.bin']
        with self.assertRaisesRegex(ValueError, 'Complete host readback differs'):
            job.verify()
        self.assertEqual(job.state['phase'], 'NEEDS_REVIEW')
        job._invoke.assert_not_called()  # Stop before runtime/native execution.
        self.assertEqual(archived['cpapp-b.bin'], original)
        self.assertEqual(self.evidence(job), evidence)

    def test_completed_old_job_verifies_then_restores_from_fresh_native_state(self):
        job, camera, archived = self.old_job()
        evidence = self.evidence(job)
        original_archive = dict(archived)
        self.assertEqual(job.state['phase'], 'COMPLETE')
        self.assertEqual(job.verify()['phase'], 'RELOAD_VERIFIED')
        self.assertTrue(job._later_slot_updates)
        self.assertTrue(job._later_name_updates)
        job._invoke.assert_called_once_with(camera, 'runtime', 0)
        self.assertEqual(archived, original_archive)
        self.assertEqual(self.evidence(job), evidence)

        # A fresh restoration must undo slot 1 over B, preserving the later
        # slot 6. The historical A inverse remains unchanged offline evidence.
        restoration = devicejob.Job(self.root / 'restore', factory=camera)
        restoration._native_bank = Mock(return_value=self.bank)
        planned = {}

        def prepare(current_camera, name, slot, second, raw):
            current = {name: current_camera.read(path) for name, path in
                       devicejob.PROGRAM_PATHS.items()}
            self.assertEqual(current, self.later_target)
            self.assertEqual(name, 'Original 1')
            self.assertEqual(raw, device_layout.tables(self.before['cpapp-b.bin'])[0])
            forward, reverse, after = device_layout.replace(
                current['appFw.so'], current['cpapp-b.bin'], {slot: raw},
                hash_checks=False, native_bank=self.bank,
                native_photo={slot: restoration.state['native_photo_binding']})
            planned.update(before=current, forward=forward, reverse=reverse, after=after)

        restoration._prepare = Mock(side_effect=prepare)
        # This is the preparation boundary, not a physical installation test.
        restoration._install = Mock()
        before_camera = dict(camera.files)
        restoration.restore_slot(job, 90, self.root / 'independent-backup',
                                 power_confirmed=True)
        restoration._prepare.assert_called_once()
        restoration._install.assert_called_once_with(camera)
        self.assertEqual(camera.files, before_camera)
        after_cp = planned['after']['cpapp-b.bin']
        self.assertEqual(after_cp[uploadgate.OFFSET:uploadgate.OFFSET + 4],
                         uploadgate.NATIVE)
        self.assertEqual(device_layout.tables(after_cp)[0],
                         device_layout.tables(self.before['cpapp-b.bin'])[0])
        self.assertEqual(photoio.slot_bytes(after_cp, 1),
                         photoio.slot_bytes(self.before['cpapp-b.bin'], 1))
        self.assertEqual(device_layout.tables(after_cp)[5],
                         device_layout.tables(self.later_target['cpapp-b.bin'])[5])
        self.assertEqual(photoio.slot_bytes(after_cp, 6),
                         photoio.slot_bytes(self.later_target['cpapp-b.bin'], 6))
        self.assertEqual(firmware.apply(planned['before'], planned['forward']),
                         planned['after'])
        self.assertEqual(firmware.apply(planned['after'], planned['reverse']),
                         self.later_target)
        for window in planned['forward']['files']['cpapp-b.bin']['windows']:
            at = int(window['offset'], 16)
            self.assertFalse(at <= uploadgate.OFFSET < at + window['bytes'])
        self.assertEqual(archived, original_archive)
        self.assertEqual(self.evidence(job), evidence)
        self.assertEqual(firmware.apply(self.old_target, self.old_reverse), self.before)

    def test_later_migration_forward_and_inverse_are_exact(self):
        self.assertEqual(firmware.apply(self.old_target, self.later_forward),
                         self.later_target)
        self.assertEqual(firmware.apply(self.later_target, self.later_reverse),
                         self.old_target)
        self.assertEqual(photoio.slot_bytes(self.old_target['cpapp-b.bin'], 1),
                         photoio.slot_bytes(self.later_target['cpapp-b.bin'], 1))

    def test_immediate_readback_keeps_strict_gate_bytes(self):
        actual = dict(self.old_target, **{'cpapp-b.bin':
            uploadgate.restore(self.old_target['cpapp-b.bin'])})
        job, camera, _ = self.old_job(actual=actual)
        evidence = self.evidence(job)
        with self.assertRaisesRegex(ValueError, 'Complete host readback differs'):
            job._read_programs(camera, job.state['target_hashes'],
                               allow_later_slots=False)
        job._invoke.assert_not_called()
        self.assertEqual(self.evidence(job), evidence)

    def test_selected_data_and_other_code_are_not_relaxed(self):
        cases = {}
        cases['selected-table'] = dict(self.later_target, **{
            'cpapp-b.bin': replace_table(self.later_target['cpapp-b.bin'], 1,
                                        bytes([9]) * six.TABLE_BYTES)})
        delta = photobasis.pack(self.bank, tone=(32, 0, 0))[1]
        cases['selected-photo'] = dict(self.later_target, **{
            'cpapp-b.bin': photoio.update(self.later_target['cpapp-b.bin'],
                                         {1: delta}, self.bank)})
        cases['AP'] = dict(self.later_target, **{'appFw.so': AP[:-1] + b'!'})
        cp = bytearray(self.later_target['cpapp-b.bin'])
        cp[0x40000] ^= 1
        cases['other-code'] = dict(self.later_target, **{'cpapp-b.bin': bytes(cp)})
        for label, actual in cases.items():
            with self.subTest(label=label):
                self.assert_rejected(label, actual)

    def test_unknown_gate_native_context_and_retired_stub_changes_reject(self):
        for label, offset in (('unknown-gate', uploadgate.OFFSET),
                              ('native-context', uploadgate.OFFSET + 4),
                              ('retired-stub', 0xb2750e)):
            cp = bytearray(self.later_target['cpapp-b.bin'])
            cp[offset] ^= 1
            with self.subTest(label=label):
                self.assert_rejected(label, dict(self.later_target, **{
                    'cpapp-b.bin': bytes(cp)}))

    def test_historical_context_and_reachable_stubs_must_be_valid(self):
        # Equal damage on both sides cannot be ignored as merely unchanged
        # shared code when the old forced entry is normalized to native.
        for label, offset in (('old-context', uploadgate.OFFSET + 4),
                              ('first-reachable-stub', 0xb2750e),
                              ('second-reachable-stub', 0xb27578)):
            expected = bytearray(self.old_target['cpapp-b.bin'])
            actual = bytearray(self.later_target['cpapp-b.bin'])
            expected[offset] ^= 1
            actual[offset] ^= 1
            with self.subTest(label=label):
                self.assert_rejected(label,
                    dict(self.later_target, **{'cpapp-b.bin': bytes(actual)}),
                    expected=dict(self.old_target, **{'cpapp-b.bin': bytes(expected)}))

    def test_native_to_forced_regression_is_not_a_compatible_upgrade(self):
        source = dict(self.before, **{
            'cpapp-b.bin': uploadgate.restore(self.before['cpapp-b.bin'])})
        expected = dict(self.old_target, **{
            'cpapp-b.bin': uploadgate.restore(self.old_target['cpapp-b.bin'])})
        actual = bytearray(self.later_target['cpapp-b.bin'])
        actual[uploadgate.OFFSET:uploadgate.OFFSET + 4] = uploadgate.FORCED
        uploadgate.validate(actual)
        self.assert_rejected('reverse-migration',
            dict(self.later_target, **{'cpapp-b.bin': bytes(actual)}),
            expected=expected, source=source)

    def test_hash_job_accepts_only_gate_upgrade_without_rewriting_old_evidence(self):
        self.assertFalse(photoio.present(self.hash_target['cpapp-b.bin']))
        job, camera, archived = self.old_job(
            actual=self.hash_upgraded, expected=self.hash_target,
            source=self.hash_before, byte_checks=False, names=self.old_names)
        old_hashes = dict(job.state['target_hashes'])
        evidence = self.evidence(job)
        original_archive = dict(archived)
        self.assertTrue(job._hashes())
        self.assertEqual(job.verify()['phase'], 'RELOAD_VERIFIED')
        self.assertTrue(job._later_upload_gate)
        self.assertFalse(job._later_fl23)
        self.assertFalse(job._later_slot_updates)
        self.assertEqual(job.state['target_hashes'], old_hashes)
        self.assertNotEqual(old_hashes['cpapp-b.bin'],
                            firmware.sha(self.hash_upgraded['cpapp-b.bin']))
        self.assertEqual(archived, original_archive)
        self.assertEqual(self.evidence(job), evidence)
        readback = next(row for row in job.state['journal'] if
                        row['event'] == 'complete_host_program_readback_verified')
        self.assertEqual(readback['comparison'],
                         'complete-bytes-with-native-upload-entry')
        job._invoke.assert_called_once_with(camera, 'runtime', 0)

    def test_hash_job_still_rejects_other_slot_data_and_code_changes(self):
        cases = {}
        for slot in (1, 6):
            cases['hash-table-' + str(slot)] = dict(self.hash_upgraded, **{
                'cpapp-b.bin': replace_table(self.hash_upgraded['cpapp-b.bin'],
                                            slot, bytes([9]) * six.TABLE_BYTES)})
        cases['hash-AP'] = dict(self.hash_upgraded, **{'appFw.so': AP[:-1] + b'!'})
        for label, offset in (('hash-other-code', 0x40000),
                              ('hash-unknown-gate', uploadgate.OFFSET),
                              ('hash-native-context', uploadgate.OFFSET + 4)):
            cp = bytearray(self.hash_upgraded['cpapp-b.bin'])
            cp[offset] ^= 1
            cases[label] = dict(self.hash_upgraded, **{'cpapp-b.bin': bytes(cp)})
        for label, actual in cases.items():
            with self.subTest(label=label):
                self.assert_rejected(label, actual, expected=self.hash_target,
                                     source=self.hash_before, byte_checks=False)

    def test_hash_job_source_and_immediate_readbacks_do_not_admit_gate_upgrade(self):
        source_upgraded = dict(self.hash_before, **{'cpapp-b.bin':
            uploadgate.restore(self.hash_before['cpapp-b.bin'])})
        for label, actual, expected_key, allow_later_slots in (
                ('hash-immediate', self.hash_upgraded, 'target_hashes', False),
                ('hash-source', source_upgraded, 'source_hashes', True)):
            with self.subTest(label=label):
                job, camera, _ = self.old_job(
                    label, actual=actual, expected=self.hash_target,
                    source=self.hash_before, byte_checks=False, names=self.old_names)
                evidence = self.evidence(job)
                with self.assertRaisesRegex(ValueError, 'Complete host readback differs'):
                    job._read_programs(camera, job.state[expected_key],
                                       allow_later_slots=allow_later_slots)
                job._invoke.assert_not_called()
                self.assertEqual(self.evidence(job), evidence)

    def test_hash_job_native_to_forced_is_rejected(self):
        source = dict(self.hash_before, **{'cpapp-b.bin':
            uploadgate.restore(self.hash_before['cpapp-b.bin'])})
        self.assert_rejected('hash-reverse-migration', self.hash_target,
                             expected=self.hash_upgraded, source=source,
                             byte_checks=False)


if __name__ == '__main__':
    unittest.main()
