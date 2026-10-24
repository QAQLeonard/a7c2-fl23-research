"""Volume changes stay offline and use the original selected PCM each time."""
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_codec
import sound_cli as cli


@pytest.fixture
def converted(tmp_path):
    source=tmp_path/'click.wav'
    native_codec.write_wav(source,[round(9000*math.sin(i*.2)) for i in range(4800)],24000)
    work=tmp_path/'sound'
    cli.import_audio(work,None,source,duration=.15)
    return work


def audio(work):
    folder=Path(cli.selected_conversion(work,None))
    return folder,json.loads((folder/'conversion.private.json').read_text()),native_codec.read_wav(folder/'preview.private.wav')[0]


def test_up_down_reset_use_original_pcm_and_preserve_camera_task(converted):
    work=converted
    cli.save(work,dict(schema=cli.SCHEMA,pending={'command':'install','outcome':'needs_review'},history=[]))
    state=(work/'sound.private.json').read_bytes()
    original,_,base=audio(work)
    first=cli.volume_audio(work,decibels=3)
    louder,report,preview=audio(work)
    assert report['volume_gain_db']==3
    assert max(map(abs,preview))>max(map(abs,base))*1.35
    assert (louder/'selected.private.wav').read_bytes()==(original/'selected.private.wav').read_bytes()
    assert first['camera_io'] is False
    cli.volume_audio(work,decibels=-3)
    again,report,_=audio(work)
    assert report['volume_gain_db']==0
    assert (again/'custom-native.private.bin').read_bytes()==(original/'custom-native.private.bin').read_bytes()
    cli.volume_audio(work,decibels=-6)
    assert max(map(abs,audio(work)[2]))<max(map(abs,base))*.55
    cli.volume_audio(work,reset=True)
    assert (audio(work)[0]/'custom-native.private.bin').read_bytes()==(original/'custom-native.private.bin').read_bytes()
    assert (work/'sound.private.json').read_bytes()==state


def test_loudness_cap_prevents_clipping_and_matches_saved_payload(converted):
    cli.volume_audio(converted,decibels=30)
    folder,report,preview=audio(converted)
    assert report['volume_limited'] is True
    assert report['peak_fraction']<=.951
    assert max(map(abs,preview))<=32512
    assert native_codec.decode((folder/'custom-native.private.bin').read_bytes())[:len(preview)]==preview
    cli.volume_audio(converted,decibels=-3)
    assert audio(converted)[1]['peak_fraction']<.68


def test_failed_gain_keeps_previous_selection_and_removes_partial_folder(converted):
    pointer=(converted/'conversion.private.json').read_bytes()
    folders=set((converted/'jobs').iterdir())
    with patch.object(native_codec,'candidate',side_effect=ValueError('encoding failed')):
        with pytest.raises(ValueError,match='encoding failed'):cli.volume_audio(converted,decibels=3)
    assert (converted/'conversion.private.json').read_bytes()==pointer
    assert set((converted/'jobs').iterdir())==folders


def test_cli_and_desktop_volume_need_no_backup_or_camera(converted):
    from desktopapp import worker,jobs
    from desktopapp.platforms import macos_authorization as macadmin
    with patch.object(cli,'workspace',side_effect=AssertionError('No camera workspace')):
        result=worker.run('sound_volume',{'workspace':str(converted),'decibels':3},converted)
        assert result['volume_gain_db']==3 and result['camera_io'] is False
        result=worker.run('sound_volume',{'workspace':str(converted),'reset':True},converted)
        assert result['volume_gain_db']==0
    assert 'sound_volume' not in jobs.CAMERA_ACTIONS | jobs.POWER_ACTIONS
    with patch.object(sys,'platform','darwin'),patch.object(__import__('os'),'geteuid',return_value=501,create=True):
        assert not macadmin.required('sound_volume')


def test_volume_before_conversion_gives_actionable_error(tmp_path):
    with pytest.raises(ValueError,match='先转换'):cli.volume_audio(tmp_path,decibels=3)
