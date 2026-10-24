"""Optional current-state snapshots stay read-only and never become factory points."""
import json
from pathlib import Path
from unittest.mock import Mock,patch
from zipfile import ZipFile
import pytest
from desktopapp import backup,recovery,worker,jobs,screenreader
from looktool import checkpoint
from test_checkpoint import Camera,values,BODY


def arguments(tmp_path,**extra):
    return dict(firmware='2.01',workspace=str(tmp_path/'backup'),**extra)


def test_project_backup_matches_current_bytes_and_is_not_auto_original(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    current=values();camera=Camera(current)
    # Backup must not invoke a native program or issue any setting/file write.
    camera.temp_write=Mock(side_effect=AssertionError('No native staging'))
    camera.property_write=Mock(side_effect=AssertionError('No setting writes'))
    report=backup.run(arguments(tmp_path),tmp_path,factory=lambda:camera)
    assert report['phase']=='COMPLETE' and report['state']=='current-not-factory'
    manifest,restored=checkpoint.read(report['project_backup'])
    assert restored==current
    assert manifest['provenance']['type']=='current-project-backup'
    assert report['camera_firmware_written'] is report['camera_settings_written'] is False
    assert not report.get('voice_backup')
    camera.temp_write.assert_not_called();camera.property_write.assert_not_called()
    assert recovery.discover([tmp_path])==[]
    assert recovery.describe(report['project_backup'])['identity']==BODY


def test_voice_sidecar_has_complete_files_and_no_project_programs(tmp_path):
    camera=Camera(values());read=camera.read
    def voice(path,missing=False):
        return Path(path).name.encode() if path.startswith(screenreader.CAMERA_ROOT) else read(path,missing)
    camera.read=voice
    report=backup.run(arguments(tmp_path,include_voice=True),tmp_path,factory=lambda:camera)
    assert report['voice_backup']['files']==20
    with ZipFile(report['voice_backup']['path']) as z:
        assert set(z.namelist())==set(screenreader.NAMES)|{'manifest.json'}
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['identity']==BODY
        for name in screenreader.NAMES:assert z.read(name)==name.encode()


def test_voice_failure_preserves_project_backup_without_false_completion(tmp_path):
    camera=Camera(values())
    with pytest.raises(ValueError,match='语音包备份未完成'):
        backup.run(arguments(tmp_path,include_voice=True),tmp_path,factory=lambda:camera)
    folder=tmp_path/'backup'
    assert checkpoint.read(folder/'checkpoint.private.zip')[1]==values()
    assert not (folder/'voice-resources.private.zip').exists()
    report=json.loads((folder/'backup.private.json').read_text())
    assert report['phase']=='FAILED' and report['project_backup_complete']


def test_interrupted_capture_is_not_published(tmp_path):
    camera=Camera(values());camera.read=Mock(side_effect=TimeoutError('read interrupted'))
    with pytest.raises(TimeoutError):backup.run(arguments(tmp_path),tmp_path,factory=lambda:camera)
    assert not (tmp_path/'backup/checkpoint.private.zip').exists()
    assert json.loads((tmp_path/'backup/backup.private.json').read_text())['phase']=='FAILED'


@pytest.mark.parametrize('reason',['version','existing'])
def test_invalid_destination_or_version_never_connects(tmp_path,reason):
    args=arguments(tmp_path)
    if reason=='version':args['firmware']='2.00'
    else:Path(args['workspace']).mkdir()
    connect=Mock(side_effect=AssertionError('No connection'))
    with pytest.raises(ValueError):backup.run(args,tmp_path,factory=connect)
    connect.assert_not_called()


def test_dispatch_and_privilege_category_keep_backup_out_of_power_actions(tmp_path):
    with patch.object(backup,'run',return_value={'phase':'COMPLETE'}) as run:
        result=worker.run('backup_current',arguments(tmp_path),tmp_path)
    assert result['phase']=='COMPLETE' and run.call_count==1
    assert 'backup_current' in jobs.CAMERA_ACTIONS
    assert 'backup_current' not in jobs.POWER_ACTIONS


def test_ui_backup_is_optional_and_creates_fresh_read_only_request(tmp_path,monkeypatch):
    from PySide6 import QtWidgets as W
    from desktopapp.window import Window
    app=W.QApplication.instance() or W.QApplication([])
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    window=Window();window.timer.stop()
    try:
        button=window.findChild(W.QPushButton,'action_backup_current')
        assert button and not window.backup_voice.isChecked()
        window.fields['backup_folder'].setText(str(tmp_path/'saved'))
        window.backup_voice.setChecked(True)
        with patch.object(W.QMessageBox,'question',side_effect=AssertionError('Backup does not write')), \
             patch('desktopapp.window.QtCore.QProcess'):
            button.click()
        request=json.loads((window.current_job/'request.private.json').read_text())
        assert request['action']=='backup_current'
        assert request['arguments']['include_voice'] is True
        assert Path(request['arguments']['workspace']).parent==tmp_path/'saved'
        assert window.camera_operation and not window.stop.isEnabled()
    finally:
        window.process=None;window.close()
