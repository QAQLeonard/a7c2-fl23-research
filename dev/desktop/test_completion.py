"""Completed setup presentation and history; no camera or driver calls."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets as W
from desktopapp import allinone, completion, jobs, worker
from desktopapp.paths import data_root, write_json
from desktopapp.window import Window


class CompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, A7C2_DESKTOP_DATA=str(self.root / 'app'))
        env.start(); self.addCleanup(env.stop)
        self.setup = self.root / 'setup'
        self.state = dict(phase='COMPLETE', workspace=str(self.setup),
            options=dict(fl23=True, sound=False, vertical=True, plugin=False,
                looks=[dict(slot=4, name='Astia', path='slot4.a7look')]),
            vertical_result=dict(running='ON', saved='OFF'),
            completed_steps=['drivers', 'persistent_features', 'vertical'],
            physical_checks_accepted=False, error='historic EBUSY')
        write_json(self.setup / 'setup.private.json', self.state)
        write_json(data_root() / 'desktop.json', dict(setup_work=str(self.setup)))

    def window(self):
        window = Window(); window.timer.stop()
        self.addCleanup(window.close)
        return window

    def test_final_popup_once_after_process_cleanup_and_no_fake_acceptance(self):
        window = self.window()
        window.current_job = jobs.new_job('setup_all', {})
        write_json(window.current_job / 'status.private.json',
            dict(phase='SUCCEEDED', action='setup_all', result=self.state))
        process = window.process = Mock()
        def dialog(parent, title, text):
            self.assertIsNone(window.process)
            self.assertEqual(window.progress.value(), 100)
            self.assertEqual(title, '安装完成')
            self.assertIn('电子快门声：本次未选择', text)
            self.assertIn('未保存为开机默认', text)
            self.assertIn('自订 4：Astia', text)
        with patch.object(W.QMessageBox, 'information', side_effect=dialog) as popup:
            window.finished(0, None)
            window.finished(0, None)
        popup.assert_called_once(); process.deleteLater.assert_called_once()
        saved = json.loads((self.setup / 'setup.private.json').read_text())
        self.assertFalse(saved['physical_checks_accepted'])
        self.assertNotIn('error', saved)
        self.assertEqual(saved['previous_errors'][0]['error'], 'historic EBUSY')
        self.assertIn('新的一键安装', window.setup_button.text())

    def test_view_previous_result_needs_no_new_job_and_preserves_failed_evidence(self):
        evidence = self.setup / 'failed/result.bin'
        evidence.parent.mkdir(); evidence.write_bytes(b'original failure evidence')
        window = self.window()
        with patch.object(jobs, 'new_job') as new_job, patch.object(worker, 'run') as run, \
                patch.object(W.QMessageBox, 'information') as popup:
            window.setup_result_button.click()
            window.setup_result_button.click()
        self.assertEqual(popup.call_count, 2)
        new_job.assert_not_called(); run.assert_not_called()
        state = json.loads((self.setup / 'setup.private.json').read_text())
        self.assertEqual(len(state['previous_errors']), 1)
        self.assertEqual(evidence.read_bytes(), b'original failure evidence')

    def test_completed_old_setup_archives_error_without_dispatch(self):
        dispatch = Mock(side_effect=AssertionError('must not connect'))
        state = allinone.run(dict(workspace=str(self.setup), firmware='2.01',
            power_confirmed=True), dispatch=dispatch)
        dispatch.assert_not_called()
        self.assertNotIn('error', state)
        self.assertEqual(len(state['previous_errors']), 1)

    def test_successful_resume_archives_prior_error_but_new_failure_stays_active(self):
        self.state.update(phase='WAIT_RELOAD', options=dict(vertical=True, sound=False),
            completed_steps=['drivers', 'persistent_features'])
        write_json(self.setup / 'setup.private.json', self.state)
        def dispatch(action, args, folder):
            if action == 'direct_verify':return dict(phase='LOADED')
            if action == 'vertical_enable':raise RuntimeError('new vertical failure')
            raise AssertionError(action)
        with self.assertRaisesRegex(RuntimeError, 'new vertical failure'):
            allinone.run(dict(workspace=str(self.setup), firmware='2.01', power_confirmed=True), dispatch=dispatch)
        state = json.loads((self.setup / 'setup.private.json').read_text())
        self.assertEqual(state['phase'], 'NEEDS_REVIEW')
        self.assertEqual(state['error'], 'new vertical failure')
        self.assertEqual(state['previous_errors'][0]['error'], 'historic EBUSY')

    def test_failed_setup_keeps_active_error_and_cannot_show_success(self):
        self.state['phase'] = 'NEEDS_REVIEW'
        write_json(self.setup / 'setup.private.json', self.state)
        with self.assertRaises(ValueError): completion.text(self.state)
        window = self.window()
        with patch.object(W.QMessageBox, 'information') as popup:
            window.show_setup_result()
        self.assertEqual(popup.call_args.args[1], '安装尚未结束')
        self.assertEqual(json.loads((self.setup / 'setup.private.json').read_text())['error'], 'historic EBUSY')

    def test_persistent_completed_result_explains_no_per_boot_computer_action(self):
        self.state['vertical_result']=dict(persistent=True,loaded_verified=True,running='ON',saved='ON',alias_count=3)
        text=completion.text(self.state)
        self.assertIn('已保存开启',text)
        self.assertIn('无需每次连接电脑',text)
        self.assertNotIn('旧版仅开启',text)

    def test_worker_summary_is_short_but_full_private_evidence_is_retained(self):
        self.state.pop('error')
        self.state['previous_errors'] = [dict(error='historic EBUSY')]
        self.state['private_evidence'] = str(self.setup / 'failed')
        job = jobs.new_job('setup_all', {})
        # On macOS a camera action would otherwise open a real Terminal sudo
        # prompt (worker.execute_request routes through macos_authorization);
        # this test only exercises the summary logging path.
        from desktopapp.platforms import macos_authorization
        with patch.object(worker, 'run', return_value=self.state), \
                patch.object(macos_authorization, 'required', return_value=False):
            self.assertEqual(worker.execute_request(job / 'request.private.json'), 0)
        log = (job / 'worker.log').read_text(encoding='utf-8')
        self.assertNotIn('historic EBUSY', log)
        self.assertNotIn('private_evidence', log)
        self.assertIn('previous_error_count', log)
        self.assertEqual(json.loads((job / 'result.private.json').read_text()), self.state)
        self.assertEqual(json.loads((job / 'status.private.json').read_text())['result'], self.state)
