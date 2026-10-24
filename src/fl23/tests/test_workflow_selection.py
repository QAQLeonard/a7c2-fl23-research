"""Backup-selection regressions adapted from PR #9; no physical camera access."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup as backup_mod
import core
import layout
import transport
import workflow


class BackupSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.programs = [b'synthetic AP', b'synthetic CP']
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(core, 'ORIGINAL', [core.sha(p) for p in self.programs]))
        self.stack.enter_context(patch.object(core, 'backup_records', return_value=[
            {key: SimpleNamespace(data=b'\0', attr=0) for key in core.AP_KEYS}, {}]))
        self.stack.enter_context(patch.object(layout, 'BACKUP', self.root / 'default'))
        self.stack.enter_context(patch.object(core, 'assets'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.selected = self.make_backup(self.root / 'chosen', '1' * 64, 11)

    def make_backup(self, folder, serial, salt):
        units = [bytearray(n) for n in (8192, 28672)]
        for unit in units:
            unit[0x80] = salt
        files = {layout.PROGRAM_FILES[n]: p for n, p in zip(core.PROGRAMS, self.programs)}
        files.update({layout.UNIT_FILES[k]: bytes(p) for k, p in zip(core.CP_KEYS, units)})
        files[layout.SETTINGS_FILE] = b'synthetic BK4 snapshot'
        store = backup_mod.Backup(folder)
        report = store.write(files, {'model': core.MODEL, 'serial_sha256': serial})
        self.assertTrue(report['ok'], report)
        return store

    def restore_selected(self):
        expected = {'model': core.MODEL, 'serial_sha256': '1' * 64}
        context = Mock()
        context.__enter__ = Mock(return_value=SimpleNamespace(identity=expected))
        context.__exit__ = Mock(return_value=False)

        def check_settings(job, session, restore=False):
            self.assertTrue(restore)
            originals, _ = job.units()
            self.assertEqual(originals, self.selected.load_units())

        with patch.object(transport, 'Session', return_value=context) as session, \
                patch.object(workflow.Job, 'program_state', return_value='original'), \
                patch.object(workflow.Job, 'module'), patch.object(workflow.Job, 'files'), \
                patch.object(workflow.Job, 'settings', autospec=True, side_effect=check_settings):
            job = workflow.restore_from_backup(80, self.root / 'work', self.selected.path)
        session.assert_called_once_with(expected)
        self.assertEqual(job.backup.path, self.selected.path)
        self.assertEqual(job.state['phase'], 'restored_pending_cold_start')
        return job

    def test_explicit_external_backup_works_with_empty_default_store(self):
        self.restore_selected()

    def test_explicit_backup_is_not_replaced_by_other_body_default(self):
        self.make_backup(layout.BACKUP / 'other', '2' * 64, 22)
        self.restore_selected()

    def test_selected_units_override_stale_workspace_files(self):
        folder = self.root / 'work' / 'original'
        folder.mkdir(parents=True)
        for key, n in zip(core.CP_KEYS, (8192, 28672)):
            (folder / layout.UNIT_FILES[key]).write_bytes(bytes([77]) * n)
        self.restore_selected()

    def test_corrupt_selected_backup_never_falls_back_or_opens_usb(self):
        self.make_backup(layout.BACKUP / 'other', '2' * 64, 22)
        (self.selected.path / layout.SETTINGS_FILE).write_bytes(b'damaged')
        with patch.object(transport, 'Session') as session:
            with self.assertRaisesRegex(ValueError, '备份未通过校验'):
                workflow.restore_from_backup(80, self.root / 'work', self.selected.path)
        session.assert_not_called()

    def test_explicit_backup_with_wrong_expected_body_is_rejected(self):
        job = workflow.Job(self.root / 'work')
        job.backup = self.selected
        with self.assertRaisesRegex(ValueError, '机身不同'):
            job.attach_backup('2' * 64)

    def test_verify_reloads_selected_backup_without_workspace_originals(self):
        job = workflow.Job(self.root / 'install')
        job.backup = self.selected
        job.attach_backup()
        job.save('installed_pending_cold_start')
        units = dict(zip(core.CP_KEYS, core.merge_colors(*self.selected.load_units().values())))
        records = [{k: SimpleNamespace(data=bytes([10+i])) for i, k in enumerate(core.AP_KEYS)},
                   {k: SimpleNamespace(data=v) for k, v in units.items()}]
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.call.return_value = b'current'
        fresh = workflow.Job(job.root)
        with patch.object(transport, 'Session', return_value=session) as connect, \
                patch.object(fresh, 'files'), patch.object(fresh, 'module', return_value={'spans': []}), \
                patch.object(core, 'patch_program', return_value=b'loaded AP') as patch_program, \
                patch.object(core, 'backup_records', side_effect=lambda raw: records if raw == b'current' else [
                    {k: SimpleNamespace(data=b'\0') for k in core.AP_KEYS}, {}]):
            fresh.verify()
        connect.assert_called_once_with({'model': core.MODEL, 'serial_sha256': '1' * 64})
        patch_program.assert_called_once_with(self.programs[0], 0)
        self.assertEqual(fresh.backup.path, self.selected.path)


class NativeResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'assets').mkdir()
        (self.root / 'assets/installer.so').write_bytes(b'SYNTHETIC WORKER')
        self.job = workflow.Job(self.root / 'work')
        self.files, self.calls = {}, []
        self.launched = False
        self.failure = None
        self.session = SimpleNamespace(healthy=True, read=self.read, temp=self.temp)
        self.base = patch.object(core, 'BASE', self.root)
        self.base.start()
        self.addCleanup(self.base.stop)

    def read(self, path, optional=False):
        name = path.rsplit('/', 1)[-1]
        self.calls.append(('read', name))
        if self.launched and name == 'a7c2.install.result' and self.failure == 'read':
            raise TimeoutError('Unknown native result')
        if name == 'a7c2-preview-staged.so' and name in self.files and self.failure == 'stage':
            return b'BAD STAGE'
        return self.files.get(name)

    def temp(self, name, blob=None, remove=False):
        self.calls.append(('remove' if remove else 'write', name))
        if remove:
            self.files.pop(name, None)
            return
        self.files[name] = blob
        if name == 'libJit.so':
            self.launched = True
            self.files['a7c2.install.result'] = b'SYNTHETIC RESULT'
            if self.failure == 'launch':
                raise TimeoutError('Unknown launch outcome')

    def test_unknown_launch_or_result_never_sends_cleanup(self):
        for failure in ('launch', 'read'):
            with self.subTest(failure=failure):
                self.files.clear(); self.calls.clear()
                self.launched = False; self.failure = failure; self.session.healthy = True
                with self.assertRaises(TimeoutError):
                    self.job.module(self.session, 'installer', 1)
                self.assertFalse(self.session.healthy)
                self.assertIn('libJit.so', self.files)
                self.assertFalse(any(kind == 'remove' for kind, _ in self.calls))

    def test_malformed_or_interrupted_result_retains_raw_evidence(self):
        for error in (ValueError('Malformed report'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.files.clear(); self.calls.clear(); self.launched = False
                self.session.healthy = True
                with patch.object(core, 'parse_native', side_effect=error), self.assertRaises(type(error)):
                    self.job.module(self.session, 'installer', 1)
                self.assertFalse(self.session.healthy)
                self.assertFalse(any(kind == 'remove' for kind, _ in self.calls))
                self.assertTrue(any(p.read_bytes() == b'SYNTHETIC RESULT' for p in
                                    (self.job.root / 'evidence').glob('*.bin')))

    def test_known_prelaunch_failure_cleans_only_staging(self):
        self.failure = 'stage'
        with self.assertRaisesRegex(RuntimeError, '临时模块读回不符'):
            self.job.module(self.session, 'installer', 1)
        self.assertFalse(self.launched)
        self.assertTrue(self.session.healthy)
        self.assertEqual(self.files, {})
        self.assertEqual([name for kind, name in self.calls if kind == 'remove'],
                         ['a7c2-preview-staged.so'])

    def test_verified_success_cleans_owned_files(self):
        with patch.object(core, 'parse_native', return_value={'ok': True}):
            self.assertEqual(self.job.module(self.session, 'installer', 1), {'ok': True})
        self.assertTrue(self.session.healthy)
        self.assertEqual(self.files, {})


if __name__ == '__main__':
    unittest.main()
