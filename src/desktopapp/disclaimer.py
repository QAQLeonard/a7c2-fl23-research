"""Explicit, per-launch GUI consent. No camera access or remembered acceptance."""
import re
from PySide6 import QtCore,QtWidgets as W
from .paths import ROOT
from .theme import WINDOW as STYLE

HEADING='## 风险告知与使用声明'
SUMMARY=(
    '<p><b>本工具属于非官方独立研究，仅供学习与技术交流，与索尼无隶属、授权或背书关系。</b></p>'
    '<p><b>风险自担：</b>修改相机可能导致无法开机、反复重启、功能异常或数据丢失，'
    '也可能影响官方更新、保修或维修。写入成功及读回一致不代表启动安全，恢复功能也不保证能救回相机。</p>'
    '<p><b>严禁冒充官方或作者授权：</b>作者免费提供本项目，不提供有偿代刷，明确反对第三方'
    '倒卖、收费远程安装、激活码／加密狗及捆绑硬件牟利。不得假借索尼或作者名义宣传、收费或承诺保修。</p>'
    '<p>仅操作本人合法持有或已获机主明确授权的设备；请妥善备份重要数据。'
    '如无法承担设备损坏与维修风险，请退出。</p>'
    '<p>代码继续采用 MIT；本声明不撤回该许可证已授予的商用及再分发权利，'
    '也不排除法律禁止免除的责任。</p>'
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
        self.resize(710,510);self.setMinimumWidth(580);self.setStyleSheet(STYLE)
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
