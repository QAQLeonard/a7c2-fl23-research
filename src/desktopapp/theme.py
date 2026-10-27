"""Color tokens and Qt style sheets for the desktop GUI.

A warm, quiet look: ivory pages, a cream sidebar, white rounded cards, serif
page titles and one clay accent for primary actions and checked states. Only
visual values live here; widgets stay in `window.py`, `lookeditor.py` and
`chrome.py`.
"""
from string import Template
from .paths import ROOT

COLORS = dict(
    window='#faf9f5', sidebar='#f0eee6', surface='#ffffff', raised='#f5f4ed', group='#ffffff',
    hover='#e8e6dc', border='#e5e3da', strong='#d1cfc5', strong_hover='#b0aea5',
    text='#141413', muted='#6f6e68', faint='#b0aea5', nav_text='#3d3d3a',
    log='#f5f4ed', log_text='#3d3d3a',
    accent='#d97757', accent_hover='#c96846', accent_pressed='#b3583a', accent_text='#ffffff',
    accent_soft='#f7e6de', accent_line='#ebbca8', accent_disabled_text='#ffffff', selection='#f3d9cd',
    warning='#a45a12', danger='#b3261e', danger_soft='#f9e5e2', ok='#5b8c51',
)
STATES = dict(idle=COLORS['faint'], running=COLORS['accent'], ok=COLORS['ok'],
              wait=COLORS['warning'], error=COLORS['danger'])
SANS = '"Segoe UI","Helvetica Neue","PingFang SC","Microsoft YaHei UI","Microsoft YaHei","Noto Sans CJK SC"'
SERIF = '"Tiempos Headline","Georgia","Times New Roman","Songti SC","Noto Serif CJK SC","Microsoft YaHei UI","Microsoft YaHei"'
MONO = '"Cascadia Mono","Consolas","Menlo","Microsoft YaHei"'
ICONS = ROOT / 'src/desktopapp/assets'


def _sheet(text):
    return Template(text).substitute(COLORS, sans=SANS, serif=SERIF, mono=MONO,
                                     check=(ICONS / 'check.svg').as_posix(),
                                     chevron=(ICONS / 'chevron-down.svg').as_posix(),
                                     chevron_up=(ICONS / 'chevron-up.svg').as_posix())


_COMMON = '''
QLabel[hint="true"],QLabel[muted="true"] {color:$muted;}
QLabel[warning="true"] {color:$warning;}
QComboBox::drop-down {border:0;width:24px;}
QComboBox::down-arrow {image:url("$chevron");width:10px;height:10px;}
QComboBox QAbstractItemView {background:$surface;border:1px solid $border;color:$text;padding:4px;
    selection-background-color:$hover;selection-color:$text;outline:0;}
QPushButton:hover {background:$raised;border-color:$strong;}
QPushButton:pressed {background:$hover;}
QPushButton:disabled {background:$raised;color:$faint;border-color:$border;}
QPushButton[primary="true"] {background:$accent;color:$accent_text;border-color:$accent;font-weight:600;}
QPushButton[primary="true"]:hover {background:$accent_hover;border-color:$accent_hover;}
QPushButton[primary="true"]:pressed {background:$accent_pressed;}
QPushButton[primary="true"]:disabled {background:$accent_line;color:$accent_disabled_text;border-color:$accent_line;}
QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus,QPlainTextEdit:focus {border-color:$accent;}
QLineEdit:hover,QComboBox:hover,QSpinBox:hover,QDoubleSpinBox:hover {border-color:$strong_hover;}
QLineEdit:disabled,QComboBox:disabled {color:$faint;}
QScrollArea {border:0;background:transparent;}
QScrollBar:vertical {background:transparent;width:8px;margin:2px;}
QScrollBar::handle:vertical {background:$strong;border-radius:3px;min-height:30px;}
QScrollBar::handle:vertical:hover {background:$strong_hover;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QAbstractSpinBox::up-button,QAbstractSpinBox::down-button {border:0;background:transparent;width:16px;}
QAbstractSpinBox::up-button:hover,QAbstractSpinBox::down-button:hover {background:$hover;}
QAbstractSpinBox::up-arrow {image:url("$chevron_up");width:10px;height:10px;}
QAbstractSpinBox::down-arrow {image:url("$chevron");width:10px;height:10px;}
QToolTip {background:$text;color:$window;border:0;border-radius:6px;padding:6px 8px;}
'''

WINDOW = _sheet('''
QWidget {font-family:$sans;font-size:13px;color:$text;background:$window;}
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QPlainTextEdit {background:$surface;border:1px solid $border;border-radius:8px;
    padding:7px 9px;selection-background-color:$selection;selection-color:$text;}
QPlainTextEdit {background:$log;color:$log_text;font-family:$mono;font-size:12px;border-radius:10px;padding:8px 10px;}
QPushButton {background:$surface;border:1px solid $strong;border-radius:8px;padding:8px 16px;color:$text;}
QWidget#pageBody,QStackedWidget {background:$window;}

QFrame#sidebar {background:$sidebar;border:0;border-right:1px solid $border;}
QFrame#sidebar QLabel {background:transparent;}
QLabel#brand {font-family:$serif;font-size:21px;color:$text;}
QLabel#edition {color:$muted;font-size:11px;}
QLabel#fieldLabel {color:$muted;font-size:12px;}
QFrame#sidebar QComboBox {background:$surface;}
QListWidget#nav {background:transparent;border:0;outline:0;}
QListWidget#nav::item {padding:9px 12px;margin:1px 0;border-radius:8px;color:$nav_text;}
QListWidget#nav::item:hover {background:$hover;color:$text;}
QListWidget#nav::item:selected {background:$hover;color:$text;font-weight:600;}

QLabel#pageTitle {font-family:$serif;font-size:28px;color:$text;}
QLabel#pageHint {color:$muted;font-size:14px;}

QGroupBox {background:$group;border:1px solid $border;border-radius:12px;margin-top:26px;padding:18px 14px 12px;
    font-size:12px;font-weight:600;color:$muted;}
QGroupBox::title {subcontrol-origin:margin;left:4px;top:4px;padding:0;background:transparent;}
QGroupBox QLabel,QGroupBox QCheckBox {background:transparent;font-size:13px;font-weight:400;color:$text;}

QCheckBox {spacing:10px;padding:5px 0;background:transparent;}
QCheckBox::indicator {width:16px;height:16px;border:1px solid $strong_hover;border-radius:4px;background:$surface;}
QCheckBox::indicator:hover {border-color:$accent;}
QCheckBox::indicator:checked {background:$accent;border-color:$accent;image:url("$check");}
QCheckBox::indicator:disabled {background:$raised;border-color:$border;}
QCheckBox::indicator:checked:disabled {background:$accent_line;border-color:$accent_line;}
QCheckBox:disabled {color:$faint;}
QToolButton {background:transparent;border:0;color:$muted;padding:6px 0;}
QToolButton:hover,QToolButton:checked {color:$text;}

QFrame#console {background:$window;border:0;border-top:1px solid $border;}
QFrame#console QLabel {background:transparent;}
QLabel#status {font-size:13px;}
QProgressBar {border:0;background:$hover;border-radius:2px;max-height:4px;min-height:4px;}
QProgressBar::chunk {background:$accent;border-radius:2px;}

QMessageBox,QDialog {background:$window;}
QMessageBox QLabel {background:transparent;}
QTextBrowser {background:$surface;border:1px solid $border;border-radius:10px;padding:10px;}
''' + _COMMON)

EDITOR = _sheet('''
QWidget {font-family:$sans;font-size:13px;color:$text;background:transparent;}
QLabel[heading="true"] {font-family:$serif;font-size:19px;}
QLabel[summary="true"] {font-size:14px;font-weight:600;}
QFrame[card="true"] {background:$group;border:1px solid $border;border-radius:12px;}
QFrame[card="true"][summary="true"] {background:$raised;}
QFrame[card="true"] QLabel {background:transparent;}
QComboBox,QLineEdit {background:$surface;border:1px solid $strong;border-radius:8px;padding:7px 9px;min-height:19px;
    selection-background-color:$selection;}
QComboBox {padding-right:25px;}
QPushButton {background:$surface;border:1px solid $strong;border-radius:8px;padding:8px 16px;color:$text;}
QWidget#operationDetails,QStackedWidget#operationStack {background:transparent;}
''' + _COMMON + '''
QComboBox::down-arrow {image:none;}
QPushButton[quiet="true"] {background:transparent;border:0;color:$muted;padding:6px 10px;}
QPushButton[quiet="true"]:hover {background:$danger_soft;color:$danger;}
''')
