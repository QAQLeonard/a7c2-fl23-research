import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def _replace_retry(temporary, path, attempts=6):
    # Windows AV/indexers can hold the destination briefly (#44): retry
    # access-denied instead of losing the final status/journal write.
    for attempt in range(attempts):
        try:
            return temporary.replace(path)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(.05 * 2 ** attempt)


def data_root():
    explicit = os.environ.get('A7C2_DESKTOP_DATA')
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'A7C2Tools'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/A7C2Tools'
    return Path.home() / '.local/share/a7c2-tools'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    _replace_retry(temporary, path)


def load_settings():
    path = data_root() / 'desktop.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
