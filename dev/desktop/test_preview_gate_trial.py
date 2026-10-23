"""Four-byte A/B trial uses the real direct transaction with a simulated camera."""
import copy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/looks/tests'))
from test_checkpoint import Camera, fake_compile, values
from test_direct import SimDirect
from test_uploadgate import synthetic, STUBS
from looktool import checkpointworker, direct, uploadgate
from desktopapp import jobs, reloadguide


@pytest.fixture
def trial(tmp_path):
    before = values()
    before['cpapp-b.bin'] = synthetic(uploadgate.FORCED)
    camera = Camera(before)
    identity = {'kind': 'legacy-six', 'mask': 63}
    with patch.object(Camera, '__call__', lambda self, expected=None: self), \
         patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile), \
         patch.object(direct.device_layout, 'structural', return_value=identity):
        yield before, camera, tmp_path


def test_trial_changes_only_gate_and_preserves_every_other_file_and_setting(trial):
    before, camera, folder = trial
    files, ram, saved = copy.deepcopy(camera.files), copy.deepcopy(camera.ram), copy.deepcopy(camera.saved)
    job = SimDirect(folder / 'native', factory=camera)
    state = job.run_direct('preview_native', version='2.01', power_confirmed=True)
    expected = uploadgate.restore(before['cpapp-b.bin'])
    assert state['phase'] == 'AWAITING_RELOAD'
    assert state['preview_source_entry'] == uploadgate.FORCED.hex()
    files['/cp/cpapp-b.bin'] = expected
    assert camera.files == files
    assert camera.ram == ram and camera.saved == saved and camera.saves == []
    assert sum(a != b for a, b in zip(before['cpapp-b.bin'], expected)) == 4
    assert [call for call in camera.native_calls if call[0] == 'program'] == [('program', 0), ('program', 1)]
    assert not any(kind == 'names' for kind, mode in camera.native_calls)
    camera.boot = 'test-boot-2'
    assert job.verify_direct()['phase'] == 'LOADED'


def test_trial_inverse_restores_the_exact_original_cp_without_touching_other_features(trial):
    before, camera, folder = trial
    SimDirect(folder / 'native', factory=camera).run_direct('preview_native', version='2.01', power_confirmed=True)
    camera.boot = 'test-boot-2'
    state = SimDirect(folder / 'legacy', factory=camera).run_direct('preview_legacy', version='2.01', power_confirmed=True)
    assert state['phase'] == 'AWAITING_RELOAD'
    assert state['preview_source_entry'] == uploadgate.NATIVE.hex()
    assert camera.files['/cp/cpapp-b.bin'] == before['cpapp-b.bin']
    assert camera.files['/usr/lib/appFw.so'] == before['appFw.so']
    assert camera.saves == []


def test_reapplying_native_trial_does_not_write_programs_again(trial):
    _, camera, folder = trial
    camera.files['/cp/cpapp-b.bin'] = uploadgate.restore(camera.files['/cp/cpapp-b.bin'])
    state = SimDirect(folder / 'native', factory=camera).run_direct('preview_native', version='2.01', power_confirmed=True)
    assert state['phase'] == 'LOADED'
    assert not any(kind == 'program' and mode == 1 for kind, mode in camera.native_calls)


def test_trial_does_not_retry_an_unknown_write_result(trial):
    _, camera, folder = trial
    job = SimDirect(folder / 'unknown', factory=camera)
    job.lose_after_program = True
    with pytest.raises(TimeoutError):
        job.run_direct('preview_native', version='2.01', power_confirmed=True)
    assert job.state['phase'] == 'NEEDS_REVIEW'
    assert camera.native_calls.count(('program', 1)) == 1
    assert camera.saves == []


def test_trial_refuses_uninstalled_custom_runtime(trial):
    before, _, _ = trial
    with patch.object(direct.device_layout, 'structural', return_value={'first_install': True, 'mask': 0}):
        with pytest.raises(ValueError, match='已安装'):
            direct.plan(before, None, 'preview_native')


def test_inverse_requires_both_complete_historical_trampolines():
    forced = synthetic(uploadgate.FORCED)
    native = uploadgate.restore(forced)
    assert uploadgate.restore_legacy_for_test(native) == forced
    assert uploadgate.restore_legacy_for_test(forced) == forced
    for at, raw in STUBS:
        for index in range(len(raw)):
            changed = bytearray(native)
            changed[at + index] ^= 1
            with pytest.raises(ValueError, match='trampoline'):
                uploadgate.restore_legacy_for_test(changed)


def test_trial_requires_power_and_has_explicit_restart_and_visual_checks():
    for action in ('direct_preview_native', 'direct_preview_legacy'):
        assert action in jobs.CAMERA_ACTIONS and action in jobs.POWER_ACTIONS
        assert reloadguide.required(action, {'phase': 'AWAITING_RELOAD'})
    for mode in ('preview_native', 'preview_legacy'):
        text = reloadguide.text(mode=mode)
        for phrase in ('六个自定义槽', '至少等待 1 分钟', '只读核对', '撤回候选', 'CP RAM'):
            assert phrase in text


@pytest.mark.skipif(not os.environ.get('A7C2_RESEARCH_FIXTURES'), reason='Optional private firmware; no USB')
def test_real_private_layout_plans_exactly_the_same_four_byte_inverse():
    index = Path(os.environ['A7C2_RESEARCH_FIXTURES'])
    paths = json.loads(index.read_text(encoding='utf-8'))
    current = {name: (index.parent / paths[key]).read_bytes()
               for name, key in (('appFw.so', 'six_ap'), ('cpapp-b.bin', 'v4_cp'))}
    target, wanted, names = direct.plan(current, None, 'preview_native')
    assert wanted == [{}, {}] and names is None
    assert target['appFw.so'] is current['appFw.so']
    assert target['cpapp-b.bin'] == uploadgate.restore(current['cpapp-b.bin'])
    assert list(checkpointworker.differences(current['cpapp-b.bin'], target['cpapp-b.bin'])) == [
        (uploadgate.OFFSET, uploadgate.FORCED, uploadgate.NATIVE)]
    restored, wanted, names = direct.plan(target, None, 'preview_legacy')
    assert restored == current and wanted == [{}, {}] and names is None
