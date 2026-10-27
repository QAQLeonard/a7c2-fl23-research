"""The operation interface remains closed until explicit per-launch consent."""
import sys
from unittest.mock import Mock,patch
import pytest
from PySide6 import QtCore,QtWidgets as W
from desktopapp import disclaimer,window


@pytest.fixture(scope='module')
def app():
    return W.QApplication.instance() or W.QApplication([])


def test_checkbox_is_required_and_acceptance_is_not_remembered(app):
    dialog=disclaimer.ConsentDialog()
    assert not dialog.agreement.isChecked() and not dialog.continue_button.isEnabled()
    dialog.accept()
    assert dialog.result()==W.QDialog.Rejected
    dialog.agreement.setChecked(True)
    assert dialog.continue_button.isEnabled()
    dialog.agreement.setChecked(False)
    assert not dialog.continue_button.isEnabled()
    dialog.agreement.setChecked(True);dialog.continue_button.click()
    assert dialog.result()==W.QDialog.Accepted
    again=disclaimer.ConsentDialog()
    assert not again.agreement.isChecked() and not again.continue_button.isEnabled()


def test_reading_link_does_not_accept_or_check_the_parent(app):
    dialog=disclaimer.ConsentDialog()
    with patch.object(disclaimer.TermsDialog,'exec',return_value=W.QDialog.Rejected) as opened:
        dialog.terms_link.linkActivated.emit('terms')
    opened.assert_called_once()
    assert not dialog.agreement.isChecked() and dialog.result()==W.QDialog.Rejected
    reader=disclaimer.TermsDialog(dialog)
    text=reader.body.toPlainText()
    assert all(phrase in text for phrase in ('风险告知','PolyForm Noncommercial','DMCA','同机备份','重大过失','从未授权任何人',
        '禁止一切商用牟利行为','严禁冒充官方或作者授权'))
    assert '不撤回' not in text


def test_long_notice_stays_readable_in_a_small_window(app):
    dialog=disclaimer.ConsentDialog()
    dialog.resize(640,500);dialog.show();app.processEvents()
    text=dialog.summary.toPlainText()
    assert text.index('可能变砖')<text.index('禁止一切商用牟利行为')
    bar=dialog.summary.verticalScrollBar()
    assert bar.maximum()>0
    bar.setValue(bar.maximum());app.processEvents()
    assert bar.value()==bar.maximum()
    assert dialog.continue_button.isVisible() and not dialog.continue_button.isEnabled()
    assert not dialog.agreement.isChecked()
    dialog.close()


@pytest.mark.parametrize('exit_action',['reject','close'])
def test_decline_or_window_close_does_not_enter_the_app(app,exit_action):
    dialog=disclaimer.ConsentDialog()
    QtCore.QTimer.singleShot(0,getattr(dialog,exit_action))
    with patch.object(disclaimer,'ConsentDialog',return_value=dialog):
        assert not disclaimer.require_consent()


def test_startup_stops_before_constructing_main_window_on_decline():
    app=Mock()
    with patch.object(window.W.QApplication,'instance',return_value=app), \
         patch.object(window,'require_consent',return_value=False), \
         patch.object(window,'Window') as main_window, \
         patch.object(sys,'argv',['A7C2Tools.exe']):
        assert window.main()==0
    main_window.assert_not_called();app.exec.assert_not_called()


def test_startup_accepts_before_constructing_or_showing_main_window():
    events=[];app=Mock();app.exec.return_value=0
    view=Mock();view.show.side_effect=lambda:events.append('show')
    def consent():events.append('consent');return True
    def create():events.append('construct');return view
    with patch.object(window.W.QApplication,'instance',return_value=app), \
         patch.object(window,'require_consent',side_effect=consent), \
         patch.object(window,'Window',side_effect=create), \
         patch.object(window.QtCore.QTimer,'singleShot'), \
         patch.object(sys,'argv',['A7C2Tools.exe']):
        assert window.main()==0
    assert events==['consent','construct','show']
