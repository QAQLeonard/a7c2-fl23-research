"""备份库：写入、校验，并保证备份确实是原厂、未打过 FL2／FL3 补丁的状态。

备份放在源码目录下的 ``backup/<机身短码>/``，每台机身一份。校验分三层：

1. **完整性**：清单里每个文件的 SHA-256 与记录一致（防篡改、防拷贝损坏）。
2. **原厂性**：两个完整程序必须与 ``core.ORIGINAL`` 完全一致。
3. **未打补丁**：机身设置里不能出现本工具写入的任何痕迹 ——
   AP 绑定槽（0x02CF1287／0x02CF1289）必须为空，CP 色彩单元里
   FL2／FL3 的参数映射必须为空、目标色彩槽必须没有数据。

只有三层全过的备份才会被还原与安装流程接受。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import core
import layout

BACKUP_FORMAT = 2
BACKUP_MANIFEST = layout.BACKUP_MANIFEST


class BackupError(RuntimeError):
    pass


def program_checks():
    """程序文件名 -> 芯片序号与原厂杂凑。"""
    return {layout.PROGRAM_FILES['appFw.so']: 0,
            layout.PROGRAM_FILES['cpapp-b.bin']: 1}


class Backup:
    """一份机身备份的读写与校验。"""

    def __init__(self, path):
        self.path = Path(path)
        self.manifest_path = self.path / BACKUP_MANIFEST

    # ---------- 写入 ----------
    def write(self, files, identity, created=None):
        """files: {文件名: bytes}；写入后立刻做一次完整校验。"""
        self.path.mkdir(parents=True, exist_ok=True)
        digests = {}
        for name, data in files.items():
            target = self.path / name
            target.write_bytes(data)
            if core.sha(target.read_bytes()) != core.sha(data):
                raise BackupError('备份写入后读回不符：' + name)
            digests[name] = core.sha(data)
        manifest = {
            'format': BACKUP_FORMAT,
            'created': created or datetime.now().isoformat(timespec='seconds'),
            'model': core.MODEL,
            'version': core.VERSION,
            'serial_sha256': (identity or {}).get('serial_sha256'),
            'identity': identity,
            'files': digests,
            'programs': {name: core.ORIGINAL[chip] for name, chip in program_checks().items()},
            'ap_keys': [hex(k) for k in core.AP_KEYS],
            'colour_slots': [[p, s] for p, s in core.COLOUR_SLOTS],
        }
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return self.verify()

    # ---------- 读取 ----------
    def manifest(self):
        if not self.manifest_path.is_file():
            raise BackupError('没有备份清单，这不是一份可用备份')
        try:
            data = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise BackupError('备份清单无法解析：%s' % exc)
        if data.get('format') != BACKUP_FORMAT:
            raise BackupError('备份清单格式不是 %d' % BACKUP_FORMAT)
        if data.get('model') != core.MODEL or data.get('version') != core.VERSION:
            raise BackupError('备份属于 %s %s，与本机工具不符'
                              % (data.get('model'), data.get('version')))
        return data

    def files(self):
        return self.manifest()['files']

    # ---------- 校验 ----------
    def verify(self):
        """三层校验；返回结果字典，不抛异常。"""
        report = {'path': str(self.path), 'ok': False, 'checks': [], 'problems': []}

        def check(name, ok, detail=''):
            report['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail})
            if not ok:
                report['problems'].append(f'{name}：{detail}' if detail else name)
            return ok

        try:
            manifest = self.manifest()
        except BackupError as exc:
            check('备份清单', False, str(exc))
            return report
        check('备份清单', True, manifest.get('created', ''))

        # 1. 完整性
        blobs = {}
        for name, expected in manifest['files'].items():
            target = self.path / name
            if not target.is_file():
                check('文件完整', False, '缺少 ' + name)
                continue
            data = target.read_bytes()
            got = core.sha(data)
            if got != expected:
                check('文件完整', False, f'{name} 杂凑不符（可能被改动或拷贝损坏）')
                continue
            blobs[name] = data
        if not report['problems']:
            check('文件完整', True, f"{len(manifest['files'])} 个文件杂凑一致")

        # 2. 原厂性
        for name, chip in program_checks().items():
            data = blobs.get(name)
            if data is None:
                continue
            expected = core.ORIGINAL[chip]
            got = core.sha(data)
            check(f'原厂程序 {name}', got == expected,
                  '' if got == expected else '不是未打补丁的原厂程序')

        # 3. 未打 FL2／FL3 补丁
        settings = blobs.get(layout.SETTINGS_FILE)
        if settings is None:
            check('机身设置', False, '缺少 ' + layout.SETTINGS_FILE)
        else:
            try:
                records = core.backup_records(settings)
                check('机身设置 BK4 校验', True, '两份 BK4 校验通过')
                ap = {}
                for key in core.AP_KEYS:
                    value = records[0][key].data if key in records[0] else None
                    ap[key] = value
                dirty = [hex(k) for k, v in ap.items() if v not in (None, b'\0')]
                check('AP 绑定槽为空', not dirty,
                      '' if not dirty else '已存在 FL2／FL3 绑定：' + ', '.join(dirty))
            except Exception as exc:
                check('机身设置 BK4 校验', False, str(exc))

        unit01 = blobs.get(layout.UNIT_FILES[core.CP_KEYS[0]])
        unit0d = blobs.get(layout.UNIT_FILES[core.CP_KEYS[1]])
        if unit01 is None or unit0d is None:
            check('CP 色彩单元', False, '缺少色彩单元备份')
        else:
            mapped = [(p, unit01[0x1200 + p], unit0d[0x196 + p]) for p, _ in core.COLOUR_SLOTS]
            used = [hex(p) for p, a, b in mapped if a or b]
            check('FL2／FL3 参数映射为空', not used,
                  '' if not used else '映射已占用：' + ', '.join(used))
            occupied = []
            for _, slot in core.COLOUR_SLOTS:
                if any(unit01[0x1250 + slot * 64:0x1250 + slot * 64 + 64]):
                    occupied.append(f'unit01 槽 {slot}')
                if any(unit0d[0x1e0 + slot * 768:0x1e0 + slot * 768 + 576]):
                    occupied.append(f'unit0d 槽 {slot}')
            check('目标色彩槽为空', not occupied,
                  '' if not occupied else '已有数据：' + ', '.join(occupied))

        report['ok'] = not report['problems']
        report['serial_sha256'] = manifest.get('serial_sha256')
        report['created'] = manifest.get('created')
        return report

    def require(self):
        report = self.verify()
        if not report['ok']:
            raise BackupError('备份未通过校验：' + '；'.join(report['problems']))
        return report

    def load_units(self):
        self.require()
        return {key: (self.path / name).read_bytes() for key, name in layout.UNIT_FILES.items()}

    def load_settings(self):
        self.require()
        return (self.path / layout.SETTINGS_FILE).read_bytes()


def verified_backup(serial_sha256=None):
    """找出一份通过校验的备份；没有就返回 None。"""
    for info in layout.list_backups():
        try:
            backup = Backup(info['path'])
            report = backup.verify()
        except Exception:
            continue
        if not report['ok']:
            continue
        if serial_sha256 and (report.get('serial_sha256') or '')[:layout.SERIAL_LENGTH] \
                != serial_sha256[:layout.SERIAL_LENGTH]:
            continue
        report['backup'] = backup
        return report
    return None
