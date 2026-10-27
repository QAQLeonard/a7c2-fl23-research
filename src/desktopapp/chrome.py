"""Window chrome: navigation, page headings and the status lamp.

Pure presentation. Nothing here starts jobs, reads job records or opens USB.
"""
from PySide6 import QtCore, QtWidgets as W
from .theme import STATES

PAGES = ('首页 · 一键安装', '连接与驱动', '恢复原厂功能', 'FL2 / FL3', '自定义创意外观', '竖屏显示', '电子快门声音')


def navigation():
    nav = W.QListWidget()
    nav.setObjectName('nav')
    nav.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    nav.addItems(PAGES)
    return nav


def page_head(layout, title, detail):
    """Serif page title over a muted one-paragraph summary."""
    label = W.QLabel(title)
    label.setObjectName('pageTitle')
    layout.addWidget(label)
    hint = W.QLabel(detail)
    hint.setObjectName('pageHint')
    hint.setWordWrap(True)
    hint.setProperty('hint', True)
    layout.addWidget(hint)
    layout.addSpacing(10)


def place(layout, widget):
    """Add a button at its natural width in a column; rows keep sharing the width."""
    if isinstance(layout, W.QVBoxLayout):
        layout.addWidget(widget, 0, QtCore.Qt.AlignLeft)
    else:
        layout.addWidget(widget)


def set_state(lamp, state):
    """Color the status lamp: idle, running, ok, wait (power cycle needed) or error."""
    lamp.setStyleSheet('background:%s;border-radius:4px;' % STATES[state])
    lamp.setProperty('state', state)
