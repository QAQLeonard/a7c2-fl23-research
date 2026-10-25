"""GUI/backend contracts and driver sequencing, with camera calls replaced."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from desktopapp import jobs, worker
from desktopapp.platforms import usb_drivers as drivers


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'A7C2_DESKTOP_DATA': str(self.root / 'app')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_driver_installer_only_targets_camera_ids(self):
        for pid in ('0e8a', '0336'):
            args = drivers.driver_arguments('wdi-simple.exe', pid, self.root)
            self.assertIn('0x054C', args)
            self.assertIn('0x' + pid, args)
            self.assertNotIn('--filter', args)
        with self.assertRaises(ValueError):
            drivers.driver_arguments('installer', '1234', self.root)

    def test_windows_scan_retains_native_query_error_without_powershell(self):
        import libusb_package
        import usb.backend.libusb1
        with patch.object(drivers.sys, 'platform', 'win32'), \
             patch.object(drivers.platform, 'machine', return_value='AMD64'), \
             patch('desktopapp.platforms.windows_pnp.devices',side_effect=OSError('native-query-error')), \
             patch.object(drivers.subprocess,'run') as subprocess_run, \
             patch('usb.backend.libusb1.get_backend', return_value=object()), \
             patch('usb.core.find', return_value=[]):
            result = drivers.scan()
        self.assertEqual(result['errors'][0]['stage'],'windows-pnp')
        self.assertIn('native-query-error',result['errors'][0]['error'])
        subprocess_run.assert_not_called()

    def test_driver_query_failure_is_not_reported_as_missing_camera(self):
        report=dict(devices=[],errors=[dict(stage='windows-pnp',error='query-timeout')],
            libusb_devices=[dict(pid='0e8a',product='ILCE-7CM2')])
        with patch.object(drivers.sys,'platform','win32'),patch.object(drivers,'installer') as installer:
            with self.assertRaisesRegex(RuntimeError,'Windows 驱动查询失败.*054C:0E8A.*query-timeout'):
                drivers.install({'pid':'0e8a'},self.root,report=report)
        installer.assert_not_called()

    def test_two_stage_driver_setup_has_one_session_no_auth_retry(self):
        events = []
        transport = SimpleNamespace(SERVICE_DRIVER_SETUP=None)
        @contextmanager
        def camera():
            events.append('first-auth')
            transport.SERVICE_DRIVER_SETUP()
            events.append('second-auth')
            yield SimpleNamespace(identity={'model': 'ILCE-7CM2'})
            events.append('end')
        with patch.object(drivers.sys, 'platform', 'win32'), \
             patch.object(drivers, 'install', side_effect=lambda args, job, **kw: events.append(args['pid'])), \
             patch.object(drivers, 'scan', return_value={'devices': [{'id': 'USB\\VID_054C&PID_0336'}]}), \
             patch('looktool.devicesession.modules', return_value=(transport, None)), \
             patch('looktool.devicesession.Camera', side_effect=camera):
            result = drivers.prepare(self.root)
        self.assertEqual(events, ['0e8a', 'first-auth', '0336', 'second-auth', 'end'])
        self.assertFalse(result['camera_firmware_written'])
        self.assertIsNone(transport.SERVICE_DRIVER_SETUP)

    def test_compile_uses_current_cli_calibration_option(self):
        args = dict(source='look.cube', name='Look', output='look.a7look', model='response.npz')
        with patch('looktool.compilelook.main', return_value=0) as compile:
            result = worker.run('compile_look', args, self.root)
        argv = compile.call_args.args[0]
        self.assertIn('--calibration', argv)
        self.assertNotIn('--model', argv)
        self.assertEqual(result['output'], 'look.a7look')

    def test_failed_offline_job_retains_full_traceback_and_no_success(self):
        job = jobs.new_job('compile_look', {})
        with patch.object(worker, 'run', side_effect=RuntimeError('native status -28 raw error')):
            code = worker.execute_request(job / 'request.private.json')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads((job / 'status.private.json').read_text())['phase'], 'FAILED')
        self.assertIn('Traceback', (job / 'worker.log').read_text())
        self.assertIn('native status -28', (job / 'worker.log').read_text())

    def test_every_device_action_is_non_cancellable(self):
        for action in ('restore_auto', 'sound_restore_sound', 'sound_audition', 'vertical_remove', 'usb_prepare'):
            self.assertIn(action, jobs.CAMERA_ACTIONS)

    def test_standalone_fl23_is_completed_after_write_not_paused_for_verification(self):
        from desktopapp import reloadguide
        for mode in ('fl23_enable','fl23_disable'):
            obj=Mock(); obj.root=self.root/mode
            obj.run_direct.return_value=dict(phase='AWAITING_RELOAD',mode=mode)
            with patch('looktool.direct.DirectJob',return_value=obj):
                result=worker.run('direct_'+mode,dict(workspace=str(obj.root),firmware='2.01',power_confirmed=True),self.root)
            self.assertEqual(result['phase'],'COMPLETED')
            self.assertTrue(result['verification_optional'])
            self.assertTrue(reloadguide.required('direct_'+mode,result))
            obj.run_direct.assert_called_once()
            obj.verify_direct.assert_not_called()

    def test_names_resume_before_cold_boot_never_starts_program_writer(self):
        old=self.root/'old';old.mkdir();path=old/'direct.private.json';path.write_text('{"phase":"AWAITING_RESOURCE_RELOAD"}')
        fresh=Mock();fresh.root=self.root/'fresh'
        prior=Mock();prior.root=old;prior.state_path=path
        prior.verify_names_reload.return_value=dict(phase='AWAITING_RESOURCE_RELOAD',mode='install_all')
        with patch('looktool.direct.DirectJob',side_effect=[fresh,prior]):
            result=worker.run('direct_resume_looks',dict(workspace=str(fresh.root),failed_workspace=str(old),firmware='2.01',power_confirmed=True),self.root)
        self.assertEqual(result['workspace'],str(old));self.assertEqual(result['phase'],'AWAITING_RESOURCE_RELOAD')
        fresh.run_direct.assert_not_called();prior.verify_names_reload.assert_called_once()

    def test_names_resume_after_verification_uses_frozen_plan_for_one_program_install(self):
        old=self.root/'old';old.mkdir();path=old/'direct.private.json';path.write_text('{"phase":"AWAITING_RESOURCE_RELOAD"}')
        frozen=dict(fl23=True,sound=False,looks=[dict(slot=2,path='saved.a7look')])
        fresh=Mock();fresh.root=self.root/'fresh';fresh.run_direct.return_value=dict(phase='AWAITING_RELOAD',mode='install_all')
        prior=Mock();prior.root=old;prior.state_path=path
        prior.verify_names_reload.return_value=dict(phase='RESOURCE_RELOAD_VERIFIED',mode='install_all',bundle_options=frozen)
        with patch('looktool.direct.DirectJob',side_effect=[fresh,prior]):
            result=worker.run('direct_resume_looks',dict(workspace=str(fresh.root),failed_workspace=str(old),firmware='2.01',power_confirmed=True,options={}),self.root)
        self.assertEqual(result['phase'],'AWAITING_RELOAD')
        fresh.run_direct.assert_called_once()
        self.assertEqual(fresh.run_direct.call_args.kwargs['bundle_options'],frozen)

    def test_verify_resource_checkpoint_cannot_mark_program_install_complete(self):
        path=self.root/'direct.private.json';path.write_text('{"phase":"AWAITING_RESOURCE_RELOAD","mode":"install_all"}')
        obj=Mock();obj.root=self.root;obj.state_path=path
        obj.verify_names_reload.return_value=dict(phase='RESOURCE_RELOAD_VERIFIED',mode='install_all')
        with patch('looktool.direct.DirectJob',return_value=obj):
            result=worker.run('direct_verify',dict(workspace=str(self.root),accepted=True),self.root)
        self.assertEqual(result['phase'],'RESOURCE_RELOAD_VERIFIED')
        obj.verify_direct.assert_not_called();obj.run_direct.assert_not_called()

    def test_unknown_sony_pid_is_reported_without_driver_replacement(self):
        row={'id':r'USB\VID_054C&PID_0D68\private-instance','name':'USB Input Device',
             'description':'Unknown Sony interface','status':'OK','service':'HidUsb'}
        with patch.object(drivers,'scan',return_value={'devices':[row],'errors':[]}), \
             patch.object(drivers,'installer') as installer:
            with self.assertRaisesRegex(RuntimeError,'PID_0D68'):
                drivers.install({'pid':'0e8a'},self.root)
        installer.assert_not_called()
        self.assertTrue((self.root/'driver-before.private.json').exists())
        with self.assertRaises(ValueError):drivers.driver_arguments('unused','0d68',self.root)

    def test_frozen_plugin_installs_into_temporary_adobe_directory_without_camera(self):
        from desktopapp import plugins
        tool=self.root/'tools/exiftool.exe'; tool.parent.mkdir();tool.write_bytes(b'test-exiftool')
        adobe=self.root/'temporary-appdata'
        with patch.dict(os.environ,{'APPDATA':str(adobe)}), patch.object(plugins.sys,'frozen',True,create=True):
            result=plugins.install({'exiftool':str(tool),'data_root':str(self.root/'profile-data')})
        plugin=Path(result['plugin'])
        self.assertTrue((plugin/'Info.lua').is_file())
        self.assertTrue((plugin/'Config.lua').is_file())
        settings=json.loads(Path(result['settings']).read_text())
        self.assertEqual(settings['worker_prefix'],['--raw-profile-worker'])
        self.assertTrue(Path(settings['exiftool']).is_file())

    def test_factory_verification_uses_only_explicitly_selected_record(self):
        from unittest.mock import Mock
        obj=Mock();obj.root=self.root/'actual-completed'
        obj.state_path=self.root/'state';obj.state_path.write_text('{"mode":"factory_reset","factory_path":"builtin","phase":"AWAITING_RELOAD"}')
        obj.verify_direct.return_value={'phase':'LOADED','mode':'factory_reset'}
        args={'workspace':str(obj.root),'factory_verify':True,'accepted':False}
        with patch('looktool.direct.DirectJob',return_value=obj),patch('desktopapp.official.prepare_restore',return_value=({},'local-reference',None)):
            result=worker.run('direct_verify',args,self.root)
        self.assertEqual(result['workspace'],str(obj.root))
        obj.verify_direct.assert_called_once()

    def test_worker_new_restore_does_not_verify_completed_historical_recovery(self):
        from unittest.mock import Mock
        from desktopapp.paths import data_root,write_json
        prior=data_root()/'work'/'completed'
        write_json(prior/'direct.private.json',dict(mode='factory_reset',phase='LOADED',
            identity=dict(model='ILCE-7CM2',usb_serial_sha256='test-body'),
            readonly_after_reload_verified=True,physical_checks_accepted=False))
        obj=Mock();obj.root=self.root/'fresh-recovery'
        obj.run_direct.return_value=dict(mode='factory_reset',phase='AWAITING_RELOAD')
        with patch('looktool.direct.DirectJob',return_value=obj),patch('desktopapp.official.prepare_restore',return_value=({},'local-reference',None)):
            result=worker.run('direct_factory_reset',dict(workspace=str(obj.root),firmware='2.01',
                power_confirmed=True,failed_workspace=str(prior)),self.root)
        obj.verify_direct.assert_not_called();obj.continue_factory.assert_not_called()
        self.assertEqual(obj.run_direct.call_args.args,('factory_reset',))
        self.assertEqual(result['workspace'],str(obj.root))

    @unittest.skipUnless(sys.platform=='win32','Windows CMD forwarding')
    def test_current_fl23_wrapper_forwards_cli_arguments_once_with_unicode_paths(self):
        import shutil, subprocess
        from desktopapp.paths import ROOT
        base=self.root/'相机 tools'
        (base/'src/fl23').mkdir(parents=True)
        shutil.copy2(ROOT/'FL23.cmd',base/'FL23.cmd')
        (base/'src/fl23/Start.cmd').write_text('@echo off\r\n"'+sys.executable+'" -c "import json,sys; print(json.dumps(sys.argv[1:]))" %*\r\nexit /b 7\r\n',encoding='utf-8')
        command='"'+os.environ.get('COMSPEC','cmd.exe')+'" /d /c call "'+str(base/'FL23.cmd')+'" --help "with space"'
        result=subprocess.run(command,
            capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,7,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout),['--help','with space'])

    def test_desktop_vertical_off_also_removes_auxiliary_resources(self):
        from unittest.mock import Mock
        obj=Mock()
        obj.run_frames.return_value=dict(mode='vertical_disable',phase='AWAITING_RELOAD',reload_required=True,
            vertical_result=dict(saved='OFF',running='OFF',alias_count=0,persistent=True))
        with patch('desktopapp.platforms.usb_drivers.prepare') as prepare, \
             patch('looktool.portraitjob.PortraitJob',return_value=obj) as job:
            result = worker.run('vertical_disable', dict(workspace=str(self.root), firmware='2.01', power_confirmed=True), self.root)
        prepare.assert_called_once_with(self.root)
        self.assertTrue(Path(job.call_args.args[0]).name.startswith('frames-'))
        self.assertEqual(obj.run_frames.call_args.args,(False,))
        self.assertEqual(obj.run_frames.call_args.kwargs,dict(version='2.01',power_confirmed=True))
        self.assertEqual(result['vertical_result']['alias_count'],0)
        self.assertEqual(result['vertical_result']['saved'],'OFF')

    def test_sound_worker_returns_actual_phase_for_reload_dialog(self):
        obj=Mock();obj.root=self.root/'direct-switch'
        obj.run_direct.return_value=dict(phase='LOADED',mode='sound_enable')
        with patch('looktool.direct.DirectJob',return_value=obj):
            result = worker.run('sound_on', dict(workspace=str(self.root), backup='backup',
                firmware='2.01', power_confirmed=True), self.root)
        self.assertEqual(result['phase'], 'LOADED')
        self.assertEqual(obj.run_direct.call_args.args,('sound_enable',))
        from desktopapp import reloadguide
        self.assertFalse(reloadguide.required('sound_on',result))

    def test_failed_sound_command_never_returns_reload_success(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'dev/shutter_sound'))
        with patch('sound_cli.main', return_value=2), self.assertRaisesRegex(RuntimeError,'Sound operation stopped'):
            worker.run('sound_install', dict(workspace=str(self.root), firmware='2.01', power_confirmed=True), self.root)

    def test_sound_save_forwards_backup_for_automatic_workspace_creation(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'dev/shutter_sound'))
        def success(argv,*,report,failure=None):
            self.assertIn('--backup-copy',argv)
            self.assertEqual(argv[argv.index('--backup-copy')+1],str(self.root/'backup'))
            report(dict(phase='installed_cold_test_pending'));return 0
        with patch('sound_cli.main',side_effect=success):
            result=worker.run('sound_install',dict(workspace=str(self.root/'sound'),backup=str(self.root/'backup'),
                firmware='2.01',power_confirmed=True),self.root)
        self.assertEqual(result['phase'],'installed_cold_test_pending')

    def test_lut_write_publishes_profile_binding_without_separate_verify(self):
        result=dict(phase='AWAITING_RELOAD',mode='install_all',job_id='test-profile-write',
            raw_profile_effective_since='2026-10-21T12:00:00',bundle_options=dict(looks=[],reset_slots=[2]))
        obj=Mock();obj.root=self.root/'direct';obj.state_path=obj.root/'direct.private.json';obj.state=dict(result)
        obj.run_direct.return_value=result
        with patch('looktool.direct.DirectJob',return_value=obj), \
             patch('looktool.rawidentity.activated',return_value=dict(status='published')) as publish:
            answer=worker.run('direct_looks_import',dict(workspace=str(obj.root),firmware='2.01',
                power_confirmed=True,operations=[dict(slot=2,action='restore')]),self.root)
        self.assertEqual(answer['phase'],'COMPLETED')
        self.assertEqual(publish.call_args.args[1],[2])
        obj.verify_direct.assert_not_called()


if __name__ == '__main__':
    unittest.main()
