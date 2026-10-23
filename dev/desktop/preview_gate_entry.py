"""Explicit test-build launcher; camera workers retain their ordinary entry."""
from pathlib import Path
import runpy
import sys

if not any(flag in sys.argv for flag in (
        '--worker', '--privileged-worker', '--raw-profile-worker', '--offline-self-test')):
    sys.argv.append('--preview-gate-test')
runpy.run_path(str(Path(sys._MEIPASS) / 'dev/desktop/frozen_entry.py'), run_name='__main__')
