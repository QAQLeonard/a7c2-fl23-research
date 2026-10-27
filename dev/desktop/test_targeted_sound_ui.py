"""The shared custom-sound entry forwards the selected capture target."""
from unittest.mock import patch
import pytest
from PySide6 import QtWidgets as W
from desktopapp import window
from desktopapp.actions import sound


@pytest.fixture(scope='module')
def app():return W.QApplication.instance() or W.QApplication([])


@pytest.mark.parametrize('selection',['mechanical','electronic','both'])
def test_save_button_sends_the_current_target(app,selection):
    with patch.object(window,'load_settings',return_value={}):view=window.Window()
    view.sound_target.setCurrentIndex(view.sound_target.findData(selection))
    button=next(b for b in view.findChildren(W.QPushButton) if b.text()=='保存到所选快门')
    with patch.object(view,'launch') as launch:button.click()
    assert launch.call_args.args[0]=='sound_install'
    assert launch.call_args.args[1]['sound_target']==selection
    assert all(any(label in b.text() for b in view.findChildren(W.QPushButton)) for label in (
        '开启机械快门音效','关闭机械快门音效','开启电子快门专属音效','关闭电子快门专属音效'))
    view.close()


def test_targeted_save_does_not_fall_through_to_the_legacy_electronic_installer():
    with patch('targeted_sound.run',return_value=dict(sound_target='mechanical')) as save:
        result=sound.run('sound_install',dict(sound_target='mechanical',workspace='selected'))
    assert result['sound_target']=='mechanical'
    assert save.call_args.args[0]['sound_target']=='mechanical'
