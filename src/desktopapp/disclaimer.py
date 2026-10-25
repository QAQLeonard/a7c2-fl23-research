"""Explicit, per-launch GUI consent. No camera access or remembered acceptance."""
import re
from PySide6 import QtCore,QtWidgets as W
from .paths import ROOT
from .theme import WINDOW as STYLE

HEADING='## 风险告知与使用声明'
SUMMARY=(
    '<p><b>本工具属于非官方独立研究，仅供学习与技术交流，与索尼无隶属、授权或背书关系。</b></p>'
    '<h3 style="font-size:19px;color:#a51524;">严禁收费代刷、售卖或付费解锁本工具</h3>'
    '<p><b>作者使用要求：严禁收费代刷、售卖或付费解锁本工具，包括远程收费安装、倒卖或打包售卖工具、'
    '通过激活码／加密狗收费解锁，以及收费搭售本工具。作者免费提供本项目，不提供有偿代刷。</b></p>'
    '<h3 style="font-size:19px;color:#a51524;">严禁冒充官方或作者授权</h3>'
    '<p><b>作者从未授权任何人以作者或索尼官方名义开展收费服务、宣传或承诺保修。'
    '严禁冒充索尼官方、作者本人或授权服务商；第三方收费不代表作者参与、认可、背书或担保。</b></p>'
    '<h3 style="font-size:18px;">风险自担 · 不保证恢复成功</h3>'
    '<p><b>修改相机可能导致无法开机、反复重启、功能异常或数据丢失，也可能影响官方更新、保修或维修。'
    '写入成功及读回一致不代表启动安全，恢复功能也不保证能救回相机。</b></p>'
    '<p><b>仅操作本人合法持有或已获机主明确授权的设备；请妥善备份重要数据。'
    '如无法承担设备损坏与维修风险，请退出。</b></p>'
    '<p><b>本发行版的项目原创代码采用 MIT＋Commons Clause 1.0，按其中 Sell 定义限制上述收费行为。第三方及旧版许可分别保留；'
    '本声明不排除法律禁止免除的责任。</b></p>'
)


def terms_text():
    text=(ROOT/'docs/zh-CN/notices.md').read_text(encoding='utf-8')
    return text[text.index(HEADING):]


class TermsDialog(W.QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('风险告知与使用声明 · 全文')
        self.resize(760,680);self.setStyleSheet(STYLE)
        layout=W.QVBoxLayout(self)
        self.body=W.QTextBrowser()
        self.body.document().setBaseUrl(QtCore.QUrl.fromLocalFile(str(ROOT/'docs/zh-CN/notices.md')))
        # Qt's CommonMark parser needs boundaries around CJK bold spans.
        self.body.setMarkdown(re.sub(r'\*\*(.+?)\*\*',r' **\1** ',terms_text()))
        self.body.setOpenExternalLinks(True)
        layout.addWidget(self.body)
        close=W.QPushButton('关闭全文，返回确认')
        close.clicked.connect(self.reject);layout.addWidget(close)


class ConsentDialog(W.QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('使用前请阅读 · A7C II Tools')
        self.resize(760,740);self.setMinimumWidth(640);self.setStyleSheet(STYLE)
        layout=W.QVBoxLayout(self);layout.setContentsMargins(26,22,26,22);layout.setSpacing(14)
        title=W.QLabel('使用前，请先了解风险')
        title.setStyleSheet('font-size:23px;font-weight:650;');layout.addWidget(title)
        subtitle=W.QLabel('非官方相机研究工具 · 每次启动均需本人确认')
        subtitle.setProperty('hint',True);layout.addWidget(subtitle)
        summary=W.QLabel(SUMMARY);summary.setWordWrap(True)
        summary.setAlignment(QtCore.Qt.AlignTop|QtCore.Qt.AlignLeft)
        summary.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(summary,1)
        row=W.QHBoxLayout();row.setSpacing(8)
        self.agreement=W.QCheckBox('我已阅读并接受')
        self.agreement.setObjectName('disclaimerAgreement')
        row.addWidget(self.agreement)
        self.terms_link=W.QLabel('<a href="terms">《风险告知与使用声明》</a>')
        self.terms_link.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        self.terms_link.linkActivated.connect(self.show_terms)
        row.addWidget(self.terms_link);row.addStretch();layout.addLayout(row)
        buttons=W.QHBoxLayout();buttons.addStretch()
        leave=W.QPushButton('不同意，退出');leave.clicked.connect(self.reject)
        buttons.addWidget(leave)
        self.continue_button=W.QPushButton('接受并进入')
        self.continue_button.setProperty('primary',True)
        self.continue_button.setEnabled(False);self.continue_button.setDefault(True)
        self.agreement.toggled.connect(self.continue_button.setEnabled)
        self.continue_button.clicked.connect(self.accept)
        buttons.addWidget(self.continue_button);layout.addLayout(buttons)

    def show_terms(self,*args):
        TermsDialog(self).exec()

    def accept(self):
        if self.agreement.isChecked():super().accept()


def require_consent():
    return ConsentDialog().exec()==W.QDialog.Accepted
