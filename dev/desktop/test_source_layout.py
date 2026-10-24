"""Stable public imports and separated runtime/build modules, offline only."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]

def test_sound_runtime_and_native_sources_are_in_src():
    sys.path.insert(0,str(ROOT/'src/shutter_sound'))
    import candidate,media,sound_cli,files_worker
    for module in (candidate,media,sound_cli,files_worker):
        assert Path(module.__file__).resolve().parent==ROOT/'src/shutter_sound'
    assert candidate.ROOT==ROOT
    for name in ('sound_probe.c','sound_files.c','buffer_probe.c'):
        assert (ROOT/'src/shutter_sound/native'/name).is_file()
    assert not (ROOT/'dev/shutter_sound/sound_cli.py').exists()
