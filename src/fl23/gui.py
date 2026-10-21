"""A7C II · FL2／FL3 预览版图形界面（简体中文）。

界面只负责显示状态与启动命令行流程；所有判断与写入仍在 app.py /
workflow.py 里，可以脱离界面单独复核。

按钮规则：

* **检查** — 随时可用。先确认 054C:0E8A 驱动，再让相机进入
  SonyUSBDevice（054C:0336），最后复检 0336 驱动。
* **备份** — 已有通过校验的备份时禁用。
* **还原** — 只有存在通过校验的备份时可用，独立模块，只用备份文件。
* **安装** — 没有备份会先自动备份；已有备份则只读回一次确认初始状态，
  等 5 秒 USB 刷新后再写入。
* **重启后核对** — 安装完成并冷启动后核对。
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

BASE = Path(__file__).resolve().parent
APP = BASE / 'app.py'

GREEN = '#0F6E56'
RED = '#A32D2D'
AMBER = '#854F0B'
GRAY = '#5F5E5A'


def _import_state_modules():
    """延迟导入，避免界面启动时就触碰 USB 相关依赖。"""
    sys.path.insert(0, str(BASE))
    import backup as backup_mod
    import layout
    return backup_mod, layout


class App:
    def __init__(self, root):
        self.root = root
        self.backup_mod, self.layout = _import_state_modules()
        self.queue = queue.Queue()
        self.running = False
        self.last_workspace = None
        self.driver_ok = {'0e8a': None, '0336': None}
        self.backup_report = None
        root.title('A7C II · FL2／FL3 预览版')
        root.geometry('900x720')
        root.minsize(820, 640)
        self._build()
        self.refresh()
        self._tick()

    # ---------- 界面 ----------
    def _build(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill='both', expand=True)

        ttk.Label(outer, text='A7C II · FL2 / FL3 预览版',
                  font=('Microsoft YaHei UI', 21, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='仅适用于原厂 2.01 机身的实验预览版，操作前请确认电量充足并保持 USB 连接。',
                  wraplength=840).pack(anchor='w', pady=(4, 2))
        ttk.Label(outer, text='工作目录自动建在 workdir/ 下，备份自动放在 backup/ 下，无需手动指定。',
                  wraplength=840).pack(anchor='w', pady=(0, 12))

        panel = ttk.LabelFrame(outer, text='当前状态', padding=12)
        panel.pack(fill='x')
        self.status = {}
        for key, label in [
            ('driver_0e8a', 'USB 驱动 054C:0E8A（海量存储）'),
            ('driver_0336', 'USB 驱动 054C:0336（SonyUSBDevice）'),
            ('backup', '备份（原厂未打补丁）'),
            ('phase', '机身阶段'),
        ]:
            line = ttk.Frame(panel)
            line.pack(fill='x', pady=2)
            ttk.Label(line, text=label, width=34).pack(side='left')
            value = ttk.Label(line, text='—', font=('Microsoft YaHei UI', 10, 'bold'))
            value.pack(side='left')
            self.status[key] = value

        battery_row = ttk.Frame(outer)
        battery_row.pack(fill='x', pady=(12, 4))
        ttk.Label(battery_row, text='当前电量：').pack(side='left')
        self.battery = tk.StringVar()
        ttk.Entry(battery_row, width=6, textvariable=self.battery).pack(side='left')
        ttk.Label(battery_row, text='%   写入与还原至少需要 50%，期间不要拔线或关机。').pack(side='left', padx=(6, 0))

        self.paths = tk.StringVar(value='')
        ttk.Label(outer, textvariable=self.paths, wraplength=840,
                  foreground=GRAY).pack(anchor='w', pady=(2, 8))

        buttons = ttk.Frame(outer)
        buttons.pack(fill='x')
        self.buttons = {}
        for key, text, command in [
            ('check', '1  检查', 'check'),
            ('backup', '2  备份', 'backup'),
            ('install', '3  安装', 'install'),
            ('restore', '还原', 'restore'),
            ('verify', '重启后核对', 'verify'),
        ]:
            button = ttk.Button(buttons, text=text, command=lambda c=command: self.run(c))
            button.pack(side='left', padx=(0, 8))
            self.buttons[key] = button
        ttk.Button(buttons, text='打开备份目录', command=self.open_backup).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='打开最近工作目录', command=self.open_workspace).pack(side='left')

        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x', pady=(12, 4))
        self.headline = tk.StringVar(value='请先点“检查”，确认两个 USB 身份的驱动都已安装。')
        ttk.Label(outer, textvariable=self.headline, wraplength=840).pack(anchor='w')

        log_frame = ttk.LabelFrame(outer, text='运行日志', padding=6)
        log_frame.pack(fill='both', expand=True, pady=(10, 0))
        self.log = tk.Text(log_frame, height=14, wrap='word', state='disabled',
                           font=('Consolas', 10))
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)

        self.root.protocol('WM_DELETE_WINDOW', self.close)

    # ---------- 状态 ----------
    def _paint(self, widget, text, color):
        widget.configure(text=text, foreground=color)

    def refresh(self):
        report = self.backup_mod.verified_backup()
        self.backup_report = report
        if report:
            self._paint(self.status['backup'], '已验证 · ' + str(report.get('created') or ''), GREEN)
        else:
            entries = self.layout.list_backups()
            if entries:
                self._paint(self.status['backup'],
                            '未找到通过校验的备份（backup/ 下 %d 份不可用）' % len(entries), RED)
            else:
                self._paint(self.status['backup'], '尚未备份', AMBER)
        for key, token in (('driver_0e8a', '0e8a'), ('driver_0336', '0336')):
            state = self.driver_ok[token]
            if state is None:
                self._paint(self.status[key], '未检查', GRAY)
            elif state:
                self._paint(self.status[key], '已就绪', GREEN)
            else:
                self._paint(self.status[key], '驱动不可用', RED)
        sessions = self.layout.sorted_sessions()
        if sessions:
            state_file = sessions[0] / 'state.json'
            phase = '—'
            if state_file.is_file():
                try:
                    phase = json.loads(state_file.read_text(encoding='utf-8')).get('phase', '—')
                except Exception:
                    phase = '读取失败'
            self._paint(self.status['phase'], '%s（%s）' % (phase, sessions[0].name),
                        GREEN if phase in ('checked', 'backed_up', 'installed_pending_cold_start',
                                           'restored_pending_cold_start') else GRAY)
            self.last_workspace = sessions[0]
        else:
            self._paint(self.status['phase'], '尚无工作记录', GRAY)
            if self.last_workspace is None:
                self.last_workspace = None
        self.paths.set('备份目录：%s    最近工作目录：%s'
                       % (self.layout.BACKUP, self.last_workspace or '（无）'))
        self._sync_buttons()

    def _enable(self, key, on):
        self.buttons[key].configure(state='normal' if (on and not self.running) else 'disabled')

    def _sync_buttons(self):
        has_backup = self.backup_report is not None
        self._enable('check', True)
        self._enable('backup', not has_backup)
        self._enable('restore', has_backup)
        self._enable('install', True)
        self._enable('verify', self.last_workspace is not None)

    # ---------- 执行 ----------
    def run(self, command):
        if self.running:
            return
        needs_battery = command in ('install', 'restore')
        cmd = [sys.executable, '-u', str(APP), command]
        if command == 'verify':
            if self.last_workspace is None:
                messagebox.showinfo('缺少工作目录', '请先选择已完成安装的工作记录。')
                return
            cmd += ['--workspace', str(self.last_workspace)]
        if needs_battery:
            try:
                battery = int(self.battery.get().strip())
            except ValueError:
                battery = -1
            if not 50 <= battery <= 100:
                messagebox.showinfo('请确认电量', '写入与还原至少需要 50% 电量，请填写当前实际电量。')
                return
            cmd += ['--battery-percent', str(battery)]
        self.running = True
        self.progress.start(12)
        self.headline.set('处理中，请勿拔线、关机或关闭窗口。')
        self._sync_buttons()
        self._log('\n$ %s\n' % ' '.join(cmd[2:]))

        def worker():
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            try:
                with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding='utf-8', errors='replace',
                                      env=env, cwd=str(BASE), creationflags=flags) as proc:
                    for line in proc.stdout:
                        self.queue.put(('line', line))
                    self.queue.put(('done', proc.wait()))
            except Exception as exc:
                self.queue.put(('line', str(exc) + '\n'))
                self.queue.put(('done', 1))

        threading.Thread(target=worker, daemon=True).start()

    def _log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.configure(state='disabled')

    def _tick(self):
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == 'line':
                    if value.startswith('工作目录：'):
                        self.last_workspace = Path(value.split('：', 1)[1].strip())
                    self._log(value)
                else:
                    self.running = False
                    self.progress.stop()
                    self.refresh()
                    self.headline.set('处理完成，请阅读下方日志确认结果。' if value == 0
                                      else '已停止。请保留工作目录，按日志内容确认状态，不要盲目重跑写入。')
        except queue.Empty:
            pass
        text = self.log.get('1.0', 'end')
        for token, key in (('0E8A', '0e8a'), ('0336', '0336')):
            if ('通过：驱动预检（%s）' % token) in text or ('通过：驱动复检（%s）' % token) in text:
                self.driver_ok[key] = True
            elif ('未通过：驱动预检（%s）' % token) in text or ('未通过：驱动复检（%s）' % token) in text:
                self.driver_ok[key] = False
        if self.driver_ok['0e8a'] is not None:
            self._paint(self.status['driver_0e8a'], '已就绪' if self.driver_ok['0e8a'] else '驱动不可用',
                        GREEN if self.driver_ok['0e8a'] else RED)
        if self.driver_ok['0336'] is not None:
            self._paint(self.status['driver_0336'], '已就绪' if self.driver_ok['0336'] else '驱动不可用',
                        GREEN if self.driver_ok['0336'] else RED)
        self.root.after(120, self._tick)

    # ---------- 杂项 ----------
    def _open(self, path):
        if path is None or not Path(path).exists():
            messagebox.showinfo('目录不存在', '该目录还没有创建。')
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showinfo('无法打开', str(exc))

    def open_backup(self):
        self._open(self.layout.BACKUP)

    def open_workspace(self):
        self._open(self.last_workspace)

    def close(self):
        if self.running:
            messagebox.showinfo('仍在处理', '读写尚未结束，请等待结果。')
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        tkfont.nametofont('TkDefaultFont').configure(family='Microsoft YaHei UI', size=10)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
