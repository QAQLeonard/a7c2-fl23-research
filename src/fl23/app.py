"""A7C II 2.01 FL2／FL3 预览版：命令行入口。

命令与界面按钮一致：check（检查）、backup（备份）、install（安装）、
restore（还原）、verify（重启后核对）。工作目录默认在源码目录下的
workdir/ 里自动新建，备份默认放在源码目录下的 backup/ 里。
"""
import argparse
from datetime import datetime
from pathlib import Path

import core
from workflow import Job, restore_from_backup

COMMANDS = ['check', 'backup', 'prepare', 'install', 'restore', 'verify', 'check-package']


def event(message):
    print(message, flush=True)


def build_parser():
    p = argparse.ArgumentParser(description='A7C II 2.01 FL2／FL3 实验预览版')
    p.add_argument('command', choices=COMMANDS)
    p.add_argument('--workspace', type=Path,
                   help='工作目录；省略时在 workdir/ 下自动新建')
    p.add_argument('--backup-path', type=Path,
                   help='还原时指定备份目录；省略时用 backup/ 下通过校验的那份')
    p.add_argument('--battery-percent', type=int, default=-1)
    p.add_argument('--backup-copy', type=Path, help='prepare: independent empty backup directory')
    p.add_argument('--firmware-version', help='prepare: version from the camera version screen')
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command == 'prepare' and (not args.workspace or not args.backup_copy or not args.firmware_version):
        parser.error('prepare requires --workspace, --backup-copy and --firmware-version')
    if args.command == 'check-package':
        core.assets()
        event('套件资产完整；此检查不连接相机。')
        return
    job = Job(args.workspace)
    event('工作目录：' + str(job.root))
    try:
        if args.command == 'check':
            job.check()
        elif args.command == 'backup':
            job.backup_flow()
        elif args.command == 'prepare':
            job.prepare(args.backup_copy, args.firmware_version)
        elif args.command == 'install':
            job.install(args.battery_percent)
        elif args.command == 'restore':
            if args.backup_path:
                restore_from_backup(args.battery_percent, job.root, args.backup_path)
            else:
                job.restore(args.battery_percent)
        else:
            job.verify()
    except Exception as exc:
        job.state['last_error'] = str(exc)
        job.state['failed_during'] = job.state.get('phase')
        job.save('needs_review')
        event('已停止：' + str(exc))
        event('不要盲目重跑写入或重新开机；保留工作目录供确认。')
        import traceback
        diagnostic = job.root / 'evidence'
        diagnostic.mkdir(parents=True, exist_ok=True)
        (diagnostic / f'{datetime.now():%Y%m%d-%H%M%S-%f}-error.txt').write_text(
            traceback.format_exc(), encoding='utf-8')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
