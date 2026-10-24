"""Integrated sound workflow; status/help/conversion/confirmation stay offline.

on/off changes the narrow CP electronic-capture branch, not Audio Signals or AF
beeps. install/restore-sound controls the separate persistent kind3 sound hook.
Every device operation retains its own native report and body-bound job.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import uuid
from contextlib import nullcontext

import trial
from replacement import replace_request,optional_job,command_lock,supersede_pending

SCHEMA = 'a7c2-sound-workspace/1'
RELOAD = ('USB I/O ended. Shut down normally, wait for the access light, unplug '
          'USB/all external power and remove the battery for at least one minute. '
          'Reinstall, power on and test. Disk readback is not a loaded-state test.')


def load_job(path):
    return json.loads((Path(path) / 'job.private.json').read_text(encoding='utf-8'))


def save(root, state):
    root = Path(root)
    temp = root / 'sound.pending'
    temp.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    temp.replace(root / 'sound.private.json')


def workspace(root, create=False, backup_copy=None,*,replace_existing=False):
    root = Path(root).resolve()
    path = root / 'sound.private.json'
    if path.exists():
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('schema') != SCHEMA:
            raise ValueError('Not a sound workspace')
        if backup_copy and str(Path(backup_copy).resolve()) != state['backup_root']:
            if not replace_existing:raise ValueError('Use the original backup root for this workspace')
            other=Path(backup_copy).resolve()
            if other==root or root in other.parents or other in root.parents:
                raise ValueError('Keep the backup outside the sound workspace')
            state['backup_root']=str(other)
            save(root,state)
    elif create:
        if not backup_copy:
            raise ValueError('A new workspace requires --backup-copy outside the workspace')
        other = Path(backup_copy).resolve()
        if other == root or root in other.parents or other in root.parents:
            raise ValueError('Keep the second backup outside the workspace, in a separate directory')
        existing=list(root.glob('jobs/*/job.private.json'))
        if (root/'sound.pending').exists() or existing:
            if not replace_existing:raise ValueError('Existing camera-job evidence needs review; keep this workspace')
            pending=root/'sound.pending'
            if pending.exists():
                history=root/'workspace-history';history.mkdir(exist_ok=True)
                shutil.copy2(pending,history/(uuid.uuid4().hex+'.private.json'))
        root.mkdir(parents=True, exist_ok=True)
        state = {'schema': SCHEMA, 'backup_root': str(other), 'history': [], 'pending': None}
        if replace_existing:
            state['history']=[dict(command='previous_sound_job',job=str(p.parent),phase='read_current_camera_before_replacement') for p in existing]
        save(root, state)
    else:
        raise ValueError('Create a workspace with on or attach first')
    return root, state


def new_path(root, label):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return root / 'jobs' / (stamp + '-' + label + '-' + uuid.uuid4().hex[:8])


def require_idle(state, root=None):
    if root is not None:
        retire_readonly_failure(root, state)
    if state.get('pending'):
        pending=state['pending']
        raise ValueError('上一次声音操作（%s）中途停止，结果还没确认，所以没有开始新的操作，也没有连接相机。'
                         '请点窗口底部“导出诊断包”发给作者核对；不要删除声音工作目录。'
                         '（Previous operation is unresolved: %s）'%(pending.get('command','?'),pending.get('job','')))


def retire_readonly_failure(root, state):
    pending = state.get('pending')
    if pending and pending.get('command')=='install':
        return retire_prewrite_install(root,state)
    if pending and pending.get('command')=='audition':
        return retire_preallocation_audition(root,state)
    if not pending or pending.get('command') not in ('on', 'adopt'):
        return False
    path = pending.get('job')
    if not path or path != state.get('native_job'):
        return False
    try:
        previous = load_job(path)
    except (OSError, ValueError):
        return False
    if not trial.completed_readonly_failure(previous):
        return False
    # Keep the original immutable evidence; discard only its active binding.
    state.setdefault('history', []).append(dict(command=pending['command'], job=path,
        phase='failed_before_mutation', retired_readonly_failure=True))
    if previous.get('identity'):
        state['native_identity'] = previous['identity']
    state['native_job'] = None
    state['pending'] = None
    save(root, state)
    print('旧声音任务已确认停在写入前，检查结果和临时清理均完整；已解除占用，原日志保留。', flush=True)
    return True


def retire_prewrite_install(root,state):
    pending=state['pending'];path=pending.get('job')
    if not path or path!=state.get('boot_job'):return False
    try:previous=load_job(path)
    except (OSError,ValueError):return False
    if (previous.get('schema')!='a7c2-native-boot-sound-job/1' or
            previous.get('phase')!='needs_review' or
            previous.get('camera_firmware_written') is not False or
            previous.get('journal')!=[]):return False
    state.setdefault('history',[]).append(dict(command='install',job=path,
        phase='failed_before_native_execution'))
    state['pending']=None;state['boot_job']=None
    save(root,state)
    print('上次保存停在电脑端准备阶段，未执行相机写入；已解除占用，保留原日志。',flush=True)
    return True


def retire_preallocation_audition(root,state):
    import buffer_trial
    pending=state['pending']
    path=pending.get('job')
    if not path or path!=state.get('audio_job'):
        return False
    try:
        job=load_job(path)
        if buffer_trial.stopped_before_native(job,path):
            reason,message='stopped_before_native_worker',('上次试听在调用相机原生程序之前就已停止，没有注册任何声音；'
                '已解除占用，原记录保留。')
        elif job.get('phase')=='needs_review' and buffer_trial.preallocation_marker_rejection(
                job,(Path(path)/'report.private.bin').read_bytes()):
            reason,message='existing_completed_marker','上次试听因旧标记在分配前停止，没有注册新声音；本次按当前状态新建试听。'
        else:
            return False
    except (OSError,ValueError,KeyError,struct.error):
        return False
    state.setdefault('history',[]).append(dict(command='audition',job=path,
        phase='rejected_before_allocation',reason=reason))
    state['pending']=None
    state['audio_job']=None
    save(root,state)
    print(message,flush=True)
    return True


def audio_evidence(root,state):
    paths=[state.get('audio_job'),*state.get('legacy_audio_jobs',[])]
    paths.extend(item.get('job') for item in state.get('history',[]) if item.get('command')=='audition')
    paths.extend(str(path.parent) for path in (Path(root)/'jobs').glob('*/job.private.json'))
    return list(dict.fromkeys(str(path) for path in paths if path))


def native_job(state, *, enabled=True):
    path = state.get('native_job')
    if not path:
        raise ValueError('Run on first, or attach an existing completed native-sound job')
    value = load_job(path)
    if enabled and (value['phase'] != 'written' or not value.get('complete_readback_and_settings_verified')):
        raise ValueError('Electronic-sound support is not recorded as enabled; run on and reload first')
    return Path(path), value


def operate(root, state, command, job, operation):
    # Durable intent precedes camera action. Only proven pre-mutation enable/
    # adoption failures can release their binding; writes are never replayed.
    require_idle(state, root)
    state['pending'] = {'command': command, 'job': str(job)}
    save(root, state)
    try:
        result = operation()
    except BaseException:
        state['pending']['outcome'] = 'needs_review'
        save(root, state)
        raise
    state['history'].append({'command': command, 'job': str(job), 'phase': result['phase']})
    state['pending'] = None
    save(root, state)
    return result


@replace_request('on')
def on(root, state, battery, zig=None, *, power_confirmed=False,defer_reload=False):
    import trial
    require_idle(state, root)
    from looktool.power import require_power
    state['power_confirmation'] = require_power(battery, confirmed=power_confirmed)
    job = new_path(root, 'native-on')
    state['native_job'] = str(job)
    def run():
        options = {'expected': state['native_identity']} if state.get('native_identity') else {}
        prepared=trial.preflight(job, Path(state['backup_root']) / job.name, zig, **options)
        if prepared and prepared.get('adopted_existing_enabled'):
            print('电子快门声已启用；已核对并接入声音工具，没有重复刷写。',flush=True)
            return prepared
        return trial.change(job, zig=zig)
    result = operate(root, state, 'on', job, run)
    print('声音支援已准备，继续保存当前片段；全部写入结束后统一提示断电。' if defer_reload else
          '本次只接入已启用的声音开关，保持开机继续。' if result.get('adopted_existing_enabled') else RELOAD)
    return result


@replace_request('off',refresh=False)
def off(root, state, zig=None):
    require_idle(state,root)
    recorded=optional_job(state.get('native_job'))
    if not recorded or recorded.get('phase') not in ('written','reload_pending'):
        # A switch record that stopped part-way is archived, never replayed;
        # adopt the connected body's current switch state and close from it.
        if state.get('native_job'):
            state.setdefault('history',[]).append(dict(command='previous_native_support',
                job=state.pop('native_job'),phase='refresh_from_current_camera'))
        adoption=new_path(root,'native-off-adopt')
        state['native_job']=str(adoption)
        operate(root,state,'adopt',adoption,lambda: trial.preflight(adoption,
            Path(state['backup_root'])/adoption.name,zig,adopt_only=True))
    job, _ = native_job(state)
    result = operate(root, state, 'off', job, lambda: trial.change(job, restore=True, zig=zig))
    print(RELOAD)
    return result


def attach(root, state, original, audio=None):
    require_idle(state)
    if any(state.get(key) for key in ('native_job', 'audio_job', 'boot_job')):
        raise ValueError('Attach only to a new workspace; existing evidence is retained')
    original = Path(original).resolve()
    value = load_job(original)
    if value.get('phase') != 'written' or not value.get('complete_readback_and_settings_verified'):
        raise ValueError('Attach a completed native-sound job')
    if audio:
        audio = Path(audio).resolve()
        evidence = load_job(audio)
        if evidence.get('identity') != value['identity'] or evidence.get('wire_format') != 0:
            raise ValueError('Attach only a same-body format0 audio trial')
        if not evidence.get('result', {}).get('temporary_pcm_registered'):
            raise ValueError('The audio trial did not complete registration')
        state['audio_job'] = str(audio)
    state['native_job'] = str(original)
    save(root, state)
    return {'phase': 'attached_existing_evidence', 'camera_io': False}


def import_audio(root, state, source, **options):
    import media
    # Conversion has its own host-only selection file. Never inherit or clear
    # a camera transaction lock, or overwrite its state while ffmpeg is busy.
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    folder = new_path(root, 'converted')
    report = media.convert(source, folder, **options)
    return select_conversion(root,folder,report,'converted_offline')


def select_conversion(root,folder,report,phase):
    import media
    temp=root/('conversion-'+uuid.uuid4().hex+'.pending')
    try:
        temp.write_text(json.dumps(dict(schema='a7c2-sound-conversion/1',conversion=str(folder)),indent=2),encoding='utf-8')
        temp.replace(root/'conversion.private.json')
    except BaseException:
        temp.unlink(missing_ok=True)
        media.cleanup(folder)
        raise
    return {'phase': phase, 'camera_io': False, 'bytes': report['encoded_bytes'],
            'preview': str(folder / 'preview.private.wav'),
            'volume_gain_db': report.get('volume_gain_db',0),
            'volume_limited': report.get('volume_limited',False)}


def selected_conversion(root,state):
    path=Path(root)/'conversion.private.json'
    if path.is_file():return json.loads(path.read_text(encoding='utf-8'))['conversion']
    return (state or {}).get('conversion')


def volume_audio(root, *, decibels=0, reset=False):
    import media
    root=Path(root).resolve();conversion=selected_conversion(root,None)
    if not conversion:
        raise ValueError('请先转换所选片段，再调节音量。')
    folder=new_path(root,'volume')
    report=media.adjust_volume(conversion,folder,decibels=decibels,reset=reset)
    return select_conversion(root,folder,report,'volume_adjusted_offline')


@replace_request('audition')
def audition(root, state, zig=None):
    import buffer_trial
    require_idle(state, root)
    conversion=selected_conversion(root,state)
    if not conversion:
        raise ValueError('请先点「转换所选片段」，转换成功后再试听。')
    # The current request reconciles the actual marker once, before adoption.
    payload = (Path(conversion) / 'custom-native.private.bin').read_bytes()
    previous_native=load_job(state['native_job']) if state.get('native_job') else None
    if not previous_native or not previous_native.get('electronic_only_gate'):
        # A temporary audition never enables the permanent CP branch silently.
        # Adopt an already-enabled branch through fresh read-only evidence.
        adoption = new_path(root, 'native-adopt')
        expected=(previous_native or {}).get('identity') or state.get('native_identity')
        state['native_job'] = str(adoption)
        operate(root, state, 'adopt', adoption, lambda: trial.preflight(adoption,
            Path(state['backup_root']) / adoption.name, zig,
            expected=expected, adopt_only=True))
    original, _ = native_job(state)
    job = new_path(root, 'audition')
    state['audio_job'] = str(job)
    result = operate(root, state, 'audition', job, lambda: buffer_trial.run(job, original,
        zig, payload=payload, register=True, wire_format=0, recovered_job=None,replace_jobs=()))
    print('USB I/O ended. Unplug USB WITHOUT switching off, removing the battery or changing Audio Signals. '
          'Take one electronic exposure; check volume/distortion/pitch/speed and normal shooting/playback. '
          'Then record confirm --result correct (or the actual failure). No ROM was written.')
    return result


def confirm_audio(root, state, result):
    import buffer_trial
    supersede_pending(root,state,'confirm-audio')
    previous=optional_job(state.get('audio_job'))
    if previous and previous.get('phase')=='temporary_pcm_registered_cold_reload_required_after_test':
        value=buffer_trial.confirm(Path(state['audio_job']),result)
    else:
        state.setdefault('history',[]).append(dict(command='confirm-audio',result=result,owner_statement_only=True))
        save(root,state)
        value=dict(phase='owner_audio_statement_recorded',camera_io=False,owner_audio_correct=result=='correct')
    print('试听结果已记录；可直接保存当前转换片段，无需先断电恢复。')
    return value


def confirm_recovery(root, state):
    import buffer_trial
    supersede_pending(root,state,'confirm-recovery')
    previous=optional_job(state.get('audio_job'))
    if previous and previous.get('phase') in ('temporary_pcm_registered_cold_reload_required_after_test',
            'owner_confirmed_audio_cold_reload_required','owner_audio_failed_cold_reload_required',
            'owner_requested_gain_adjustment_cold_reload_required'):
        return buffer_trial.confirm_recovery(Path(state['audio_job']))
    state.setdefault('history',[]).append(dict(command='confirm-recovery',owner_statement_only=True))
    save(root,state)
    return dict(phase='owner_confirmed_cold_recovered',camera_io=False,owner_statement_only=True)


@replace_request('install')
def install(root, state, battery, zig=None, *, power_confirmed=False):
    import boot_trial
    require_idle(state,root)
    conversion=selected_conversion(root,state)
    if conversion:
        payload=(Path(conversion)/'custom-native.private.bin').read_bytes()
    else:
        # Older CLI workspaces may have only an audition payload.
        audio=Path(state['audio_job'])/'payload.private.bin' if state.get('audio_job') else None
        if audio is None or not audio.is_file():
            return installation_step('sound_conversion_required','import')
        payload=audio.read_bytes()
    # Conversion deliberately has no camera/workspace dependency. Saving its
    # output must prepare/adopt native support itself, including after a reset.
    boot_trial.require_dependencies()
    previous_native=optional_job(state.get('native_job'))
    if previous_native and previous_native.get('identity'):
        state['native_identity']=previous_native['identity']
    if not previous_native or previous_native.get('phase')=='restored':
        print('自动准备电子快门声支援；已有开关直接接入，不要求先手动开启或关联旧任务。',flush=True)
        on(root,state,battery,zig,power_confirmed=power_confirmed,defer_reload=True)
    original, _ = native_job(state)
    # Each Save derives the current hook/files from the camera. A previous
    # completed installation is not a restore/old-job prerequisite.
    from looktool.power import require_power
    state['power_confirmation'] = require_power(battery, confirmed=power_confirmed)
    # Save the current converted bytes. Audition and cold recovery are optional.
    job = new_path(root, 'persistent')
    state['boot_job'] = str(job)
    options = {'power_confirmed': True} if power_confirmed else {}
    result = operate(root, state, 'install', job, lambda: boot_trial.install(job,
        Path(state['backup_root']) / job.name, original, None, payload, battery, zig, **options))
    print(RELOAD)
    return result


def installation_step(phase,next_action):
    return dict(phase=phase,next_action=next_action,user_action_required=True,
                camera_io=False,camera_firmware_written=False)


def compile_install(ap,cp,payload,output,zig=None):
    import boot_trial
    target,parts=boot_trial.prepare(Path(ap).read_bytes(),Path(cp).read_bytes(),
        Path(payload).read_bytes(),Path(output),zig)
    return dict(phase='sound_install_compiled_offline',camera_io=False,camera_firmware_written=False,
                program_windows=len(parts['windows']))


RESTORABLE = ('installed_cold_test_pending', 'loaded_owner_confirmation_pending', 'owner_confirmed_working')


def restorable_install(root, state):
    """Newest installation that a restore can start from.

    Restore plans its program inverse from the current camera bytes; the
    record supplies the body identity and its built components. An earlier
    failed or superseded record therefore does not block a restore.
    """
    paths = [state.get('boot_job')]
    paths += [h.get('job') for h in reversed(state.get('history', []))]
    paths += [str(p.parent) for p in sorted(Path(root).glob('jobs/*/job.private.json'),
                                            key=lambda p: p.stat().st_mtime_ns, reverse=True)]
    for path in dict.fromkeys(p for p in paths if p):
        value = optional_job(path)
        if value and value.get('phase') in RESTORABLE and value.get('components'):
            return Path(path)
    return None


@replace_request('restore-sound',refresh=False)
def restore_sound(root, state, zig=None):
    import boot_trial
    require_idle(state,root)
    job = restorable_install(root, state)
    if job is None:
        raise ValueError('这个声音工作目录里没有可用的永久声音安装记录，本次没有连接相机。'
                         '要还原相机的原厂快门音效，请点“恢复原厂功能”：它按相机当前字节还原全部声音程序，不依赖旧记录。')
    if str(job) != state.get('boot_job'):
        # The latest record stopped part-way; it is archived, never repeated.
        if state.get('boot_job'):
            state.setdefault('history', []).append(dict(command='previous_installation', job=state['boot_job'],
                phase='superseded_by_restorable_installation'))
        state['boot_job'] = str(job)
        print('最近的声音安装记录不可直接恢复；改用同一机身最近一次完成的安装记录，从相机当前字节规划恢复。', flush=True)
    result = operate(root, state, 'restore-sound', job, lambda: boot_trial.restore(job, zig))
    print(RELOAD)
    return result


@replace_request('verify',refresh=False)
def verify(root, state, heard_correct=False):
    import boot_trial
    require_idle(state)
    if not state.get('boot_job'):
        raise ValueError('No persistent installation to verify')
    job = Path(state['boot_job'])
    return operate(root, state, 'verify', job, lambda: boot_trial.verify_loaded(job, heard_correct))


def status(state,root=None):
    result = {'phase': 'local_status_only', 'camera_io': False, 'pending': state.get('pending'),
              'hardware_state_not_inferred_from_local_status': True}
    for key in ('native_job', 'audio_job', 'boot_job'):
        path = state.get(key)
        if path:
            job_file = Path(path) / 'job.private.json'
            phase = load_job(path)['phase'] if job_file.is_file() else 'job_not_created_or_missing'
            result[key] = {'path': path, 'phase': phase}
        else:
            result[key] = None
    result['conversion'] = selected_conversion(root,state) if root is not None else state.get('conversion')
    return result


def check_connection(state):
    """Read the current sound branch without staging or invoking any worker."""
    import candidate
    expected=state.get('native_identity')
    if expected is None and state.get('native_job'):
        expected=load_job(state['native_job']).get('identity')
    with trial.factory(expected) as camera:
        ap=camera.read('/usr/lib/appFw.so')
        cp=camera.read('/cp/cpapp-b.bin')
        enabled=candidate.is_enabled(cp)
        candidate.guard(ap,cp,installed=enabled)
    return dict(phase='sound_connection_checked',camera_io=True,camera_firmware_written=False,
                sound_support_enabled_on_disk=enabled)


def prepare_audition(root,state):
    """Exercise marker replacement only; do not stage or register audio."""
    import buffer_trial
    import candidate
    require_idle(state,root)
    original,value=native_job(state)
    job=new_path(root,'audition-preparation');job.mkdir(parents=True)
    with trial.factory(value['identity']) as camera:
        candidate.guard(camera.read('/usr/lib/appFw.so'),camera.read('/cp/cpapp-b.bin'),installed=True)
        result=buffer_trial.replace_completed_marker(camera,job,audio_evidence(root,state))
    return dict(result,phase='sound_audition_prepared',camera_firmware_written=False,
                audio_registration_started=False)


def doctor():
    names = ('numpy', 'scipy', 'usb', 'libusb_package', 'Cryptodome', 'yaml', 'elftools',
             'unicorn', 'keystone')
    missing = [name for name in names if importlib.util.find_spec(name) is None]
    if not shutil.which('zig') and importlib.util.find_spec('ziglang') is None:
        missing.append('ziglang (or zig on PATH)')
    return {'camera_io': False, 'python': sys.version.split()[0], 'bits': struct.calcsize('P') * 8,
            'platform': sys.platform, 'missing': missing,
            'ffmpeg_available': bool(shutil.which('ffmpeg') or importlib.util.find_spec('imageio_ffmpeg')),
            'mac_camera_USB_verified': False}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Offline dependency inventory; never connects')
    for name, help_text in (
        ('on', 'Enable electronic shutter sound independently of AF beeps; CP patch, cold reload'),
        ('off', 'Disable only the electronic-capture sound branch; AF audio setting preserved'),
        ('attach', 'Offline: reuse a completed native-sound job and optional RAM audition'),
        ('import', 'Offline: extract selected WAV/MP3/MP4 audio and encode a private candidate'),
        ('volume', 'Offline: adjust converted audio volume without camera access'),
        ('audition', 'Temporarily register converted audio in RAM, no ROM write'),
        ('confirm', 'Offline: record the actual listening result'),
        ('confirm-recovery', 'Offline statement: cold power-off done, native sound/shooting/playback normal'),
        ('install', 'Persist the exact owner-accepted sound; files before boot hook'),
        ('verify', 'Read loaded code/files/descriptor after cold boot'),
        ('restore-sound', 'Restore native sound; disable/read back boot hook before removing files'),
        ('check-connection', 'Read current sound programs and body identity; no workers or writes'),
        ('prepare-audition', 'Replace only an exact completed prior marker; no audio registration'),
        ('compile-install','Offline boot-reader verification and native worker generation; no USB'),
        ('status', 'Read local workspace state; no camera connection')):
        s = sub.add_parser(name, help=help_text)
        s.add_argument('--workspace', required=True, type=Path)
        if name in ('on', 'attach', 'import','install','audition'):
            s.add_argument('--backup-copy', type=Path)
        if name in ('on', 'install'):
            power = s.add_mutually_exclusive_group(required=True)
            power.add_argument('--battery-percent', type=int)
            power.add_argument('--power-confirmed', action='store_true')
        if name in ('on', 'off', 'audition', 'install', 'restore-sound'):
            s.add_argument('--zig')
        if name == 'on':
            s.add_argument('--firmware', required=True, choices=('2.01',))
        if name == 'attach':
            s.add_argument('--native-job', required=True, type=Path)
            s.add_argument('--audio-job', type=Path)
        if name == 'import':
            s.add_argument('source', type=Path)
            s.add_argument('--start', type=float, default=0)
            s.add_argument('--duration', type=float)
            s.add_argument('--peak', type=float, default=0.4)
            s.add_argument('--ffmpeg', type=Path)
        if name == 'confirm':
            s.add_argument('--result', required=True,
                           choices=('correct', 'quiet', 'noise', 'wrong-speed', 'native', 'silent'))
        if name == 'volume':
            gain = s.add_mutually_exclusive_group(required=True)
            gain.add_argument('--decibels', type=float)
            gain.add_argument('--reset', action='store_true')
        if name == 'verify':
            s.add_argument('--heard-correct', action='store_true')
        if name=='compile-install':
            for flag in ('ap','cp','native-bin'):s.add_argument('--'+flag,type=Path,required=True)
    return p


def workspace_command(args):
    command=args.command
    with (nullcontext() if command=='status' else command_lock(args.workspace)):
        creates=command in ('on','attach','import','install','audition')
        backup=getattr(args,'backup_copy',None)
        if command in ('install','audition') and not backup and not (args.workspace/'sound.private.json').exists():
            backup=args.workspace.with_name(args.workspace.name+'-backup')
        root,state=workspace(args.workspace,creates,backup,replace_existing=command in ('install','audition'))
        if command=='on':return on(root,state,args.battery_percent,args.zig,power_confirmed=args.power_confirmed)
        if command=='off':return off(root,state,args.zig)
        if command=='attach':return attach(root,state,args.native_job,args.audio_job)
        if command=='audition':return audition(root,state,args.zig)
        if command=='confirm':return confirm_audio(root,state,args.result)
        if command=='confirm-recovery':return confirm_recovery(root,state)
        if command=='install':return install(root,state,args.battery_percent,args.zig,power_confirmed=args.power_confirmed)
        if command=='restore-sound':return restore_sound(root,state,args.zig)
        if command=='verify':return verify(root,state,args.heard_correct)
        if command=='check-connection':return check_connection(state)
        if command=='prepare-audition':return prepare_audition(root,state)
        return status(state,root)


def main(argv=None, *, report=None, failure=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'doctor':
            result = doctor()
        elif args.command=='import':
            result=import_audio(args.workspace,None,args.source,start=args.start,
                duration=args.duration,peak=args.peak,ffmpeg=args.ffmpeg)
        elif args.command=='volume':
            result=volume_audio(args.workspace,decibels=args.decibels or 0,reset=args.reset)
        elif args.command=='compile-install':
            result=compile_install(args.ap,args.cp,args.native_bin,args.workspace)
        elif args.command=='status' and not (args.workspace/'sound.private.json').exists():
            result=status({},args.workspace)
        else:
            if sys.version_info < (3, 10) or struct.calcsize('P') != 8:
                raise ValueError('Use 64-bit Python 3.10 or newer')
            result=workspace_command(args)
        # The desktop needs the actual result phase, especially for cold reload
        # versus adoption/temporary audition. Do not infer it from command success.
        public = {key: result[key] for key in ('phase', 'camera_io', 'camera_firmware_written',
            'complete_readback_and_settings_verified', 'owner_audio_correct', 'bytes', 'preview', 'volume_gain_db','volume_limited',
            'adopted_existing_enabled', 'sound_support_enabled_on_disk','audio_registration_started',
            'audio_resources_written','resource_update','adopted_same_sound',
            'completed_prior_marker_replaced','previous_marker_absent','previous_cp_handle_released') if key in result}
        public.update({key:result[key] for key in ('next_action','user_action_required') if key in result})
        if report is not None:
            report(public)
        # Never print body identity, raw native buffers or the complete private journal.
        print(json.dumps(public if args.command not in ('status', 'doctor') else result, indent=2))
        return 0
    except (ValueError, OSError, ImportError, RuntimeError, KeyError) as exc:
        detail=('\n电脑端音频处理失败，本次没有相机读写；请修正输入后重试。' if args.command=='volume' else
                '\n电脑端转换失败，本次没有相机读写；请修正输入后重新转换。' if args.command=='import' else
                '\nKeep the workspace and backup; do not repeat unknown writes.')
        print('Stopped: ' + str(exc) + detail, file=sys.stderr)
        if failure is not None:
            failure(str(exc) + detail)
        return 2
    except KeyboardInterrupt:
        print('Interrupted. Preserve the workspace; inspect status before further device operations.', file=sys.stderr)
        return 130
