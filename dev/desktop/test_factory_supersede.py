"""A fresh reset uses a provided source and supersedes inert work files."""
import copy
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from test_checkpoint import Camera,values,fake_compile,KEYS
from test_direct import SimDirect
from looktool import direct,checkpointworker,requestcleanup


@pytest.mark.parametrize('platform',['win32','darwin'])
@pytest.mark.parametrize('leftovers',[
    {'lut-names-staged.so':b'old-name-worker'},
    {'lut-names-staged.so':b'old-name-worker','a7c2.names.request':b'old-request','a7c2.names.result':b'old-or-incomplete-report'},
    {'a7c2.names.result':b'report-left-after-partial-cleanup'},
    {'checkpoint.staged.so':b'old-restore-worker','checkpoint.names.request':b'old-request','checkpoint.names.result':b'old-report'},
])
def test_reset_archives_then_reads_fresh_and_writes_builtin_target(tmp_path,monkeypatch,platform,leftovers):
    monkeypatch.setattr(sys,'platform',platform)
    camera=Camera(values())
    camera.files.update({'/tmp/jiritsu/'+name:raw for name,raw in leftovers.items()})
    camera.files['/tmp/jiritsu/unrelated-user-file']=b'keep'
    before=copy.deepcopy(camera.ram)
    job=SimDirect(tmp_path/'fresh-reset',factory=lambda:camera)
    order=[]
    def plan(current,records,mode,**kwargs):
        assert mode=='factory_reset'
        assert all(camera.temp_read(name,True) is None for name in leftovers)
        order.append('fresh-plan')
        target=dict(current)
        target['appFw.so']=current['appFw.so'][:3]+b'\x12\x34'+current['appFw.so'][5:]
        return target,[{KEYS[0]:b'\x05'},{}],None
    def vertical(camera):
        # This shared namespace check was the actual failure in diagnostic21.
        assert camera.temp_read('lut-names-staged.so',True) is None
        order.append('vertical')
    with patch.object(direct,'plan',side_effect=plan),patch.object(job,'prepare_vertical',side_effect=vertical), \
         patch.object(checkpointworker,'compile_worker',side_effect=fake_compile):
        result=job.run_direct('factory_reset',version='2.01',power_confirmed=True,factory_values={'builtin':True})
    assert result['phase']=='AWAITING_RELOAD'
    assert order==['fresh-plan','vertical']
    assert ('program',1) in camera.native_calls
    assert camera.files['/usr/lib/appFw.so'][3:5]==b'\x12\x34'
    for name,raw in leftovers.items():
        assert (job.root/'evidence/superseded-temporary'/name).read_bytes()==raw
    assert camera.files['/tmp/jiritsu/unrelated-user-file']==b'keep'
    for chip in (0,1):
        for key,prop in before[chip].items():
            if (chip,key)!=(0,KEYS[0]):assert camera.ram[chip][key]==prop
    assert result['backup_created'] is False


def test_active_loader_is_not_overwritten_or_archived(tmp_path):
    camera=Camera(values())
    camera.files.update({'/tmp/jiritsu/lut-names-staged.so':b'old','/tmp/jiritsu/libJit.so':b'active'})
    before=copy.deepcopy(camera.files)
    with pytest.raises(ValueError,match='执行插件仍存在'):
        requestcleanup.supersede_temporary(camera,tmp_path/'archive',lambda *a,**k:None)
    assert camera.files==before and not (tmp_path/'archive').exists()


def test_actual_loader_without_old_task_files_is_still_not_replaced(tmp_path):
    from looktool.requestcleanup import supersede_temporary
    camera = Camera(values())
    camera.files['/tmp/jiritsu/libJit.so'] = b'occupied executor'
    before = copy.deepcopy(camera.files)
    with pytest.raises(ValueError, match='执行入口空闲'):
        supersede_temporary(camera, tmp_path / 'archive', lambda *a, **kwargs: None)
    assert camera.files == before


def test_empty_namespace_needs_no_old_report_or_archive(tmp_path):
    from looktool.requestcleanup import supersede_temporary
    camera = Camera(values())
    before = copy.deepcopy(camera.files)
    assert supersede_temporary(camera, tmp_path / 'unused', lambda *a, **kwargs: None) == 0
    assert camera.files == before and not (tmp_path / 'unused').exists()


def test_archive_failure_never_deletes_camera_work_files(tmp_path):
    camera=Camera(values());camera.files['/tmp/jiritsu/lut-names-staged.so']=b'old'
    before=copy.deepcopy(camera.files)
    with patch.object(requestcleanup.os,'fsync',side_effect=OSError('disk full')):
        with pytest.raises(OSError,match='disk full'):
            requestcleanup.supersede_temporary(camera,tmp_path/'archive',lambda *a,**k:None)
    assert camera.files==before


def test_changing_temporary_state_is_not_deleted(tmp_path):
    camera=Camera(values());camera.files['/tmp/jiritsu/lut-names-staged.so']=b'old'
    def record(event,**kwargs):
        if event=='factory_temporary_archived':camera.files['/tmp/jiritsu/a7c2.names.result']=b'new-report'
    with pytest.raises(ValueError,match='仍在变化'):
        requestcleanup.supersede_temporary(camera,tmp_path/'archive',record)
    assert camera.temp_read('lut-names-staged.so')==b'old'
    assert camera.temp_read('a7c2.names.result')==b'new-report'


@pytest.mark.parametrize('platform',['win32','darwin'])
def test_gui_failed_reset_uses_provided_source_without_older_worker_files(tmp_path,monkeypatch,platform):
    import json
    from unittest.mock import Mock
    from desktopapp import worker
    monkeypatch.setattr(sys,'platform',platform)
    root=tmp_path/'old';root.mkdir()
    prior=dict(mode='factory_reset',phase='NEEDS_REVIEW',factory_path='missing-old-reference',
               identity=dict(model='ILCE-7CM2',serial_sha256='test-body'),resume_from='missing-ancestor')
    (root/'direct.private.json').write_text(json.dumps(prior))
    fresh=Mock();fresh.root=tmp_path/'new'
    fresh.run_direct.return_value=dict(mode='factory_reset',phase='AWAITING_RELOAD')
    reference={'source':'user-provided'}
    with patch('looktool.direct.DirectJob',return_value=fresh), \
         patch('desktopapp.official.prepare_restore',return_value=(reference,str(tmp_path/'reference.json'),None)) as prepare:
        result=worker.run('direct_resume_factory',dict(workspace=str(fresh.root),failed_workspace=str(root),
            firmware='2.01',power_confirmed=True,sony_firmware='user-owned.DAT',restore_voice=False),tmp_path)
    prepare.assert_called_once()
    assert prepare.call_args.args[0]['sony_firmware']=='user-owned.DAT'
    assert fresh.run_direct.call_args.kwargs['factory_values']==reference
    fresh.continue_factory.assert_not_called()
    assert fresh.run_direct.call_args.args==('factory_reset',)
    assert result['phase']=='AWAITING_RELOAD' and not result['recovery_complete']


@pytest.mark.parametrize('platform', ['win32', 'darwin'])
@pytest.mark.parametrize('mode', ['factory_reset', 'look_import', 'slot_default', 'fl23_enable',
    'fl23_disable', 'vertical_enable', 'vertical_disable', 'preview_pending', 'install_all',
    'sound_enable', 'sound_disable', 'sound_restore'])
def test_every_fresh_direct_write_supersedes_old_names_sound_and_restore_files(tmp_path,monkeypatch,platform,mode):
    monkeypatch.setattr(sys, 'platform', platform)
    camera = Camera(values())
    leftovers = {'a7c2-preview-staged.so': b'legacy worker',
                 'lut-names-staged.so': b'unrelated old task worker',
                 'a7c2.names.result': b'not a valid old result',
                 'shutter.probe.result': b'unknown old sound outcome',
                 'checkpoint.program.request': b'old restore request'}
    camera.files.update({'/tmp/jiritsu/' + name: raw for name, raw in leftovers.items()})
    camera.files['/tmp/jiritsu/unrelated-user-file'] = b'keep'
    job = SimDirect(tmp_path / 'fresh', factory=lambda: camera)
    def plan(current, *args, **kwargs):
        assert all(camera.temp_read(name, True) is None for name in leftovers)
        target = dict(current)
        target['appFw.so'] = current['appFw.so'][:3] + b'\x12\x34' + current['appFw.so'][5:]
        return target, [{KEYS[0]: b'\x05'}, {}], None
    with patch.object(direct, 'plan', side_effect=plan), \
            patch('looktool.bundle.plan', side_effect=plan), patch.object(job, 'prepare_vertical'), \
            patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile):
        result = job.run_direct(mode, version='2.01', power_confirmed=True,
                                factory_values={'builtin': True}, slot=1,
                                bundle_options=dict(looks=[], fl23=False, sound=False))
    assert result['phase'] == 'AWAITING_RELOAD'
    assert camera.files['/tmp/jiritsu/unrelated-user-file'] == b'keep'
    archive = job.root / ('evidence/sound-current' if mode.startswith('sound_') else
                          'evidence/superseded-temporary')
    for name, raw in leftovers.items():
        path = archive / (name + '.before.private.bin' if mode.startswith('sound_') else name)
        assert path.read_bytes() == raw


@pytest.mark.parametrize('platform', ['win32', 'darwin'])
@pytest.mark.parametrize('action', ['direct_factory_reset', 'direct_resume_factory'])
@pytest.mark.parametrize('old_record', [b'{broken', b'null',
    b'{"mode":"factory_reset","phase":"AWAITING_RELOAD","identity":{"model":"ILCE-7CM2","serial_sha256":"other-body"}}'])
def test_restore_buttons_never_discover_read_or_verify_an_old_task(tmp_path,monkeypatch,platform,action,old_record):
    from unittest.mock import Mock
    from desktopapp import worker
    monkeypatch.setattr(sys, 'platform', platform)
    old = tmp_path / 'old'
    old.mkdir()
    (old / 'direct.private.json').write_bytes(old_record)
    job = Mock(root=tmp_path / 'fresh')
    job.run_direct.return_value = dict(mode='factory_reset', phase='AWAITING_RELOAD')
    job.verify_direct.side_effect = AssertionError('Old verification must not run')
    original_read = Path.read_text
    def reject_old_read(path, *args, **kwargs):
        if path.parent == old:
            raise AssertionError('Old task must not be read')
        return original_read(path, *args, **kwargs)
    with patch('looktool.direct.DirectJob', return_value=job), \
            patch('desktopapp.official.prepare_restore',return_value=({'source':'user-provided'},str(tmp_path/'reference.json'),None)) as prepare, \
            patch.object(Path, 'read_text', reject_old_read):
        result = worker.run(action, dict(workspace=str(job.root), firmware='2.01',
            power_confirmed=True, failed_workspace=str(old),sony_firmware='user-owned.DAT',restore_voice=False), tmp_path)
    prepare.assert_called_once()
    assert prepare.call_args.args[0]['sony_firmware']=='user-owned.DAT'
    job.run_direct.assert_called_once()
    assert job.run_direct.call_args.args == ('factory_reset',)
    assert job.run_direct.call_args.kwargs.get('recovery_identity') is None
    assert (old / 'direct.private.json').read_bytes() == old_record
    assert result['phase'] == 'AWAITING_RELOAD'


@pytest.mark.parametrize('platform', ['win32', 'darwin'])
def test_selected_backup_restore_also_supersedes_stale_shared_files(tmp_path,monkeypatch,platform):
    from test_checkpoint import SimRollback
    from looktool import checkpoint
    monkeypatch.setattr(sys, 'platform', platform)
    original = values()
    camera = Camera(original)
    archive = tmp_path / 'backup/checkpoint.private.zip'
    checkpoint.write(archive, original, camera.identity, provenance={'type': 'synthetic-backup'})
    camera.files['/usr/lib/appFw.so'] = b'\x03' + camera.files['/usr/lib/appFw.so'][1:]
    leftovers = {'checkpoint.program.result': b'incomplete report with no task record',
                 'a7c2.names.request': b'old names request',
                 'shutter.staged.so': b'old sound worker'}
    camera.files.update({'/tmp/jiritsu/' + name: raw for name, raw in leftovers.items()})
    job = SimRollback(tmp_path / 'fresh-backup-restore', factory=camera)
    with patch.object(checkpoint, 'recipe_keys', return_value=KEYS), \
            patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile):
        result = job.run(archive, 90, '2.01')
    assert result['phase'] == 'RESTORED_AWAITING_RELOAD'
    assert camera.files['/usr/lib/appFw.so'] == original['appFw.so']
    for name, raw in leftovers.items():
        assert camera.temp_read(name, True) is None
        assert (job.root / 'evidence/superseded-temporary' / name).read_bytes() == raw
