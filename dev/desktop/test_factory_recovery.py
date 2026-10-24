"""Factory recovery faults and discovery; all camera access is simulated."""
import copy
import json
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import test_direct_resume as resume_fixture
from looktool import checkpointworker, direct, factoryrecover, nameworker


class FactoryRecoveryTests(unittest.TestCase):
    job = resume_fixture.DirectResumeTests.job
    write_prior = resume_fixture.DirectResumeTests.write_prior
    target = resume_fixture.DirectResumeTests.target

    def setUp(self):
        resume_fixture.DirectResumeTests.setUp(self)
        self.intent = dict(event='native_stage_intent', stage='checkpoint.staged.so',
            result='checkpoint.names.result', request='checkpoint.names.request', mode=2,
            contents_hex=struct.pack('<8sII', b'A7NAM001', 2, 0).hex())
        self.prior['journal'].insert(-1, self.intent)
        self.write_prior()

    def test_original_enospc_is_discovered_despite_later_read_only_failure(self):
        later = self.root / 'later-no-write'
        later.mkdir()
        state = dict(self.prior, journal=[], program_builds=[])
        (later / 'direct.private.json').write_text(json.dumps(state))
        os.utime(later / 'direct.private.json', (4_000_000_000, 4_000_000_000))
        selected = factoryrecover.pending(self.root)
        self.assertEqual(selected[0], self.failed.resolve())

    def test_cleanup_and_names_resume_preserve_evidence_and_skip_programs(self):
        for status in (-28, -5):
            with self.subTest(status=status):
                self.temps['checkpoint.names.result'] = resume_fixture.report(68, status=status)
                job = self.job()
                if job.root.exists():
                    job = type(job)(self.root / 'next-continuation', factory=self.camera)
                before = {p: p.read_bytes() for p in self.failed.rglob('*') if p.is_file()}
                with patch.object(direct, 'plan', side_effect=self.target):
                    result = job.continue_factory(self.failed, power_confirmed=True, factory_values={})
                self.assertEqual(result['phase'], 'AWAITING_RELOAD')
                self.assertEqual(result['program_builds'], [])
                self.assertFalse(any(k == 'program' for k, m in self.camera.native_calls))
                self.assertEqual(self.temps, {})
                self.assertEqual(before, {p: p.read_bytes() for p in self.failed.rglob('*') if p.is_file()})

    def test_missing_result_does_not_clear_worker_or_start_writes(self):
        self.temps.pop('checkpoint.names.result')
        before = dict(self.temps)
        with patch.object(direct, 'plan', side_effect=self.target), self.assertRaisesRegex(ValueError, '结果报告缺失'):
            self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(before, self.temps)
        self.assertEqual(self.camera.native_calls, [])
        self.assertEqual(self.camera.saves, [])

    def test_unknown_worker_or_request_is_not_deleted(self):
        for name in ('checkpoint.staged.so', 'checkpoint.names.request', 'libJit.so'):
            with self.subTest(name=name):
                values = dict(self.temps, **{name: b'foreign'})
                self.camera.temp_read = lambda n, missing=False: values.get(n)
                self.camera.temp_remove = lambda n: values.pop(n)
                before = dict(values)
                with self.assertRaises(ValueError):
                    factoryrecover.cleanup(self.camera, factoryrecover.chain(self.failed), lambda *a, **kw: None, lambda *a: None)
                self.assertEqual(values, before)

    def test_partial_cleanup_preserves_result_and_can_resume(self):
        original_remove = self.camera.temp_remove
        def disconnect(name):
            if name == 'checkpoint.names.request':
                raise TimeoutError('host disconnected during cleanup')
            original_remove(name)
        self.camera.temp_remove = disconnect
        history = factoryrecover.chain(self.failed)
        with self.assertRaises(TimeoutError):
            factoryrecover.cleanup(self.camera, history, lambda *a, **kw: None, lambda *a: None)
        self.assertNotIn('checkpoint.staged.so', self.temps)
        self.assertEqual(self.temps['checkpoint.names.result'], self.raw)
        self.camera.temp_remove = original_remove
        factoryrecover.cleanup(self.camera, history, lambda *a, **kw: None, lambda *a: None)
        self.assertEqual(self.temps, {})

    def test_download_failed_but_camera_result_present_is_usable(self):
        # Recovery reads the camera result, not the presence of a host copy.
        (self.failed / 'evidence/known-names-2.bin').unlink()
        with patch.object(direct, 'plan', side_effect=self.target):
            self.assertEqual(self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})['phase'], 'AWAITING_RELOAD')

    def test_partial_programs_only_remaining_window_is_written(self):
        # The first attempted reset window has rolled back to its exact old
        # value. Rebuild only that difference; don't replay earlier requests.
        self.camera.files['/usr/lib/appFw.so'] = b'\x03' + self.camera.files['/usr/lib/appFw.so'][1:]
        def target(current, *a, **kw):
            result, wanted, _ = self.target(current)
            result['appFw.so'] = b'\0' + result['appFw.so'][1:]
            return result, wanted, None
        with patch.object(direct, 'plan', side_effect=target):
            result = self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(result['phase'], 'AWAITING_RELOAD')
        self.assertEqual(sum(b['windows'] for b in result['program_builds']), 1)
        self.assertEqual(self.camera.files['/usr/lib/appFw.so'][0], 0)
        self.assertEqual(self.camera.native_calls.count(('program', 1)), 1)

    def test_unknown_program_bytes_stop_before_temp_cleanup(self):
        self.camera.files['/usr/lib/appFw.so'] = b'\x7f' + self.camera.files['/usr/lib/appFw.so'][1:]
        before = dict(self.temps)
        with self.assertRaisesRegex(ValueError, '未确认的字节'):
            self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(self.temps, before)

    def test_partial_names_already_restored_are_not_written_again(self):
        restored = nameworker.filenames()[:40]
        for n in restored:
            from looktool import resources
            self.camera.files['/usr/share/app/' + n] = resources.before_custom(self.camera.files['/usr/share/app/' + n])
        with patch.object(direct, 'plan', side_effect=self.target):
            result = self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(result['inverse_name_build']['count'], 28)

    def test_second_failure_after_names_can_continue_settings_without_names_or_program_writes(self):
        first = self.job()
        native = first.native
        def recorded(camera, kind, mode, build=None):
            result = native(camera, kind, mode, build)
            if kind == 'runtime':
                first.record('native_result_verified', result=result)
            return result
        with patch.object(direct, 'plan', side_effect=self.target), patch.object(first, 'native', side_effect=recorded), \
             patch.object(first, 'restore_settings', side_effect=TimeoutError('settings connection lost')), self.assertRaises(TimeoutError):
            first.continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.camera.native_calls.clear()
        second = type(first)(self.root / 'second', factory=self.camera)
        # The earlier invocation has been accounted for and its namespace is
        # empty; settings are planned again from fresh live/saved snapshots.
        with patch.object(direct, 'plan', side_effect=self.target):
            result = second.continue_factory(first.root, power_confirmed=True, factory_values={})
        self.assertEqual(result['phase'], 'AWAITING_RELOAD')
        self.assertIsNone(result['inverse_name_build'])
        self.assertFalse(any(k in ('program', 'names') and m in (1, 2) for k, m in self.camera.native_calls))

    def test_completed_recovery_selects_verification_and_complete_recovery_is_not_replayed(self):
        continued = self.root / 'continued'
        continued.mkdir()
        for phase in ('AWAITING_RELOAD', 'LOADED', 'COMPLETE'):
            state = dict(self.prior, phase=phase, resume_from=str(self.failed))
            (continued / 'direct.private.json').write_text(json.dumps(state))
            os.utime(continued / 'direct.private.json', (4_000_000_000, 4_000_000_000))
            chosen = factoryrecover.pending(self.root, self.failed)
            if phase == 'COMPLETE':
                self.assertIsNone(chosen)
            else:
                self.assertEqual(chosen[0], continued.resolve())
                self.assertEqual(chosen[1]['phase'], phase)

    def test_loaded_readonly_verified_is_not_pending_even_without_photo_acceptance(self):
        continued=self.root/'loaded-recovery';continued.mkdir()
        state=dict(self.prior,phase='LOADED',resume_from=str(self.failed),
            readonly_after_reload_verified=True,physical_checks_accepted=False)
        path=continued/'direct.private.json';path.write_text(json.dumps(state))
        os.utime(path,(4_000_000_000,4_000_000_000))
        original=self.failed.joinpath('direct.private.json').read_bytes()
        self.assertIsNone(factoryrecover.pending(self.root,self.failed))
        self.assertIsNone(factoryrecover.pending(self.root,continued))
        self.assertEqual(self.failed.joinpath('direct.private.json').read_bytes(),original)
        self.assertFalse(json.loads(path.read_text())['physical_checks_accepted'])

    def test_multiple_bodies_plan_fresh_unless_selected_and_ancestry_loops_stop(self):
        other = self.root / 'other'
        other.mkdir()
        state = copy.deepcopy(self.prior)
        state['identity']['serial_sha256'] = 'another-body'
        (other / 'direct.private.json').write_text(json.dumps(state))
        # The connected body is unknown before USB opens: plan fresh, keep both.
        self.assertIsNone(factoryrecover.pending(self.root))
        self.assertEqual(factoryrecover.pending(self.root, self.failed)[0], self.failed.resolve())
        self.prior['resume_from'] = str(self.failed)
        self.write_prior()
        with self.assertRaisesRegex(ValueError, 'loop'):
            factoryrecover.chain(self.failed)

    def test_unreadable_or_unattributed_records_never_block_discovery(self):
        broken = self.root / 'broken'; broken.mkdir()
        (broken / 'direct.private.json').write_text('{truncated')
        anonymous = self.root / 'anonymous'; anonymous.mkdir()
        state = copy.deepcopy(self.prior); state['identity'] = {'model': 'ILCE-7CM2'}
        (anonymous / 'direct.private.json').write_text(json.dumps(state))
        for preferred in (None, broken, anonymous):
            with self.subTest(preferred=preferred):
                self.assertEqual(factoryrecover.pending(self.root, preferred)[0], self.failed.resolve())
        self.assertEqual((broken / 'direct.private.json').read_text(), '{truncated')

    def test_native_program_failure_requires_successful_rollback_and_remount(self):
        from looktool import worker
        sizes = self.prior['program_builds'][0]['sizes']
        for status, rollback, readonly, accepted in ((0, 0, 0, True), (-5, 0, 0, True), (-5, -5, 0, False), (-5, 0, -30, False)):
            with self.subTest(status=status, rollback=rollback, readonly=readonly):
                raw = worker.REPORT.pack(b'A7IRP001', 1, 1, 9 if status == 0 else 6,
                    1, status, rollback, 0, readonly, 0, 0, 519, 11, 12, *sizes) + bytes(128)
                if accepted:
                    factoryrecover.outcome(raw, 'checkpoint.program.result', 1, self.prior, self.camera)
                else:
                    with self.assertRaises(ValueError):
                        factoryrecover.outcome(raw, 'checkpoint.program.result', 1, self.prior, self.camera)

    def test_host_dispatch_replans_builtin_reset_without_old_worker_dependency(self):
        from desktopapp import worker
        from unittest.mock import Mock
        instance = Mock()
        instance.root = self.root / 'next'
        instance.run_direct.return_value = {'phase': 'AWAITING_RELOAD', 'mode': 'factory_reset'}
        args = dict(workspace=str(instance.root), firmware='2.01', power_confirmed=True)
        with patch('looktool.factoryrecover.pending', return_value=(self.failed, self.prior)), \
             patch('looktool.direct.DirectJob', return_value=instance), \
             patch('desktopapp.official.load', return_value={}):
            result = worker.run('direct_factory_reset', args, self.root)
        instance.continue_factory.assert_not_called()
        instance.run_direct.assert_called_once()
        self.assertEqual(instance.run_direct.call_args.args,('factory_reset',))
        self.assertEqual(instance.run_direct.call_args.kwargs['factory_path'],'builtin')
        self.assertIsNone(instance.run_direct.call_args.kwargs.get('recovery_identity'))
        self.assertEqual(result['phase'], 'AWAITING_RELOAD')

    def dispatch(self, prior, configure):
        """Run the restore button's worker path with one mock job per folder."""
        from desktopapp import worker
        from unittest.mock import Mock
        jobs = {}
        def job(root):
            if Path(root) not in jobs:
                jobs[Path(root)] = Mock(root=Path(root))
                jobs[Path(root)].run_direct.return_value = {'phase': 'AWAITING_RELOAD', 'mode': 'factory_reset'}
                configure(Path(root), jobs[Path(root)])
            return jobs[Path(root)]
        (self.failed / 'direct.private.json').write_text(json.dumps(prior))
        args = dict(workspace=str(self.root / 'next'), firmware='2.01', power_confirmed=True)
        with patch('looktool.factoryrecover.pending', return_value=(self.failed, prior)), \
             patch('looktool.direct.DirectJob', side_effect=job), \
             patch('desktopapp.official.load', return_value={}):
            return worker.run('direct_factory_reset', args, self.root), jobs

    def test_old_finished_or_failed_recovery_never_redirects_a_fresh_reset(self):
        for phase in ('AWAITING_RELOAD','LOADED','COMPLETE','NEEDS_REVIEW'):
            prior = dict(self.prior, phase=phase)
            def reject_old_verification(root, job):
                job.verify_direct.side_effect = AssertionError('Old task verification must not gate a fresh reset')
            result, jobs = self.dispatch(prior, reject_old_verification)
            fresh = jobs[self.root / 'next']
            fresh.verify_direct.assert_not_called()
            fresh.run_direct.assert_called_once()
            self.assertIsNone(fresh.run_direct.call_args.kwargs.get('recovery_identity'))
            self.assertEqual(result['phase'], 'AWAITING_RELOAD')
            self.assertEqual(result['workspace'], str(self.root / 'next'))

    def test_old_other_body_record_is_not_used_to_bind_the_fresh_reset(self):
        prior = dict(self.prior, identity={'model':'ILCE-7CM2','serial_sha256':'other-body'})
        result, jobs = self.dispatch(prior, lambda root, job: None)
        self.assertEqual(set(jobs), {self.root / 'next'})
        jobs[self.root / 'next'].run_direct.assert_called_once()
        self.assertIsNone(jobs[self.root / 'next'].run_direct.call_args.kwargs.get('recovery_identity'))
        self.assertEqual(result['workspace'], str(self.root / 'next'))

    def test_unreadable_selected_record_replans_fresh(self):
        result, jobs = self.dispatch({}, lambda root, job: None)
        (self.failed / 'direct.private.json').write_text('{truncated')
        from desktopapp import worker
        from unittest.mock import Mock
        instance = Mock(root=self.root / 'again')
        instance.run_direct.return_value = {'phase': 'AWAITING_RELOAD', 'mode': 'factory_reset'}
        with patch('looktool.factoryrecover.pending', return_value=None), \
             patch('looktool.direct.DirectJob', return_value=instance), \
             patch('desktopapp.official.load', return_value={}):
            worker.run('direct_resume_factory', dict(workspace=str(instance.root), firmware='2.01',
                       power_confirmed=True, failed_workspace=str(self.failed)), self.root)
        self.assertIsNone(instance.run_direct.call_args.kwargs.get('recovery_identity'))

    def test_empty_temporary_namespace_without_any_completion_proof_stops(self):
        self.temps.clear()
        (self.failed / 'evidence/known-names-2.bin').unlink()
        with patch.object(direct, 'plan', side_effect=self.target), self.assertRaisesRegex(ValueError, '尚无执行完成'):
            self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(self.camera.native_calls, [])
        self.assertEqual(self.camera.saves, [])

    def test_empty_namespace_can_use_complete_saved_name_report(self):
        self.temps.clear()
        with patch.object(direct, 'plan', side_effect=self.target):
            result = self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(result['phase'], 'AWAITING_RELOAD')
        event = next(r for r in result['journal'] if r['event'] == 'previous_temporary_namespace_empty')
        self.assertEqual(event['completion_evidence'], 'complete-saved-native-report')

    def test_empty_namespace_can_use_valid_new_boot_but_not_empty_boot(self):
        self.temps.clear()
        (self.failed / 'evidence/known-names-2.bin').unlink()
        self.prior['source_boot_id'] = '00000000-0000-0000-0000-000000000001'
        self.write_prior()
        history = factoryrecover.chain(self.failed)
        for boot in (b'', b'not-a-boot-id', b'00000000-0000-0000-0000-000000000001'):
            self.camera.read = lambda *a: boot
            with self.assertRaisesRegex(ValueError, '尚无执行完成'):
                factoryrecover.cleanup(self.camera, history, lambda *a, **kw: None, lambda *a: None)
        self.camera.read = lambda *a: b'00000000-0000-0000-0000-000000000002\n'
        events = []
        factoryrecover.cleanup(self.camera, history, lambda event, **kw: events.append((event, kw)), lambda *a: None)
        self.assertEqual(events[0][1]['completion_evidence'], 'new-camera-boot')

    def test_unknown_outcome_marks_session_unhealthy_before_teardown(self):
        from unittest.mock import Mock
        self.camera.mark_unknown = Mock()
        self.temps.pop('checkpoint.names.result')
        with patch.object(direct, 'plan', side_effect=self.target), self.assertRaisesRegex(ValueError, '结果报告缺失'):
            self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.camera.mark_unknown.assert_called_once()

    def mount_busy_after_all_names(self):
        from looktool import resources
        for n in nameworker.filenames():
            path = '/usr/share/app/' + n
            self.camera.files[path] = resources.before_custom(self.camera.files[path])
        values = list(nameworker.REPORT.unpack(self.raw))
        values[3] = 9; values[5] = values[8] = -16
        values[12] = values[15] = 68
        self.temps['checkpoint.names.result'] = nameworker.REPORT.pack(*values)
        self.camera.usr_mount_readonly = False

    def test_completed_names_busy_mount_continues_only_settings_and_requires_new_ro_boot(self):
        self.mount_busy_after_all_names()
        job = self.job()
        with patch.object(direct, 'plan', side_effect=self.target):
            result = job.continue_factory(self.failed, power_confirmed=True, factory_values={})
            self.assertEqual(result['phase'], 'AWAITING_RELOAD')
            self.assertTrue(result['readonly_deferred_busy'])
            self.assertEqual(result['program_builds'], [])
            self.assertIsNone(result['inverse_name_build'])
            self.assertFalse(any(k in ('program', 'names') for k, m in self.camera.native_calls))
            self.camera.boot = 'test-boot-2'
            with self.assertRaisesRegex(ValueError, '只读挂载尚未确认'):
                job.verify_direct(factory_values={})
            self.assertEqual(job.state['phase'], 'AWAITING_RELOAD')
            self.camera.usr_mount_readonly = True
            verified = job.verify_direct(factory_values={})
        self.assertEqual(verified['phase'], 'LOADED')
        self.assertTrue(verified['readonly_after_reload_verified'])

    def test_busy_mount_is_not_accepted_when_programs_or_names_still_need_writes(self):
        self.mount_busy_after_all_names()
        self.camera.files['/usr/lib/appFw.so'] = b'\x03' + self.camera.files['/usr/lib/appFw.so'][1:]
        def target(current, *a, **kw):
            result, wanted, _ = self.target(current)
            result['appFw.so'] = b'\0' + result['appFw.so'][1:]
            return result, wanted, None
        before = dict(self.temps)
        with patch.object(direct, 'plan', side_effect=target), self.assertRaisesRegex(ValueError, 'cleanup/remount'):
            self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
        self.assertEqual(self.temps, before)
        self.assertEqual(self.camera.native_calls, [])
        self.assertEqual(self.camera.saves, [])

    def test_other_readonly_failures_remain_errors(self):
        self.mount_busy_after_all_names()
        values = list(nameworker.REPORT.unpack(self.temps['checkpoint.names.result']))
        values[5] = values[8] = -30
        self.temps['checkpoint.names.result'] = nameworker.REPORT.pack(*values)
        with patch.object(direct, 'plan', side_effect=self.target), self.assertRaisesRegex(ValueError, 'cleanup/remount'):
            self.job().continue_factory(self.failed, power_confirmed=True, factory_values={})
