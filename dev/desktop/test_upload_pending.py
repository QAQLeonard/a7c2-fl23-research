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


def test_trial2_candidate_remains_reversible_and_upgrades_to_current_candidate():
    source = uploadgate.restore(synthetic())
    previous = bytearray(source)
    for _, at, _, after in uploadpending.TRIAL2_WINDOWS:
        raw = bytes.fromhex(after)
        previous[at:at + len(raw)] = raw
    previous = bytes(previous)
    assert uploadpending.active(previous)
    assert uploadpending.normalize(previous) == source
    assert uploadpending.install(previous) == uploadpending.install(source)


def test_checked_in_instruction_bytes_match_reviewable_assembler():
    from evf_pending_asm import build
    blocks = build()
    windows = {name: bytes.fromhex(after) for name, _, _, after in uploadpending.WINDOWS}
    assert windows['consumer_copy'][56:] == blocks['resolver']
    assert windows['consumer_override_copy'] == blocks['override']
    assert windows['consume'] == blocks['consume']
    assert windows['unlock_hook'] == blocks['unlock_hook']


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
def native_images(monkeypatch):
    if not os.environ.get('A7C2_RESEARCH_FIXTURES'):
        pytest.skip('Optional private firmware; never reads USB')
    from test_uploadgate_native import Replay
    import test_preview_native as native
    # The shared-state regressions also use the real owner address. The
    # two-frame cases below independently exercise copies and publication.
    cpu_for = native.cpu_for
    def mapped_cpu(image):
        cpu = cpu_for(image)
        cpu.mem_map(0x2000000, 0x10000)
        return cpu
    monkeypatch.setattr(native, 'cpu_for', mapped_cpu)
    monkeypatch.setattr(native, 'STATE', 0x2003738 + 0x664)
    index = Path(os.environ['A7C2_RESEARCH_FIXTURES'])
    paths = json.loads(index.read_text(encoding='utf-8'))
    old = (index.parent / paths['v4_cp']).read_bytes()
    return native, Replay, old, uploadgate.restore(old), uploadpending.install(old)


def test_real_trial1_to_trial3_plan_is_cp_only_and_reversible(native_images):
    _, _, _, first, candidate = native_images
    index = Path(os.environ['A7C2_RESEARCH_FIXTURES'])
    paths = json.loads(index.read_text(encoding='utf-8'))
    current = {'appFw.so': (index.parent / paths['six_ap']).read_bytes(), 'cpapp-b.bin': first}
    target, wanted, names = direct.plan(current, None, 'preview_pending')
    assert target['appFw.so'] is current['appFw.so']
    assert target['cpapp-b.bin'] == candidate
    assert wanted == [{}, {}] and names is None
    restored, wanted, names = direct.plan(target, None, 'preview_native')
    assert restored == current
    assert wanted == [{}, {}] and names is None


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
    assert struct.unpack('<I', replay.cpu.mem_read(native.MMIOS[0] + 0xad40, 4))[0] == 0


def test_native_consumer_accepts_a_bounded_parameter_copy(native_images):
    """The original consumer reads a 28-byte parameter, not a producer object.

    Place the copy at the end of mapped memory so an invented source+0x17c
    read cannot silently pass as it did in the original shared-state model.
    This checks the function's read extent; it does not prove camera aliasing.
    """
    native, Replay, _, before, candidate = native_images
    from unicorn import UC_PROT_READ
    for image in (before, candidate):
        replay = Replay(image)
        replay.prepare(249)
        parameter = 0x30020000 - 28
        raw = bytes(replay.cpu.mem_read(native.STATE + 0xc, 28))
        replay.cpu.mem_write(parameter, raw)
        replay.cpu.mem_write(0x3001f000, bytes(8))
        replay.cpu.mem_protect(0x3001f000, 4096, UC_PROT_READ)
        native.call(replay.cpu, 0x42cd28, native.DEV, native.DEV, native.CONTROL, parameter)
        assert replay.matches(249)


class FrameReplay:
    """Native two-frame copies and controller/consumer calls, without USB.

    Only the frame-copy instruction slice is executed, not the surrounding
    scheduler. Publication/consumption order is deliberately selected by tests.
    """
    FRAME = 0x2003738
    STRIDE = 0x19fc
    STATE_OFFSET = 0x664
    INDEX = 0x1acd713

    def __init__(self, images, image):
        self.native, Replay = images[:2]
        self.replay = Replay(image)
        self.cpu = self.replay.cpu
        self.index = 0
        self.cpu.mem_write(self.state(0), bytes(self.cpu.mem_read(self.native.STATE, 0x190)))
        self.publish(0)

    def state(self, index):
        return self.FRAME + index * self.STRIDE + self.STATE_OFFSET

    def publish(self, index):
        self.index = index
        self.cpu.mem_write(self.INDEX, bytes([index]))

    def clone(self, destination):
        from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_R8, UC_ARM_REG_LR
        self.cpu.reg_write(UC_ARM_REG_R5, self.FRAME + self.index * self.STRIDE + 0x2dc)
        self.cpu.reg_write(UC_ARM_REG_R8, self.FRAME + destination * self.STRIDE + 0x2dc)
        self.cpu.reg_write(UC_ARM_REG_LR, 0x31000001)
        self.cpu.emu_start(0x23cf37, 0x23cf5a, count=100)
        assert bytes(self.cpu.mem_read(self.state(destination), 0x190)) == bytes(
            self.cpu.mem_read(self.state(self.index), 0x190))

    def prepare(self, marker, destination=None, consumer=0):
        if destination is None:
            destination = self.index
        self.cpu.mem_write(self.native.OUTPUT + 8, struct.pack('<I', self.state(destination)))
        self.replay.prepare(marker, consumer)

    def consume(self, source=None, consumer=0):
        if source is None:
            source = self.index
        self.cpu.mem_write(self.native.DEV + 0x184, struct.pack('<I', self.native.MMIOS[consumer]))
        self.cpu.mem_write(0x3001f000, bytes(8))
        self.native.call(self.cpu, 0x42cd28, self.native.DEV, self.native.DEV,
                         self.native.CONTROL, self.state(source) + 0xc)


@pytest.mark.parametrize('publication', ('before_consume', 'after_consume'))
def test_native_frame_copy_does_not_lose_hardware_ack(native_images, publication):
    frames = FrameReplay(native_images, native_images[-1])
    frames.prepare(249)
    for _ in range(6):
        source, destination = frames.index, 1 - frames.index
        frames.clone(destination)
        frames.prepare(249, destination)
        if publication == 'before_consume':
            frames.publish(destination)
        frames.consume(source)
        if publication == 'after_consume':
            frames.publish(destination)
        assert frames.replay.matches(249)
    assert frames.replay.counts['builds'] == 1
    assert frames.replay.counts['uploads'] == 1


@pytest.mark.parametrize('publication', ('before_consume', 'after_consume'))
def test_native_frame_switches_and_dropped_consumption_recover(native_images, publication):
    frames = FrameReplay(native_images, native_images[-1])
    for marker in (249, 250, 251, 252, 253, 254, 249):
        frames.prepare(marker)
        for consumer in range(4):
            count = frames.replay.counts['uploads']
            for cycle in range(5):
                source, destination = frames.index, 1 - frames.index
                frames.clone(destination)
                frames.prepare(marker, destination, consumer)
                if publication == 'before_consume':
                    frames.publish(destination)
                # Miss two controller/consumer handoffs before an upload.
                if cycle >= 2:
                    frames.consume(source, consumer)
                    assert frames.replay.matches(marker, consumer)
                if publication == 'after_consume':
                    frames.publish(destination)
            assert frames.replay.counts['uploads'] == count + 1


def test_native_reused_readonly_parameter_copy_does_not_repeat_uploads(native_images):
    native, Replay, _, _, candidate = native_images
    from unicorn import UC_PROT_READ
    replay = Replay(candidate)
    replay.prepare(249)
    parameter = 0x30020000 - 28
    replay.cpu.mem_write(parameter, bytes(replay.cpu.mem_read(native.STATE + 0xc, 28)))
    replay.cpu.mem_write(0x3001f000, bytes(8))
    replay.cpu.mem_protect(0x3001f000, 4096, UC_PROT_READ)
    for consumer in range(4):
        replay.cpu.mem_write(native.DEV + 0x184, struct.pack('<I', native.MMIOS[consumer]))
        for _ in range(3):
            native.call(replay.cpu, 0x42cd28, native.DEV, native.DEV, native.CONTROL, parameter)
            assert replay.matches(249, consumer)
    assert replay.counts['uploads'] == 4


@pytest.mark.parametrize('destination', (0xf3b30000, 0xf3d30000, 0xf3e30000, 0xf3f30000))
def test_native_other_destination_does_not_borrow_a_custom_ack_bit(native_images, destination):
    native, Replay, _, _, candidate = native_images
    replay = Replay(candidate)
    replay.prepare(249)
    replay.cpu.mem_map(destination, 0x10000)
    replay.cpu.mem_write(native.DEV + 0x184, struct.pack('<I', destination))
    replay.cpu.mem_write(0x3001f000, bytes(8))
    for _ in range(2):
        native.call(replay.cpu, 0x42cd28, native.DEV, native.DEV, native.CONTROL, native.STATE + 0xc)
    assert replay.counts['uploads'] == 2
    assert replay.cpu.mem_read(native.STATE + 0x24, 1)[0] == 0x81


def test_native_override_copy_preserves_read_order_and_hardware_registers(native_images):
    native, Replay, _, before, candidate = native_images
    from unicorn import UC_HOOK_MEM_READ
    for seed in range(5):
        results, accesses = [], []
        for image in (before, candidate):
            replay = Replay(image)
            replay.cpu.mem_write(native.DEV + 0x184, struct.pack('<I', native.MMIOS[0]))
            replay.cpu.mem_write(native.CONTROL + 4, b'\x01')
            replay.cpu.mem_write(0x1795bbd, b'\x01')
            replay.cpu.mem_write(0x1795c45, random.Random(seed).randbytes(18))
            replay.cpu.mem_write(native.STATE + 0x24, b'\0')
            reads = []
            def hook(cpu, access, address, size, value, data):
                if 0x1795c45 <= address < 0x1795c57:
                    reads.append((address, size))
            replay.cpu.hook_add(UC_HOOK_MEM_READ, hook)
            replay.consume()
            results.append(bytes(replay.cpu.mem_read(native.MMIOS[0], 0x10000)))
            accesses.append(reads)
        assert results[0] == results[1]
        assert accesses[0] == accesses[1]
