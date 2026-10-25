"""One job per child process. Full tracebacks stay in the GUI's private log."""
import contextlib
import json
import os
from pathlib import Path
import sys
import traceback
import uuid
from .paths import ROOT, data_root, write_json


def setup_runtime():
    sys.path[:0] = [str(ROOT / 'src/looks'), str(ROOT / 'src/camera_runtime'),
                   str(ROOT / 'src/fl23/vendor')]
    os.environ['A7C2_VERBOSE_ERRORS'] = '1'
    os.environ.setdefault('A7LOOK_AUTO_SETTINGS', str(data_root() / 'raw-profiles/settings.json'))
    if getattr(sys, 'frozen', False):
        os.environ['A7C2_DESKTOP_EXECUTABLE'] = sys.executable


def run(action, args, job):
    setup_runtime()
    if action=='voice_restore':raise ValueError('请在“一键恢复原厂功能”中勾选恢复语音包；不再提供独立语音恢复入口。')
    from .jobs import POWER_ACTIONS
    if action in POWER_ACTIONS:
        from looktool.power import require_power
        require_power(args.get('battery'), confirmed=args.get('power_confirmed', False))
    if action=='mac_authorization_self_test':
        if sys.platform!='darwin' or os.geteuid()!=0:raise RuntimeError('Self-test requires an authorized Mac worker')
        write_json(data_root()/'authorization-self-test.private.json',dict(euid=os.geteuid(),camera_io=False))
        return dict(euid=os.geteuid(),home=str(Path.home()),data_root=str(data_root()),camera_io=False)
    if action == 'factory_prepare':
        from . import official
        return official.prepare(args['source'])
    if action == 'setup_all':
        from . import allinone
        return allinone.run(args, dispatch=run)
    if action=='voice_cleanup':
        from .voicespace import run as voice_space
        work=Path(args['workspace'])/('request-'+uuid.uuid4().hex[:8])
        write_json(Path(job)/'backend-workspace.private.json',dict(action=action,workspace=str(work/'disable')))
        return voice_space(action,dict(args,workspace=str(work)),job)
    if action == 'review_failed_names':
        from . import reviewnames
        return reviewnames.run(args['workspace'],job)
    if action in ('vertical_enable','vertical_disable') and not args.get('session_only'):
        from .platforms import usb_drivers
        from looktool.portraitjob import PortraitJob
        print('准备竖屏显示的 USB 驱动与服务连接。',flush=True)
        if not args.get('drivers_prepared'):usb_drivers.prepare(job)
        work=Path(args['workspace'])/('frames-'+uuid.uuid4().hex[:8])
        if action=='vertical_enable':
            from .vertical_native import run as native_vertical
            return native_vertical(dict(args,workspace=str(work)),job)
        write_json(Path(job)/'backend-workspace.private.json',dict(action=action,workspace=str(work)))
        values=dict(version=args['firmware'],power_confirmed=args.get('power_confirmed',False))
        if args.get('combined'):values['combined']=True
        return PortraitJob(work).run_frames(action=='vertical_enable',**values)
    if action in ('sound_on','sound_off','sound_restore_sound','sound_mechanical_on','sound_mechanical_off'):
        mode={'sound_on':'sound_enable','sound_off':'sound_disable','sound_restore_sound':'sound_reset',
              'sound_mechanical_on':'sound_mechanical_enable','sound_mechanical_off':'sound_mechanical_disable'}[action]
        result=run('direct_'+mode,dict(args,workspace=str(Path(args['workspace'])/('switch-'+uuid.uuid4().hex[:8]))),job)
        result['command']={'sound_on':'on','sound_off':'off','sound_restore_sound':'restore-sound',
                           'sound_mechanical_on':'mechanical-on','sound_mechanical_off':'mechanical-off'}[action]
        if action=='sound_restore_sound':
            # A RAM audition also clears on cold power-off when disk was
            # already stock; no previous installation record is needed.
            result.update(phase='restored_cold_test_pending',reload_required=True,verification_required=True,
                restoration_complete=False)
        elif result['phase']=='AWAITING_RELOAD':
            result.update(phase='written' if action in ('sound_on','sound_mechanical_on') else 'restored',reload_required=True)
        return result
    if action=='sound_verify':
        from .actions.sound_state import verify
        return verify(args,job)
    if action.startswith('direct_'):
        from looktool.direct import DirectJob
        mode = action.removeprefix('direct_')
        if mode == 'looks_import':
            from . import lookbatch
            args = dict(args, options=lookbatch.options(args.get('operations',args.get('looks', []))))
            mode = 'install_all'
        if not args.get('workspace'):
            raise ValueError('先完成一次本页操作，再核对重新加载状态。')
        obj = DirectJob(Path(args['workspace']))
        reference, reference_path = None, args.get('factory')
        voice_source=None
        if mode in ('factory_reset','resume_factory'):
            from .official import prepare_restore
            reference,reference_path,voice_source=prepare_restore(args)
        if mode=='resume_settings':
            result=obj.resume_install_settings(args['failed_workspace'],power_confirmed=args.get('power_confirmed',False))
        elif mode=='resume_looks':
            prior_root=Path(args['failed_workspace'])
            prior=DirectJob(prior_root)
            saved=json.loads(prior.state_path.read_text(encoding='utf-8'))
            if saved['phase']=='NEEDS_REVIEW':
                result=obj.prepare_names_reload(prior_root,power_confirmed=args.get('power_confirmed',False))
                if result['phase']=='RESOURCE_RELOAD_VERIFIED':
                    prior_root=obj.root
                    obj=DirectJob(prior_root/'program-install')
            else:
                result=prior.verify_names_reload()
                if result['phase']!='RESOURCE_RELOAD_VERIFIED':
                    obj=prior
            if result['phase']=='RESOURCE_RELOAD_VERIFIED':
                result=obj.run_direct(result['mode'],version=args['firmware'],power_confirmed=args.get('power_confirmed',False),
                    bundle_options=result.get('bundle_options'),slot=result.get('slot'),name=result.get('name'),
                    look_path=str(prior_root/'reference.a7look') if result['mode']=='look_import' else None)
        elif mode == 'verify':
            prior = json.loads(obj.state_path.read_text(encoding='utf-8'))
            if prior['mode'] == 'factory_reset':
                from .official import load_restore
                if prior.get('factory_path') in (None,'builtin'):
                    from .official import prepare_restore
                    reference,reference_path,_=prepare_restore(args)
                    obj.state=prior;obj.save(prior['phase'],factory_path=reference_path)
                else:reference = load_restore(prior['factory_path'])
            if prior.get('phase') in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED'):
                result=obj.verify_names_reload()
            else:
                result = obj.verify_direct(factory_values=reference, accepted=bool(args.get('accepted')))
        elif mode == 'resume_factory':
            # This button starts a fresh built-in reset. Historical jobs are
            # optional provenance, never a prerequisite or a source of targets.
            result = obj.run_direct('factory_reset', version=args['firmware'],
                power_confirmed=args.get('power_confirmed', False), factory_values=reference,
                factory_path=reference_path, recovery_source=args.get('failed_workspace'),voice_source=voice_source,
                restore_voice=args.get('restore_voice',True))
        else:
            result = obj.run_direct(mode, version=args['firmware'], power_confirmed=args.get('power_confirmed', False),
                factory_values=reference, factory_path=reference_path if mode == 'factory_reset' else None,
                slot=args.get('slot'), look_path=args.get('look'), name=args.get('name') or None,
                bundle_options=args.get('options'),voice_source=voice_source,restore_voice=args.get('restore_voice',True))
        response = {'workspace': str(obj.root), 'phase': result['phase'], 'mode': result['mode'],
                    'backup_created': False}
        if result['mode']=='factory_reset':
            complete=result['phase'] in ('LOADED','COMPLETE') and result.get('private_sound_files_removed') is True
            response.update(recovery_complete=complete,verification_required=not complete,
                            private_sound_files_removed=result.get('private_sound_files_removed',False),
                            restore_voice=result.get('restore_voice',True))
        if result.get('vertical_result'):response['vertical_result']=result['vertical_result']
        if mode in ('fl23_enable', 'fl23_disable') and result['phase'] == 'AWAITING_RELOAD':
            # The device write is finished. Keep reload evidence internally,
            # without presenting standalone FL23 as a paused installation.
            response.update(phase='COMPLETED', reload_required=True, verification_optional=True)
        if action == 'direct_looks_import':
            response['slots'] = [r['slot'] for r in args['options']['slot_operations']]
            response['operations']=args['options']['slot_operations']
            if result['phase'] == 'AWAITING_RELOAD':
                response.update(phase='COMPLETED', reload_required=True)
        if (action in ('direct_looks_import','direct_resume_looks') and
                result['phase'] in ('AWAITING_RELOAD','LOADED','COMPLETE') and
                result.get('raw_profile_effective_since') and result.get('job_id')):
            # Publish computer-side profile mapping after the same write/readback
            # operation; no separate user verification click is required.
            from looktool import bundle,rawidentity
            try:
                opts,rows=bundle.documents(result.get('bundle_options',{}))
                docs=[dict(r['document'],name=r['name']) for r in rows]
                slots=[r['slot'] for r in rows]
                slots+=opts.get('reset_slots',[])
                docs += [dict(name='ST',raw_profile=None) for _ in opts.get('reset_slots',[])]
                sync=rawidentity.activated(docs,slots,result['job_id'],result['raw_profile_effective_since'])
            except (OSError,ValueError,KeyError) as exc:
                sync=dict(status='profile_sync_failed',error=str(exc))
            obj.state['raw_profile_sync']=sync;write_json(obj.state_path,obj.state)
            response['raw_profile_sync']=sync
        return response
    if action in ('driver_scan', 'driver_install', 'driver_uninstall', 'usb_prepare', 'mac_unmount'):
        from .platforms import usb_drivers as drivers
        if action == 'driver_scan':
            result = drivers.scan()
            write_json(job / 'driver-report.private.json', result)
            return result
        if action == 'driver_install':
            return drivers.install(args, job)
        if action == 'driver_uninstall':
            return drivers.uninstall(args, job)
        if action == 'usb_prepare':
            return drivers.prepare(job)
        return drivers.unmount_camera_volume(args['volume'])
    if action == 'connect':
        from looktool.devicesession import Camera
        with Camera() as camera:
            return {'model': camera.identity['model'], 'service_connected': True,
                    'firmware_programs_written': False}
    if action=='usb_stability':
        from .usbcheck import run as check_usb
        return check_usb(job)
    if action == 'backup_inspect':
        from looktool import checkpoint
        manifest, target = checkpoint.load_target(args['backup'])
        return {'model': manifest['model'], 'firmware': manifest['version'],
                'files': len(target), 'legacy_backup': manifest.get('legacy_raw', False),
                'limitations': manifest.get('limitations', []), 'camera_io': False}
    if action == 'backup_current':
        from .backup import run as backup_current
        return backup_current(args,job)
    if action == 'restore_auto':
        from .recovery import restore_auto
        return restore_auto(args, job)
    if action in ('restore', 'restore_verify'):
        from looktool.checkpointjob import Rollback
        obj = Rollback(Path(args['workspace']))
        if action == 'restore_verify' and not obj.state_path.is_file():
            raise ValueError('所选目录没有旧备份恢复记录，本次没有连接相机。用内置原厂基准或固件文件恢复后，'
                             '请点“重启后核对并完成恢复”。')
        if action == 'restore':
            from .screenreader import restore_source
            voice_source=restore_source(args)
            voice_options=dict(voice_source=voice_source) if voice_source else {}
            result = obj.run(args['backup'], args.get('battery'), args['firmware'],
                             power_confirmed=args.get('power_confirmed', False),**voice_options)
        else:
            result = obj.verify(accept_photos=bool(args.get('accepted')))
        return {'workspace': str(obj.root), 'phase': result.get('phase')}
    if action == 'compile_look':
        from .actions.look_compiler import run as compile_look
        return compile_look(args)
    if action == 'plugin_install':
        from .plugins import install
        return install(args)
    if action.startswith('vertical_'):
        sys.path.insert(0, str(ROOT / 'src/vertical'))
        from verticaltool.device import execute
        command = 'remove' if action == 'vertical_disable' else action.removeprefix('vertical_')
        return execute(command, Path(args['workspace']))
    if action.startswith('sound_'):
        from .actions.sound import run as sound
        return sound(action,args)
    raise ValueError('Unknown desktop action: ' + action)


def execute_request(path):
    request = json.loads(Path(path).read_text(encoding='utf-8'))
    from .platforms import macos_authorization as macadmin
    if macadmin.required(request['action']):return macadmin.execute(path)
    job = Path(request['job_dir'])
    status = job / 'status.private.json'
    if sys.platform=='darwin':
        write_json(job/'privilege.private.json',dict(uid=os.getuid(),euid=os.geteuid(),camera_io=False))
    write_json(status, {'phase': 'RUNNING', 'action': request['action'], 'pid': os.getpid()})
    with (job / 'worker.log').open('a', encoding='utf-8', buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            print('Action:', request['action'], flush=True)
            try:
                result = run(request['action'], request['arguments'], job)
                write_json(job / 'result.private.json', result)
                display=result
                if request['action']=='setup_all':
                    from .completion import console_summary
                    display=console_summary(result)
                print(json.dumps(display, ensure_ascii=False, indent=2, default=str), flush=True)
                write_json(status, {'phase': 'SUCCEEDED', 'action': request['action'], 'result': result})
                return 0
            except BaseException as exc:
                traceback.print_exc()
                write_json(status, {'phase': 'FAILED', 'action': request['action'],
                                    'error_type': type(exc).__name__, 'error': str(exc),
                                    'log': str(job / 'worker.log')})
                return 2
