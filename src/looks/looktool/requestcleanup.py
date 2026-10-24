"""Fresh-operation cleanup over current files, independent of old task records."""
import os
from pathlib import Path


def namespace():
    from .devicesession import TEMP_NAMES
    from .checkpointjob import TEMPS
    return sorted((TEMP_NAMES | TEMPS | {'a7c2-preview-staged.so'}) - {'libJit.so'})


def supersede_temporary(camera, folder, record):
    """Archive inert project work files before planning a fresh device operation.

    This does not infer success of, or replay, the former operation. The caller
    captures current programs/settings/resources AFTER cleanup and builds new
    byte-checked writes from the requested target. Never replace libJit.so.
    """
    names=namespace()
    if camera.temp_read('libJit.so',True) is not None:
        raise ValueError('相机执行插件仍存在，尚不能确认执行入口空闲；本次操作没有开始，请等待当前操作结束')
    if camera.read('/etc/ld.so.preload',True):
        raise ValueError('相机存在启用中的 preload，尚未覆盖临时工作文件或开始写入')
    actual={name:camera.temp_read(name,True) for name in names}
    actual={name:raw for name,raw in actual.items() if raw is not None}
    if not actual:return 0
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    # Save every captured byte before removing anything on the camera. These
    # are tiny private worker/request/report files, not a body firmware backup.
    for name,raw in actual.items():
        path=folder/name
        with path.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if path.read_bytes()!=raw:raise ValueError('Temporary archive readback differs: '+name)
    record('factory_temporary_archived',files={name:len(raw) for name,raw in actual.items()},
           old_operation_replayed=False,previous_outcome_inferred=False)
    # Check the whole namespace before deletion. A newly appearing report or
    # loader means it is changing, not merely leftover data.
    if camera.temp_read('libJit.so',True) is not None:
        raise ValueError('相机执行插件出现，已保存诊断，未覆盖工作文件')
    for name in names:
        if camera.temp_read(name,True)!=actual.get(name):
            raise ValueError('相机临时状态仍在变化，已保存诊断，未覆盖工作文件：'+name)
    # Keep reports until last if the connection fails during cleanup.
    for name in sorted(actual,key=lambda value:value.endswith('.result')):
        if camera.temp_read(name,True)!=actual[name]:
            raise ValueError('Temporary state changed during factory cleanup: '+name)
        camera.temp_remove(name)
        if camera.temp_read(name,True) is not None:
            raise ValueError('Temporary cleanup incomplete: '+name)
    record('factory_temporary_superseded',files=list(actual),old_operation_replayed=False)
    print('旧临时工作文件已保存诊断并清理；重新读取相机现况，直接生成本次操作计划，不重放旧任务。',flush=True)
    return len(actual)

