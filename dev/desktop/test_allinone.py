"""One-click ordering and interruption boundaries; no devices or drivers."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import pytest
from desktopapp import allinone


class AllInOneTests(unittest.TestCase):
    def test_native_portrait_migration_waits_before_lut_install_then_continues(self):
        def migrating(action,args,folder):
            if action=='vertical_enable' and not self.booted:
                self.calls.append((action,args))
                return dict(phase='AWAITING_RELOAD',migration_pending=True,mode='vertical_native_prepare')
            return self.dispatch(action,args,folder)
        result=allinone.run(self.args,dispatch=migrating)
        self.assertEqual(result['phase'],'PREPARING_VERTICAL')
        self.assertTrue(result['reload_required'])
        self.assertNotIn('direct_install_all',[a for a,_ in self.calls])
        self.booted=True
        result=allinone.run(self.args,dispatch=migrating)
        self.assertEqual(result['phase'],'WAIT_RELOAD')
        self.assertEqual([a for a,_ in self.calls].count('direct_install_all'),1)

    def test_plugin_failure_retries_host_step_without_opening_camera(self):
        root=self.root/'host-only';install=root/'install';install.mkdir(parents=True)
        (install/'direct.private.json').write_text(json.dumps(dict(phase='LOADED',bundle_options=dict(looks=[]))))
        state=dict(schema='a7c2-one-click/1',phase='FINALIZING',workspace=str(root),
            options=dict(plugin=True,sound=True,vertical=False,looks=[]),
            completed_steps=['drivers','persistent_features','sound'],install_workspace=str(install),
            verify_result=dict(phase='LOADED',workspace=str(install)))
        (root/'setup.private.json').write_text(json.dumps(state))
        calls=[]
        def dispatch(action,args,folder):
            calls.append(action);self.assertEqual(action,'plugin_install')
            if len(calls)==1:raise PermissionError('locked ExifTool')
            return dict(plugin='installed')
        arguments=dict(self.args,workspace=str(root))
        with self.assertRaises(PermissionError):allinone.run(arguments,dispatch=dispatch)
        failed=json.loads((root/'setup.private.json').read_text())
        self.assertEqual(failed['phase'],'FINALIZING')
        self.assertEqual(allinone.run(arguments,dispatch=dispatch)['phase'],'COMPLETE')
        self.assertEqual(calls,['plugin_install','plugin_install'])

    def test_legacy_plugin_failure_uses_saved_loaded_proof_without_camera_recheck(self):
        root=self.root/'legacy-host';install=root/'install';install.mkdir(parents=True)
        (install/'direct.private.json').write_text(json.dumps(dict(phase='LOADED',bundle_options=dict(looks=[]))))
        state=dict(schema='a7c2-one-click/1',phase='NEEDS_REVIEW',workspace=str(root),
            options=dict(plugin=True,sound=True,vertical=False,looks=[]),
            completed_steps=['drivers','persistent_features','sound'],install_workspace=str(install),
            verify_result=dict(phase='LOADED',workspace=str(install)),error='Permission denied: exiftool.exe')
        (root/'setup.private.json').write_text(json.dumps(state))
        calls=[]
        def dispatch(action,args,folder):
            calls.append(action);self.assertEqual(action,'plugin_install');return dict(plugin='installed')
        result=allinone.run(dict(self.args,workspace=str(root)),dispatch=dispatch)
        self.assertEqual(result['phase'],'COMPLETE')
        self.assertEqual(calls,['plugin_install'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        env = patch.dict(os.environ, {'A7C2_DESKTOP_DATA': str(self.root / 'app')})
        env.start(); self.addCleanup(env.stop)
        self.args = dict(workspace=str(self.root / 'setup'), firmware='2.01', power_confirmed=True,
            options=dict(fl23=True, sound=True, vertical=True, plugin=False, looks=[]))
        self.calls = []
        self.booted = False

    def dispatch(self, action, args, folder):
        self.calls.append((action, args))
        vertical=dict(persistent=True, loaded_verified=True, running='ON', saved='ON', alias_count=3)
        if action == 'direct_install_all':
            return dict(phase='AWAITING_RELOAD', mode='install_all', workspace=args['workspace'], vertical_result=vertical)
        if action == 'vertical_enable':
            return dict(phase='AWAITING_RELOAD',mode='vertical_enable',workspace=args['workspace'])
        if action == 'direct_verify':
            if not self.booted:raise ValueError('尚未确认新的冷启动。不要重复写入。')
            return dict(phase='LOADED', mode='install_all', workspace=args['workspace'], vertical_result=vertical)
        return {'ok': True}

    def test_one_write_then_wait_then_verify_then_vertical(self):
        state = allinone.run(self.args, dispatch=self.dispatch)
        self.assertEqual(state['phase'], 'WAIT_RELOAD')
        self.assertEqual([a for a, _ in self.calls], ['usb_prepare', 'vertical_enable', 'direct_install_all'])
        self.assertTrue(self.calls[1][1]['power_confirmed'])
        state = allinone.run(self.args, dispatch=self.dispatch)
        self.assertEqual(state['phase'], 'WAIT_RELOAD')
        self.assertEqual(self.calls[-1][0], 'direct_verify')
        self.booted = True
        state = allinone.run(self.args, dispatch=self.dispatch)
        self.assertEqual(state['phase'], 'COMPLETE')
        self.assertEqual([a for a, _ in self.calls].count('direct_install_all'), 1)
        self.assertEqual([a for a,_ in self.calls][-2:], ['direct_verify','sound_on'])
        self.assertTrue(self.calls[2][1]['options']['vertical_persistent'])
        self.assertEqual([a for a,_ in self.calls].count('vertical_enable'),1)
        self.assertFalse(state['physical_checks_accepted'])
        before = list(self.calls)
        allinone.run(self.args, dispatch=self.dispatch)
        self.assertEqual(before, self.calls)

    def test_native_timeout_does_not_repeat_install_on_next_click(self):
        def fail(action, args, folder):
            result = self.dispatch(action, args, folder)
            if action == 'direct_install_all':raise TimeoutError('ambiguous native result')
            return result
        with self.assertRaises(TimeoutError):allinone.run(self.args, dispatch=fail)
        before = list(self.calls)
        with self.assertRaisesRegex(ValueError, '不会重复刷写'):
            allinone.run(self.args, dispatch=self.dispatch)
        self.assertEqual(before, self.calls)

    def test_accounted_preprogram_failure_gets_new_child_not_old_job_replay(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);path=root/'setup.private.json'
        state=json.loads(path.read_text());state['phase']='NEEDS_REVIEW';path.write_text(json.dumps(state))
        old=root/'install';old.mkdir();(old/'direct.private.json').write_text('{"phase":"NEEDS_REVIEW"}')
        before=(old/'direct.private.json').read_bytes()
        def dispatch(action,args,folder):
            if action=='review_failed_names':
                self.calls.append((action,args));return dict(pre_program_failure_accounted=True)
            return self.dispatch(action,args,folder)
        with patch('desktopapp.reviewnames.source',return_value=(old,{},b'known report')):
            result=allinone.run(self.args,dispatch=dispatch)
        self.assertEqual(result['phase'],'WAIT_RELOAD')
        self.assertEqual([a for a,_ in self.calls].count('usb_prepare'),1)
        self.assertEqual([a for a,_ in self.calls][-2:],['review_failed_names','direct_install_all'])
        self.assertNotEqual(self.calls[-1][1]['workspace'],str(old))
        self.assertEqual(result['failed_install_workspaces'],[str(old)])
        self.assertEqual((old/'direct.private.json').read_bytes(),before)

    def test_completed_child_survives_parent_interruption_without_replay(self):
        allinone.run(self.args, dispatch=self.dispatch)
        root = Path(self.args['workspace'])
        child = root / 'install/direct.private.json'; child.parent.mkdir()
        child.write_text('{"phase":"AWAITING_RELOAD"}')
        path = root / 'setup.private.json'
        state = json.loads(path.read_text()); state['phase'] = 'INSTALLING'; path.write_text(json.dumps(state))
        before = [a for a, _ in self.calls].count('direct_install_all')
        self.booted = True
        state = allinone.run(self.args, dispatch=self.dispatch)
        self.assertEqual(state['phase'], 'COMPLETE')
        self.assertEqual([a for a, _ in self.calls].count('direct_install_all'), before)

    def test_loaded_child_after_parent_interruption_recovers_vertical_proof_without_rewrite(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);child=root/'install/direct.private.json'
        child.parent.mkdir();child.write_text('{"phase":"LOADED"}')
        path=root/'setup.private.json';state=json.loads(path.read_text())
        state.update(phase='INSTALLING');state.pop('install_result',None)
        path.write_text(json.dumps(state))
        self.booted=True;before=len(self.calls)
        result=allinone.run(self.args,dispatch=self.dispatch)
        self.assertEqual(result['phase'],'COMPLETE')
        self.assertEqual([a for a,_ in self.calls[before:]],['direct_verify','sound_on'])
        self.assertTrue(result['vertical_result']['loaded_verified'])
        self.assertEqual(result['completed_steps'].count('persistent_features'),1)

    def test_unstarted_resource_dispatch_continues_from_original_source(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);path=root/'setup.private.json'
        state=json.loads(path.read_text())
        previous=root/'resource-checkpoint';previous.mkdir()
        (previous/'direct.private.json').write_text('{"phase":"AWAITING_RESOURCE_RELOAD"}')
        state.update(phase='RESUMING_RESOURCES',install_workspace=str(root/'never-started'),
            resume_resource_from=str(previous))
        path.write_text(json.dumps(state));before=len(self.calls)
        def dispatch(action,args,folder):
            self.calls.append((action,args))
            self.assertEqual(action,'direct_resume_looks')
            self.assertEqual(args['failed_workspace'],str(previous))
            return dict(phase='AWAITING_RESOURCE_RELOAD',workspace=str(previous))
        result=allinone.run(self.args,dispatch=dispatch)
        self.assertEqual(result['phase'],'WAIT_RESOURCE_RELOAD')
        self.assertEqual([a for a,_ in self.calls[before:]],['direct_resume_looks'])

    def test_nested_program_child_is_verified_after_resource_parent_interruption(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);candidate=root/'resource-child'
        candidate.mkdir();(candidate/'direct.private.json').write_text('{"phase":"RESOURCE_RELOAD_VERIFIED"}')
        nested=candidate/'program-install';nested.mkdir()
        (nested/'direct.private.json').write_text('{"phase":"AWAITING_RELOAD"}')
        path=root/'setup.private.json';state=json.loads(path.read_text())
        state.update(phase='RESUMING_RESOURCES',install_workspace=str(candidate),resume_resource_from=str(root/'install'))
        path.write_text(json.dumps(state));before=len(self.calls);self.booted=True
        result=allinone.run(self.args,dispatch=self.dispatch)
        self.assertEqual(result['phase'],'COMPLETE')
        self.assertEqual(self.calls[before][0],'direct_verify')
        self.assertEqual(self.calls[before][1]['workspace'],str(nested))
        self.assertNotIn('direct_install_all',[a for a,_ in self.calls[before:]])

    def test_nonempty_unrecorded_resource_child_stays_stopped(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);candidate=root/'unknown-child';candidate.mkdir()
        (candidate/'unexpected.bin').write_bytes(b'unknown')
        path=root/'setup.private.json';state=json.loads(path.read_text())
        state.update(phase='RESUMING_RESOURCES',install_workspace=str(candidate),resume_resource_from=str(root/'install'))
        path.write_text(json.dumps(state));before=list(self.calls)
        with self.assertRaisesRegex(ValueError,'不会重复刷写'):
            allinone.run(self.args,dispatch=self.dispatch)
        self.assertEqual(self.calls,before)

    def test_bad_inputs_fail_before_any_driver_or_device_call(self):
        for options in (dict(looks=[dict(slot=7, path='missing.a7look')]),
                        dict(looks=[dict(slot=1, path='missing.a7look')])):
            with self.subTest(options=options), self.assertRaises((ValueError, FileNotFoundError)):
                allinone.run(dict(self.args, options=options), dispatch=self.dispatch)
            self.assertEqual(self.calls, [])

    def test_new_install_does_not_inspect_historical_factory_verification(self):
        result=allinone.run(self.args,dispatch=self.dispatch)
        self.assertEqual(result['phase'],'WAIT_RELOAD')
        self.assertEqual([a for a,_ in self.calls],['usb_prepare','vertical_enable','direct_install_all'])

    def test_saved_configuration_is_not_replaced_mid_install(self):
        allinone.run(self.args, dispatch=self.dispatch)
        changed = dict(self.args, options=dict(vertical=False, fl23=False, sound=False))
        self.booted = True
        state = allinone.run(changed, dispatch=self.dispatch)
        self.assertTrue(state['options']['fl23'])
        self.assertTrue(state['options']['vertical'])
        self.assertEqual([a for a,_ in self.calls][-2:], ['direct_verify','sound_on'])

    def test_persistent_vertical_requires_actual_loaded_proof_not_session_fallback(self):
        allinone.run(self.args, dispatch=self.dispatch)
        self.booted=True
        def no_proof(action,args,folder):
            result=self.dispatch(action,args,folder)
            if action=='direct_verify':result.pop('vertical_result')
            return result
        with self.assertRaisesRegex(ValueError,'持久化加载尚未确认'):
            allinone.run(self.args,dispatch=no_proof)
        self.assertEqual([a for a,_ in self.calls].count('vertical_enable'),1)

    def test_resource_busy_pause_then_continue_does_not_rewrite_names_or_drivers(self):
        resource_boot=False
        def dispatch(action,args,folder):
            if action=='direct_install_all':
                self.calls.append((action,args))
                return dict(phase='AWAITING_RESOURCE_RELOAD',workspace=args['workspace'])
            if action=='direct_resume_looks':
                self.calls.append((action,args))
                return dict(phase='AWAITING_RELOAD' if resource_boot else 'AWAITING_RESOURCE_RELOAD',
                    workspace=args['workspace'] if resource_boot else args['failed_workspace'])
            return self.dispatch(action,args,folder)
        self.assertEqual(allinone.run(self.args,dispatch=dispatch)['phase'],'WAIT_RESOURCE_RELOAD')
        self.assertEqual(allinone.run(self.args,dispatch=dispatch)['phase'],'WAIT_RESOURCE_RELOAD')
        resource_boot=True
        self.assertEqual(allinone.run(self.args,dispatch=dispatch)['phase'],'WAIT_RELOAD')
        self.assertEqual(allinone.run(self.args,dispatch=dispatch)['phase'],'WAIT_RELOAD')
        self.booted=True
        self.assertEqual(allinone.run(self.args,dispatch=dispatch)['phase'],'COMPLETE')
        self.assertEqual([a for a,_ in self.calls].count('usb_prepare'),1)
        self.assertEqual([a for a,_ in self.calls].count('direct_install_all'),1)
        self.assertEqual([a for a,_ in self.calls][-2:], ['direct_verify','sound_on'])

    def test_recorded_v7_busy_goes_to_name_reload_instead_of_replaying_install(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);path=root/'setup.private.json'
        state=json.loads(path.read_text());state['phase']='NEEDS_REVIEW';path.write_text(json.dumps(state))
        old=root/'install';old.mkdir();p=old/'direct.private.json';p.write_text('{"phase":"NEEDS_REVIEW"}')
        before=p.read_bytes()
        def dispatch(action,args,folder):
            self.calls.append((action,args))
            self.assertEqual(action,'direct_resume_looks')
            return dict(phase='AWAITING_RESOURCE_RELOAD',workspace=args['workspace'])
        with patch('desktopapp.reviewnames.source',side_effect=ValueError('committed')), \
             patch('looktool.namespause.source',return_value=(old,{},b'known completed report')):
            result=allinone.run(self.args,dispatch=dispatch)
        self.assertEqual(result['phase'],'WAIT_RESOURCE_RELOAD')
        self.assertEqual([a for a,_ in self.calls].count('direct_install_all'),1)
        self.assertEqual(p.read_bytes(),before)

    def test_already_target_noop_does_not_request_an_unnecessary_cold_boot(self):
        def noop(action, args, folder):
            result = self.dispatch(action, args, folder)
            return dict(result, phase='LOADED') if action == 'direct_install_all' else result
        result = allinone.run(self.args, dispatch=noop)
        self.assertEqual(result['phase'], 'COMPLETE')
        self.assertNotIn('direct_verify', [a for a, _ in self.calls])

    def test_driver_failure_rechecks_connection_without_reinstalling_driver(self):
        def fail(action, args, folder):
            self.calls.append((action, args))
            raise RuntimeError('Driver setup not completed')
        with self.assertRaises(RuntimeError):allinone.run(self.args, dispatch=fail)
        result = allinone.run(self.args, dispatch=self.dispatch)
        self.assertEqual(result['phase'], 'WAIT_RELOAD')
        self.assertEqual([a for a, _ in self.calls].count('usb_prepare'), 1)
        self.assertIn('connect', [a for a, _ in self.calls])

    def test_fixed_tool_replans_a_prewrite_window_conflict_without_reinstalling_drivers(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);path=root/'setup.private.json'
        state=json.loads(path.read_text());state.update(phase='NEEDS_REVIEW',completed_steps=['drivers'])
        path.write_text(json.dumps(state))
        old=root/'install';old.mkdir()
        child=old/'direct.private.json'
        child.write_text(json.dumps(dict(schema='a7c2-direct-job/1',mode='install_all',
            phase='NEEDS_REVIEW',failed_during='READING',journal=[],error='cpapp-b.bin 0x138832')))
        before=child.read_bytes();count=len(self.calls)
        result=allinone.run(self.args,dispatch=self.dispatch)
        self.assertEqual(result['phase'],'WAIT_RELOAD')
        self.assertEqual([a for a,_ in self.calls[count:]],['direct_install_all'])
        self.assertNotEqual(self.calls[-1][1]['workspace'],str(old))
        self.assertEqual(child.read_bytes(),before)
        self.assertIn(str(old),result['failed_install_workspaces'])

    def test_unknown_native_execution_cannot_be_replanned_as_an_initial_conflict(self):
        allinone.run(self.args,dispatch=self.dispatch)
        root=Path(self.args['workspace']);path=root/'setup.private.json'
        state=json.loads(path.read_text());state['phase']='NEEDS_REVIEW';path.write_text(json.dumps(state))
        old=root/'install';old.mkdir()
        (old/'direct.private.json').write_text(json.dumps(dict(schema='a7c2-direct-job/1',mode='install_all',
            phase='NEEDS_REVIEW',failed_during='WRITING',journal=[dict(event='native_intent',mode=1)])))
        count=len(self.calls)
        with self.assertRaises(ValueError):allinone.run(self.args,dispatch=self.dispatch)
        self.assertEqual(len(self.calls),count)


def test_missing_exiftool_is_prepared_before_first_device_call(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    tool=tmp_path/'prepared-exiftool.exe';tool.write_bytes(b'helper')
    calls=[]
    def dispatch(action,args,folder):
        calls.append(action)
        if action=='vertical_enable':return dict(phase='AWAITING_RELOAD',workspace=args['workspace'])
        if action=='direct_install_all':
            assert args['options']['exiftool']==str(tool)
            return dict(phase='AWAITING_RELOAD',mode='install_all',workspace=args['workspace'])
        return {}
    args=dict(workspace=str(tmp_path/'work'),firmware='2.01',power_confirmed=True,
              options=dict(plugin=True,exiftool='old-computer/missing.exe',looks=[]))
    with patch('desktopapp.exiftool.ensure',return_value=str(tool)) as prepare:
        result=allinone.run(args,dispatch=dispatch)
    prepare.assert_called_once_with('old-computer/missing.exe')
    assert result['phase']=='WAIT_RELOAD'
    assert calls==['usb_prepare','vertical_enable','direct_install_all']


def test_helper_download_failure_does_not_open_camera(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    dispatch=Mock()
    with patch('desktopapp.exiftool.ensure',side_effect=RuntimeError('mirror connection failed')):
        import pytest
        with pytest.raises(RuntimeError,match='mirror connection failed'):
            allinone.run(dict(workspace=str(tmp_path/'work'),firmware='2.01',power_confirmed=True,
                options=dict(plugin=True,looks=[])),dispatch=dispatch)
    dispatch.assert_not_called()


@pytest.mark.parametrize('phase',['NEEDS_REVIEW','RESOURCE_RELOAD_VERIFIED','READING'])
def test_unfinished_program_result_never_finishes_setup(tmp_path,phase):
    args=dict(workspace=str(tmp_path/'setup'),firmware='2.01',power_confirmed=True,
              options=dict(sound=False,vertical=False,plugin=False,looks=[]))
    def dispatch(action,values,folder):
        return dict(phase=phase,workspace=values.get('workspace',''))
    with pytest.raises(ValueError,match='程序安装尚未完成'):
        allinone.run(args,dispatch=dispatch)
    state=json.loads((tmp_path/'setup/setup.private.json').read_text())
    assert state['phase']=='NEEDS_REVIEW'
    assert 'persistent_features' not in state['completed_steps']


@pytest.mark.parametrize('phase',['AWAITING_RELOAD','AWAITING_RESOURCE_RELOAD','NEEDS_REVIEW'])
def test_unfinished_verify_result_does_not_run_finalizers(tmp_path,phase):
    root=tmp_path/'setup';root.mkdir()
    state=dict(schema='a7c2-one-click/1',phase='WAIT_RELOAD',workspace=str(root),
               options=dict(sound=True,vertical=False,plugin=True,looks=[]),
               completed_steps=['drivers','persistent_features'])
    (root/'setup.private.json').write_text(json.dumps(state))
    calls=[]
    def dispatch(action,values,folder):
        calls.append(action)
        return dict(phase=phase,workspace=str(root/'install'))
    with pytest.raises(ValueError,match='重启后核对尚未完成'):
        allinone.run(dict(workspace=str(root),firmware='2.01',power_confirmed=True),dispatch=dispatch)
    saved=json.loads((root/'setup.private.json').read_text())
    assert saved['phase']=='WAIT_RELOAD' and calls==['direct_verify']


def test_plugin_activation_includes_st_reset_slots(tmp_path):
    root=tmp_path/'setup';install=root/'install';install.mkdir(parents=True)
    child=dict(bundle_options=dict(looks=[],reset_slots=[4]),job_id='current-mixed-install',
               raw_profile_effective_since='2026-10-24T12:00:00')
    (install/'direct.private.json').write_text(json.dumps(child))
    state=dict(schema='a7c2-one-click/1',phase='FINALIZING',workspace=str(root),
               options=dict(plugin=True,sound=False,vertical=False,looks=[]),
               completed_steps=['drivers','persistent_features'],install_workspace=str(install))
    (root/'setup.private.json').write_text(json.dumps(state))
    with patch('looktool.rawidentity.activated',return_value=dict(status='published')) as activated:
        result=allinone.run(dict(workspace=str(root),firmware='2.01',power_confirmed=True),
            dispatch=lambda *args:dict(plugin='installed'))
    assert result['phase']=='COMPLETE'
    activated.assert_called_once_with([dict(name='ST',raw_profile=None)],[4],
        'current-mixed-install','2026-10-24T12:00:00')
