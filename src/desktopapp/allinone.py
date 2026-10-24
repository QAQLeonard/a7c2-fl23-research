"""Guided combined persistent install, cold reload and loaded-state verification.

All device work goes through existing explicit worker actions. A failed or
unknown installation is never replayed. Physical power removal remains manual.
"""
import json
import uuid
from pathlib import Path
from .paths import write_json
from . import lookbatch


def run(arguments, *, dispatch):
    from looktool import bundle, settingsresume
    from looktool.power import require_power
    require_power(confirmed=arguments.get('power_confirmed', False))
    if arguments.get('firmware') != '2.01':
        raise ValueError('One-click setup supports ILCE-7CM2 2.01')
    root = Path(arguments['workspace']).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'setup.private.json'
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    if state and state['phase'] == 'COMPLETE':
        from .completion import archive_error
        if archive_error(state):write_json(path,state)
        print('本次一键安装已结束，没有重复写入。', flush=True)
        return state
    if state is None:
        from .presets import resolve
        inputs = root / 'inputs'
        inputs.mkdir(exist_ok=True)
        options, _ = bundle.documents(resolve(arguments.get('options', {})), inputs)
        # Version the behavior so already-written older jobs keep their plan.
        options['vertical_persistent'] = bool(options.get('vertical', True))
        options['portrait_frames'] = bool(options.get('vertical', True))
        if options.get('plugin'):
            from .exiftool import ensure
            options['exiftool']=ensure(options.get('exiftool'))
        state = dict(schema='a7c2-one-click/1', phase='READY', workspace=str(root), options=options,
                     firmware='2.01', completed_steps=[], physical_checks_accepted=False)
        write_json(path, state)

    def save(phase, **values):
        if phase!='NEEDS_REVIEW' and 'error' not in values:
            from .completion import archive_error
            archive_error(state)
        state.update(values, phase=phase)
        write_json(path, state)
        print('一键安装：' + phase, flush=True)

    def call(action, values, name):
        step = root / 'steps' / name
        step.mkdir(parents=True, exist_ok=True)
        print('执行：' + action, flush=True)
        return dispatch(action, values, step)

    def finish_programs(result):
        if result['phase'] not in ('AWAITING_RELOAD','LOADED','COMPLETE'):
            raise ValueError('程序安装尚未完成，不能继续收尾：'+str(result['phase']))
        state['install_result'] = result
        state['completed_steps'].append('persistent_features')
        waiting = result['phase'] == 'AWAITING_RELOAD'
        save('WAIT_RELOAD' if waiting else 'FINALIZING')
        return waiting

    options = state['options']
    common = dict(firmware='2.01', power_confirmed=True)
    install = Path(state.get('install_workspace') or root / 'install')
    if state['phase']=='NEEDS_REVIEW' and state.get('verify_result',{}).get('phase') in ('LOADED','COMPLETE'):
        # Older packages called a computer-only plugin failure NEEDS_REVIEW.
        # Once camera work was verified, resume only the remaining host steps.
        done=state.get('completed_steps',[])
        child=install/'direct.private.json'
        verified=state['verify_result'].get('workspace')
        if ('persistent_features' in done and (not options.get('sound',True) or 'sound' in done)
                and (not options.get('vertical',True) or options.get('vertical_persistent'))
                and verified and Path(verified).resolve()==install.resolve() and child.is_file()
                and json.loads(child.read_text(encoding='utf-8')).get('phase') in ('LOADED','COMPLETE')):
            print('相机安装与重启核对已通过；只继续电脑端插件步骤。',flush=True)
            save('FINALIZING')
    if state['phase']=='PREPARING_VERTICAL' or (state['phase']=='NEEDS_REVIEW' and state.get('failed_step')=='portrait_frames'):
        print('重新读取当前竖屏与线框状态，续接本次安装；相同内容不重复写入。',flush=True)
        save('PREPARED')
    if state['phase'] in ('INSTALLING', 'NEEDS_REVIEW', 'RESUMING_RESOURCES','RESUMING_SETTINGS'):
        child = install / 'direct.private.json'
        child_state = json.loads(child.read_text(encoding='utf-8')) if child.exists() else {}
        # A ready resource checkpoint can start its program child before the
        # parent receives the returned workspace. Recover that exact child.
        nested=install/'program-install/direct.private.json'
        if child_state.get('phase')=='RESOURCE_RELOAD_VERIFIED' and nested.is_file():
            install=nested.parent
            child_state=json.loads(nested.read_text(encoding='utf-8'))
            state['install_workspace']=str(install)
        if (state['phase'] in ('RESUMING_SETTINGS','NEEDS_REVIEW') and state.get('resume_settings_from') and not child_state and
                (not install.exists() or not any(install.iterdir()))):
            install=Path(state['resume_settings_from'])
            save('SETTINGS_REVIEW_REQUIRED',install_workspace=str(install))
        elif (state['phase']=='RESUMING_RESOURCES' and not child_state and
                (not install.exists() or not any(install.iterdir()))):
            # Dispatch never created a transaction; continue from the saved
            # resource source in a fresh child, never reuse an unknown job.
            install=Path(state['resume_resource_from'])
            save('WAIT_RESOURCE_RELOAD',install_workspace=str(install))
        elif child_state.get('phase') in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED'):
            save('WAIT_RESOURCE_RELOAD')
        elif child_state.get('phase') in ('AWAITING_RELOAD', 'LOADED', 'COMPLETE'):
            # Re-read device proof even when the child finished before the
            # parent saved its result. LOADED children need no further reboot.
            save('WAIT_RELOAD')
        elif (child_state.get('schema')=='a7c2-direct-job/1' and child_state.get('mode')=='install_all'
              and not child_state.get('settings_resume_from')
              and isinstance(child_state.get('journal'),list)
              and lookbatch.read_only_failure(child_state)):
            # A version/window conflict can occur while building the host plan,
            # before any camera write. A fixed tool must allow a fresh plan,
            # preserving the failed child and its saved selection.
            print('上次安装在写入前停止；保留失败记录，使用新版代码重新生成方案，不重装驱动。',flush=True)
            state.setdefault('failed_install_workspaces',[]).append(str(install))
            install=root/('install-retry-'+uuid.uuid4().hex[:8])
            save('PREPARED',install_workspace=str(install))
        elif settingsresume.eligible(child_state):
            save('SETTINGS_REVIEW_REQUIRED')
        else:
            from . import reviewnames
            try:reviewnames.source(install)
            except (ValueError,OSError,KeyError):
                from looktool import namespause
                try:namespause.source(install)
                except (ValueError,OSError,KeyError):
                    detail='；原始阶段：%s；原始错误：%s'%(child_state.get('failed_during',child_state.get('phase','未知')),
                        child_state.get('error','缺少原始错误，请导出包含子事务的新诊断包'))
                    raise ValueError('上次安装结果需要核对，不会重复刷写。保留本目录并查看完整错误：' + str(root)+detail)
                save('RESOURCE_REVIEW_REQUIRED')
            else:
                print('上次在名称提交前空间不足；先核对现有字节并清理该次已完成的临时报告。',flush=True)
                reviewed=call('review_failed_names',dict(workspace=str(install)),'review-'+uuid.uuid4().hex[:6])
                if not reviewed.get('pre_program_failure_accounted'):raise ValueError('Name failure review did not finish; no retry')
                state.setdefault('failed_install_workspaces',[]).append(str(install))
                install=root/('install-retry-'+uuid.uuid4().hex[:8])
                save('PREPARED',install_workspace=str(install),last_name_failure_review=reviewed)
    host_step=False
    try:
        if state['phase']=='SETTINGS_REVIEW_REQUIRED':
            previous=install
            failed=state.setdefault('failed_install_workspaces',[])
            if str(previous) not in failed:failed.append(str(previous))
            candidate=root/('install-settings-'+uuid.uuid4().hex[:8])
            save('RESUMING_SETTINGS',resume_settings_from=str(previous),install_workspace=str(candidate))
            print('上次程序与名称已完整读回；核对当前内容后只继续设置，不重装驱动、不重复刷写程序。',flush=True)
            result=call('direct_resume_settings',dict(common,workspace=str(candidate),failed_workspace=str(previous)),
                        'settings-resume-'+uuid.uuid4().hex[:6])
            install=Path(result['workspace']);state['install_result']=result
            if result['phase']!='AWAITING_RELOAD':raise ValueError('Settings continuation did not reach reload preparation')
            save('WAIT_RELOAD')
            from .reloadguide import text
            print('所有读写已结束。\n'+text(setup=True),flush=True)
            return state
        if state['phase'] in ('WAIT_RESOURCE_RELOAD','RESOURCE_REVIEW_REQUIRED'):
            print('名称已经写好；核对／准备资源重新加载，不重写名称，不重装驱动。',flush=True)
            previous=install
            candidate=root/('install-continue-'+uuid.uuid4().hex[:8])
            save('RESUMING_RESOURCES',resume_resource_from=str(previous),install_workspace=str(candidate))
            result=call('direct_resume_looks',dict(common,workspace=str(candidate),failed_workspace=str(previous)),
                        'resource-resume-'+uuid.uuid4().hex[:6])
            if result['phase']=='RESOURCE_RELOAD_VERIFIED':
                previous=Path(result['workspace'])
                candidate=root/('install-after-resources-'+uuid.uuid4().hex[:8])
                save('RESUMING_RESOURCES',resume_resource_from=str(previous),install_workspace=str(candidate))
                result=call('direct_resume_looks',dict(common,workspace=str(candidate),failed_workspace=str(previous)),
                            'resource-continue-'+uuid.uuid4().hex[:6])
            install=Path(result['workspace']);state['install_workspace']=str(install)
            if result['phase']=='AWAITING_RESOURCE_RELOAD':
                # A names-only preparation returns a checkpoint; never treat
                # it as a completed program install or enable other features.
                save('WAIT_RESOURCE_RELOAD',resource_result=result)
                from .reloadguide import text
                print('所有读写已结束。\n'+text(setup=True,mode='resource_reload'),flush=True)
                return state
            if finish_programs(result):return state
        if state['phase'] in ('READY', 'DRIVERS'):
            if state['phase'] == 'READY':
                save('DRIVERS')
                state['driver_result'] = call('usb_prepare', {}, 'drivers')
            else:
                print('上次停在连接准备；本次只测试连接，不重复更换驱动。', flush=True)
                state['driver_result'] = call('connect', {}, 'driver-recheck')
            state['completed_steps'].append('drivers')
            save('PREPARED')
        if state['phase'] == 'PREPARED':
            if options.get('portrait_frames') and not state.get('portrait_frames_preinstalled'):
                save('PREPARING_VERTICAL',failed_step='portrait_frames')
                result=call('vertical_enable',dict(common,workspace=str(root/'vertical'),drivers_prepared=True,combined=True),
                            'vertical-frames-'+uuid.uuid4().hex[:6])
                if result.get('migration_pending'):
                    save('PREPARING_VERTICAL',portrait_frames_result=result)
                    from .reloadguide import text
                    print('所有读写已结束。\n'+text(mode='vertical_native_prepare'),flush=True)
                    return dict(state,reload_required=True,mode='vertical_native_prepare')
                if result.get('phase') not in ('AWAITING_RELOAD','LOADED','COMPLETE'):
                    raise ValueError('竖屏线框步骤没有返回已写入／已符合目标状态，请保留日志')
                state['portrait_frames_preinstalled']=True
                state['portrait_frames_result']=result
                state.pop('failed_step',None)
                save('PREPARED')
            save('INSTALLING')
            result = call('direct_install_all', dict(common, workspace=str(install), options=options), 'install')
            if result['phase']=='AWAITING_RESOURCE_RELOAD':
                save('WAIT_RESOURCE_RELOAD', install_result=result)
                from .reloadguide import text
                print('所有读写已结束。\n'+text(setup=True,mode='resource_reload'),flush=True)
                return state
            if finish_programs(result):
                from .reloadguide import text
                print('本次程序／外观写入和完整读回已结束。\n' + text(setup=True), flush=True)
                return state
        if state['phase'] == 'WAIT_RELOAD':
            print('继续已保存的安装计划；先核对新开机，不重新刷写。', flush=True)
            try:
                result = call('direct_verify', dict(workspace=str(install), accepted=False), 'verify')
            except ValueError as exc:
                if '冷启动' in str(exc):
                    save('WAIT_RELOAD', message=str(exc))
                    print(str(exc), flush=True)
                    return state
                raise
            if result['phase'] not in ('LOADED','COMPLETE'):
                raise ValueError('重启后核对尚未完成，不能标记安装完成：'+str(result['phase']))
            state['verify_result'] = result
            if 'persistent_features' not in state['completed_steps']:
                state['completed_steps'].append('persistent_features')
            save('FINALIZING')
        if state['phase'] == 'FINALIZING':
            if options.get('sound',True) and 'sound' not in state['completed_steps']:
                sound=root/'sound'
                state['sound_result']=call('sound_on',dict(common,workspace=str(sound),backup=str(root/'sound-backups')),'sound-adoption')
                state['sound_workspace']=str(sound)
                state['sound_backup']=str(root/'sound-backups')
                state['completed_steps'].append('sound')
                save('FINALIZING')
            if options.get('plugin') and 'plugin' not in state['completed_steps']:
                host_step=True
                state['plugin_result'] = call('plugin_install', {'exiftool': options.get('exiftool')}, 'plugin')
                child = json.loads((install / 'direct.private.json').read_text(encoding='utf-8'))
                selected, rows = bundle.documents(child['bundle_options'])
                resets=selected.get('reset_slots',[])
                if rows or resets:
                    from looktool.rawidentity import activated
                    state['raw_profile_result'] = activated(
                        [dict(r['document'], name=r['name']) for r in rows]+[dict(name='ST',raw_profile=None) for _ in resets],
                        [r['slot'] for r in rows]+resets,
                        child['job_id'], child['raw_profile_effective_since'])
                state['completed_steps'].append('plugin')
                save('FINALIZING')
                host_step=False
            if options.get('vertical', True) and 'vertical' not in state['completed_steps']:
                if options.get('vertical_persistent'):
                    result = state.get('verify_result', state.get('install_result', {})).get('vertical_result', {})
                    if not (result.get('persistent') and result.get('loaded_verified') and
                            result.get('saved') == result.get('running') == 'ON' and result.get('alias_count') == 3):
                        raise ValueError('竖屏持久化加载尚未确认，不以会话临时开启代替完成。请保留日志。')
                    state['vertical_result'] = result
                else:
                    # Resume old plans without silently adding a new flash write.
                    state['vertical_result'] = call('vertical_enable', dict(common, workspace=str(root / 'vertical'), session_only=True), 'vertical')
                state['completed_steps'].append('vertical')
            message='所选安装已完成；请在机身检查预览、名称、拍摄和回放。'
            if options.get('vertical',True):
                message+=('竖屏已保存开启，并已核对重开后的实际运行状态。' if options.get('vertical_persistent') else
                    '旧安装的竖屏仅在本次开机开启；可用新版竖屏页保存开启。')
            save('COMPLETE', message=message)
            print(state['message'], flush=True)
        return state
    except BaseException as exc:
        phase = state['phase']
        if phase not in ('DRIVERS', 'WAIT_RELOAD') and not (phase == 'FINALIZING' and host_step):
            phase = 'NEEDS_REVIEW'
        save(phase, error=str(exc))
        raise
