"""Six explicit workflows, background workers and a complete diagnostic log."""
from datetime import datetime
import json
from pathlib import Path
import sys
import uuid
from PySide6 import QtCore, QtGui, QtWidgets as W
from . import VERSION
from . import jobs
from . import presets
from . import reloadguide

DRIVER_HINT = ('\n驱动或连接没有成功：先在“连接与驱动”页卸载驱动后重装；仍不行，'
               '可点该页的“用 Zadig 手动安装驱动”，按说明给 0E8A 和 0336 两个身份分别装 libusbK。')
from . import connectionguide
from .paths import ROOT, data_root, load_settings, write_json
from .theme import WINDOW as STYLE


class Window(W.QMainWindow):
    def __init__(self, *, demo=False):
        super().__init__()
        self.setWindowTitle('A7C II Tools · LUT Preview Test 2' if '--preview-gate-test' in sys.argv else
                            'A7C II Tools · Desktop Preview')
        self.resize(1130, 850)
        self.setMinimumSize(960, 730)
        self.settings = load_settings()
        self.fields, self.buttons = {}, []
        self.current_job = None
        self.log_offset = 0
        self.process = None
        self.demo = demo
        self.camera_operation = False
        self.setStyleSheet(STYLE)
        central = W.QWidget()
        self.setCentralWidget(central)
        layout = W.QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.nav = W.QListWidget()
        self.nav.setFixedWidth(205)
        self.nav.addItems(['首页 · 一键安装', '连接与驱动', '恢复原厂功能', 'FL2 / FL3', '自定义创意外观', '竖屏显示', '电子快门声音'])
        layout.addWidget(self.nav)
        right = W.QVBoxLayout()
        right.setContentsMargins(22, 18, 22, 16)
        layout.addLayout(right, 1)
        heading = W.QHBoxLayout()
        title = W.QLabel('A7C II Tools')
        title.setStyleSheet('font-size:25px;font-weight:650;')
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(W.QLabel('固件版本'))
        self.firmware = W.QComboBox()
        self.firmware.addItems(['2.01'])
        heading.addWidget(self.firmware)
        right.addLayout(heading)
        self.description = W.QLabel(('Windows 测试版' if sys.platform == 'win32' else '桌面开发版') + ' · 一键安装与六个功能入口 · ' + VERSION)
        self.description.setProperty('hint', True)
        right.addWidget(self.description)
        self.pages = W.QStackedWidget()
        right.addWidget(self.pages, 1)
        self.home_page()
        self.connection_page()
        self.recovery_page()
        self.fl23_page()
        self.look_page()
        self.vertical_page()
        self.sound_page()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.progress = W.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        right.addWidget(self.progress)
        self.status = W.QLabel('就绪。选择左侧功能；启动软件不会访问相机。')
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(180)
        self.log.setPlaceholderText('完整运行日志与原始报错会显示在这里。')
        right.addWidget(self.log)
        bottom = W.QHBoxLayout()
        open_log = W.QPushButton('打开任务目录')
        open_log.clicked.connect(self.open_job)
        bottom.addWidget(open_log)
        export = W.QPushButton('导出诊断包')
        export.clicked.connect(self.export_logs)
        bottom.addWidget(export)
        bottom.addStretch()
        self.stop = W.QPushButton('停止离线任务')
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.cancel_offline)
        bottom.addWidget(self.stop)
        right.addLayout(bottom)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll_job)
        self.timer.start(250)

    def page(self, title, detail):
        wrapper = W.QScrollArea()
        wrapper.setWidgetResizable(True)
        body = W.QWidget()
        layout = W.QVBoxLayout(body)
        layout.setContentsMargins(0, 8, 8, 8)
        label = W.QLabel(title)
        label.setStyleSheet('font-size:20px;font-weight:600;')
        layout.addWidget(label)
        hint = W.QLabel(detail)
        hint.setWordWrap(True)
        hint.setProperty('hint', True)
        layout.addWidget(hint)
        wrapper.setWidget(body)
        self.pages.addWidget(wrapper)
        return layout

    def box(self, layout, title):
        group = W.QGroupBox(title)
        form = W.QFormLayout(group)
        form.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow)
        layout.addWidget(group)
        return form

    def advanced(self, layout, title):
        toggle = W.QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(QtCore.Qt.RightArrow)
        content = W.QWidget()
        content.setVisible(False)
        inner = W.QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        toggle.toggled.connect(content.setVisible)
        toggle.toggled.connect(lambda open: toggle.setArrowType(QtCore.Qt.DownArrow if open else QtCore.Qt.RightArrow))
        layout.addWidget(toggle)
        layout.addWidget(content)
        return inner

    def direct_args(self, group, **values):
        work = self.work(group)
        return dict(self.common(), workspace=work, **{key: value for key, value in values.items() if key != 'mode'})

    def setup_args(self):
        root = self.settings.get('setup_work', '')
        state = Path(root, 'setup.private.json') if root else None
        if state is not None and state.is_file():
            saved = json.loads(state.read_text(encoding='utf-8'))
            if saved['phase'] != 'COMPLETE':
                return dict(self.common(), workspace=root, options=saved['options'])
        root = self.work('setup')
        tool = ROOT / ('desktop-assets/exiftool/exiftool.exe' if sys.platform=='win32' else 'desktop-assets/exiftool/exiftool')
        looks = [dict(slot=s, path=self.text('setup_look_' + str(s))) for s in range(1, 7) if self.text('setup_look_' + str(s))]
        options = dict(fl23=self.setup_fl23.isChecked(), sound=self.setup_sound.isChecked(),
            vertical=self.setup_vertical.isChecked(), plugin=self.setup_plugin.isChecked(),
            exiftool=str(tool), looks=[] if self.setup_presets.isChecked() else looks,
            preset_pack=presets.PACK if self.setup_presets.isChecked() else None)
        return dict(self.common(), workspace=root, options=options)

    def home_page(self):
        layout = self.page('一键安装', '六款外观、FL2／FL3、电子快门声及竖屏保存开关合并安装。按提示断电重开后，同一按钮只核对加载；无需逐槽安装。')
        self.setup_presets = W.QCheckBox('安装内置六款外观（替换自订 1–6，原有创意外观保留）')
        self.setup_presets.setChecked(True)
        self.setup_fl23 = W.QCheckBox('启用 FL2／FL3'); self.setup_fl23.setChecked(True)
        self.setup_sound = W.QCheckBox('启用索尼原生电子快门声音'); self.setup_sound.setChecked(True)
        self.setup_vertical = W.QCheckBox('保存开启竖屏拍摄信息显示（重开后自动生效）'); self.setup_vertical.setChecked(True)
        self.setup_plugin = W.QCheckBox('安装 Lightroom 自动识别插件（需要 Lightroom）')
        prior_path=Path(self.settings.get('setup_work',''),'setup.private.json')
        prior=json.loads(prior_path.read_text(encoding='utf-8')) if prior_path.is_file() else {}
        if prior and prior.get('phase')!='COMPLETE':
            options=prior['options']
            self.setup_presets.setChecked(options.get('preset_pack') == presets.PACK)
            for box,key in ((self.setup_fl23,'fl23'),(self.setup_sound,'sound'),(self.setup_vertical,'vertical'),(self.setup_plugin,'plugin')):
                box.setChecked(bool(options.get(key,key!='plugin')))
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(False)

        self.setup_note=W.QLabel('安装尚未结束，请点击“继续安装”，按弹窗完成下一步；需要断电时，接回 USB 后仍点击此按钮。')
        self.setup_note.setWordWrap(True)
        self.setup_note.setVisible(bool(prior) and prior.get('phase')!='COMPLETE')
        layout.addWidget(self.setup_note)
        layout.addWidget(self.setup_presets)
        self.setup_preset_summary = W.QLabel(presets.SUMMARY)
        self.setup_preset_summary.setWordWrap(True)
        if prior and prior.get('phase')!='COMPLETE':
            names = ['%s %s' % (r['slot'], r.get('name', Path(r['path']).stem)) for r in prior['options'].get('looks', [])]
            self.setup_preset_summary.setText('本次已保存外观：' + (' · '.join(names) if names else '未选择外观，不会新增六款'))
        else:
            self.setup_preset_summary.setEnabled(self.setup_presets.isChecked())
            self.setup_presets.toggled.connect(self.setup_preset_summary.setEnabled)
        layout.addWidget(self.setup_preset_summary)
        for check in (self.setup_fl23, self.setup_sound, self.setup_vertical, self.setup_plugin):layout.addWidget(check)
        self.setup_button=self.button(layout, '开始新的一键安装' if prior.get('phase')=='COMPLETE' else '继续安装' if prior else '一键安装',
                                      'setup_all', self.setup_args, primary=True)
        self.setup_result_button=W.QPushButton('查看上次安装结果（不连接相机）')
        self.setup_result_button.clicked.connect(self.show_setup_result)
        self.setup_result_button.setVisible(prior.get('phase')=='COMPLETE')
        layout.addWidget(self.setup_result_button);self.buttons.append(self.setup_result_button)
        look_section=self.advanced(layout,'改用自己的 A7Look 文件（先取消勾选内置六款）')
        custom_container = self.setup_custom_container = look_section.parentWidget()
        custom_container.setEnabled(not self.setup_presets.isChecked() and not (prior and prior.get('phase')!='COMPLETE'))
        self.setup_presets.toggled.connect(lambda enabled: custom_container.setEnabled(not enabled))
        form = self.box(look_section, '选择 A7Look 文件')
        for slot in range(1, 7):
            self.field(form, 'setup_look_' + str(slot), '自订 ' + str(slot), kind='file', filter='Compiled looks (*.a7look)')
        compile_button = W.QPushButton('从 DCP／LUT 生成 A7Look…')
        compile_button.clicked.connect(self.compiler_dialog); look_section.addWidget(compile_button); self.buttons.append(compile_button)
        hint = W.QLabel('恢复出厂、卸载驱动和删除外观不会混入安装流程。自定义声音请在“电子快门声音”中转换后直接保存，试听可选。')
        hint.setWordWrap(True); layout.addWidget(hint); layout.addStretch()

    def drivers_first(self, arguments):
        """Suggest the connection page before a first one-click install on Windows."""
        if (sys.platform != 'win32' or self.settings.get('connection_verified')
                or Path(arguments.get('workspace', ''), 'setup.private.json').is_file()):
            return True
        choice = self.ask_drivers_first()
        if choice == 'drivers':
            self.nav.setCurrentRow(1)
        return choice == 'continue'

    def ask_drivers_first(self):
        box = W.QMessageBox(self)
        box.setWindowTitle('建议先安装驱动')
        box.setText('这台电脑还没有成功连接过相机。建议先到“连接与驱动”页，点“准备两阶段驱动并测试连接”，'
                    '看到连接成功后再回来一键安装。')
        box.setInformativeText('一键安装也会自动尝试安装驱动，但驱动失败时排查更麻烦。'
                               '驱动反复装不上，可点该页的“用 Zadig 手动安装驱动”，按说明操作。')
        go = box.addButton('先去安装驱动', W.QMessageBox.AcceptRole)
        box.addButton('直接一键安装', W.QMessageBox.DestructiveRole)
        cancel = box.addButton(W.QMessageBox.Cancel)
        box.setDefaultButton(go)
        box.exec()
        return 'drivers' if box.clickedButton() is go else 'cancel' if box.clickedButton() is cancel else 'continue'

    def driver_step_failed(self, action):
        if action in ('usb_prepare', 'connect', 'driver_install'):
            return True
        if action != 'setup_all':
            return False
        try:
            state = json.loads(Path(self.settings.get('setup_work', ''), 'setup.private.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        return 'drivers' not in state.get('completed_steps', [])

    def direct_verify_args(self, group, accepted=False):
        workspace=self.settings.get(group + '_direct_work', '')
        args={'workspace': workspace, 'accepted': accepted}
        if group=='factory':args.update(factory_verify=True,factory_preferred=self.text('factory_failed_work'))
        return args

    def show_setup_result(self):
        from .completion import archive_error,text
        path=Path(self.settings.get('setup_work',''),'setup.private.json')
        if not path.is_file():return
        state=json.loads(path.read_text(encoding='utf-8'))
        if state.get('phase')!='COMPLETE':
            W.QMessageBox.information(self,'安装尚未结束','请点首页“继续安装”，按提示完成后续步骤。')
            return
        if archive_error(state):write_json(path,state)
        W.QMessageBox.information(self,'安装完成',text(state))

    def refresh_setup_controls(self):
        path=Path(self.settings.get('setup_work',''),'setup.private.json')
        state=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        pending=bool(state) and state.get('phase')!='COMPLETE'
        self.setup_button.setText('继续安装' if pending else '开始新的一键安装' if state else '一键安装')
        self.setup_result_button.setVisible(state.get('phase')=='COMPLETE')
        self.setup_note.setVisible(pending)
        self.setup_custom_container.setEnabled(not pending and not self.setup_presets.isChecked() and self.process is None)
        if not state:
            self.setup_preset_summary.setText(presets.SUMMARY)
            self.setup_preset_summary.setEnabled(self.setup_presets.isChecked())
        for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):
            box.setEnabled(not pending and self.process is None)

    def clear_installation_state(self, verified=True):
        # Clear active navigation/resume pointers, not diagnostic evidence or
        # user source files. A verified factory reset invalidates these plans.
        # Before verification only the sound records are retired: the restore
        # has already returned every sound program window to stock.
        if verified:
            for key in ('setup_work','fl23_direct_work','look_direct_work',
                        'look_resume_source','look_job_dir'):
                self.settings.pop(key,None)
            self._look_displayed_pending=None
            self.look_editor.set_operations([])
            self.fl23_accept.setChecked(False)
        self.sound_accept.setChecked(False)
        # The old sound workspace describes the pre-reset camera installation.
        # Start fresh while retaining its files and the selected source clip.
        sound=self.work('sound')
        for key,value in (('sound_work',sound),('sound_backup',sound+'-backup')):
            self.fields[key].setText(value);self.settings[key]=value
        write_json(data_root()/'desktop.json',self.settings)
        self.log.appendPlainText('原厂恢复已核对通过；已清除旧安装状态。历史诊断日志保留，新安装从头开始。' if verified else
                                 '原厂恢复写入已完成；旧的声音记录已停用（文件保留），之后的声音操作不再受它们影响。')

    def reload_controls(self, layout, checks):
        guide = W.QPushButton('如何断电重开？查看详细步骤')
        guide.clicked.connect(lambda: self.show_reload_guide())
        layout.addWidget(guide)
        self.buttons.append(guide)
        confirm = W.QCheckBox('已拔 USB、等灯停、关机，取下电池至少 1 分钟后重开；\n已确认' + checks)
        confirm.setToolTip(reloadguide.text())
        layout.addWidget(confirm)
        return confirm

    def show_reload_guide(self, *, setup=False, mode=None):
        title = ('恢复尚未开始，请断电后重试' if mode=='factory_prewrite_temporary' else
                 '恢复尚未完成，请重启后核对' if mode=='factory_reset' else
                 '试听结果已记录，请断电恢复原声' if mode=='sound_confirm' else '读写已结束，请断电重开')
        W.QMessageBox.information(self, title, reloadguide.text(setup=setup, mode=mode))

    def show_connection_notice(self):
        W.QMessageBox.information(self,connectionguide.TITLE,connectionguide.TEXT)

    def field(self, form, key, label, *, kind=None, filter='All files (*)', value=''):
        line = W.QLineEdit(str(self.settings.get(key, value)))
        line.setObjectName(key)
        self.fields[key] = line
        if kind:
            row = W.QHBoxLayout()
            row.addWidget(line, 1)
            button = W.QPushButton('选择…')
            button.clicked.connect(lambda: self.browse(line, kind, filter))
            row.addWidget(button)
            form.addRow(label, row)
        else:
            form.addRow(label, line)
        return line

    def browse(self, field, kind, filter):
        if kind == 'folder':
            path = W.QFileDialog.getExistingDirectory(self, '选择目录', field.text())
        elif kind == 'save':
            path = W.QFileDialog.getSaveFileName(self, '保存文件', field.text(), filter)[0]
        else:
            path = W.QFileDialog.getOpenFileName(self, '选择文件', field.text(), filter)[0]
        if path:
            field.setText(path)

    def button(self, layout, text, action, arguments=lambda: {}, *, primary=False):
        button = W.QPushButton(text)
        button.setObjectName('action_' + action)
        button.setProperty('primary', primary)
        button.clicked.connect(lambda: self.launch(action, arguments()))
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def text(self, key):
        return self.fields[key].text().strip()

    def common(self):
        return {'firmware': self.firmware.currentText()}

    def work(self, label):
        return str(data_root() / 'work' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + label + '-' + uuid.uuid4().hex[:5]))

    def connection_page(self):
        layout = self.page('连接与驱动', '相机开机并选择“海量存储／Mass Storage”，使用可传数据的 USB 线。一次只连接一台相机。')
        form = self.box(layout, 'USB 连接')
        self.driver_identity = W.QComboBox()
        self.driver_identity.addItems(['普通连接 · 054C:0E8A', '服务连接 · 054C:0336'])
        form.addRow('驱动目标', self.driver_identity)
        if sys.platform == 'darwin':
            self.field(form, 'mac_volume', 'macOS 相机存储卷', kind='folder', value='/Volumes/')
        self.button(layout, '检测相机与驱动', 'driver_scan', primary=True)
        if sys.platform == 'win32':
            # Manual Zadig installation sits beside the automatic one: many
            # computers where the automatic install fails succeed with it.
            drivers = W.QHBoxLayout()
            layout.addLayout(drivers)
            self.button(drivers, '准备两阶段驱动并测试连接（自动）', 'usb_prepare', primary=True)
            zadig = W.QPushButton('用 Zadig 手动安装驱动（自动失败时）')
            zadig.setObjectName('zadig_guide')
            zadig.setProperty('primary', True)
            zadig.clicked.connect(self.show_zadig_guide)
            drivers.addWidget(zadig)
            self.buttons.append(zadig)
        else:
            self.button(layout, '准备 USB 服务连接', 'usb_prepare', primary=True)
        self.button(layout, '单独安装所选身份的驱动（高级）' if sys.platform == 'win32'
                    else '检查 USB 访问（macOS 无需 Zadig）', 'driver_install',
                    lambda: {'pid': ['0e8a', '0336'][self.driver_identity.currentIndex()]})
        if sys.platform == 'darwin':
            self.button(layout, '推出选中的相机存储卷', 'mac_unmount', lambda: {'volume': self.text('mac_volume')})
        self.button(layout, '测试服务连接（不写固件）', 'connect')
        self.button(layout, '检测 USB 连接稳定性（只读）', 'usb_stability')
        if sys.platform == 'win32':
            self.button(layout, '卸载相机驱动，恢复 Windows 默认连接', 'driver_uninstall',
                        lambda: {'pids': ['0e8a', '0336']})
        hint = W.QLabel('连接中断后先查看完整日志。报错不会触发重新刷写或自动重装驱动。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def recovery_page(self):
        layout = self.page('恢复原厂功能', '已内置本项目修改区域的原厂 2.01 基准。移除已支持的项目修改，六个自订栏位设为 ST 默认，保留机身校准。无需旧备份或下载完整固件；旧配方不找回。')
        self.factory_button=self.button(layout, '恢复／继续恢复原厂 2.01 功能（无需旧备份）', 'direct_factory_reset',
                    lambda: self.direct_args('factory', mode='factory_reset', factory='builtin'), primary=True)
        self.factory_status=W.QLabel('恢复写入后必须按弹窗重启，再接回核对；核对通过前不会标记恢复完成。')
        self.factory_status.setWordWrap(True);layout.addWidget(self.factory_status)
        resume_section = self.advanced(layout, '恢复事务（自动识别；也可手动选择）')
        resume_form = W.QFormLayout()
        self.field(resume_form, 'factory_failed_work', '恢复事务目录（通常自动）', kind='folder',
                   value=self.settings.get('factory_direct_work', ''))
        resume_section.addLayout(resume_form)
        self.factory_accept = self.reload_controls(layout, '取景、拍照和回放正常')
        self.button(layout, '重启后核对并完成恢复（恢复写入后必做）', 'direct_verify',
                    lambda: self.direct_verify_args('factory', self.factory_accept.isChecked()))
        layout.addWidget(W.QLabel('相机仍需能够进入 USB 服务通信；此操作不是索尼更新器的降级重刷。'))
        expert = self.advanced(layout, '导入完整原厂 2.01 参考文件（高级、可选）')
        reference = self.box(expert, '原厂文件')
        self.field(reference, 'factory_file', 'Sony BODYDATA.DAT', kind='file', filter='Sony firmware (*.DAT *.bin);;All files (*)')
        self.button(expert, '准备所选原厂文件（不连接相机）', 'factory_prepare',
                    lambda: {'source': self.text('factory_file') or str(data_root() / 'factory-2.01')})
        self.button(expert, '使用导入的完整原厂文件恢复', 'direct_factory_reset',
                    lambda: self.direct_args('factory', mode='factory_reset', factory=str(data_root() / 'factory-2.01')))
        legacy = self.advanced(layout, '使用旧备份回到过去的状态（可选）')
        self.backup_recovery_controls(legacy)
        layout.addStretch()
        self.refresh_factory_controls()

    def refresh_factory_controls(self):
        work=self.settings.get('factory_direct_work') or self.text('factory_failed_work')
        path=Path(work,'direct.private.json') if work else None
        try:state=json.loads(path.read_text(encoding='utf-8')) if path and path.is_file() else {}
        except (OSError,ValueError):return
        phase=state.get('phase')
        if phase=='AWAITING_RELOAD':
            self.factory_button.setText('重启后核对并完成恢复')
            self.factory_status.setText('恢复尚未完成：写入与读回已结束。请断电重启、接回 USB，再点击上方按钮核对。')
        elif phase in ('LOADED','COMPLETE') and state.get('readonly_after_reload_verified'):
            self.factory_button.setText('重新恢复原厂 2.01 功能（无需旧备份）')
            self.factory_status.setText('上次恢复核对已通过。程序、设置、加载状态及只读挂载已核对；当前功能和拍摄验收以机身为准。')
        elif phase=='NEEDS_REVIEW':
            from looktool.factoryrecover import connection_failed_before_restore,prewrite_temporary_conflict
            if prewrite_temporary_conflict(state):
                self.factory_button.setText('断电后重试恢复（本次尚未写入）')
                self.factory_status.setText('本次恢复尚未写入，遇到相机临时文件冲突。请按弹窗完整断电，接回 USB，再点击上方按钮重试；不需要旧 LUT 记录。')
                return
            if connection_failed_before_restore(state):
                self.factory_button.setText('恢复原厂 2.01 功能（上次尚未开始）')
                self.factory_status.setText('上次在 USB 连接阶段停止，尚未开始恢复写入。点击上方按钮，完成系统授权后重新连接。')
                return
            self.factory_button.setText('继续恢复／核对未完成事务')
            self.factory_status.setText('恢复尚未完成，请继续处理未完成事务；当前不代表已恢复成功。')

    def backup_recovery_controls(self, layout):
        form = self.box(layout, '恢复来源')
        self.field(form, 'restore_backup', '备份目录', kind='folder')
        choose_zip = W.QPushButton('或选择完整备份 ZIP…')
        choose_zip.clicked.connect(lambda: self.browse(self.fields['restore_backup'], 'file', 'Backup (*.zip);;All files (*)'))
        form.addRow('', choose_zip)
        self.field(form, 'restore_work', '恢复任务目录', kind='folder', value=self.work('recovery'))
        self.button(layout, '检查所选备份（离线）', 'backup_inspect', lambda: {'backup': self.text('restore_backup')})
        auto = W.QPushButton('一键还原：查找并使用最初完整备份')
        auto.setObjectName('one_click_restore')
        auto.clicked.connect(self.one_click_restore)
        self.buttons.append(auto)
        layout.addWidget(auto)
        self.button(layout, '恢复所选备份并完整读回', 'restore', lambda: dict(self.common(),
            backup=self.text('restore_backup'), workspace=self.text('restore_work')), primary=True)
        self.recovery_accept = self.reload_controls(layout, '恢复后取景、拍照和回放正常')
        self.button(layout, '核对旧备份恢复后的加载状态', 'restore_verify', lambda: {
            'workspace': self.text('restore_work'), 'accepted': self.recovery_accept.isChecked()})
        note = W.QLabel('相机需要仍可进入服务通信。此入口使用机身备份；不把官方 BODYDATA.DAT 当作备份刷入。')
        note.setWordWrap(True)
        layout.addWidget(note)

    def fl23_page(self):
        layout = self.page('FL2 / FL3', '直接启用／移除，不要求创建备份。移除只关闭 FL2／FL3 的列表入口，保留自定义外观所需的共用色彩代码；之后可以重新启用。')
        self.button(layout, '启用／重新启用 FL2 / FL3', 'direct_fl23_enable',
                    lambda: self.direct_args('fl23', mode='fl23_enable'), primary=True)
        self.button(layout, '从列表移除 FL2 / FL3，保留自定义外观', 'direct_fl23_disable',
                    lambda: self.direct_args('fl23', mode='fl23_disable'))
        info = W.QLabel('写入读回后按弹窗断电重开，在相机确认即可使用；无需再接电脑核对。')
        info.setWordWrap(True); layout.addWidget(info)
        diagnostic = self.advanced(layout, '加载核对（可选诊断，不是使用前提）')
        self.fl23_accept = self.reload_controls(diagnostic, '菜单、拍照和回放正常')
        self.button(diagnostic, '只读核对已加载的版本（可选）', 'direct_verify',
                    lambda: self.direct_verify_args('fl23', self.fl23_accept.isChecked()))
        if '--preview-gate-test' in sys.argv:
            preview = layout
            preview.addWidget(W.QLabel('取景器横线＋实时预览：第 2 版候选（等待实机验收）'))
            hint = W.QLabel('第 1 版横线消失，但切槽预览可能停在上一个外观。第 2 版在未提交时补传，'
                           '按硬件目标去重；不改色表、名称或配方。应用后按弹窗断电重开，再检查横线和六槽切换。')
            hint.setWordWrap(True); preview.addWidget(hint)
            self.button(preview, '应用横线＋实时预览修复候选（第 2 版）', 'direct_preview_pending',
                        lambda: self.direct_args('preview'), primary=True)
            self.button(preview, '切回第 1 版：原生刷新（预览可能滞留）', 'direct_preview_native',
                        lambda: self.direct_args('preview'))
            self.button(preview, '撤回测试：恢复旧版刷新方式', 'direct_preview_legacy',
                        lambda: self.direct_args('preview'))
            self.preview_accept = self.reload_controls(preview, '横线消失、六槽实时切换、拍摄和回放正常')
            self.button(preview, '断电重开后只读核对本轮测试', 'direct_verify',
                        lambda: self.direct_verify_args('preview', self.preview_accept.isChecked()))
        layout.addStretch()

    def look_page(self):
        from .lookeditor import LookEditor
        layout=self.page('自定义创意外观','按需添加本次要改的槽位；未添加的槽位保持原样。可在同一批操作中写入外观和恢复 ST 默认。')
        self.look_pending=W.QLabel();self.look_pending.setWordWrap(True);layout.addWidget(self.look_pending)
        self.look_editor=LookEditor();layout.addWidget(self.look_editor)
        self.look_button=W.QPushButton('添加操作项后继续');self.look_button.setProperty('primary',True)
        self.look_button.setObjectName('action_direct_looks_import');self.look_button.clicked.connect(self.launch_look_changes)
        layout.addWidget(self.look_button);self.buttons.append(self.look_button)
        tools=W.QHBoxLayout();layout.addLayout(tools)
        for title,callback in [('打开内置 DCP／A7Look 配对库',self.open_profile_library),('从 DCP／LUT 生成 A7Look…',self.compiler_dialog),('安装 LrC 自动识别插件…',self.plugin_dialog)]:
            button=W.QPushButton(title);button.clicked.connect(callback);tools.addWidget(button);self.buttons.append(button)
        formats=W.QPushButton('LUT 格式说明：ST / sRGB，不是 S-Log3…')
        formats.clicked.connect(self.show_look_format_guide);layout.addWidget(formats);self.buttons.append(formats)
        layout.addWidget(W.QLabel('写入页选择 .a7look；.cube / .dcp 先用上方工具转换。仅更改清单内的槽位。'))
        hint=W.QLabel('同一次操作自动检查当前状态、写入并完整读回。结束后按弹窗断电加载，无需单独点击核对。')
        hint.setWordWrap(True);layout.addWidget(hint)
        layout.addStretch()
        self._look_displayed_pending=None;self._look_refreshing=False
        self.look_editor.changed.connect(self.refresh_look_controls)
        self.refresh_look_controls()

    def open_profile_library(self):
        from .profilelibrary import location
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(location())))

    def look_pending_state(self):
        prior=self.settings.get('look_direct_work')
        if not prior:return None
        try:
            job=self.settings.get('look_job_dir')
            if job and Path(job,'status.private.json').is_file():
                status=json.loads(Path(job,'status.private.json').read_text(encoding='utf-8'))
                request=json.loads(Path(job,'request.private.json').read_text(encoding='utf-8'))
                matches=prior in (request.get('arguments',{}).get('workspace'),status.get('result',{}).get('workspace'))
                if matches and status.get('phase')=='SUCCEEDED':
                    prior=status['result']['workspace']
                elif matches and status.get('phase') in ('RUNNING','QUEUED') and self.process is None:
                    return prior,dict(phase='BACKGROUND_UNCONFIRMED',error='后台任务尚未确认结束，请等待原结果或查看日志，不重复写入。')
            if not Path(prior,'direct.private.json').is_file():
                prior=self.settings.get('look_resume_source')
                if not prior or not Path(prior,'direct.private.json').is_file():return None
            state=json.loads(Path(prior,'direct.private.json').read_text(encoding='utf-8'))
            nested=Path(prior,'program-install/direct.private.json')
            if state.get('phase')=='RESOURCE_RELOAD_VERIFIED' and nested.is_file():
                prior=str(nested.parent);state=json.loads(nested.read_text(encoding='utf-8'))
        except (ValueError,OSError,KeyError) as exc:return str(prior),dict(phase='UNREADABLE',error=str(exc))
        return None if state.get('phase') in ('AWAITING_RELOAD','LOADED','COMPLETE') else (prior,state)

    def refresh_look_controls(self):
        if self._look_refreshing:return
        self._look_refreshing=True
        try:
            pending=self.look_pending_state();busy=self.process is not None
            if pending:
                prior,state=pending;phase=state.get('phase')
                token=(prior,phase)
                if self._look_displayed_pending!=token:
                    options=state.get('bundle_options',{});by_slot={r['slot']:r for r in options.get('looks',[])}
                    operations=options.get('slot_operations') or [dict(r,action='write') for r in by_slot.values()]+[dict(slot=n,action='restore') for n in options.get('reset_slots',[])]
                    if not operations and state.get('mode')=='slot_default':operations=[dict(slot=state['slot'],action='restore')]
                    if not operations and state.get('mode')=='look_import':operations=[dict(slot=state['slot'],action='write',path=str(Path(prior)/'reference.a7look'),name=state.get('name') or '')]
                    operations=[dict(r,**{k:v for k,v in by_slot.get(r['slot'],{}).items() if k!='slot'}) if r.get('action')=='write' else r for r in operations]
                    self.look_editor.set_operations(operations);self._look_displayed_pending=token
                self.look_editor.setEnabled(False);self.look_button.setEnabled(not busy)
                if phase in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED') or (phase=='NEEDS_REVIEW' and state.get('forward_name_build',{}).get('stream_install') and 'readonly=-16' in state.get('error','')):
                    text='上次操作正在等待资源续接，将沿用已保存的清单。'
                    self.look_button.setText('继续槽位更改')
                else:
                    from .lookbatch import read_only_failure
                    if read_only_failure(state):
                        text='上次在写入前停止，旧记录已保留；可以调整清单后重试。'
                        self.look_editor.setEnabled(not busy)
                        self.look_button.setText('重试本次更改（上次未写入）')
                        self.look_button.setEnabled(not busy and bool(self.look_editor.values()) and not self.look_editor.errors())
                    else:
                        text='上次操作尚未完成；请查看原任务记录，不自动重复写入。'
                        self.look_button.setText('查看未完成任务记录')
                self.look_pending.setText(text);self.look_pending.show()
            else:
                if self._look_displayed_pending is not None:
                    self._look_displayed_pending=None;self.look_editor.set_operations([])
                self.look_pending.hide();self.look_editor.setEnabled(not busy)
                rows=self.look_editor.values()
                self.look_button.setText('查看并应用这 %d 项更改'%len(rows) if rows else '添加操作项后继续')
                self.look_button.setEnabled(bool(rows) and not self.look_editor.errors() and not busy)
        finally:self._look_refreshing=False

    def look_batch_args(self):
        return self.direct_args('look',operations=self.look_editor.values())

    def launch_look_changes(self):
        pending=self.look_pending_state()
        if pending:
            prior,state=pending;phase=state.get('phase')
            if phase in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED') or (phase=='NEEDS_REVIEW' and state.get('forward_name_build',{}).get('stream_install') and 'readonly=-16' in state.get('error','')):
                self.launch('direct_resume_looks',dict(self.common(),workspace=self.work('look'),failed_workspace=prior));return
            from .lookbatch import read_only_failure
            if read_only_failure(state):
                self.launch('direct_looks_import',self.look_batch_args());return
            W.QMessageBox.warning(self,'上次任务尚未完成',state.get('error','请保留原记录，核对未知结果后再继续。')+'\n任务目录：'+prior)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(prior));return
        self.launch('direct_looks_import',self.look_batch_args())

    def vertical_page(self):
        layout = self.page('竖屏显示', '竖握相机时，拍摄信息、图标和布局跟随转向。开启会保存原生开关，断电重开后自动生效；不是整个 MENU 转向。')
        form = self.box(layout, '显示任务')
        self.field(form, 'vertical_work', '任务目录', kind='folder', value=str(data_root() / 'vertical'))
        args = lambda: dict(self.common(), workspace=self.text('vertical_work'))
        self.button(layout, '开启竖屏显示', 'vertical_enable', args, primary=True)
        self.button(layout, '关闭竖屏显示', 'vertical_disable', args)
        frame_hint=W.QLabel('开启会保存竖屏开关并应用当前的 Fn／子菜单显示修正；关闭会先关闭竖屏，再撤销显示修正。两个操作都支持重复覆盖。')
        frame_hint.setWordWrap(True);layout.addWidget(frame_hint)
        known=W.QLabel('已知显示问题：竖屏创意外观选择页的外框仍偏粗；刻度已横向显示，但橙色指针朝向尚未修正。')
        known.setWordWrap(True);layout.addWidget(known)
        hint = W.QLabel('开启／关闭会一次完成所选写入和读回，再统一弹窗提示断电加载。相同状态可重复点击，相同内容不重复写入。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def sound_page(self):
        layout = self.page('电子快门声音', '独立开关控制电子快门发声分支。音频转换后可直接保存，临时试听可选；写入后按弹窗断电加载。')
        form = self.box(layout, '声音工作区')
        self.field(form, 'sound_work', '工作目录', kind='folder', value=str(data_root() / 'sound'))
        self.field(form, 'sound_backup', '第二份备份', kind='folder', value=str(data_root() / 'sound-backup'))
        args = lambda: dict(self.common(), workspace=self.text('sound_work'), backup=self.text('sound_backup'))
        row = W.QHBoxLayout()
        layout.addLayout(row)
        self.button(row, '开启电子快门声', 'sound_on', args)
        self.button(row, '关闭电子快门声', 'sound_off', args)
        media = self.box(layout, '导入音频／视频片段')
        self.field(media, 'sound_source', '声音文件', kind='file', filter='Audio / video (*.wav *.mp3 *.mp4 *.m4a *.flac *.ogg);;All files (*)')
        self.sound_start = W.QDoubleSpinBox()
        self.sound_start.setRange(0, 86400)
        self.sound_start.setDecimals(3)
        media.addRow('起点（秒）', self.sound_start)
        self.sound_duration = W.QDoubleSpinBox()
        self.sound_duration.setRange(.01, 2)
        self.sound_duration.setDecimals(3)
        self.sound_duration.setValue(.5)
        media.addRow('长度（秒）', self.sound_duration)
        row = W.QHBoxLayout()
        layout.addLayout(row)
        self.button(row, '转换所选片段', 'sound_import', lambda: dict(args(), source=self.text('sound_source'),
            start=self.sound_start.value(), duration=self.sound_duration.value(), peak=.4))
        self.button(row, '相机内临时试听', 'sound_audition', args)
        volume = W.QHBoxLayout()
        layout.addLayout(volume)
        self.button(volume, '音量降低 −3 dB', 'sound_volume', lambda: dict(args(), decibels=-3))
        self.button(volume, '音量提高 +3 dB', 'sound_volume', lambda: dict(args(), decibels=3))
        self.button(volume, '还原转换时音量', 'sound_volume', lambda: dict(args(), reset=True))
        volume_hint=W.QLabel('先转换片段，再调节音量；仅处理电脑上的音频，不连接相机。达到音量上限会自动限制以避免削波；保存时使用调整后的声音。重新转换会重置音量。')
        volume_hint.setWordWrap(True);layout.addWidget(volume_hint)
        self.button(layout, '保存当前自定义声音', 'sound_install', args, primary=True)
        hint=W.QLabel('转换成功即可直接保存；自动建立工作区并准备电子快门声支援，不必先开启或关联旧任务。试听可选；全部写入完成后按弹窗统一断电加载。')
        hint.setWordWrap(True);layout.addWidget(hint)
        optional=self.advanced(layout,'试听确认与恢复记录（可选，不影响保存）')
        self.button(optional, '确认试听正确', 'sound_confirm', lambda: dict(args(), result='correct'))
        self.button(optional, '已断电恢复原声，记录恢复完成', 'sound_confirm_recovery', args)
        self.sound_accept = self.reload_controls(layout, '声音正确、拍摄和回放正常')
        self.button(layout, '重开后核对声音', 'sound_verify', lambda: dict(args(), accepted=self.sound_accept.isChecked()))
        self.button(layout, '恢复原厂音效', 'sound_restore_sound', args)
        layout.addStretch()

    def show_zadig_guide(self):
        from .zadigguide import TITLE, TEXT, URL
        dialog = W.QDialog(self); dialog.setWindowTitle(TITLE); dialog.resize(820, 680)
        layout = W.QVBoxLayout(dialog)
        content = W.QTextBrowser(); content.setPlainText(TEXT); layout.addWidget(content)
        row = W.QHBoxLayout(); layout.addLayout(row)
        download = W.QPushButton('打开 Zadig 下载页'); download.setProperty('primary', True)
        download.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(URL)))
        close = W.QPushButton('关闭'); close.clicked.connect(dialog.accept)
        row.addWidget(download); row.addWidget(close)
        dialog.exec()

    def show_look_format_guide(self):
        from .lookguide import TITLE,TEXT
        dialog=W.QDialog(self);dialog.setWindowTitle(TITLE);dialog.resize(800,650)
        layout=W.QVBoxLayout(dialog)
        content=W.QTextBrowser();content.setPlainText(TEXT);layout.addWidget(content)
        close=W.QPushButton('关闭');close.clicked.connect(dialog.accept);layout.addWidget(close)
        dialog.exec()

    def compiler_dialog(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle('生成 A7Look')
        dialog.resize(760, 370)
        layout = W.QVBoxLayout(dialog)
        hint = W.QLabel('CUBE：输入必须是 Sony ST / sRGB，输出 sRGB；不能直接使用 S-Log3 / S-Gamut3.Cine 或其他 Log LUT。\nDCP：内置离线解析与拟合，不需要 Lightroom、插件或联网。转换 LookTable／色调曲线，机内效果为拟合近似。此工具只生成 .a7look，不写相机。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        help_button=W.QPushButton('支持哪些格式和色彩空间？查看完整说明…')
        help_button.clicked.connect(self.show_look_format_guide);layout.addWidget(help_button)
        form = self.box(layout, '源文件与输出')
        self.field(form, 'compile_source', 'DCP / CUBE', kind='file', filter='Reference (*.dcp *.cube)')
        self.field(form, 'compile_name', '外观名称')
        self.field(form, 'compile_output', '输出 A7Look', kind='save', filter='A7Look (*.a7look)')
        self.field(form, 'compile_model', '响应文件', kind='file', filter='Response (*.npz)',
                   value=str(ROOT / 'calibration/a7c2-2.01.virtual.npz'))
        run = W.QPushButton('开始生成')
        run.clicked.connect(lambda: (dialog.accept(), self.launch('compile_look', {
            'source': self.text('compile_source'), 'name': self.text('compile_name'),
            'output': self.text('compile_output'), 'model': self.text('compile_model'),
            'input_space': 'sony-st-srgb', 'passes': 3})))
        layout.addWidget(run)
        dialog.exec()

    def plugin_dialog(self):
        self.launch('plugin_install', {})

    def one_click_restore(self):
        roots = [str(data_root() / 'backups'), str(data_root() / 'initial-checkpoints')]
        for key in ('fl23_backup', 'look_backup', 'restore_backup'):
            if key in self.fields and self.text(key):
                roots.append(self.text(key))
        self.fields['restore_work'].setText(self.work('recovery'))
        self.launch('restore_auto', dict(self.common(), roots=roots, workspace=self.text('restore_work')))

    def launch(self, action, arguments):
        if self.process is not None:
            return
        factory_finished = False
        if action == 'setup_all' and not self.drivers_first(arguments):
            return
        if action=='direct_looks_import' and arguments.get('failed_workspace'):
            action='direct_resume_looks'
        if action=='direct_looks_import':
            try:
                from .worker import setup_runtime
                setup_runtime()
                from .lookbatch import options
                chosen=options(arguments.get('operations',arguments.get('looks',[])))
                arguments=dict(arguments,operations=chosen['slot_operations'])
            except (ValueError,OSError,KeyError,TypeError) as exc:
                W.QMessageBox.warning(self,'请检查操作清单',str(exc));return
        if action == 'sound_audition':
            from .actions.sound import has_conversion
            try:
                ready = has_conversion(arguments['workspace'])
            except (ValueError, OSError, KeyError) as exc:
                W.QMessageBox.warning(self, '声音工作区需要核对', str(exc));return
            if not ready:
                W.QMessageBox.information(self, '请先转换片段', '还没有转换好的声音。请先选择声音文件、设置起点和长度，点「转换所选片段」，成功后再试听。');return
        if action == 'restore_verify' and not Path(arguments.get('workspace', ''), 'rollback.private.json').is_file():
            # This button checks a backup restore only. A built-in or firmware
            # file restore is checked by the factory verification button.
            answer = W.QMessageBox.question(self, '这里没有旧备份恢复记录',
                '“核对旧备份恢复后的加载状态”只用于“使用旧备份回到过去的状态”。\n'
                '用内置原厂基准或固件文件恢复后，应点“重启后核对并完成恢复”。\n现在改为核对原厂恢复？',
                W.QMessageBox.Yes | W.QMessageBox.Cancel, W.QMessageBox.Yes)
            if answer != W.QMessageBox.Yes:
                return
            action, arguments = 'direct_verify', self.direct_verify_args('factory', bool(arguments.get('accepted')))
        if action == 'direct_factory_reset':
            # A failed fresh attempt must not hide the original interrupted
            # transaction. Resolve the explicitly selected evidence locally,
            # before the power/write confirmation and before any USB access.
            from .worker import setup_runtime
            setup_runtime()
            from looktool.factoryrecover import pending, FINISHED
            try:
                found = pending(data_root() / 'work', self.text('factory_failed_work'))
            except (ValueError, OSError):
                found = None  # Records are evidence only; the worker re-plans.
            if found:
                # A finished restore is verified first; the worker re-plans
                # from current bytes if the camera changed since then.
                original, prior = found
                factory_finished = prior['phase'] in FINISHED
                action = 'direct_resume_factory'
                arguments = dict(arguments, failed_workspace=str(original), accepted=self.factory_accept.isChecked())
        if action == 'driver_uninstall':
            answer = W.QMessageBox.question(self, '卸载相机驱动',
                '将备份并卸载 Sony 054C:0E8A／0336 的第三方驱动，让 Windows 重新识别相机。\n'
                '完成后可能需要拔插 USB，重新选择海量存储模式。此操作不修改相机固件。\n现在卸载？',
                W.QMessageBox.Yes | W.QMessageBox.Cancel, W.QMessageBox.Cancel)
            if answer != W.QMessageBox.Yes:
                return
        writing = action in jobs.POWER_ACTIONS
        if writing:
            target = (('首页勾选的功能；替换自订 1–6：' + presets.SUMMARY if arguments.get('options', {}).get('preset_pack') else '首页勾选的功能及所选 A7Look 槽位') if action == 'setup_all' else
                      '自动选择已连接机身最早可用的完整备份' if action == 'restore_auto' else
                      arguments.get('backup') if action == 'restore' else arguments.get('look') or arguments.get('workspace'))
            if action in jobs.DIRECT_ACTIONS:
                target = ('；'.join('自订 %s → %s' % (r['slot'], '恢复 ST 默认' if r['action']=='restore' else '写入 '+r['name']) for r in arguments.get('operations', []))
                          if action == 'direct_looks_import' else
                          '继续已写好名称的外观安装：'+arguments.get('failed_workspace','') if action=='direct_resume_looks' else
                          ('核对上次恢复；相机内容若已改变，则按当前字节重新恢复：' if factory_finished else
                           '继续完成名称／设置恢复：') + arguments.get('failed_workspace', '') if action == 'direct_resume_factory' else
                          '竖屏显示＋Fn／子菜单线框修正' if action=='vertical_enable' else
                          '关闭竖屏显示并撤销线框修正' if action=='vertical_disable' else
                          '原厂 2.01 功能' if action == 'direct_factory_reset' else
                          'FL2／FL3：启用' if action == 'direct_fl23_enable' else
                          'FL2／FL3：从列表移除' if action == 'direct_fl23_disable' else
                          '自订 %s：%s' % (arguments.get('slot'), 'ST 默认' if action == 'direct_slot_default'
                                           else arguments.get('name') or Path(arguments.get('look', '')).stem))
            scope = ('仅更改 CP 的 LUT 刷新代码；保留色表、名称、配方和其他功能。写入后完整断电重开，检查横线及切槽刷新。\n' if action in ('direct_preview_native','direct_preview_legacy','direct_preview_pending') else
                     '一次应用清单内的写入和恢复，未添加的槽位保持原样；保留 FL23、声音和竖屏。写入读回完成后统一提示断电重开。\n' if action=='direct_looks_import' else
                     '自动准备驱动并安装首页勾选的功能。断电重开必须由你按提示完成；结果不明时停止，不自动重复刷写。\n' if action == 'setup_all' else
                     '先只读核对；只有相机内容已改变时才按当前字节写入，已符合原厂的内容不重复写入。\n' if action == 'direct_resume_factory' and factory_finished else
                     '根据当前字节继续未完成阶段，已恢复的内容不重复写入；原失败事务保留，结果不明时先读取报告核对。\n' if action == 'direct_resume_factory' else
                     '将移除项目程序修改、将六个自订栏位设为 ST 默认；旧配方不找回。请先在相机选择 ST。\n' if action == 'direct_factory_reset' else
                     '只关闭 FL2／FL3 列表入口，保留 LUT 与共用代码。请先在相机选择 ST。\n' if action == 'direct_fl23_disable' else
                     '将所选自订栏位设为 ST 默认，保留其他栏位。\n' if action == 'direct_slot_default' else '')
            answer = W.QMessageBox.question(self, '开始相机写入',
                scope + '目标：' + str(target) + '\n请确认机身为 ILCE-7CM2、固件 2.01，电量充足（建议至少 50%）。\n'
                '其它项目修改的固件可能与本工具冲突。\n'
                '操作和完整读回期间保持供电、USB 连接，不要关机或拔线。\n确认供电充足并开始？',
                W.QMessageBox.Yes | W.QMessageBox.Cancel, W.QMessageBox.Cancel)
            if answer != W.QMessageBox.Yes:
                return
            arguments = dict(arguments, power_confirmed=True)
            arguments.pop('battery', None)
        if action in jobs.DIRECT_ACTIONS:
            group = ('preview' if action in ('direct_preview_native', 'direct_preview_legacy', 'direct_preview_pending') else
                     'factory' if action in ('direct_factory_reset', 'direct_resume_factory') else 'fl23' if 'fl23' in action else 'look')
            self.settings[group + '_direct_work'] = arguments['workspace']
            if group=='look':
                self.settings['look_resume_source']=arguments.get('failed_workspace','')
            if group!='look':getattr(self, group + '_accept').setChecked(False)
        if action == 'setup_all':
            self.settings['setup_work'] = arguments['workspace']
            self.setup_button.setText('正在安装…')
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(False)
        for key, field in self.fields.items():
            self.settings[key] = field.text()
        write_json(data_root() / 'desktop.json', self.settings)
        self.current_job = jobs.new_job(action, arguments)
        if action in ('direct_looks_import','direct_resume_looks') or (action=='direct_verify' and arguments.get('workspace')==self.settings.get('look_direct_work')):
            self.settings['look_job_dir']=str(self.current_job)
            write_json(data_root()/'desktop.json',self.settings)
        self.log_offset = 0
        self.log.clear()
        self.camera_operation = action in jobs.CAMERA_ACTIONS or action == 'driver_install'
        for button in self.buttons:
            button.setEnabled(False)
        self.look_editor.setEnabled(False)
        self.stop.setEnabled(not self.camera_operation)
        self.progress.setRange(0, 0)
        self.status.setText('正在执行：' + action + '。详细日志持续保存。')
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUTF8', '1')
        env.insert('PYTHONIOENCODING', 'utf-8')
        self.process.setProcessEnvironment(env)
        command = jobs.worker_command(self.current_job / 'request.private.json')
        self.process.readyReadStandardOutput.connect(self.process_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.process.start(command[0], command[1:])

    def process_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        if text:
            with (self.current_job / 'process.log').open('a', encoding='utf-8') as stream:
                stream.write(text)
            self.log.appendPlainText(text.rstrip())

    def tail_log(self):
        if not self.current_job:
            return
        path = self.current_job / 'worker.log'
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(self.log_offset)
                text = stream.read()
                self.log_offset = stream.tell()
            if text:
                self.log.appendPlainText(text.decode('utf-8', errors='replace').rstrip())

    def poll_job(self):
        self.tail_log()
        if self.process is None and (self._look_displayed_pending is not None or self.look_pending_state()):self.refresh_look_controls()
        # The status file also recovers completion if Qt missed its signal.
        if self.process is not None and self.process.state() == QtCore.QProcess.NotRunning:
            self.finished(self.process.exitCode(), self.process.exitStatus())

    def finished(self, code, exit_status):
        if self.process is None:
            return
        self.tail_log()
        status_path = self.current_job / 'status.private.json'
        status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
        success = code == 0 and status.get('phase') == 'SUCCEEDED'
        if success and (status.get('action') in ('usb_prepare', 'connect') or
                        (status.get('action') == 'setup_all' and 'drivers' in status.get('result', {}).get('completed_steps', []))):
            self.settings['connection_verified'] = True
        if success and status.get('action') == 'restore_auto':
            self.fields['restore_backup'].setText(status['result']['backup'])
            self.fields['restore_work'].setText(status['result']['workspace'])
        if success and status.get('action') == 'look_restore' and 'look_work' in self.fields:
            self.fields['look_work'].setText(status['result']['workspace'])
        if success and status.get('action') in ('direct_factory_reset', 'direct_resume_factory'):
            self.settings['factory_direct_work'] = status['result']['workspace']
            self.fields['factory_failed_work'].setText(status['result']['workspace'])
        if success and status.get('action')=='direct_verify' and status['result'].get('mode')=='factory_reset':
            self.settings['factory_direct_work']=status['result']['workspace']
        if success and (status.get('action') in ('direct_looks_import','direct_resume_looks') or
                (status.get('action')=='direct_verify' and status['result'].get('mode') in ('install_all','look_import','slot_default'))):
            self.settings['look_direct_work']=status['result']['workspace']
            self.settings.pop('look_resume_source',None)
        if success and status.get('action') == 'setup_all':
            for key in ('sound_workspace','sound_backup'):
                target='sound_work' if key=='sound_workspace' else 'sound_backup'
                if status['result'].get(key):self.fields[target].setText(status['result'][key])
        for key, field in self.fields.items():
            self.settings[key] = field.text()
        write_json(data_root() / 'desktop.json', self.settings)
        waiting=success and reloadguide.required(status.get('action'),status.get('result',{}))
        sound_notice=reloadguide.sound_notice(status.get('action'),status.get('result',{})) if success else None
        factory_wait=success and status.get('result',{}).get('mode')=='factory_reset' and status['result'].get('phase')=='AWAITING_RELOAD'
        factory_done=success and status.get('result',{}).get('mode')=='factory_reset' and status['result'].get('phase') in ('LOADED','COMPLETE')
        if factory_done:self.clear_installation_state()
        elif factory_wait:self.clear_installation_state(verified=False)
        resource_wait=status.get('result',{}).get('phase') in ('WAIT_RESOURCE_RELOAD','AWAITING_RESOURCE_RELOAD')
        resource_ready=success and status.get('result',{}).get('phase')=='RESOURCE_RELOAD_VERIFIED'
        setup_wait=waiting and status.get('action')=='setup_all'
        self.status.setText(('名称已写好，程序尚未写入。按弹窗断电重开、接回 USB，再点击首页“继续安装”。' if resource_wait and setup_wait else
                             '名称已写好，程序尚未写入。按弹窗断电重开、接回 USB，再点自定义外观页“继续槽位更改”。' if resource_wait else
                             '批量外观写入完成，已完整读回；按弹窗统一断电重开即可加载。' if status.get('action')=='direct_looks_import' else
                             'FL23 操作完成，写入与完整读回均已结束。重开相机后生效，无需再点核对。' if
                             status.get('result',{}).get('mode') in ('fl23_enable','fl23_disable') else
                             '读写已结束。拔 USB → 等灯停 → 关机并等灯灭 → 取电池至少 1 分钟 → 开机 → 接回 USB → 点击首页“继续安装”。详见弹窗。' if setup_wait else
                             '读写已结束。拔 USB → 等灯停 → 关机并等灯灭 → 取电池至少 1 分钟 → 开机；详见弹窗。') if waiting else
                           '名称与只读挂载已确认；程序尚未安装，请点首页“继续安装”。' if resource_ready and status.get('action')=='setup_all' else
                           '名称与只读挂载已确认；程序尚未安装，请点自定义外观页“继续槽位更改”。' if resource_ready else
                           '完成。请按日志提示进行下一步。' if success else
                           '操作停止：' + status.get('error', '进程异常退出，退出码 ' + str(code)) + '。请导出诊断包。')
        if not success and sys.platform == 'win32' and self.driver_step_failed(status.get('action')):
            self.status.setText(self.status.text() + DRIVER_HINT)
        if sound_notice:self.status.setText(sound_notice['status'])
        if factory_wait:self.status.setText('恢复尚未完成：写入和读回已结束，必须断电重启、接回 USB，再点“重启后核对并完成恢复”。')
        elif factory_done:self.status.setText('原厂恢复核对通过，旧安装状态已清除。请继续检查机身拍摄和回放；重新安装请点首页“一键安装”。')
        self.progress.setRange(0, 100)
        self.progress.setValue(70 if factory_wait else 0 if sound_notice and status.get('action')=='sound_install' else
                              40 if success and (resource_wait or resource_ready) else 70 if waiting and status.get('action')=='setup_all' else 100 if success else 0)
        for button in self.buttons:
            button.setEnabled(True)
        self.stop.setEnabled(False)
        self.process.deleteLater()
        self.process = None
        if success and status.get('action') in ('direct_looks_import','direct_resume_looks','direct_verify') and status.get('result',{}).get('mode') in ('install_all','look_import','slot_default') and status['result'].get('phase') in ('COMPLETED','AWAITING_RELOAD','LOADED','COMPLETE') and (status['action']!='direct_verify' or self._look_displayed_pending is not None):
            self.look_editor.set_operations([])
        self.refresh_look_controls()
        self.refresh_setup_controls()
        self.refresh_factory_controls()
        if not success and status.get('action')=='direct_factory_reset':
            from looktool.factoryrecover import prewrite_temporary_conflict
            work=self.settings.get('factory_direct_work')
            path=Path(work,'direct.private.json') if work else None
            try:state=json.loads(path.read_text(encoding='utf-8')) if path and path.is_file() else {}
            except (OSError,ValueError):state={}
            if prewrite_temporary_conflict(state) and state.get('error')==status.get('error'):
                self.status.setText('本次恢复尚未写入。按弹窗完整断电、接回 USB，再点“断电后重试恢复”。')
                self.show_reload_guide(mode='factory_prewrite_temporary')
        if sound_notice:
            W.QMessageBox.information(self,sound_notice['title'],sound_notice['text'])
        elif status.get('action')=='usb_stability':
            if success:
                result=status['result']
                W.QMessageBox.information(self,'USB 只读检测通过',
                    '已完成 %d 轮、共 %.1f MB 程序文件只读传输，持续 %.0f 秒，每轮字节一致。\n\n没有写入固件、设置或运行原生写入程序。\n\n%s'%
                    (len(result['rounds']),result['total_bytes']/1024/1024,result.get('seconds',0),result['note']))
            else:
                error=status.get('error','请查看日志并换线后重测。')
                W.QMessageBox.warning(self,'USB 连接检测未完成' if '未完成' in error else 'USB 连接检测未通过',error)
        elif waiting:
            self.show_reload_guide(setup=status.get('action')=='setup_all', mode=('resource_reload' if resource_wait else status.get('action') if
                status.get('action','').startswith('sound_') else status.get('result',{}).get('mode')))
        elif success and status.get('action')=='setup_all' and status.get('result',{}).get('phase')=='COMPLETE':
            self.status.setText('安装完成。可查看上次安装结果，无需再次刷写。')
            self.setup_button.setText('开始新的一键安装')
            self.setup_result_button.setVisible(True)
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(True)
            self.show_setup_result()

    def process_error(self, error):
        if self.process and error == QtCore.QProcess.FailedToStart:
            self.log.appendPlainText(self.process.errorString())
            self.finished(-1, None)

    def open_job(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.current_job or data_root())))

    def export_logs(self):
        if not self.current_job:
            return
        path = W.QFileDialog.getSaveFileName(self, '导出诊断包', 'a7c2-diagnostics.zip', 'ZIP (*.zip)')[0]
        if path:
            try:
                jobs.export_support(self.current_job, path)
            except Exception as exc:
                W.QMessageBox.warning(self, '导出失败', str(exc))

    def cancel_offline(self):
        if self.process and not self.camera_operation:
            self.process.terminate()

    def closeEvent(self, event):
        if self.process:
            W.QMessageBox.information(self, '任务仍在运行', '请等待当前任务结束后关闭。相机写入期间不要结束程序或拔线。')
            event.ignore()
        else:
            event.accept()


def main():
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    if '--smoke-test' in sys.argv and sys.platform == 'win32':
        # Qt's headless test platform does not enumerate Windows system fonts.
        import os
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if font.is_file():
            QtGui.QFontDatabase.addApplicationFont(str(font))
    app.setApplicationName('A7C2Tools')
    app.setOrganizationName('QAQLeonard')
    window = Window()
    if '--preview-gate-test' in sys.argv:
        window.nav.setCurrentRow(3)
    window.show()
    if '--smoke-test' in sys.argv:
        data_root().mkdir(parents=True, exist_ok=True)
        for index in range(window.pages.count()):
            window.nav.setCurrentRow(index)
            app.processEvents()
            if not window.grab().save(str(data_root() / ('desktop-page-' + str(index + 1) + '.png'))):
                raise OSError('Could not save desktop smoke screenshot')
        window.nav.setCurrentRow(0)
        QtCore.QTimer.singleShot(800, app.quit)
    else:
        QtCore.QTimer.singleShot(0,window.show_connection_notice)
    return app.exec()
