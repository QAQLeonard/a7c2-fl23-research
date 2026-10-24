"""Incremental custom-slot editor. This module never opens a camera."""
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets as W
from .theme import COLORS, EDITOR as STYLE


def label(text, *, muted=False):
    result=W.QLabel(text)
    result.setProperty('muted',muted)
    return result


class Choice(W.QComboBox):
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QtGui.QPainter(self);painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen);painter.setBrush(QtGui.QColor(COLORS['muted']))
        x,y=self.width()-13,self.height()//2
        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x-4,y-2),QtCore.QPoint(x+4,y-2),QtCore.QPoint(x,y+3)]))


class Operation(W.QFrame):
    changed=QtCore.Signal()
    remove_requested=QtCore.Signal(object)

    def __init__(self,slot):
        super().__init__()
        self.setProperty('card',True)
        self.file_path=''
        box=W.QVBoxLayout(self);box.setContentsMargins(17,15,17,15);box.setSpacing(12)
        top=W.QHBoxLayout();box.addLayout(top)
        top.addWidget(label('目标槽位',muted=True))
        self.slot=Choice()
        for number in range(1,7):self.slot.addItem('自订 '+str(number),number)
        self.slot.setCurrentIndex(slot-1);self.slot.setFixedWidth(115)
        top.addWidget(self.slot);top.addSpacing(18)
        top.addWidget(label('本次操作',muted=True))
        self.action=Choice();self.action.addItems(['恢复 ST 默认','写入 A7Look'])
        self.action.setFixedWidth(160);top.addWidget(self.action);top.addStretch()
        remove=W.QPushButton('移除这项');remove.setProperty('quiet',True)
        remove.setToolTip('仅移除此操作项，该槽保持原样')
        remove.clicked.connect(lambda:self.remove_requested.emit(self));top.addWidget(remove)
        self.details=W.QStackedWidget();self.details.setObjectName('operationStack');box.addWidget(self.details)
        restore=W.QWidget();restore.setObjectName('operationDetails');restore_box=W.QHBoxLayout(restore);restore_box.setContentsMargins(0,0,0,0)
        note=label('此槽恢复为 ST 默认；不会找回导入前的旧配方。',muted=True)
        restore_box.addWidget(note);restore_box.addStretch();self.details.addWidget(restore)
        write=W.QWidget();write.setObjectName('operationDetails');grid=W.QGridLayout(write);grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(12);grid.setVerticalSpacing(6)
        grid.addWidget(label('A7Look 文件',muted=True),0,0)
        grid.addWidget(label('机内显示名称',muted=True),0,2)
        self.file=W.QLineEdit();self.file.setReadOnly(True);self.file.setPlaceholderText('请选择 .a7look 文件')
        self.browse=W.QPushButton('选择文件…');self.browse.clicked.connect(self.choose_file)
        self.name=W.QLineEdit();self.name.setPlaceholderText('留空沿用文件内名称')
        grid.addWidget(self.file,1,0);grid.addWidget(self.browse,1,1);grid.addWidget(self.name,1,2)
        grid.setColumnStretch(0,3);grid.setColumnStretch(2,2);self.details.addWidget(write)
        self.action.currentIndexChanged.connect(self.update_mode)
        self.slot.currentIndexChanged.connect(self.changed)
        self.name.textChanged.connect(self.changed)
        self.update_mode()

    def update_mode(self):
        self.details.setCurrentIndex(self.action.currentIndex())
        self.details.setFixedHeight(36 if self.action.currentIndex()==0 else 74)
        self.setFixedHeight(115 if self.action.currentIndex()==0 else 153)
        self.changed.emit()

    def choose_file(self):
        from .profilelibrary import location
        path=W.QFileDialog.getOpenFileName(self,'选择 A7Look 文件',self.file_path or str(location()),'A7Look (*.a7look)')[0]
        if path:self.set_file(path)

    def set_file(self,path):
        self.file_path=str(path);self.file.setText(Path(path).name);self.file.setToolTip(str(path));self.changed.emit()

    def value(self):
        value=dict(slot=self.slot.currentData(),action='restore' if self.action.currentIndex()==0 else 'write')
        if value['action']=='write':value.update(path=self.file_path,name=self.name.text().strip())
        return value


class LookEditor(W.QWidget):
    changed=QtCore.Signal()

    def __init__(self):
        super().__init__();self.rows=[];self._loading=False;self.setStyleSheet(STYLE)
        box=W.QVBoxLayout(self);box.setContentsMargins(0,0,0,0);box.setSpacing(12)
        top=W.QHBoxLayout();self.add=W.QPushButton('+ 添加操作项')
        self.add.clicked.connect(lambda:self.add_row());top.addWidget(self.add)
        top.addWidget(label('新增项默认“恢复 ST 默认”，可切换为写入。',muted=True));top.addStretch();box.addLayout(top)
        self.row_box=W.QVBoxLayout();self.row_box.setSpacing(12);box.addLayout(self.row_box)
        self.empty=W.QFrame();self.empty.setProperty('card',True)
        empty_box=W.QVBoxLayout(self.empty);empty_box.setContentsMargins(20,25,20,25)
        empty_title=label('尚未添加操作项');empty_title.setAlignment(QtCore.Qt.AlignCenter)
        empty_title.setStyleSheet('font-size:17px;font-weight:600;');empty_box.addWidget(empty_title)
        note=label('点击“添加操作项”，选择目标槽位和操作。当前六个槽位均保持原样。',muted=True)
        note.setWordWrap(True);note.setAlignment(QtCore.Qt.AlignCenter);empty_box.addWidget(note)
        self.row_box.addWidget(self.empty)
        summary=W.QFrame();summary.setProperty('card',True)
        summary_box=W.QVBoxLayout(summary);summary_box.setContentsMargins(15,12,15,12)
        self.summary=label('');self.summary.setStyleSheet('font-size:15px;font-weight:600;');summary_box.addWidget(self.summary)
        self.preserved=label('',muted=True);self.preserved.setWordWrap(True);summary_box.addWidget(self.preserved)
        self.validation=label('');self.validation.setProperty('warning',True);self.validation.setWordWrap(True);summary_box.addWidget(self.validation)
        box.addWidget(summary);self.update_summary()

    def add_row(self,slot=None):
        occupied={r.slot.currentData() for r in self.rows};free=[n for n in range(1,7) if n not in occupied]
        if not free:return None
        row=Operation(slot if slot is not None else free[0]);self.rows.append(row)
        row.changed.connect(self.update_summary);row.remove_requested.connect(self.remove_row)
        self.row_box.addWidget(row);self.update_summary();return row

    def remove_row(self,row):
        self.rows.remove(row);self.row_box.removeWidget(row);row.setParent(None);row.deleteLater();self.update_summary()

    def values(self):return [row.value() for row in self.rows]

    def set_operations(self,operations):
        self._loading=True
        try:
            for row in list(self.rows):self.remove_row(row)
            for value in operations:
                row=self.add_row(value['slot'])
                if value.get('action','write')=='write':
                    row.action.setCurrentIndex(1);row.set_file(value.get('path') or value.get('file',''))
                    row.name.setText(value.get('name') or '')
        finally:self._loading=False
        self.update_summary()

    def errors(self):
        values=self.values();slots=[r['slot'] for r in values];errors=[]
        if len(slots)!=len(set(slots)):errors.append('同一槽位只能添加一个操作。')
        missing=[str(r['slot']) for r in values if r['action']=='write' and not r['path']]
        if missing:errors.append('请为自订 '+'、'.join(missing)+' 选择 A7Look 文件。')
        return errors

    def update_summary(self):
        values=self.values();used={r['slot'] for r in values};writes=sum(r['action']=='write' for r in values)
        self.empty.setVisible(not values);self.add.setEnabled(len(values)<6)
        for row in self.rows:
            for i in range(6):row.slot.model().item(i).setEnabled(i+1 not in used or i+1==row.slot.currentData())
        self.summary.setText('本次更改 %d 个槽位：%d 项写入 · %d 项恢复'%(len(values),writes,len(values)-writes))
        kept=[str(n) for n in range(1,7) if n not in used]
        self.preserved.setText('保持原样：'+('自订 '+'、'.join(kept) if kept else '无（六个槽位均在本次清单中）'))
        errors=self.errors()
        self.validation.setText(' '.join(errors));self.validation.setVisible(bool(errors))
        if not self._loading:self.changed.emit()
