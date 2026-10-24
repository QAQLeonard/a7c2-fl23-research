"""Optional current-state backup. Reads the camera without staging workers."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from .paths import write_json


def voice_archive(camera, destination, identity):
    from .screenreader import NAMES, CAMERA_ROOT
    destination = Path(destination)
    temporary = destination.with_suffix('.pending.zip')
    files = {}
    with ZipFile(temporary, 'x', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for index, name in enumerate(NAMES, 1):
            raw = camera.read(CAMERA_ROOT + name, True)
            if raw is None or not 0 < len(raw) <= 40 * 1024 * 1024:
                raise ValueError('语音包备份未完成，文件不可读或长度不符：'+name+'；已完成的项目备份仍保留。')
            archive.writestr(name, raw)
            files[name] = dict(bytes=len(raw), sha256=sha256(raw).hexdigest())
            print('语音文件备份：%d/%d'%(index,len(NAMES)),flush=True)
        archive.writestr('manifest.json', json.dumps(dict(schema='a7c2-voice-backup/1',
            model='ILCE-7CM2',version='2.01',identity=identity,files=files),ensure_ascii=False))
    with ZipFile(temporary) as archive:
        if archive.testzip() or set(archive.namelist()) != set(NAMES)|{'manifest.json'}:
            raise ValueError('语音包备份本地校验失败')
    temporary.rename(destination)
    return dict(path=str(destination), files=len(files), bytes=sum(r['bytes'] for r in files.values()))


def run(arguments, job, *, factory=None):
    from looktool import checkpoint
    from looktool.checkpointjob import CheckpointCamera, Rollback
    if arguments['firmware'] != '2.01':
        raise ValueError('当前状态备份只支持 ILCE-7CM2 2.01')
    folder = Path(arguments['workspace']).expanduser().resolve()
    if folder.exists():
        raise ValueError('请选择新的备份目录，已有备份不会覆盖')
    folder.mkdir(parents=True)
    report = dict(schema='a7c2-current-backup/1',phase='READING',workspace=str(folder),
                  created_at=datetime.now().isoformat(timespec='seconds'),
                  state='current-not-factory',include_voice=bool(arguments.get('include_voice')),
                  camera_firmware_written=False,camera_settings_written=False)
    state_path=folder/'backup.private.json'
    write_json(state_path,report)
    try:
        with (factory or CheckpointCamera)() as camera:
            checkpoint.same_body(camera.identity,camera.identity)
            # Reuse the current programs/settings/name capture and existing rollback format.
            values=Rollback(folder).capture(camera)
            target=folder/'checkpoint.private.zip'
            checkpoint.write(target,values,camera.identity,
                provenance=dict(type='current-project-backup',captured_at=report['created_at']),
                limitations=['备份的是创建时的当前项目状态，可能已修改，不是原厂基准或完整相机镜像。',
                             '不包含完整文件系统；自定义声音文件与其他未列入的资源不在项目检查点中。'])
            del values
            report.update(project_backup=str(target),project_backup_complete=True,phase='PROJECT_SAVED')
            write_json(state_path,report)
            if report['include_voice']:
                report['voice_backup']=voice_archive(camera,folder/'voice-resources.private.zip',camera.identity)
        report.update(phase='COMPLETE',camera_io=True)
        write_json(state_path,report)
        print('当前状态备份已完成并通过本地校验；没有写入相机。',flush=True)
        return report
    except BaseException as exc:
        report.update(phase='FAILED',error=str(exc))
        write_json(state_path,report)
        raise
