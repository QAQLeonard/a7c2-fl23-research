"""Synthetic backups and fake sessions: never enumerate or open a camera."""
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
import compat


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
        session.read.side_effect = lambda path: b'loaded AP' if path.endswith('appFw.so') else b'loaded CP'
        fresh = workflow.Job(job.root)
        with patch.object(transport, 'Session', return_value=session), \
                patch.object(fresh, 'files'), patch.object(fresh, 'module', return_value={'spans': []}), \
                patch.object(compat, 'plan', return_value=({}, True, {}, None, None)) as plan, \
                patch.object(core, 'backup_records', side_effect=lambda raw: records if raw == b'current' else [
                    {k: SimpleNamespace(data=b'\0') for k in core.AP_KEYS}, {}]):
            fresh.verify()
        plan.assert_called_once_with(b'loaded AP', b'loaded CP', core.VERSION, transitions=False)
        self.assertEqual(fresh.backup.path, self.selected.path)


class CompatiblePreparationGuards(unittest.TestCase):
    def test_unsaved_unrelated_recipe_stops_before_any_native_program_write(self):
        with tempfile.TemporaryDirectory() as folder:
            job=workflow.Job(Path(folder)/'work')
            job.state={'phase':'prepared','compatibility':{'already_enabled':False},'identity':{'model':core.MODEL,'serial_sha256':'body'}}
            for n in core.PROGRAMS:(job.root/'original'/layout.PROGRAM_FILES[n]).write_bytes(b'synthetic original')
            units={k:b'color' for k in core.CP_KEYS}
            before=[{k:SimpleNamespace(data=b'\0',attr=0) for k in core.AP_KEYS},{k:SimpleNamespace(data=v,attr=0) for k,v in units.items()}]
            before[0][0x02cf0001]=SimpleNamespace(data=b'unsaved',attr=0)
            saved=[dict(before[0]),dict(before[1])]
            saved[0][0x02cf0001]=SimpleNamespace(data=b'saved',attr=0)
            session=Mock();session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
            with patch.object(job,'load',return_value=job),patch.object(job,'files'),patch.object(job,'units',return_value=(units,units)), \
                    patch.object(transport,'Session',return_value=session),patch.object(core,'backup_records',side_effect=[before,saved]), \
                    patch.object(job,'module') as native:
                with self.assertRaisesRegex(ValueError,'Unselected unsaved'):job.install_prepared(90)
            native.assert_not_called()
            self.assertEqual(job.state['phase'],'prepared')

    def test_invalid_version_and_nonempty_workspace_stop_before_usb(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(transport,'Session') as session:
            root=Path(folder);job=workflow.Job(root/'work')
            with self.assertRaisesRegex(ValueError,'2.01'):job.prepare(root/'second','2.00')
            (job.root/'keep.txt').write_text('existing evidence')
            with self.assertRaisesRegex(ValueError,'空白'):job.prepare(root/'second','2.01')
            self.assertEqual((job.root/'keep.txt').read_text(),'existing evidence')
        session.assert_not_called()

    def test_backup_directory_cannot_contain_workspace(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(transport,'Session') as session:
            root=Path(folder);job=workflow.Job(root/'work')
            for second in (job.root,job.root/'nested',root):
                with self.assertRaisesRegex(ValueError,'独立目录'):job.prepare(second,'2.01')
        session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
