"""目录约定：源码目录下固定的 workdir / backup，不需要用户手动指定。

- workdir/          每次工作自动在里面建一个会话目录，保留完整过程记录
- backup/<机身>/    每个机身一份已验证备份，供还原与安装前的状态核对使用

会话目录里仍然保留原来的 original/、candidate/、readback/、evidence/ 结构，
这样 0.1.0–0.5.2 留下的记录依旧能被读懂。
"""
from datetime import datetime
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
WORKDIR = SOURCE / 'workdir'
BACKUP = SOURCE / 'backup'

SESSION_DIR = 'workdir'
BACKUP_DIR = 'backup'
SERIAL_LENGTH = 8

PROGRAM_FILES = {'appFw.so': 'appFw.so.bin', 'cpapp-b.bin': 'cpapp-b.bin.bin'}
UNIT_FILES = {0x02a40001: 'unit-02a40001.bin', 0x02a4000d: 'unit-02a4000d.bin'}
SETTINGS_FILE = 'backup.private.bin'
BACKUP_MANIFEST = 'backup.json'


def _stamp():
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def session_path(serial_sha256=None, stamp=None):
    """workdir/<日期>-<机身短码>：每次工作一个，绝不复用旧目录。"""
    WORKDIR.mkdir(parents=True, exist_ok=True)
    tail = (serial_sha256 or 'unknown')[:SERIAL_LENGTH]
    name = f'{stamp or _stamp()}-{tail}'
    path = WORKDIR / name
    if path.exists():                      # 同一秒内重复启动也不会覆盖
        extra = 1
        while (WORKDIR / f'{name}-{extra}').exists():
            extra += 1
        path = WORKDIR / f'{name}-{extra}'
    for sub in ('original', 'candidate', 'readback', 'evidence'):
        (path / sub).mkdir(parents=True, exist_ok=True)
    return path


def backup_path(serial_sha256):
    """backup/<机身短码>：一个机身一份，重复备份只会更新同一处。"""
    BACKUP.mkdir(parents=True, exist_ok=True)
    path = BACKUP / (serial_sha256 or 'unknown')[:SERIAL_LENGTH]
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_backups():
    """列出 backup/ 下所有看起来像备份的目录（未校验）。"""
    if not BACKUP.is_dir():
        return []
    out = []
    for entry in sorted(BACKUP.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / BACKUP_MANIFEST
        info = {'path': entry, 'serial': None, 'created': None, 'manifest': manifest.exists()}
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding='utf-8'))
                info['serial'] = data.get('serial_sha256')
                info['created'] = data.get('created')
                info['model'] = data.get('model')
                info['version'] = data.get('version')
            except Exception:
                info['manifest'] = 'unreadable'
        out.append(info)
    return out


def find_backup(serial_sha256=None):
    """优先按机身短码精确匹配；否则在只有一个备份时退回它。"""
    entries = list_backups()
    if not entries:
        return None
    if serial_sha256:
        tail = serial_sha256[:SERIAL_LENGTH]
        for info in entries:
            if (info['serial'] or '')[:SERIAL_LENGTH] == tail or info['path'].name == tail:
                return info['path']
        return None
    usable = [e for e in entries if e['manifest'] is True]
    return usable[0]['path'] if len(usable) == 1 else None


def sorted_sessions():
    if not WORKDIR.is_dir():
        return []
    return sorted((p for p in WORKDIR.iterdir() if p.is_dir()), reverse=True)
