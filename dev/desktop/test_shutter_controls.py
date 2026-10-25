"""The sound page dispatches distinct controls; startup never opens USB."""
from unittest.mock import patch
from PySide6 import QtWidgets as W
from desktopapp import shutterguide,window
from desktopapp.actions.catalog import CAMERA_ACTIONS,POWER_ACTIONS


def test_sound_page_dispatches_four_independent_switches(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path))
    app=W.QApplication.instance() or W.QApplication([])
    with patch.object(window.Window,'launch') as launch:
        view=window.Window()
        try:
            for title,action in (
                ('打开／恢复机械快门自带音效','sound_mechanical_on'),
                ('关闭机械快门音效','sound_mechanical_off'),
                ('开启电子快门专属音效','sound_on'),
                ('关闭电子快门专属音效','sound_off')):
                button=next(b for b in view.findChildren(W.QPushButton) if b.text()==title)
                button.click()
                assert launch.call_args.args[0]==action
                assert launch.call_args.args[1]['firmware']=='2.01'
                assert action in CAMERA_ACTIONS and action in POWER_ACTIONS
        finally:view.close()
    assert '不切换快门类型' in shutterguide.TEXT
    assert '全局“音频信号”' in shutterguide.TEXT
