"""Direct transactions use no original job/backup and preserve unrelated data."""
import copy
from contextlib import redirect_stdout
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/looks/tests'))
from test_checkpoint import Camera, SimRollback, values, fake_compile, KEYS
from looktool import direct, checkpointworker, checkpoint, nameworker, resources


class SimDirect(direct.DirectJob, SimRollback):
    def cleanup_sound_resources(self,camera):
        # Native allowlist/hash/remount behavior is exercised by test_resource_files_native.
        self.state['private_sound_files_removed']=True
        self.record('simulated_private_sound_cleanup')
    def sync_look_bases(self, camera, prepared, selected=None):
        keys,ram,_,_,_=prepared
        # A separate runtime model is essential: Backup writes do not update it.
        live=getattr(camera,'live_look_bases',{})
        for key in (keys if selected is None else selected):live[key]=ram[0][key].data
        camera.live_look_bases=live
        self.record('simulated_native_look_bases_synchronized')

    def native(self, camera, kind, mode, build=None):
        result = super().native(camera, kind, mode, build)
        if kind == 'runtime':
            result['boot_id'] = getattr(camera, 'boot', 'test-boot-1')
            result['usr_mount_readonly'] = getattr(camera, 'usr_mount_readonly', True)
        return result


class DirectTransactionTests(unittest.TestCase):
    def test_factory_reset_always_waits_for_reload_to_clear_temporary_audio(self):
        job=SimDirect(self.root/'already-default',factory=self.camera)
        with patch.object(direct,'plan',side_effect=lambda current,*args,**kwargs:(dict(current),[{},{}],None)):
            result=job.run_direct('factory_reset',version='2.01',power_confirmed=True)
        self.assertEqual(result['phase'],'AWAITING_RELOAD')
        self.assertFalse(any(kind=='program' and mode==1 for kind,mode in self.camera.native_calls))
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before = values()
        self.camera = Camera(self.before)
        original = self.camera.__class__.__call__
        self.open = patch.object(Camera, '__call__', lambda obj, expected=None: obj if expected is None else original(obj, expected))
        self.open.start()
        self.addCleanup(self.open.stop)
        self.compile = patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile)
        self.compile.start()
        self.addCleanup(self.compile.stop)

    def plan(self, current, records, mode, **kw):
        target = dict(current)
        changed = bytearray(current['appFw.so'])
        changed[3:5] = b'\x12\x34'
        target['appFw.so'] = bytes(changed)
        return target, [{KEYS[0]: b'\x05'}, {}], None

    def test_install_progress_never_calls_it_factory_restoration(self):
        for mode in ('fl23_enable', 'look_import', 'install_all'):
            job = SimDirect(self.root / mode, factory=self.camera)
            job.state = dict(mode=mode)
            output = io.StringIO()
            with redirect_stdout(output):
                for phase in ('PLANNED','PREFLIGHT_VERIFIED','RESTORING_NAMES','RESTORING_SETTINGS'):job.save(phase)
            self.assertNotIn('恢复', output.getvalue())
            self.assertIn('写入计划', output.getvalue())
            self.assertNotIn('只校验完成', output.getvalue())
            self.assertIn('写入前检查通过', output.getvalue())

    def test_no_backup_and_full_readback_with_selected_settings_only(self):
        job = SimDirect(self.root / 'direct', factory=self.camera)
        before = copy.deepcopy(self.camera.ram)
        with patch.object(direct, 'plan', side_effect=self.plan):
            result = job.run_direct('slot_default', version='2.01', power_confirmed=True, slot=1)
        self.assertEqual(result['phase'], 'AWAITING_RELOAD')
        self.assertFalse(result['backup_created'])
        self.assertEqual(list(self.root.rglob('*.zip')), [])
        self.assertEqual(self.camera.files['/usr/lib/appFw.so'][3:5], b'\x12\x34')
        self.assertEqual(self.camera.ram[0][KEYS[0]].data, b'\x05')
        for chip in (0, 1):
            for key, prop in before[chip].items():
                if (chip, key) != (0, KEYS[0]):
                    self.assertEqual(self.camera.ram[chip][key], prop)

    def test_unknown_native_outcome_never_reaches_settings(self):
        job = SimDirect(self.root / 'unknown', factory=self.camera)
        job.lose_after_program = True
        with patch.object(direct, 'plan', side_effect=self.plan), self.assertRaises(TimeoutError):
            job.run_direct('slot_default', version='2.01', power_confirmed=True, slot=1)
        self.assertEqual(job.state['phase'], 'NEEDS_REVIEW')
        self.assertEqual(self.camera.saves, [])
        with self.assertRaises(ValueError):
            job.run_direct('slot_default', version='2.01', power_confirmed=True, slot=1)

    def test_verification_requires_a_new_boot_not_only_matching_disk_bytes(self):
        job = SimDirect(self.root / 'cold', factory=self.camera)
        with patch.object(direct, 'plan', side_effect=self.plan):
            job.run_direct('slot_default', version='2.01', power_confirmed=True, slot=1)
            with self.assertRaisesRegex(ValueError, '冷启动'):
                job.verify_direct()
            self.camera.boot = 'test-boot-2'
            self.assertEqual(job.verify_direct()['phase'], 'LOADED')

    def test_already_set_does_not_drop_retained_image_or_write(self):
        job = SimDirect(self.root / 'noop', factory=self.camera)
        with patch.object(direct, 'plan', side_effect=lambda current, *a, **kw: (dict(current), [{}, {}], None)):
            result = job.run_direct('fl23_disable', version='2.01', power_confirmed=True)
        self.assertEqual(result['phase'], 'LOADED')
        self.assertFalse(any(kind == 'wbi' or mode == 1 for kind, mode in self.camera.native_calls))
        self.assertFalse(self.camera.saves)

    def test_wrong_version_or_missing_power_stops_before_camera(self):
        job = SimDirect(self.root / 'stop', factory=self.camera)
        with patch.object(job, 'factory') as factory:
            for version, confirmed in [('3.00', True), ('2.01', False)]:
                with self.assertRaises(ValueError):
                    job.run_direct('factory_reset', version=version, power_confirmed=confirmed)
            factory.assert_not_called()

    def test_name_capacity_failure_precedes_any_program_or_setting_write(self):
        for n in nameworker.filenames():
            path = '/usr/share/app/' + n
            self.camera.files[path] = resources.rename(self.camera.files[path], {1: 'CC'})[0]
        def planned(current, *args, **kwargs):
            target, wanted, _ = self.plan(current, None, None)
            for n in nameworker.filenames():
                target['resources/' + n] = resources.before_custom(current['resources/' + n])
            return target, wanted, None
        job = SimDirect(self.root / 'space', factory=self.camera)
        original = job.native
        def space_failure(camera, kind, mode, build=None):
            if kind == 'names' and mode == 4:
                raise ValueError('ENOSPC preflight')
            return original(camera, kind, mode, build)
        before = copy.deepcopy(self.camera.files)
        with patch.object(direct, 'plan', side_effect=planned), patch.object(job, 'native', side_effect=space_failure), self.assertRaisesRegex(ValueError, 'ENOSPC'):
            job.run_direct('factory_reset', version='2.01', power_confirmed=True)
        self.assertEqual(self.camera.files, before)
        self.assertEqual(self.camera.saves, [])
        self.assertFalse(any(kind == 'program' and mode == 1 for kind, mode in self.camera.native_calls))

    def test_saved_and_live_calibration_stay_independent_during_group_save(self):
        for key, size in zip(checkpoint.CP_KEYS, (8192, 28672)):
            live = bytearray(size)
            stored = bytearray(size)
            live[0x80:0x88] = b'RAMDATA!'
            stored[0x80:0x88] = b'FLASHDAT'
            self.camera.ram[1][key] = self.camera.ram[1][key]._replace(data=bytes(live))
            self.camera.saved[1][key] = self.camera.saved[1][key]._replace(data=bytes(stored))
        def planned(current, records, *args, **kwargs):
            wanted = {}
            for key, spans in direct.color_regions().items():
                data = bytearray(records[1][key].data)
                for at, size in spans:
                    data[at:at + size] = bytes([7]) * size
                wanted[key] = bytes(data)
            return dict(current), [{}, wanted], None
        job = SimDirect(self.root / 'calibration', factory=self.camera)
        with patch.object(direct, 'plan', side_effect=planned):
            job.run_direct('factory_reset', version='2.01', power_confirmed=True)
        for key in checkpoint.CP_KEYS:
            self.assertEqual(self.camera.ram[1][key].data[0x80:0x88], b'RAMDATA!')
            self.assertEqual(self.camera.saved[1][key].data[0x80:0x88], b'FLASHDAT')
        self.assertEqual(list(self.root.rglob('*.zip')), [])

    def test_factory_restore_removes_stale_backups_before_any_write(self):
        stale = '/usr/share/app/.a7c2-lut-3e57ffe746c143e3-' + nameworker.filenames()[0] + '.original'
        self.camera.files[stale] = b'old backup'
        job = SimDirect(self.root / 'purge', factory=self.camera)
        with patch.object(direct, 'plan', side_effect=lambda current, *a, **k: (dict(current), [{}, {}], None)):
            result = job.run_direct('factory_reset', version='2.01', power_confirmed=True)
        self.assertNotIn(stale, self.camera.files)
        kinds = [kind for kind, mode in self.camera.native_calls]
        self.assertIn('purge', kinds)
        self.assertFalse(any(kind in ('program', 'names') and mode in (1, 2)
                             for kind, mode in self.camera.native_calls[:kinds.index('purge')]))
        event = next(e for e in result['journal'] if e['event'] == 'stale_name_backups_removed')
        self.assertEqual(event['removed'], 1)
        self.assertTrue(Path(result['purge_build']['path']).is_file())

    def named_job(self, *, fail_names=False):
        class Named(SimDirect):
            def forward_names(inner, camera, build, mode):
                camera.native_calls.append(('forward_names', mode))
                if mode == 1:
                    if fail_names:raise OSError('ENOSPC resource staging')
                    for n, raw in inner.name_targets.items():camera.files['/usr/share/app/' + n] = raw
        job = Named(self.root / 'named', factory=self.camera)
        def prepare(sources, names, ap, identifier, out, *args, **kwargs):
            job.name_targets = {n: resources.rename(raw, names)[0] for n, raw in sources.items()}
            return job.name_targets, dict(unchanged=False, count=68, files=[{'file': n} for n in sources])
        def plan(current, *args, **kwargs):
            target, fields, _ = self.plan(current, None, None)
            for n in nameworker.filenames():
                key='resources/' + n
                parsed=resources.decode(current[key])
                if parsed['entries'].get(resources.LABEL_IDS[0],{}).get('text')!='CC':
                    target[key]=resources.rename(current[key],{1:'CC'})[0]
            return target, fields, ({1:'CC'},resources.LABEL_IDS)
        return job, prepare, plan

    def test_title_staging_failure_never_writes_programs_or_recipes(self):
        job, prepare, planned = self.named_job(fail_names=True)
        before = dict(self.camera.files)
        with patch.object(direct, 'plan', side_effect=planned), patch.object(nameworker, 'prepare', side_effect=prepare), self.assertRaisesRegex(OSError,'ENOSPC'):
            job.run_direct('look_import',version='2.01',power_confirmed=True,slot=1)
        self.assertEqual(self.camera.files,before)
        self.assertEqual(self.camera.saves,[])
        self.assertNotIn(('program',1),self.camera.native_calls)

    def test_title_install_precedes_programs_and_cleanup_waits_for_new_boot(self):
        job, prepare, planned = self.named_job()
        with patch.object(direct,'plan',side_effect=planned), patch.object(nameworker,'prepare',side_effect=prepare), \
             patch.object(nameworker,'prepare_cleanup',side_effect=lambda build,*args:build):
            result=job.run_direct('look_import',version='2.01',power_confirmed=True,slot=1)
            calls=self.camera.native_calls
            self.assertLess(calls.index(('forward_names',1)),calls.index(('program',1)))
            self.assertTrue(result['names_cleanup_pending'])
            self.assertNotIn(('forward_names',3),calls)
            with self.assertRaisesRegex(ValueError,'冷启动'):job.verify_direct()
            self.assertNotIn(('forward_names',3),calls)
            self.camera.boot='test-boot-2'
            verified=job.verify_direct()
            self.assertFalse(verified['names_cleanup_pending'])
            self.assertEqual(calls.count(('forward_names',3)),1)
            job.verify_direct()
            self.assertEqual(calls.count(('forward_names',3)),1)


if __name__ == '__main__':
    unittest.main()
