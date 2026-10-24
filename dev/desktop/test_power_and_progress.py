"""Power confirmations and progress display; no camera or driver is touched."""
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtCore, QtWidgets as W
from desktopapp import jobs, worker
from desktopapp.platforms import usb_drivers as drivers
from desktopapp.window import Window
from looktool.power import require_power


class PowerProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'A7C2_DESKTOP_DATA': str(self.root / 'app')})
        env.start()
        self.addCleanup(env.stop)

    def window(self):
        value = Window()
        value.timer.stop()
        def close():
            value.process = None
            value.close()
        self.addCleanup(close)
        return value

    def test_confirmation_does_not_invent_a_battery_percentage(self):
        value = require_power(confirmed=True)
        self.assertIsNone(value.get('battery_percent'))
        self.assertEqual(value, {'confirmed': True})
        for charge in (None, 0, 49, 101):
            with self.assertRaises(ValueError):
                require_power(charge)
        self.assertEqual(require_power(82)['battery_percent'], 82)

    def test_home_defaults_to_six_looks_without_selecting_files(self):
        from desktopapp import presets
        window = self.window()
        args = window.setup_args()
        self.assertEqual(args['options']['preset_pack'], presets.PACK)
        self.assertEqual(args['options']['looks'], [])
        self.assertTrue(window.setup_presets.isChecked())
        self.assertIn('Astia', window.setup_preset_summary.text())
        self.assertIn('action_setup_all', [b.objectName() for b in window.buttons])
        window.fields['setup_look_5'].setText('old-hidden-selection.a7look')
        self.assertEqual(window.setup_args()['options']['looks'], [])

    def test_home_custom_mode_selects_only_requested_slots(self):
        window = self.window()
        window.setup_presets.setChecked(False)
        window.fields['setup_look_5'].setText('my-look.a7look')
        options = window.setup_args()['options']
        self.assertIsNone(options['preset_pack'])
        self.assertEqual(options['looks'], [dict(slot=5, path='my-look.a7look')])

    def test_look_page_starts_empty_and_supports_sparse_mixed_choices(self):
        from desktopapp import presets
        window=self.window()
        self.assertEqual(window.look_batch_args()['operations'],[])
        first=window.look_editor.add_row(2);first.action.setCurrentIndex(1)
        first.set_file(presets.catalog()[1]['path']);first.name.setText('My CC')
        window.look_editor.add_row(5)
        rows=window.look_batch_args()['operations']
        self.assertEqual([r['slot'] for r in rows],[2,5])
        self.assertEqual(rows[0]['name'],'My CC')
        self.assertEqual(rows[1],dict(slot=5,action='restore'))

    def test_empty_batch_does_not_prompt_power_or_start_a_job(self):
        window=self.window()
        with patch.object(W.QMessageBox,'warning') as warning,patch.object(W.QMessageBox,'question') as question,patch.object(jobs,'new_job') as job:
            window.launch('direct_looks_import',window.look_batch_args())
        warning.assert_called_once();question.assert_not_called();job.assert_not_called()

    def test_batch_button_starts_one_job_and_uses_look_verification_workspace(self):
        from desktopapp import presets
        window=self.window()
        window.look_editor.add_row(4)
        write=window.look_editor.add_row(6);write.action.setCurrentIndex(1);write.set_file(presets.catalog()[5]['path'])
        with patch.object(W.QMessageBox,'question',return_value=W.QMessageBox.Yes) as question,patch('desktopapp.window.QtCore.QProcess'):
            next(b for b in window.buttons if b.objectName()=='action_direct_looks_import').click()
        request=json.loads((window.current_job/'request.private.json').read_text())
        self.assertEqual(request['action'],'direct_looks_import')
        self.assertEqual(len(request['arguments']['operations']),2)
        self.assertEqual(request['arguments']['operations'][0],dict(slot=4,action='restore'))
        self.assertEqual(window.settings['look_direct_work'],request['arguments']['workspace'])
        self.assertIn('未添加的槽位保持原样',question.call_args.args[2])
        self.assertIn('恢复 ST 默认',question.call_args.args[2])
        self.assertTrue(window.camera_operation)
        self.assertFalse(window.stop.isEnabled())

    def test_home_keeps_old_pending_setup_without_injecting_six_looks(self):
        window = self.window()
        root = self.root / 'pending'; root.mkdir()
        options = dict(fl23=True, sound=False, vertical=False, looks=[])
        (root / 'setup.private.json').write_text(json.dumps(dict(phase='WAIT_RELOAD', options=options)))
        from desktopapp.paths import write_json, data_root
        write_json(data_root() / 'desktop.json', dict(setup_work=str(root)))
        pending = self.window()
        self.assertFalse(pending.setup_presets.isChecked())
        self.assertFalse(pending.setup_presets.isEnabled())
        self.assertEqual(pending.setup_args()['options'], options)
        self.assertIn('不会新增六款', pending.setup_preset_summary.text())

    def test_header_has_no_battery_input_and_cancel_opens_no_job(self):
        window = self.window()
        self.assertFalse(hasattr(window, 'battery'))
        self.assertNotIn('battery', window.common())
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel) as question, \
             patch.object(jobs, 'new_job') as job:
            window.launch('direct_fl23_enable', {'workspace': 'not-opened'})
        self.assertIn('电量充足', question.call_args.args[2])
        job.assert_not_called()

    def test_vertical_cleanup_is_part_of_off_not_a_separate_button(self):
        window = self.window()
        actions = [button.objectName() for button in window.buttons]
        self.assertIn('action_vertical_disable', actions)
        self.assertNotIn('action_vertical_remove', actions)

    def test_each_write_requires_a_fresh_popup_and_records_confirmation(self):
        window = self.window()
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes) as question, \
             patch('desktopapp.window.QtCore.QProcess') as process:
            for action in ('direct_fl23_enable', 'sound_off'):
                window.launch(action, {'workspace': 'offline-mocked'})
                request = json.loads((window.current_job / 'request.private.json').read_text())
                self.assertTrue(request['arguments']['power_confirmed'])
                self.assertNotIn('battery', request['arguments'])
                window.process = None
        self.assertEqual(question.call_count, 2)

    def test_worker_keeps_confirmation_without_fake_battery_report_or_duplicate_file(self):
        args = {'workspace': str(self.root / 'look'), 'power_confirmed': True, 'firmware': '2.01'}
        obj=Mock();obj.root=Path(args['workspace'])
        obj.run_direct.return_value={'mode':'fl23_enable','phase':'AWAITING_RELOAD'}
        with patch('looktool.direct.DirectJob',return_value=obj), redirect_stdout(io.StringIO()) as output:
            worker.run('direct_fl23_enable', args, self.root)
        self.assertTrue(obj.run_direct.call_args.kwargs['power_confirmed'])
        self.assertNotIn('Power:',output.getvalue())
        self.assertFalse((self.root/'power-confirmation.private.json').exists())

    def test_missing_confirmation_stops_before_any_camera_dispatch(self):
        for action in jobs.POWER_ACTIONS:
            with self.subTest(action=action), self.assertRaises(ValueError):
                worker.run(action, {}, self.root)

    def test_cancelled_direct_action_keeps_previous_verification_job(self):
        window = self.window()
        window.settings['fl23_direct_work'] = 'previous-completed-job'
        args = window.direct_args('fl23', mode='fl23_enable')
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel):
            window.launch('direct_fl23_enable', args)
        self.assertEqual(window.direct_verify_args('fl23')['workspace'], 'previous-completed-job')

    def test_enable_button_starts_write_directly_without_pre_restart_or_verify(self):
        window = self.window()
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes), \
             patch.object(window, 'show_reload_guide') as reload_popup, \
             patch('desktopapp.window.QtCore.QProcess') as process:
            button = next(b for b in window.buttons if b.objectName()=='action_direct_fl23_enable')
            button.click()
            request = json.loads((window.current_job / 'request.private.json').read_text())
            self.assertEqual(request['action'], 'direct_fl23_enable')
            self.assertTrue(request['arguments']['power_confirmed'])
            reload_popup.assert_not_called()
            process.return_value.start.assert_called_once()

    def test_main_factory_button_ignores_old_failure_and_starts_fresh(self):
        window = self.window()
        failed = self.root / 'original-failure'
        failed.mkdir()
        (failed / 'direct.private.json').write_text('{}')
        window.fields['factory_failed_work'].setText(str(failed))
        # Both records remain evidence, not prerequisites for the new request.
        latest = self.root / 'second-attempt'
        latest.mkdir()
        (latest / 'direct.private.json').write_text('{"phase":"NEEDS_REVIEW","journal":[]}')
        window.settings['factory_direct_work'] = str(latest)
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes) as question, \
             patch('desktopapp.window.QtCore.QProcess'):
            window.launch('direct_factory_reset', {'workspace': str(self.root / 'next'), 'firmware': '2.01'})
        request = json.loads((window.current_job / 'request.private.json').read_text())
        self.assertEqual(request['action'], 'direct_factory_reset')
        self.assertNotIn('failed_workspace', request['arguments'])
        self.assertTrue(request['arguments']['power_confirmed'])
        self.assertIn('移除项目程序修改', question.call_args.args[2])

    def test_cancelling_auto_continuation_preserves_original_selection(self):
        window = self.window()
        failed = self.root / 'original-failure'
        failed.mkdir()
        (failed / 'direct.private.json').write_text('{}')
        window.fields['factory_failed_work'].setText(str(failed))
        window.settings['factory_direct_work'] = str(failed)
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel), \
             patch.object(jobs, 'new_job') as new_job:
            window.launch('direct_factory_reset', {'workspace': 'not-started'})
        new_job.assert_not_called()
        self.assertEqual(window.settings['factory_direct_work'], str(failed))

    def test_first_one_click_on_windows_suggests_drivers_first(self):
        window = self.window()
        window.settings.pop('connection_verified', None)
        args = {'workspace': str(self.root / 'new-setup')}
        with patch('desktopapp.window.sys.platform', 'win32'):
            for choice, proceed in (('drivers', False), ('cancel', False), ('continue', True)):
                with self.subTest(choice=choice), patch.object(window, 'ask_drivers_first', return_value=choice) as ask:
                    window.nav.setCurrentRow(0)
                    self.assertEqual(window.drivers_first(args), proceed)
                    ask.assert_called_once()
                    self.assertEqual(window.nav.currentRow(), 1 if choice == 'drivers' else 0)
            # A verified connection, or an installation already in progress, is not asked again.
            with patch.object(window, 'ask_drivers_first') as ask:
                window.settings['connection_verified'] = True
                self.assertTrue(window.drivers_first(args))
                window.settings.pop('connection_verified')
                (self.root / 'new-setup').mkdir(); (self.root / 'new-setup/setup.private.json').write_text('{}')
                self.assertTrue(window.drivers_first(args))
                ask.assert_not_called()
        with patch('desktopapp.window.sys.platform', 'darwin'), patch.object(window, 'ask_drivers_first') as ask:
            self.assertTrue(window.drivers_first({'workspace': str(self.root / 'mac')}))
            ask.assert_not_called()

    def test_zadig_guide_sits_beside_automatic_driver_install_on_windows(self):
        from desktopapp import zadigguide
        with patch('desktopapp.window.sys.platform', 'win32'):
            window = self.window()
        zadig = window.findChild(W.QPushButton, 'zadig_guide')
        automatic = window.findChild(W.QPushButton, 'action_usb_prepare')
        self.assertTrue(zadig.property('primary'))
        self.assertIs(zadig.parentWidget(), automatic.parentWidget())
        self.assertIn('0336', zadigguide.TEXT); self.assertIn('libusbK', zadigguide.TEXT)
        with patch.object(W.QDialog, 'exec', return_value=0) as shown:
            zadig.click()
        shown.assert_called_once()
        with patch('desktopapp.window.sys.platform', 'darwin'):
            self.assertIsNone(self.window().findChild(W.QPushButton, 'zadig_guide'))

    def test_backup_verify_without_backup_record_offers_factory_verification(self):
        window = self.window()
        window.fields['restore_work'].setText(str(self.root / 'unused-recovery'))
        window.settings['factory_direct_work'] = str(self.root / 'factory')
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel), \
             patch('desktopapp.window.QtCore.QProcess'):
            window.findChild(W.QPushButton, 'action_restore_verify').click()
        self.assertIsNone(window.process)
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes), \
             patch('desktopapp.window.QtCore.QProcess'):
            window.findChild(W.QPushButton, 'action_restore_verify').click()
        request = json.loads((window.current_job / 'request.private.json').read_text())
        self.assertEqual(request['action'], 'direct_verify')
        self.assertTrue(request['arguments']['factory_verify'])
        window.process = None
        with self.assertRaisesRegex(ValueError, '没有旧备份恢复记录'):
            worker.run('restore_verify', {'workspace': str(self.root / 'unused-recovery')}, self.root)

    def test_completed_old_task_does_not_redirect_new_restore_to_verification(self):
        window = self.window()
        failed, completed = self.root / 'old-failure', self.root / 'completed'
        failed.mkdir(); completed.mkdir()
        (failed / 'direct.private.json').write_text('{}')
        (completed / 'direct.private.json').write_text(json.dumps({
            'resume_from': str(failed), 'phase': 'AWAITING_RELOAD'}))
        window.settings['factory_direct_work'] = str(completed)
        window.fields['factory_failed_work'].setText(str(failed))
        with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes) as question, \
             patch('desktopapp.window.QtCore.QProcess'):
            window.launch('direct_factory_reset', {'workspace': 'not-started'})
        self.assertIn('移除项目程序修改', question.call_args.args[2])
        request = json.loads((window.current_job / 'request.private.json').read_text())
        self.assertEqual(request['action'], 'direct_factory_reset')
        self.assertNotIn('failed_workspace', request['arguments'])
        self.assertTrue(request['arguments']['power_confirmed'])

    def test_restore_after_loaded_recovery_starts_fresh_write_not_old_verification(self):
        from desktopapp.paths import data_root,write_json
        work=data_root()/'work';old=work/'old-failure';loaded=work/'loaded-recovery'
        identity=dict(model='ILCE-7CM2',usb_serial_sha256='test-body')
        write_json(old/'direct.private.json',dict(mode='factory_reset',phase='NEEDS_REVIEW',identity=identity,
            journal=[dict(event='native_intent',mode=2)]))
        write_json(loaded/'direct.private.json',dict(mode='factory_reset',phase='LOADED',identity=identity,
            resume_from=str(old),readonly_after_reload_verified=True,physical_checks_accepted=False))
        window=self.window();window.fields['factory_failed_work'].setText(str(old))
        window.settings['factory_direct_work']=str(loaded)
        args=window.direct_args('factory',mode='factory_reset',factory='builtin')
        with patch.object(W.QMessageBox,'question',return_value=W.QMessageBox.Yes) as question, \
                patch('desktopapp.window.QtCore.QProcess'):
            window.launch('direct_factory_reset',args)
        request=json.loads((window.current_job/'request.private.json').read_text())
        self.assertEqual(request['action'],'direct_factory_reset')
        self.assertEqual(request['arguments']['workspace'],args['workspace'])
        self.assertNotEqual(request['arguments']['workspace'],str(loaded))
        self.assertTrue(request['arguments']['power_confirmed'])
        question.assert_called_once()

    def test_live_log_streams_partial_utf8_without_duplicates(self):
        path = self.root / 'log'
        tail = drivers.LiveLog(path)
        text = '正在卸载相机驱动\n'
        raw = text.encode('utf-8')
        output = io.StringIO()
        with redirect_stdout(output):
            path.write_bytes(raw[:5])
            tail.forward()
            with path.open('ab') as stream:
                stream.write(raw[5:])
            tail.forward()
            tail.forward(final=True)
        self.assertEqual(output.getvalue(), text)

    def test_driver_output_decode_and_raw_record(self):
        message = '驱动卸载完成'
        self.assertEqual(drivers.decode_windows_output(message.encode('utf-8')), message)
        self.assertEqual(drivers.decode_windows_output(message.encode('utf-16')), message)
        result = SimpleNamespace(stdout=message.encode('utf-8'), stderr=b'', returncode=0)
        with patch.object(drivers.subprocess, 'run', return_value=result) as command:
            drivers.run_pnputil(['/scan-devices'], log_dir=self.root)
        self.assertEqual(command.call_args.kwargs['timeout'], 180)
        self.assertEqual(next(self.root.glob('*stdout.raw')).read_bytes(), message.encode('utf-8'))

    def test_finished_worker_clears_busy_indicator_even_without_signal(self):
        window = self.window()
        window.current_job = jobs.new_job('driver_uninstall', {})
        (window.current_job / 'status.private.json').write_text('{"phase":"SUCCEEDED"}')
        process = Mock()
        process.state.return_value = QtCore.QProcess.NotRunning
        process.exitCode.return_value = 0
        window.process = process
        window.progress.setRange(0, 0)
        window.poll_job()
        self.assertIsNone(window.process)
        self.assertEqual(window.progress.value(), 100)
        self.assertIn('完成', window.status.text())

    def test_waiting_reload_popup_is_after_worker_cleanup_and_never_accepts_photos(self):
        for action, phase, mode in (('setup_all','WAIT_RELOAD','install_all'),
                                    ('direct_fl23_enable','AWAITING_RELOAD','fl23_enable'),
                                    ('restore','RESTORED_AWAITING_RELOAD','restore'),
                                    ('sound_on','written',None),
                                    ('sound_install','installed_cold_test_pending',None)):
            with self.subTest(action=action):
                window = self.window()
                window.current_job = jobs.new_job(action, {})
                (window.current_job / 'status.private.json').write_text(json.dumps(dict(
                    phase='SUCCEEDED', action=action, result=dict(phase=phase, mode=mode))))
                window.process = Mock()
                def dialog(**kwargs):
                    self.assertIsNone(window.process)
                    self.assertFalse(window.fl23_accept.isChecked())
                    self.assertEqual(kwargs, dict(setup=action=='setup_all', mode=action if action.startswith('sound_') else mode))
                with patch.object(window, 'show_reload_guide', side_effect=dialog) as popup:
                    window.finished(0, None)
                    window.finished(0, None)
                popup.assert_called_once()
                self.assertIn('无需再点核对' if mode=='fl23_enable' else '取电池至少 1 分钟', window.status.text())
                self.assertEqual(window.progress.value(),70 if action=='setup_all' else 100)

    def test_failed_or_already_loaded_job_does_not_prompt_power_removal(self):
        for phase, code in (('FAILED', 2), ('SUCCEEDED', 0)):
            window = self.window()
            window.current_job = jobs.new_job('direct_fl23_enable', {})
            (window.current_job / 'status.private.json').write_text(json.dumps(dict(
                phase=phase, action='direct_fl23_enable', result=dict(phase='LOADED'))))
            window.process = Mock()
            with patch.object(window, 'show_reload_guide') as popup:window.finished(code, None)
            popup.assert_not_called()

    def test_audition_and_save_prerequisites_popup_after_process_exit_exactly_once(self):
        for action,phase in (('sound_audition','temporary_pcm_registered_cold_reload_required_after_test'),
                ('sound_install','sound_conversion_required')):
            with self.subTest(phase=phase):
                window=self.window()
                window.current_job=jobs.new_job(action,{})
                (window.current_job/'status.private.json').write_text(json.dumps(dict(
                    phase='SUCCEEDED',action=action,result=dict(phase=phase))))
                window.process=Mock()
                def popup(*args):
                    self.assertIsNone(window.process)
                    self.assertIn('试听' if action=='sound_audition' else '保存尚未开始',args[1])
                    self.assertIn('保持相机开机' if action=='sound_audition' else '本次没有',args[2])
                with patch.object(W.QMessageBox,'information',side_effect=popup) as notice, \
                     patch.object(window,'show_reload_guide') as cold:
                    window.finished(0,None)
                    window.finished(0,None)
                    notice.assert_called_once()
                    cold.assert_not_called()
                self.assertIn('试听已准备好' if action=='sound_audition' else '等待操作',window.status.text())

    def test_reload_guide_has_order_wait_and_readonly_explanation(self):
        from desktopapp import reloadguide
        text = reloadguide.text(mode='fl23_enable')
        steps = ['1. 拔掉相机 USB', '2. 等待相机存取灯停止闪烁', '3. 将相机电源拨到 OFF',
                 '4. 取下电池', '5. 装回电池并开机']
        self.assertEqual(sorted(text.index(step) for step in steps), [text.index(step) for step in steps])
        self.assertIn('至少等待 1 分钟', text)
        self.assertIn('此前恢复原厂', text)
        self.assertIn('不会再刷一次', reloadguide.text(setup=True))
        self.assertIn('不必再接电脑点击核对', text)
        self.assertIn('继续安装', reloadguide.text(setup=True))

    def test_names_only_pause_shows_exact_instructions_and_never_claims_installed(self):
        from desktopapp import reloadguide
        window=self.window();window.current_job=jobs.new_job('setup_all',{})
        (window.current_job/'status.private.json').write_text(json.dumps(dict(phase='SUCCEEDED',action='setup_all',
            result=dict(phase='WAIT_RESOURCE_RELOAD',mode='install_all'))))
        window.process=Mock()
        with patch.object(window,'show_reload_guide') as popup:window.finished(0,None)
        popup.assert_called_once_with(setup=True,mode='resource_reload')
        self.assertEqual(window.progress.value(),40)
        self.assertIn('程序尚未写入',window.status.text())
        text=reloadguide.text(setup=True,mode='resource_reload')
        self.assertIn('先不用拍照',text);self.assertIn('不重复写名称',text)


if __name__ == '__main__':
    unittest.main()
