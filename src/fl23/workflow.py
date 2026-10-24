"""检查 / 备份 / 还原 / 安装的编排逻辑。

流程（与界面上的按钮一一对应）：

* **检查**：先确认 054C:0E8A 的驱动，再让相机切到 SonyUSBDevice（054C:0336），
  最后复检 0336 的驱动。两次驱动验证都通过才算就绪。
* **备份**：读回本机程序与设置写入 ``workdir/<会话>/original`` 与
  ``backup/<机身>``，随后校验备份为原厂未打补丁状态。已有已验证备份时不可执行。
* **还原**：只用已验证的备份恢复，独立模块，不依赖某次工作目录。
* **安装**：没有备份就先备份；已有备份则只读回一次确认机身仍是初始状态，
  读回后等 5 秒让 USB 身份刷新，再写入。

所有相机访问都经 transport.Session，所有离线判据都在 core。
"""
from __future__ import annotations

import struct
import time
from datetime import datetime
from pathlib import Path

import backup as backup_mod
import core
import layout
import usbdev

INSTALL_REFRESH_SECONDS = 5


def event(message):
    print(message, flush=True)


class Job:
    def __init__(self, workspace=None):
        self.root = Path(workspace).resolve() if workspace else layout.session_path()
        for sub in ('original', 'candidate', 'readback', 'evidence'):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / 'state.json'
        self.state = {}
        self.backup = None

    # ---------- 状态记录 ----------
    def save(self, phase, **values):
        self.state.update(values)
        self.state['phase'] = phase
        core.save_json(self.state_path, self.state)

    def audit(self, step, **values):
        row = {'time': datetime.now().isoformat(), 'step': step, **values}
        self.state.setdefault('journal', []).append(row)
        core.save_json(self.state_path, self.state)

    def load(self):
        core.assets()
        self.state = core.read_json(self.state_path)
        if self.state.get('format') != 2 or self.state.get('model') != core.MODEL:
            raise ValueError('不是有效的工作目录')
        return self

    # ---------- 备份来源 ----------
    def attach_backup(self, serial_sha256=None):
        if serial_sha256 is None:
            serial_sha256 = self.state.get('identity', {}).get('serial_sha256')
        if self.backup is not None:
            report = self.backup.require()
            if serial_sha256 and report.get('serial_sha256') != serial_sha256:
                raise ValueError('指定备份与当前机身不同，拒绝继续')
            report = dict(report, backup=self.backup)
        else:
            report = backup_mod.verified_backup(serial_sha256)
        if report is None:
            return None
        self.backup = report['backup']
        self.state.setdefault('format', 2)
        self.state.setdefault('model', core.MODEL)
        self.state.setdefault('version', core.VERSION)
        self.state.setdefault('identity', {'model': core.MODEL,
                                          'serial_sha256': report.get('serial_sha256')})
        self.state['backup'] = {'path': str(self.backup.path),
                                'created': report.get('created'),
                                'serial_sha256': report.get('serial_sha256')}
        return report

    def units(self):
        """Use the selected verified backup before any old workspace units."""
        local = self.root / 'original'
        have = all((local / layout.UNIT_FILES[k]).is_file() for k in core.CP_KEYS)
        source = self.backup.path if self.backup is not None else (local if have else None)
        if source is None:
            raise ValueError('既没有本机备份也没有可用备份库')
        originals = {k: (source / layout.UNIT_FILES[k]).read_bytes() for k in core.CP_KEYS}
        merged = core.merge_colors(originals[core.CP_KEYS[0]], originals[core.CP_KEYS[1]])
        return originals, dict(zip(core.CP_KEYS, merged))

    # ---------- 原生模块 ----------
    def module(self, session, name, mode=None):
        blob = (core.BASE / 'assets' / f'{name}.so').read_bytes()
        result = {'installer': 'a7c2.install.result', 'probe': 'a7c2.probe.result',
                  'wbi': 'a7c2.wbi.result', 'runtime': 'a7c2.runtime.result'}[name]
        request = {'installer': ('a7c2.install.request', b'A7INS001'),
                   'wbi': ('a7c2.wbi.request', b'A7WBI001')}.get(name)
        names = ['libJit.so', 'a7c2-preview-staged.so', result]
        if name == 'runtime':
            names.append('a7c2.probe.result')
        if request:
            names.append(request[0])
        for item in names:
            if session.read('/tmp/jiritsu/' + item, True) is not None:
                raise RuntimeError('存在先前临时文件，先保存并确认结果，请勿直接重试：' + item)
        if session.read('/tmp/jiritsu/../../etc/ld.so.preload', True):
            raise RuntimeError('发现既有预载配置，停止')
        created = []
        launched = False
        try:
            created.append('a7c2-preview-staged.so')
            session.temp(created[-1], blob)
            if session.read('/tmp/jiritsu/' + created[-1]) != blob:
                raise RuntimeError('临时模块读回不符')
            if request:
                contents = struct.pack('<8sII', request[1], mode, 0)
                created.append(request[0])
                session.temp(request[0], contents)
                if session.read('/tmp/jiritsu/' + request[0]) != contents:
                    raise RuntimeError('执行模式读回不符')
            self.audit('native_about_to_run', module=name, mode=mode)
            created.extend(['libJit.so', result])
            if name == 'runtime':
                created.append('a7c2.probe.result')
            launched = True
            session.temp('libJit.so', blob)
            raw = session.read('/tmp/jiritsu/' + result)
            dest = self.root / 'evidence' / f'{datetime.now():%Y%m%d-%H%M%S-%f}-{name}.bin'
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(raw)
            parsed = core.parse_native(name, raw, mode)
            self.audit('native_verified', module=name, mode=mode, result=parsed)
            return parsed
        except BaseException:
            if launched:
                session.healthy = False
            raise
        finally:
            for item in reversed(list(dict.fromkeys(created))):
                if not session.healthy:
                    self.audit('temporary_cleanup_pending', name=item)
                    continue
                if session.read('/tmp/jiritsu/' + item, True) is not None:
                    session.temp(item, remove=True)
                if session.read('/tmp/jiritsu/' + item, True) is not None:
                    raise RuntimeError('临时文件清理未完成')

    # ---------- 检查 ----------
    def check(self):
        core.assets()
        report = usbdev.preflight()
        for step in report['steps']:
            event(('通过：' if step['ok'] else '未通过：') + step['step']
                  + ((' — ' + step['detail']) if step.get('detail') else ''))
        self.state.update({'format': 2, 'model': core.MODEL, 'version': core.VERSION,
                           'phase': 'checked' if report['ok'] else 'needs_review',
                           'preflight': report})
        self.save('checked' if report['ok'] else 'needs_review')
        event(report['message'])
        if not report['ok']:
            raise RuntimeError(report['message'])
        return report

    # ---------- 备份 ----------
    def backup_flow(self):
        from transport import Session
        core.assets()
        with Session() as session:
            identity = session.identity
            self.state.update({'format': 2, 'model': core.MODEL, 'version': core.VERSION,
                               'identity': identity, 'journal': []})
            target = layout.backup_path(identity.get('serial_sha256'))
            self.save('backing_up', backup_store=str(target))
            event('已识别 ' + core.MODEL + '，正在备份原厂程序与本机设置。')
            settings = session.call(session.camera.getBackupPresetData, True)
            records = core.backup_records(settings)
            originals = {}
            for chip, name, path in [(1, core.PROGRAMS[1], '/cp/cpapp-b.bin'),
                                     (0, core.PROGRAMS[0], '/usr/lib/appFw.so')]:
                event('读取完整 ' + name)
                data = session.read('/tmp/jiritsu/../..' + path)
                if core.sha(data) != core.ORIGINAL[chip]:
                    raise ValueError('程序不是支持的原版 2.01，拒绝继续')
                originals[layout.PROGRAM_FILES[name]] = data
                (self.root / 'candidate' / name).write_bytes(core.patch_program(data, chip))
            originals[layout.SETTINGS_FILE] = settings
            for key in core.CP_KEYS:
                data = session.cp_read(key)
                if data != records[1][key].data:
                    raise ValueError('原生色彩读回与机身备份不符')
                originals[layout.UNIT_FILES[key]] = data
            for key in core.AP_KEYS:
                if session.call(session.camera.readBackup, key) != b'\0' or records[0][key].data != b'\0':
                    raise ValueError('保留槽已使用，此预览版拒绝覆盖')
            merged = core.merge_colors(originals[layout.UNIT_FILES[core.CP_KEYS[0]]],
                                       originals[layout.UNIT_FILES[core.CP_KEYS[1]]])
            for key, data in zip(core.CP_KEYS, merged):
                (self.root / 'candidate' / layout.UNIT_FILES[key]).write_bytes(data)
            for name, data in originals.items():
                for parent in (self.root / 'original', target):
                    destination = parent / name
                    destination.write_bytes(data)
                    if core.sha(destination.read_bytes()) != core.sha(data):
                        raise ValueError('备份写回验证不符')
            self.save('backup_files_written')
            store = backup_mod.Backup(target)
            report = store.write(originals, identity)
            self.state['backup'] = {'path': str(target), 'report': report}
            self.save('backup_verified')
            if not report['ok']:
                raise ValueError('备份未通过校验：' + '；'.join(report['problems']))
            for check_row in report['checks']:
                event(('通过：' if check_row['ok'] else '未通过：') + check_row['name'])
            self.module(session, 'probe')
            self.module(session, 'installer', 0)
            self.module(session, 'wbi', 0)
        self.save('backed_up')
        event('备份与实机只读校验完成，尚未改写固件或保存拍摄设置。')
        return self.state['backup']

    # ---------- 完整读回 ----------
    def files(self, session, expected):
        for chip, name, path in [(1, core.PROGRAMS[1], '/cp/cpapp-b.bin'),
                                 (0, core.PROGRAMS[0], '/usr/lib/appFw.so')]:
            event('完整读回 ' + name)
            data = session.read('/tmp/jiritsu/../..' + path)
            folder = self.root / 'readback'
            folder.mkdir(exist_ok=True)
            (folder / f'{datetime.now():%Y%m%d-%H%M%S-%f}-{name}').write_bytes(data)
            if core.sha(data) != expected[chip]:
                raise ValueError('程序完整读回不符，停止后续操作')
        self.audit('host_full_file_readback_verified', hashes=expected)

    def program_state(self, session):
        found = []
        for chip, name, path in [(1, core.PROGRAMS[1], '/cp/cpapp-b.bin'),
                                 (0, core.PROGRAMS[0], '/usr/lib/appFw.so')]:
            event('完整读回 ' + name)
            data = session.read('/tmp/jiritsu/../..' + path)
            folder = self.root / 'readback'
            folder.mkdir(exist_ok=True)
            (folder / f'{datetime.now():%Y%m%d-%H%M%S-%f}-{name}').write_bytes(data)
            digest = core.sha(data)
            if digest == core.FINAL[chip]:
                found.append('final')
            elif digest == core.ORIGINAL[chip]:
                found.append('original')
            else:
                raise ValueError(name + '既非原版也非已安装版，逐字节还原无从判定，请保存 readback 后检查')
        if len(set(found)) != 1:
            raise ValueError(f'两个程序版本状态不一致（{found}），请保存 readback 后检查')
        return found[0]

    # ---------- 设置 ----------
    def settings(self, session, restore=False):
        originals, merged = self.units()
        target = originals if restore else merged
        desired = dict(zip(core.AP_KEYS, [b'\0', b'\0'] if restore else [b'\x0a', b'\x0b']))
        before_raw = session.call(session.camera.getBackupPresetData, True)
        before = core.backup_records(before_raw)
        folder = self.root / 'evidence'
        folder.mkdir(exist_ok=True)
        (folder / f'{datetime.now():%Y%m%d-%H%M%S-%f}-settings-before.private.bin').write_bytes(before_raw)
        current_cp = {k: session.cp_read(k) for k in core.CP_KEYS}
        current_ap = {k: session.call(session.camera.readBackup, k) for k in core.AP_KEYS}
        for index, key in enumerate(core.CP_KEYS):
            if before[1][key].data != current_cp[key]:
                raise ValueError('CP 设置状态未知，拒绝写入')
            if restore:
                if not core.matches_outside_colour(current_cp[key], originals[key], index):
                    offset = core.colour_window_diff(current_cp[key], originals[key], index)
                    raise ValueError(f'CP 设置状态未知，拒绝写入（{key:#x} 于色彩窗口外不符：{offset}）')
                if current_cp[key] != originals[key]:
                    self.audit('cp_from_other_package', key=hex(key), index=index)
            elif current_cp[key] != originals[key]:
                offset = core.colour_window_diff(current_cp[key], originals[key], index)
                raise ValueError(f'CP 设置状态未知，拒绝写入（{key:#x} 于色彩窗口外不符：{offset}）')
        for i, key in enumerate(core.AP_KEYS):
            accepted = [b'\0', bytes([10 + i])] if restore else [b'\0']
            if current_ap[key] not in accepted or before[0][key].data != current_ap[key]:
                raise ValueError('AP 设置状态未知，拒绝写入')
        for key in core.CP_KEYS:
            if current_cp[key] == target[key]:
                continue
            self.audit('about_to_write_cp', key=hex(key))
            session.cp_write(key, target[key])
            if session.cp_read(key) != target[key]:
                raise ValueError('CP 读回失败')
        if any(current_cp[k] != target[k] for k in core.CP_KEYS):
            self.audit('about_to_save_cp')
            session.call(session.camera.saveBackup, 0x02a4)
        for key in core.AP_KEYS:
            if current_ap[key] == desired[key]:
                continue
            self.audit('about_to_write_ap', key=hex(key))
            session.ap_write(key, desired[key])
            if session.call(session.camera.readBackup, key) != desired[key]:
                raise ValueError('AP 绑定读回失败')
        if any(current_ap[k] != desired[k] for k in core.AP_KEYS):
            self.audit('about_to_save_ap')
            session.call(session.camera.saveBackup, 0x02cf)
        after_raw = session.call(session.camera.getBackupPresetData, True)
        stored_raw = session.call(session.camera.getBackupPresetData, False)
        (folder / f'{datetime.now():%Y%m%d-%H%M%S-%f}-settings-after.private.bin').write_bytes(after_raw)
        (folder / f'{datetime.now():%Y%m%d-%H%M%S-%f}-settings-stored.private.bin').write_bytes(stored_raw)
        expected = {(0, k): v for k, v in desired.items()}
        expected.update({(1, k): v for k, v in target.items()})
        preservation = core.verify_preservation(before, core.backup_records(after_raw), expected)
        stored = core.backup_records(stored_raw)
        for (chip, key), value in expected.items():
            if stored[chip][key].data != value:
                raise ValueError('保存后读回不符')
        self.audit('settings_storage_verified', restore=restore, **preservation)

    # ---------- 安装 ----------
    def install(self, battery):
        core.assets()
        if not 50 <= battery <= 100:
            raise ValueError('请确认电量至少 50%，并保持连接')
        from transport import Session
        report = self.attach_backup()
        if report is None:
            event('没有已验证备份，先执行备份。')
            self.backup_flow()
            report = self.attach_backup()
            if report is None:
                raise ValueError('备份后仍找不到已验证备份，停止')
        else:
            event('已找到已验证备份，先读回一次确认机身仍处于初始状态。')
            with Session(self.state.get('identity')) as session:
                self.state['identity'] = session.identity
                self.files(session, core.ORIGINAL)
            event('读回校验通过，等待 %d 秒让 USB 身份刷新。' % INSTALL_REFRESH_SECONDS)
            time.sleep(INSTALL_REFRESH_SECONDS)
        self.save('install_ready')
        with Session(self.state.get('identity')) as session:
            originals, _ = self.units()
            current = core.backup_records(session.call(session.camera.getBackupPresetData, True))
            if any(current[1][k].data != v for k, v in originals.items()) or \
               any(current[0][k].data != b'\0' for k in core.AP_KEYS):
                raise ValueError('机身目标设置已变，请勿覆盖')
            self.module(session, 'wbi', 0)
            self.save('writing_programs')
            event('正在写入固定窗口，请勿拔线或关机。')
            self.module(session, 'installer', 1)
            self.save('programs_written')
            self.files(session, core.FINAL)
            self.save('writing_settings')
            self.settings(session)
            self.save('settings_verified')
            event('程序与保存设置已验证，正在处理旧开机快照。')
            self.module(session, 'wbi', 1)
        self.save('installed_pending_cold_start')
        event('安装及读回完成。拔线、正常关机，等存取灯熄灭后取出电池 10 秒，再装回开机。')
        event('请分别重设 FL2／FL3、拍新照片并回放；目前是实验预览版。')

    # ---------- 重启后核对 ----------
    def verify(self):
        from transport import Session
        self.load()
        recorded = self.state.get('backup', {}).get('path')
        if self.backup is None and recorded:
            self.backup = backup_mod.Backup(recorded)
        if self.attach_backup() is None:
            raise ValueError('没有通过校验的备份，无法核对')
        with Session(self.state.get('identity')) as session:
            self.files(session, core.FINAL)
            current = core.backup_records(session.call(session.camera.getBackupPresetData, True))
            _, new = self.units()
            if any(current[1][k].data != v for k, v in new.items()):
                raise ValueError('重启后 CP 参数不符')
            if any(current[0][k].data != bytes([10 + i]) for i, k in enumerate(core.AP_KEYS)):
                raise ValueError('重启后 AP 绑定不符')
            runtime = self.module(session, 'runtime')
            candidate = core.patch_program(
                (self.backup.path / layout.PROGRAM_FILES['appFw.so']).read_bytes(), 0)
            for span in runtime['spans']:
                expected = candidate[span['offset']:span['offset'] + span['length']].hex()
                if span['memory'] != expected or span['disk'] != expected:
                    raise ValueError('执行期仍有旧数据，请确认已关机并取出电池后再开机')
        self.audit('post_restart_files_and_targets_verified')
        event('磁盘程序与保存参数符合预期；菜单、照片与回放仍需实际检查。')

    # ---------- 还原（独立模块入口） ----------
    def restore(self, battery):
        core.assets()
        if not 50 <= battery <= 100:
            raise ValueError('还原前需确认电量至少 50%')
        report = self.attach_backup()
        if report is None:
            raise ValueError('没有通过校验的备份，无法还原')
        from transport import Session
        event('使用备份 ' + str(self.backup.path))
        expected_identity = {'model': core.MODEL,
                             'serial_sha256': report.get('serial_sha256')}
        with Session(expected_identity) as session:
            self.state['identity'] = session.identity
            state = self.program_state(session)
            if state == 'original':
                event('两个程序已是原版，只处理设置与开机快照。')
            self.module(session, 'wbi', 0)
            self.save('restoring_settings')
            self.settings(session, True)
            if state == 'original':
                self.files(session, core.ORIGINAL)
            else:
                self.save('restoring_programs')
                self.module(session, 'installer', 2)
                self.files(session, core.ORIGINAL)
            self.module(session, 'wbi', 1)
        self.save('restored_pending_cold_start')
        event('原厂程序与四项目标设置已还原并读回。正常关机后取出电池 10 秒再开机。')


def restore_from_backup(battery, workspace=None, backup_path=None):
    """独立还原入口：只依赖备份库，不依赖某次工作目录。"""
    job = Job(workspace)
    if backup_path:
        job.backup = backup_mod.Backup(backup_path)
        report = job.backup.verify()
        if not report['ok']:
            raise ValueError('备份未通过校验：' + '；'.join(report['problems']))
        job.state['backup'] = {'path': str(job.backup.path), 'report': report}
    job.restore(battery)
    return job
