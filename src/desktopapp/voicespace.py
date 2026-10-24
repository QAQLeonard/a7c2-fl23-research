"""Optional voice-space cleanup and restoration from a user-supplied update."""
from contextlib import contextmanager
from pathlib import Path
from . import screenreader
from .paths import write_json


def run(action,args,job,*,factory=None):
    from looktool.direct import DirectJob
    from looktool.checkpointjob import CheckpointCamera
    from looktool.resourceworker import Resources,restore_voice
    from looktool import checkpoint,voicelock
    from looktool.power import require_power
    require_power(confirmed=args.get('power_confirmed',False))
    if args['firmware']!='2.01':raise ValueError('Voice space supports ILCE-7CM2 2.01 only')
    source=None
    if action=='voice_restore':
        source=screenreader.restore_source(args)
        if not source:raise ValueError('请选择索尼官方 2.01 BODYDATA.DAT 或带有语音 ZIP 的备份，用于补回语音包。')
    root=Path(args['workspace'])
    with (factory or CheckpointCamera)() as camera:
        if source:
            identity=screenreader.load(source).get('identity')
            if identity:checkpoint.same_body(identity,camera.identity)
        @contextmanager
        def reuse(expected=None):
            if expected:checkpoint.same_body(expected,camera.identity)
            yield camera
        owner=DirectJob(root/'disable',factory=reuse)
        result=owner.run_direct('voice_disable',version=args['firmware'],power_confirmed=args.get('power_confirmed',False))
        if result['phase']=='AWAITING_RELOAD':
            return dict(workspace=str(owner.root),mode='voice_disable',phase='AWAITING_RELOAD',
                message='语音指南关闭限制及菜单禁用状态已写入。按提示完整断电重开，再点击同一操作；此阶段尚未删除音频。')
        try:
            for memory in (True,False):
                records=camera.records(camera.snapshot(memory))
                if records[0][voicelock.SETTING].data!=b'\1' or records[0][voicelock.TRIGGER].data!=b'\0':
                    raise ValueError('语音指南尚未关闭，未开始资源操作')
            if action=='voice_cleanup':Resources(camera,owner,'voice').delete()
            else:restore_voice(camera,owner,source)
        except BaseException as error:
            owner.save('NEEDS_REVIEW',error=str(error));raise
        if action=='voice_restore':
            unlock=DirectJob(root/'unlock',factory=reuse)
            write_json(Path(job)/'backend-workspace.private.json',dict(action=action,workspace=str(unlock.root)))
            result=unlock.run_direct('voice_unlock',version=args['firmware'],power_confirmed=args.get('power_confirmed',False))
            return dict(workspace=str(unlock.root),mode='voice_unlock',phase=result['phase'],voice_files_restored=True)
        owner.save('COMPLETE')
        return dict(workspace=str(owner.root),phase='COMPLETED',mode='voice_cleanup',voice_audio_removed=True,
            voice_setting_locked_off=True,voice_menu_flags_verified=True,
            message='语音音频已移除，机内语音指南相关选项保持置灰、关闭限制保持启用；语音索引、对焦提示音和快门音频未删除。')
