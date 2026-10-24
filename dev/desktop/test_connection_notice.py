"""Informational startup dialog; no implicit USB work or installer consent."""
import sys
from unittest.mock import Mock,patch

from desktopapp import connectionguide
from desktopapp import window


def test_notice_distinguishes_camera_prompt_from_actual_tool_failure():
    for phrase in ('请检查所连接的设备','正常现象','完整日志','海量存储','所有读写已结束','诊断包'):
        assert phrase in connectionguide.TEXT
    with patch.object(window.W.QMessageBox,'information') as popup:
        window.Window.show_connection_notice(Mock())
    popup.assert_called_once()
    assert popup.call_args.args[1:]==(connectionguide.TITLE,connectionguide.TEXT)


def test_gui_start_schedules_notice_after_show_before_any_operation():
    app=Mock();app.exec.return_value=0
    with patch.object(window.W.QApplication,'instance',return_value=app), \
         patch.object(window,'require_consent',return_value=True), \
         patch.object(window,'Window') as ctor, \
         patch.object(window.QtCore.QTimer,'singleShot') as timer, \
         patch.object(sys,'argv',['A7C2Tools.exe']):
        assert window.main()==0
    ctor.return_value.show.assert_called_once()
    timer.assert_called_once_with(0,ctor.return_value.show_connection_notice)
    ctor.return_value.launch.assert_not_called()
