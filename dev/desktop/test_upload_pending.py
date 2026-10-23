"""Pending-only LUT trial: bounded bytes, inverse and optional native replay."""
import base64
import json
import os
from pathlib import Path
import random
import struct
import sys
import zlib
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/looks/tests'))
from test_uploadgate import synthetic as gate_fixture
from looktool import direct, uploadgate, uploadpending


def synthetic():
    cp = bytearray(gate_fixture(uploadgate.FORCED))
    cp.extend(bytes(0xb28000 - len(cp)))
    struct.pack_into('<3I', cp, 0x20124, 0, 0xb07fb0, 0x128000)
    for _, at, before, _ in uploadpending.WINDOWS:
        raw = bytes.fromhex(before)
        cp[at:at + len(raw)] = raw
    for at, text in uploadpending.GUARDS:
        raw = bytes.fromhex(text)
        cp[at:at + len(raw)] = raw
    return bytes(cp)


def test_only_declared_code_windows_change_and_inverse_is_exact():
    source = synthetic()
    target = uploadpending.install(source)
    assert target[uploadgate.OFFSET:uploadgate.OFFSET + 4] == uploadgate.NATIVE
    expected = bytearray(source)
    expected[uploadgate.OFFSET:uploadgate.OFFSET + 4] = uploadgate.NATIVE
    assert uploadpending.normalize(target) == bytes(expected)
    assert uploadgate.restore_legacy_for_test(uploadpending.normalize(target)) == source
    assert uploadpending.install(target) == target
    for _, at, _, after in uploadpending.WINDOWS:
        raw = bytes.fromhex(after)
        expected[at:at + len(raw)] = raw
    assert target == expected


@pytest.mark.parametrize('index', range(len(uploadpending.WINDOWS)))
def test_unknown_or_partial_code_is_rejected(index):
    source = synthetic()
    _, at, _, after = uploadpending.WINDOWS[index]
    target = bytearray(uploadpending.install(source))
    target[at + len(bytes.fromhex(after)) // 2] ^= 1
    with pytest.raises(ValueError):
        uploadpending.install(target)
    partial = bytearray(source)
    partial[at:at + len(bytes.fromhex(after))] = bytes.fromhex(after)
    with pytest.raises(ValueError):
        uploadpending.normalize(partial)


@pytest.mark.parametrize('index', range(len(uploadpending.GUARDS)))
def test_native_frame_and_uploader_guards_are_not_relaxed(index):
    source = bytearray(synthetic())
    at, raw = uploadpending.GUARDS[index]
    source[at + len(bytes.fromhex(raw)) // 2] ^= 1
    with pytest.raises(ValueError, match='context'):
        uploadpending.install(source)


def test_direct_apply_native_and_legacy_reverts_preserve_other_data():
    before = {'appFw.so': b'SYNTHETIC AP', 'cpapp-b.bin': synthetic(), 'other': b'UNCHANGED'}
    with patch.object(direct.device_layout, 'structural', return_value={'mask': 63}):
        target, wanted, names = direct.plan(before, None, 'preview_pending')
        assert wanted == [{}, {}] and names is None and target['other'] == before['other']
        assert target['appFw.so'] is before['appFw.so']
        native, _, _ = direct.plan(target, None, 'preview_native')
        legacy, _, _ = direct.plan(target, None, 'preview_legacy')
        assert native['cpapp-b.bin'] == uploadgate.restore(before['cpapp-b.bin'])
        assert legacy == before


def test_factory_reference_covers_every_trial_window_with_sony_originals():
    ref = json.loads((ROOT / 'src/looks/assets/factory-regions-2.01.json').read_text(encoding='utf-8'))
    rows = ref['programs']['cpapp-b.bin']['regions']
    for _, at, before, after in uploadpending.WINDOWS:
        size = len(bytes.fromhex(after))
        actual, covered = bytearray(size), set()
        for row in rows:
            start, end = max(at, row['offset']), min(at + size, row['offset'] + row['bytes'])
            if start < end:
                raw = zlib.decompress(base64.b64decode(row['zlib_base64']))
                actual[start-at:end-at] = raw[start-row['offset']:end-row['offset']]
                covered.update(range(start-at, end-at))
        assert len(covered) == size
        if any(pos == at for pos, _ in uploadpending.factory_windows()):
            assert bytes(actual) == bytes.fromhex(before)


def test_direct_trial_writes_one_batch_and_can_revert_from_a_fresh_request(tmp_path):
    from test_checkpoint import Camera, fake_compile, values
    from test_direct import SimDirect
    from looktool import checkpointworker
    before = values()
    before['cpapp-b.bin'] = synthetic()
    camera = Camera(before)
    originals = dict(camera.files)
    with patch.object(Camera, '__call__', lambda self, expected=None: self), \
         patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile), \
         patch.object(direct.device_layout, 'structural', return_value={'mask': 63}):
        job = SimDirect(tmp_path / 'pending', factory=camera)
        assert job.run_direct('preview_pending', version='2.01', power_confirmed=True)['phase'] == 'AWAITING_RELOAD'
        assert uploadpending.active(camera.files['/cp/cpapp-b.bin'])
        assert camera.native_calls.count(('program', 1)) == 1
        assert not camera.saves
        camera.boot = 'test-boot-2'
        assert job.verify_direct()['phase'] == 'LOADED'
        reverse = SimDirect(tmp_path / 'revert', factory=camera)
        assert reverse.run_direct('preview_legacy', version='2.01', power_confirmed=True)['phase'] == 'AWAITING_RELOAD'
    assert camera.files == originals and not camera.saves


@pytest.fixture
def native_images():
    if not os.environ.get('A7C2_RESEARCH_FIXTURES'):
        pytest.skip('Optional private firmware; never reads USB')
    from test_uploadgate_native import Replay
    import test_preview_native as native
    index = Path(os.environ['A7C2_RESEARCH_FIXTURES'])
    paths = json.loads(index.read_text(encoding='utf-8'))
    old = (index.parent / paths['v4_cp']).read_bytes()
    return native, Replay, old, uploadgate.restore(old), uploadpending.install(old)


def test_native_missed_consumption_recovers_and_stable_cycles_stop_repeating(native_images):
    _, Replay, _, _, candidate = native_images
    for gate in (0, 0x40):
        for source, target in ((249, 250), (250, 251), (251, 252), (252, 253), (253, 254), (254, 249)):
            for consumer in range(4):
                for missing in ('normal', 'controller_twice', 'no_device', 'no_copy_buffer'):
                    replay = Replay(candidate, gate)
                    replay.cycle(source, consumer)
                    replay.prepare(target, consumer)
                    if missing == 'normal': replay.consume(consumer)
                    elif missing == 'controller_twice':
                        replay.prepare(target, consumer)
                        replay.consume(consumer)
                    elif missing == 'no_device': replay.consume(consumer, destination=False)
                    else: replay.consume(consumer, copy=True)
                    replay.cycle(target, consumer)
                    assert replay.matches(target, consumer), (gate, source, consumer, missing)
                    count = replay.counts['uploads']
                    for _ in range(3):
                        replay.cycle(target, consumer)
                        assert replay.matches(target, consumer)
                    assert replay.counts['uploads'] == count + (3 if gate else 0)


def test_native_each_hardware_destination_acknowledges_independently(native_images):
    _, Replay, _, _, candidate = native_images
    replay = Replay(candidate)
    replay.prepare(249)
    for consumer in range(4):
        replay.consume(consumer)
        assert replay.matches(249, consumer)
    assert replay.counts['uploads'] == 4
    for consumer in (3, 2, 1, 0, 0): replay.consume(consumer)
    assert replay.counts['uploads'] == 4


def test_native_repeat_bit_keeps_repeated_consumption_without_a_new_controller(native_images):
    _, Replay, _, before, candidate = native_images
    for image in (before, candidate):
        replay = Replay(image, 0x40)
        replay.prepare(249)
        replay.consume()
        replay.consume()
        assert replay.counts['uploads'] == 2


def test_native_config_copy_loop_matches_all_original_register_writes(native_images):
    native, Replay, _, before, candidate = native_images
    for seed in range(8):
        config = random.Random(seed).randbytes(19)
        results = []
        for image in (before, candidate):
            replay = Replay(image)
            replay.cpu.mem_write(native.DEV + 0x184, struct.pack('<I', native.MMIOS[0]))
            replay.cpu.mem_write(native.STATE + 0xc, config)
            replay.cpu.mem_write(native.STATE + 0x24, b'\0')
            replay.consume()
            results.append(bytes(replay.cpu.mem_read(native.MMIOS[0], 0x10000)))
        assert results[0] == results[1]


def test_native_copy_route_does_not_acknowledge_hardware(native_images):
    native, Replay, _, _, candidate = native_images
    replay = Replay(candidate)
    replay.prepare(249)
    pointer = struct.unpack('<I', replay.cpu.mem_read(native.STATE + 0x20, 4))[0]
    expected = bytes(replay.cpu.mem_read(pointer, 1620))
    replay.consume(copy=True, buffer=0x30016000)
    assert bytes(replay.cpu.mem_read(0x30016000, 1620)) == expected
    assert replay.counts['uploads'] == 0
    replay.prepare(249)
    replay.consume()
    assert replay.matches(249) and replay.counts['uploads'] == 1


def test_native_snapshot_direct_and_native_looks_retain_full_state_and_counts(native_images):
    _, Replay, _, before, candidate = native_images
    slots = (0, 249, 250, 251, 252, 253, 254, 0, 19, 20)
    scenarios = [({'flag': 1}, slots), ({'direct': 1}, slots), ({'flag': 1, 'direct': 1}, slots),
                 ({}, (0, 1, 2, 3, 5, 13, 15, 16, 17, 18, 19, 20))]
    for options, markers in scenarios:
        for gate in (0, 0x40):
            a, b = Replay(before, gate, **options), Replay(candidate, gate, **options)
            for marker in markers:
                a.cycle(marker); b.cycle(marker)
                assert a.state() == b.state(), (options, gate, marker)


def test_native_random_slot_and_destination_changes_with_dropped_cycles(native_images):
    _, Replay, _, _, candidate = native_images
    for seed in range(3):
        rng = random.Random(seed)
        replay = Replay(candidate)
        for _ in range(50):
            marker, consumer = rng.randrange(249, 255), rng.randrange(4)
            replay.prepare(marker, consumer)
            if rng.randrange(2): replay.prepare(marker, consumer)
            replay.consume(consumer)
            assert replay.matches(marker, consumer)


def test_native_bank_changes_reset_ack_even_without_a_slot_change(native_images):
    native, Replay, _, _, candidate = native_images
    replay = Replay(candidate)
    for generation, level in enumerate((8, 4, 7, 8)):
        replay.cpu.mem_write(native.ROOTPARAM + 0x2f, bytes([level]))
        # Native callers advance this parameter generation; an isolated
        # intensity byte is not sufficient to request a custom-bank rebuild.
        replay.cpu.mem_write(native.ROOTPARAM + 0x36, bytes([generation]))
        replay.prepare(249)
        pointer = struct.unpack('<I', replay.cpu.mem_read(native.STATE + 0x20, 4))[0]
        expected = bytes(replay.cpu.mem_read(pointer, 1620))
        count = replay.counts['uploads']
        replay.consume()
        actual = b''.join(bytes(replay.cpu.mem_read(native.MMIOS[0] + at, size)) for at, size in native.CHUNKS)
        assert actual == expected and replay.counts['uploads'] == count + 1
        replay.cycle(249)
        assert replay.counts['uploads'] == count + 1


def test_native_photo_parameters_survive_apply_and_exact_inverse(native_images):
    _, _, before, _, _ = native_images
    from looktool import photoio, photobasis
    bank = photoio.neutral_bank(before)
    photo = photoio.update(before, {1: photobasis.pack(bank)[1]}, bank, allocation_proved=True)
    original = photoio.inspect(photo)
    candidate = uploadpending.install(photo)
    assert photoio.inspect(candidate) == original
    later = photoio.update(candidate, {2: photobasis.pack(bank)[1]}, bank)
    assert uploadpending.active(later) and photoio.inspect(later)['mask'] == 3
    underlay = uploadpending.normalize(candidate)
    assert photoio.inspect(underlay) == original
    assert uploadgate.restore_legacy_for_test(underlay) == photo


@pytest.mark.parametrize('when', ('before_upload', 'after_unlock'))
def test_native_new_producer_update_is_not_lost_across_upload(native_images, when):
    native, Replay, _, _, candidate = native_images
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR
    replay = Replay(candidate)
    replay.prepare(249)
    injected = []
    # Resume at the first Thumb instruction after the unlock callback. Nested
    # Unicorn execution inside the ARM-to-Thumb return hook corrupts the
    # emulator's instruction mode rather than modeling a second CP thread.
    trigger = 0x78aa20 if when == 'before_upload' else 0x78aacc
    def hook(cpu, at, size, _):
        if at != trigger or injected: return
        injected.append(at)
        saved = cpu.context_save()
        try:
            cpu.mem_write(native.ROOTPARAM + 0x2e, b'\xfa')
            for reg, value in ((UC_ARM_REG_R0, native.CONTEXT), (UC_ARM_REG_R1, native.OUTPUT),
                               (UC_ARM_REG_SP, 0x3001b000), (UC_ARM_REG_LR, 0x31000001)):
                cpu.reg_write(reg, value)
            cpu.emu_start(0x23d381, 0x31000000, count=900000)
        finally:
            cpu.context_restore(saved)
    replay.cpu.hook_add(UC_HOOK_CODE, hook)
    replay.consume()
    assert injected
    if when == 'before_upload':
        assert replay.matches(250)
        count = replay.counts['uploads']
        replay.cycle(250)
        assert replay.matches(250) and replay.counts['uploads'] == count
    else:
        assert replay.matches(249)
        replay.cycle(250)
        assert replay.matches(250) and replay.counts['uploads'] == 2


def test_native_ack_is_inside_existing_unlock_and_other_callers_keep_their_abi(native_images):
    native, Replay, _, _, candidate = native_images
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                                  UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
    replay = Replay(candidate)
    replay.prepare(249)
    config = 0x30018000
    pointer = struct.unpack('<I', replay.cpu.mem_read(native.STATE + 0x20, 4))[0]
    replay.cpu.mem_write(config, struct.pack('<II', 0, pointer))
    registers = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                 UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
    for index, reg in enumerate(registers): replay.cpu.reg_write(reg, 0xabcdef00 + index)
    native.call(replay.cpu, 0x78aa20, native.DEV + 0x180, config)
    assert [replay.cpu.reg_read(reg) for reg in registers] == [0xabcdef00 + i for i in range(8)]
    assert replay.cpu.mem_read(native.STATE + 0x24, 1)[0] == 0x81
    observed = []
    def hook(cpu, at, size, _):
        if at == 0x6073c4: observed.append(cpu.mem_read(native.STATE + 0x24, 1)[0])
    replay.cpu.hook_add(UC_HOOK_CODE, hook)
    replay.consume()
    assert observed == [0x83]
