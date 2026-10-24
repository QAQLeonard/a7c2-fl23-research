"""Direct conversion-to-save, with only proven pre-native failures retired."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sound_cli as cli
import boot_trial
import trial


@pytest.fixture
def direct(tmp_path,monkeypatch):
    root,state=cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    native=root/'native';native.mkdir()
    trial.save(native,dict(phase='written',identity=dict(model='ILCE-7CM2',serial_sha256='synthetic'),
                          complete_readback_and_settings_verified=True,electronic_only_gate=True))
    state['native_job']=str(native)
    converted=root/'converted';converted.mkdir()
    (converted/'custom-native.private.bin').write_bytes(bytes(64))
    state['conversion']=str(converted)
    cli.save(root,state)
    def adopt(job,*args,**kwargs):
        value=dict(phase='written',identity=dict(model='ILCE-7CM2',serial_sha256='synthetic'),
                   complete_readback_and_settings_verified=True,adopted_existing_enabled=True)
        Path(job).mkdir(parents=True);trial.save(job,value);return value
    monkeypatch.setattr(trial,'preflight',adopt)
    return root,state


def test_direct_save_needs_no_audition_or_confirmations(direct):
    root,state=direct
    with patch.object(boot_trial,'install',return_value={'phase':'installed_cold_test_pending'}) as install:
        assert cli.install(root,state,100)['phase']=='installed_cold_test_pending'
    assert install.call_args.args[3] is None
    assert install.call_args.args[4]==bytes(64)
    assert not state.get('audio_job')


def test_selected_conversion_does_not_read_stale_audition_payload(direct):
    root,state=direct
    old=root/'old-audition';old.mkdir()
    payload=old/'payload.private.bin';payload.write_bytes(b'old bytes')
    state['audio_job']=str(old)
    read_bytes=Path.read_bytes
    def read(path):
        if path==payload:raise PermissionError('Old audition is unavailable')
        return read_bytes(path)
    with patch.object(Path,'read_bytes',read), \
         patch.object(boot_trial,'install',return_value={'phase':'installed_cold_test_pending'}) as install:
        assert cli.install(root,state,100)['phase']=='installed_cold_test_pending'
    assert install.call_args.args[3] is None
    assert install.call_args.args[4]==bytes(64)


def test_missing_dependency_does_not_create_install_intent(direct):
    root,state=direct
    before=(root/'sound.private.json').read_bytes()
    with patch.object(boot_trial,'require_dependencies',side_effect=ModuleNotFoundError('ziglang')), \
         patch.object(boot_trial,'install') as install:
        with pytest.raises(ModuleNotFoundError):cli.install(root,state,100)
        install.assert_not_called()
    assert state['pending'] is None and not state.get('boot_job')
    assert not any(e.get('command')=='install' for e in state['history'])
    assert not list(root.glob('jobs/persistent-*'))


@pytest.mark.parametrize('native_intent',[False,True])
def test_new_current_request_archives_old_intent_without_replaying_it(direct,native_intent):
    root,state=direct
    failed=root/'jobs'/'failed';failed.mkdir(parents=True)
    value=dict(schema='a7c2-native-boot-sound-job/1',phase='needs_review',camera_firmware_written=False,
               journal=[dict(event='native_stage_intent',mode=1)] if native_intent else [])
    trial.save(failed,value)
    state.update(boot_job=str(failed),pending=dict(command='install',job=str(failed)))
    cli.save(root,state);before=(failed/'job.private.json').read_bytes()
    with patch.object(boot_trial,'install',return_value={'phase':'installed_cold_test_pending'}) as install:
        assert cli.install(root,state,100)['phase']=='installed_cold_test_pending'
        assert Path(install.call_args.args[0])!=failed
        assert state['pending'] is None
        install.assert_called_once()
    assert (failed/'job.private.json').read_bytes()==before
