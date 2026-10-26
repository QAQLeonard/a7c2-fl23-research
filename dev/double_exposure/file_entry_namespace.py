"""Linux-only test launcher: private mounts, actual production ARM64 constructor."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('qemu', 'sysroot', 'runner', 'helper'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('mode', choices=('once', 'retained', 'reload'))
    args = parser.parse_args()
    if sys.platform != 'linux': parser.error('Requires Linux user and mount namespaces')
    paths = {name: getattr(args, name).resolve(strict=True)
             for name in ('fixture', 'qemu', 'sysroot', 'runner', 'helper')}
    for path in paths.values():
        if path == Path('/tmp') or Path('/tmp') in path.parents:
            parser.error('Fixture and runner paths must be outside the masked /tmp')
    if not paths['fixture'].is_dir(): parser.error('Fixture must be a directory')
    # The host /tmp and any host jiritsu directory remain hidden and untouched.
    # Positional shell arguments preserve paths verbatim; no command interpolation.
    script = ('set -eu\nmount --make-rprivate /\nmount -t tmpfs tmpfs /tmp\n'
              'mkdir /tmp/jiritsu\nmount --bind "$1" /tmp/jiritsu\nshift\nexec "$@"')
    command = ['unshare', '--user', '--map-root-user', '--mount', '--',
               'sh', '-c', script, 'a7c2-constructor-test', str(paths['fixture']),
               str(paths['qemu']), '-L', str(paths['sysroot']), str(paths['runner']),
               str(paths['helper']), args.mode]
    return subprocess.run(command, check=False, timeout=30).returncode


if __name__ == '__main__':
    raise SystemExit(main())
