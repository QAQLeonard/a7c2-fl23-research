"""PR #9 argument-forwarding regression; actual shells, synthetic CMD/Python."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.name == 'nt', 'Windows legacy entrypoint')
class LegacyPowerShellTests(unittest.TestCase):
    def run_wrapper(self, shell):
        with tempfile.TemporaryDirectory(prefix='a7c2 legacy args ') as temporary:
            caller = Path(temporary)
            folder = caller / '工具 with spaces'
            folder.mkdir()
            script = (ROOT / 'src/fl23/Start.ps1').read_text(encoding='utf-8')
            # Bypass only old interpreter discovery when demonstrating the
            # pre-fix bug. Every version runs fake entrypoints, never USB/pip.
            interpreter = sys.executable.replace("'", "''")
            script = script.replace("$pythonPath = Join-Path $PSScriptRoot '.venv\\Scripts\\python.exe'",
                                    "$pythonPath = '" + interpreter + "'")
            (folder / 'Start.ps1').write_text(script, encoding='utf-8-sig')
            capture = ("import json,os,sys\n"
                       "print(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd()),ensure_ascii=True))\n"
                       "raise SystemExit(7)\n")
            (folder / 'capture.py').write_text(capture, encoding='utf-8')
            (folder / 'Start.cmd').write_text(
                '@echo off\r\ncall "%A7C2_PYTHON%" "%~dp0capture.py" %*\r\nexit /b %errorlevel%\r\n',
                encoding='ascii')
            (folder / 'app.py').write_text(
                'import sys\nif sys.argv[1:]==["check-package"]: raise SystemExit(0)\n' + capture,
                encoding='utf-8')
            (folder / 'gui.py').write_text('raise SystemExit(99)\n', encoding='ascii')
            arguments = ['verify', '--workspace', 'D:\\資料 test\\工作 $money', '--battery-percent', '82']
            done = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                   '-File', str(folder / 'Start.ps1'), *arguments], cwd=caller,
                                  env=dict(os.environ, A7C2_PYTHON=sys.executable, PYTHONUTF8='1'),
                                  capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(done.returncode, 7, done.stdout + done.stderr)
            result = json.loads(done.stdout)
            self.assertEqual(result['argv'], arguments)
            self.assertEqual(Path(result['cwd']), caller)

    def test_windows_powershell51_forwards_arguments_and_exit_status(self):
        self.run_wrapper(str(Path(os.environ['SystemRoot']) /
                             'System32/WindowsPowerShell/v1.0/powershell.exe'))

    def test_powershell7_forwards_arguments_and_exit_status(self):
        shell = shutil.which('pwsh')
        if not shell:
            self.skipTest('PowerShell 7 is optional')
        self.run_wrapper(shell)
