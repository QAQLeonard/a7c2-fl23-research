"""Portable LUT/DCP CLI. Device writes require explicit import --write/install."""
import argparse
import importlib.util
import json
from pathlib import Path
import struct
import sys
import shutil

ROOT=Path(__file__).resolve().parent
DEVICE_COMMANDS={'configure':'Configure local calibration/backups once','import':'Back up, convert and preflight; --write performs installation',
    'install':'Install a prepared job','verify':'Verify after reload; record actual photo acceptance',
    'restore-slot':'Restore one custom slot, preserving other slots and FL23','recover':'Inspect an existing interrupted job without replay',
    'resume':'Explicitly continue a recovered known phase; never repeat program writes'}
COMMANDS={'diagnose-job':'Explain a recorded failure without USB or changing the job','inspect':'Inspect a DCP/CUBE reference','plan':'View an existing project slot plan',
          'check-bindings':'Check host ST binding declarations','calibrate':'Generate calibration from measured inputs',
          'fit':'Fit native table candidates','prepare-transition':'Prepare exact-source forward/reverse manifests',
          'prepare-six-program':'Reproduce programs from the pinned historical three-look source',
          'prepare-preview-retry':'Prepare native LUT-upload gating from the exact historical switch-v2 source'}

def missing_packages():
    return [name for name in ['numpy','scipy'] if importlib.util.find_spec(name) is None]

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    parser=argparse.ArgumentParser(description=__doc__,epilog='Run from the extracted root: python lut.py inspect path/to/profile.dcp')
    parser.add_argument('--version',action='version',version='2.2-preview.1')
    parser.add_argument('--device',action='store_true',help='doctor: also check USB/native-build dependencies; never connect')
    parser.add_argument('command',nargs='?',choices=['doctor',*COMMANDS,*DEVICE_COMMANDS],help='doctor/offline conversion or explicit device job')
    if not argv or argv[0] in ['-h','--help']:
        parser.print_help()
        for name,description in {**COMMANDS,**DEVICE_COMMANDS}.items():print('  '+name+': '+description)
        return 0
    if argv==['--version']:print('2.2-preview.1');return 0
    try:
        if argv[0] not in ['doctor',*COMMANDS,*DEVICE_COMMANDS]:raise ValueError('Unknown command; run python lut.py --help')
        if argv[0]=='diagnose-job':
            sys.path.insert(0,str(ROOT/'src/looks'))
            from looktool.jobdiagnostics import main as explain_job
            return explain_job(argv)
        valid=sys.version_info>=(3,10) and struct.calcsize('P')==8
        missing=missing_packages()
        if argv[0]=='doctor':
            args=parser.parse_args(argv)
            device_missing=[n for n in ['usb','libusb_package','Cryptodome','yaml','elftools'] if importlib.util.find_spec(n) is None]
            if not shutil.which('zig') and importlib.util.find_spec('ziglang') is None:device_missing.append('ziglang (or zig on PATH)')
            print(json.dumps({'python':sys.executable,'version':sys.version.split()[0],
                'bits':struct.calcsize('P')*8,'platform':sys.platform,'host_supported':valid,
                'missing_packages':missing,'missing_device_packages':device_missing,'camera_io':False,'device_installation_command_included':True},indent=2))
            return 0 if valid and not missing and (not args.device or not device_missing) else 2
        if not valid:raise ValueError('64-bit Python 3.10+ is required')
        if missing:raise ValueError('Missing '+', '.join(missing)+'. Use this interpreter: '+sys.executable+' -m pip install -r '+str(ROOT/'src/looks/requirements.txt'))
        sys.path.insert(0,str(ROOT/'src/looks'))
        if argv[0] in DEVICE_COMMANDS:
            from looktool.devicecli import main as run_device
            return run_device(argv)
        from looktool.__main__ import main as run
        return run(argv)
    except (ValueError,OSError,ImportError,RuntimeError) as exc:
        print('Stopped: '+str(exc),file=sys.stderr);return 2
    except KeyboardInterrupt:
        print('Interrupted. Preserve the job folder and run recover; never repeat an unknown write.',file=sys.stderr);return 130

if __name__=='__main__':raise SystemExit(main())
