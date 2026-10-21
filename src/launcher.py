"""Shared Windows entrypoint. Environment setup and validation precede device work."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv/Scripts/python.exe'

def execute(command,cwd=ROOT,module_dir=None):
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    if module_dir is not None:
        env['PYTHONPATH']=str(module_dir)+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return subprocess.run([str(x) for x in command],cwd=str(cwd),env=env,check=False).returncode

def check_host():
    if sys.version_info<(3,10):raise RuntimeError('Python 3.10 or newer is required. Install it, then reopen the CMD entry.')
    if struct.calcsize('P')!=8:raise RuntimeError('64-bit Python is required.')
    return {'python':sys.version.split()[0],'python_bits':struct.calcsize('P')*8,'root':str(ROOT),
            'PowerShell_required':False,'camera_io':False}

def prepare(workflow,research=False):
    if os.name!='nt':raise RuntimeError('The CMD entries support Windows. Run the offline looktool directly on other systems.')
    if not PYTHON.is_file():
        if (ROOT/'.venv').exists():raise RuntimeError('Existing .venv is incomplete. Preserve it for inspection; setup will not overwrite it.')
        print('Creating the local Python environment...',flush=True)
        if execute([sys.executable,'-m','venv',ROOT/'.venv']):raise RuntimeError('Could not create .venv; no camera operation started.')
    if execute([PYTHON,'-c',"import sys,struct; assert sys.version_info >= (3,10) and struct.calcsize('P') == 8"]):
        raise RuntimeError('Existing local Python is unsupported. No environment files or camera data were replaced.')
    if workflow=='fl23':
        requirement=ROOT/'src/fl23/requirements.txt'
        imports='import usb,libusb_package,Cryptodome,yaml,numpy,scipy,elftools,ziglang'
        requirement=ROOT/'src/looks/requirements-device.txt'
    else:
        requirement=ROOT/'src/looks'/('requirements-research.txt' if research else 'requirements.txt')
        imports='import numpy,scipy'+(',keystone,unicorn,capstone' if research else '')
    # The probe imports packages only. It does not import the camera transport
    # or enumerate USB. A failed task is never retried by this launcher.
    if execute([PYTHON,'-c',imports]):
        print('Installing dependencies for '+workflow+' (Internet required)...',flush=True)
        if execute([PYTHON,'-m','pip','install','--requirement',requirement]):raise RuntimeError('Dependency installation failed; no camera operation started.')
        if execute([PYTHON,'-c',imports]):raise RuntimeError('Dependencies remain unavailable; no camera operation started.')
    if workflow=='fl23':
        if execute([PYTHON,'-c','import tkinter']):raise RuntimeError('This Python installation needs Tkinter support.')
        if execute([PYTHON,ROOT/'src/fl23/app.py','check-package']):raise RuntimeError('FL2/FL3 package validation failed; no camera operation started.')
    return PYTHON

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    try:
        info=check_host()
        if not argv:
            raise RuntimeError('Open FL23.cmd or Custom-LUT.cmd to choose the workflow.')
        if argv==['--check']:
            print(json.dumps(info,indent=2));return 0
        p=argparse.ArgumentParser(description=__doc__,add_help=False)
        p.add_argument('workflow',choices=['fl23','looks'])
        p.add_argument('--setup-only',action='store_true',help='Prepare dependencies only; no USB')
        p.add_argument('--research',action='store_true',help='Include assembler/emulator dependencies for offline program transitions')
        args,remaining=p.parse_known_args(argv)
        if remaining==['--check']:
            info['workflow']=args.workflow;print(json.dumps(info,indent=2));return 0
        if args.workflow=='fl23' and remaining and remaining[0] not in ['check','backup','prepare','install','restore','verify','check-package','--help','-h']:
            raise RuntimeError('Unknown FL2/FL3 command. Use FL23.cmd --help.')
        if args.workflow=='fl23' and remaining and remaining[0] in ['--help','-h','check-package']:
            return execute([sys.executable,ROOT/'src/fl23/app.py',*remaining],Path.cwd())
        python=prepare(args.workflow,args.research)
        if args.setup_only:
            print('Environment ready. No camera connection or firmware/settings write performed.');return 0
        if args.workflow=='fl23':
            command=[python,'-u',ROOT/'src/fl23'/('app.py' if remaining else 'gui.py')]+remaining
            return execute(command,Path.cwd())
        if not remaining:
            if execute([python,'-c','import tkinter']):raise RuntimeError('The custom-look GUI needs Tkinter. CLI commands remain available.')
            return execute([python,'-u',ROOT/'src/looks/gui.py'],Path.cwd(),ROOT/'src/looks')
        return execute([python,'-u','-m','looktool']+(remaining or ['--help']),Path.cwd(),ROOT/'src/looks')
    except (RuntimeError,OSError,EOFError) as exc:
        print('Stopped: '+str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
