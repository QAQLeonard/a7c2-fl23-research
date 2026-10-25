"""Host-only source selection uses normal preparation and never opens USB."""
import json
from unittest.mock import patch
import pytest
from PySide6 import QtWidgets as W
from desktopapp import official
from desktopapp.window import Window


def configure(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path))
    source=tmp_path/'user-owned.DAT';source.write_bytes(b'offline source fixture')
    (tmp_path/'local-recovery-source.private.json').write_text(json.dumps({'sony_firmware':str(source)}))
    return source


def test_blank_source_uses_configured_file_and_normal_program_and_voice_preparation(tmp_path,monkeypatch):
    source=configure(tmp_path,monkeypatch)
    with patch.object(official,'prepare',return_value={'cache':'prepared-cache'}) as prepare, \
         patch.object(official,'load',return_value={'original':'bytes'}), \
         patch.object(official,'regions',return_value={'schema':'test-regions'}) as regions, \
         patch('desktopapp.screenreader.prepare',return_value={'source':'prepared-voice'}) as voice:
        value,path,voice_path=official.prepare_restore({'restore_voice':True})
    prepare.assert_called_once_with(str(source));voice.assert_called_once_with(str(source))
    regions.assert_called_once_with({'original':'bytes'})
    assert json.loads(open(path,encoding='utf-8').read())==value and voice_path=='prepared-voice'


def test_explicit_file_takes_precedence_over_host_default(tmp_path,monkeypatch):
    configure(tmp_path,monkeypatch)
    with patch.object(official,'prepare',return_value={'cache':'cache'}) as prepare, \
         patch.object(official,'load',return_value={}),patch.object(official,'regions',return_value={}), \
         patch('desktopapp.screenreader.prepare') as voice:
        official.prepare_restore({'sony_firmware':'explicit.DAT','restore_voice':False})
    prepare.assert_called_once_with('explicit.DAT');voice.assert_not_called()


def test_missing_host_source_stops_before_preparation(tmp_path,monkeypatch):
    source=configure(tmp_path,monkeypatch);source.unlink()
    with patch.object(official,'prepare') as prepare:
        with pytest.raises(ValueError,match='本机恢复来源不可用'):official.prepare_restore({})
    prepare.assert_not_called()


def test_gui_blank_fields_dispatches_current_restore_with_host_default(tmp_path,monkeypatch):
    configure(tmp_path,monkeypatch)
    app=W.QApplication.instance() or W.QApplication([])
    view=Window();view.timer.stop()
    try:
        assert view.fields['factory_voice_firmware'].text()==''
        assert view.fields['factory_original_backup'].text()==''
        with patch.object(view,'launch') as launch:view.factory_button.click()
        assert launch.call_args.args[0]=='direct_factory_reset'
        assert launch.call_args.args[1]['restore_voice'] is True
    finally:view.close()
