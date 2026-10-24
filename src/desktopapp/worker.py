"""One job per child process. Full tracebacks stay in the GUI's private log."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback
import uuid
from .paths import ROOT, data_root, write_json


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def setup_runtime():
    sys.path[:0] = [str(ROOT / 'src/looks'), str(ROOT / 'src/camera_runtime'),
                   str(ROOT / 'src/camera_runtime/vendor')]
    os.environ['A7C2_VERBOSE_ERRORS'] = '1'
    os.environ.setdefault('A7LOOK_AUTO_SETTINGS', str(data_root() / 'raw-profiles/settings.json'))
    if getattr(sys, 'frozen', False):
        os.environ['A7C2_DESKTOP_EXECUTABLE'] = sys.executable


def register_backup(path):
    # Backup indexing is a convenience. If its disk is full, preserve the
    # successfully completed camera job and show the indexing error separately.
    try:
        from .recovery import register
        register(path)
    except Exception:
        print('Backup completed, but automatic recovery indexing failed. Select the backup manually.', flush=True)
        traceback.print_exc()


def run(action, args, job):
    setup_runtime()
    from .jobs import POWER_ACTIONS
    if action in POWER_ACTIONS:
        from looktool.power import require_power
        power = require_power(args.get('battery'), confirmed=args.get('power_confirmed', False))
        write_json(job / 'power-confirmation.private.json', power)
        print('Power:', json.dumps(power), flush=True)
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
    if action == 'review_failed_names':
        from . import reviewnames
        return reviewnames.run(args['workspace'],job)
    if action in ('vertical_enable','vertical_disable') and not args.get('session_only'):
        from .platforms import usb_drivers
        from looktool.portraitjob import PortraitJob
        print('准备本次线框测试的 USB 驱动与服务连接。',flush=True)
        if not args.get('drivers_prepared'):usb_drivers.prepare(job)
        work=Path(args['workspace'])/('frames-'+uuid.uuid4().hex[:8])
        write_json(Path(job)/'backend-workspace.private.json',dict(action=action,workspace=str(work)))
        values=dict(version=args['firmware'],power_confirmed=args.get('power_confirmed',False))
        if args.get('combined'):values['combined']=True
        return PortraitJob(work).run_frames(action=='vertical_enable',**values)
    if action in ('sound_on','sound_off','sound_restore_sound'):
        mode={'sound_on':'sound_enable','sound_off':'sound_disable','sound_restore_sound':'sound_restore'}[action]
        result=run('direct_'+mode,dict(args,workspace=str(Path(args['workspace'])/('switch-'+uuid.uuid4().hex[:8]))),job)
        result['command']={'sound_on':'on','sound_off':'off','sound_restore_sound':'restore-sound'}[action]
        if action=='sound_restore_sound':
            # A RAM audition also clears on cold power-off when disk was
            # already stock; no previous installation record is needed.
            result.update(phase='restored_cold_test_pending',reload_required=True)
        elif result['phase']=='AWAITING_RELOAD':
            result.update(phase='written' if action=='sound_on' else 'restored',reload_required=True)
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
        reference, reference_path = None, args.get('factory') or 'builtin'
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
                from .official import load
                reference = load(prior['factory_path'])
            if prior.get('phase') in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED'):
                result=obj.verify_names_reload()
            else:
                result = obj.verify_direct(factory_values=reference, accepted=bool(args.get('accepted')))
        elif mode == 'resume_factory':
            # This button starts a fresh built-in reset. Historical jobs are
            # optional provenance, never a prerequisite or a source of targets.
            from .official import load
            reference = load(reference_path)
            result = obj.run_direct('factory_reset', version=args['firmware'],
                power_confirmed=args.get('power_confirmed', False), factory_values=reference,
                factory_path=reference_path, recovery_source=args.get('failed_workspace'))
        else:
            if mode == 'factory_reset':
                from .official import load
                reference = load(reference_path)
            result = obj.run_direct(mode, version=args['firmware'], power_confirmed=args.get('power_confirmed', False),
                factory_values=reference, factory_path=reference_path if mode == 'factory_reset' else None,
                slot=args.get('slot'), look_path=args.get('look'), name=args.get('name') or None,
                bundle_options=args.get('options'))
        response = {'workspace': str(obj.root), 'phase': result['phase'], 'mode': result['mode'],
                    'backup_created': False}
        if result['mode']=='factory_reset':
            response.update(recovery_complete=result['phase'] in ('LOADED','COMPLETE'),
                            verification_required=result['phase']=='AWAITING_RELOAD')
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
    if action.startswith('fl23_'):
        # The tested flexible planner, with PR #5's revised color/curve assets.
        # The PR's original standalone GUI/CLI remains untouched in src/fl23.
        from looktool.devicelock import DeviceLock
        app = module('desktop_fl23', ROOT / 'src/camera_runtime/app.py')
        work = Path(args['workspace'])
        with DeviceLock():
            obj = app.Job(work)
            if action == 'fl23_prepare':
                obj.prepare(Path(args['backup']), args['firmware'])
                register_backup(Path(args['backup']) / 'checkpoint.private.zip')
            elif action == 'fl23_install':
                obj.load()
                obj.install(args.get('battery'), power_confirmed=args.get('power_confirmed', False))
            else:
                obj.verify()
        return {'workspace': str(work), 'phase': obj.state.get('phase')}
    if action == 'backup_inspect':
        from looktool import checkpoint
        manifest, target = checkpoint.load_target(args['backup'])
        return {'model': manifest['model'], 'firmware': manifest['version'],
                'files': len(target), 'legacy_backup': manifest.get('legacy_raw', False),
                'limitations': manifest.get('limitations', []), 'camera_io': False}
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
            result = obj.run(args['backup'], args.get('battery'), args['firmware'],
                             power_confirmed=args.get('power_confirmed', False))
        else:
            result = obj.verify(accept_photos=bool(args.get('accepted')))
        return {'workspace': str(obj.root), 'phase': result.get('phase')}
    if action.startswith('look_'):
        from looktool.devicecli import main
        work = str(args['workspace'])
        if action == 'look_prepare':
            argv = ['import', args['look'], '--slot', str(args['slot']),
                    '--name', args['name'], '--work-dir', work,
                    '--backup-dir', args['backup']]
        elif action == 'look_install':
            argv = ['install', work]
            argv += ['--power-confirmed'] if args.get('power_confirmed') else ['--battery-percent', str(args['battery'])]
        elif action == 'look_restore':
            restored_work = str(data_root() / 'work' / ('slot-restore-' + uuid.uuid4().hex[:12]))
            argv = ['restore-slot', work, '--work-dir', restored_work, '--backup-dir', args['backup']]
            argv += ['--power-confirmed'] if args.get('power_confirmed') else ['--battery-percent', str(args['battery'])]
            work = restored_work
        else:
            argv = ['verify', work] + (['--accept-photos'] if args.get('accepted') else [])
        code = main(argv)
        if code:
            raise RuntimeError('A7Look operation stopped; see the complete backend log above.')
        state = json.loads((Path(work) / 'job.private.json').read_text(encoding='utf-8'))
        if action == 'look_prepare' and state.get('initial_checkpoint'):
            register_backup(state['initial_checkpoint'])
        return {'workspace': work, 'phase': state['phase']}
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
