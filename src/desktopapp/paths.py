import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


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
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
    with temporary.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt==5:raise
            time.sleep(.05*2**attempt)


def load_settings():
    path = data_root() / 'desktop.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
