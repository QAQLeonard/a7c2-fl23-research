"""Native instruction replay for the restored upload gate; never physical I/O.

Optional private firmware, synthetic RAM/MMIO and modeled memcpy/barriers.
The missed-consumption tests characterize a limit, not a camera scheduling claim.
"""
import struct
import unittest

import test_preview_native as native
from looktool import uploadgate


class Replay:
    def __init__(self, image, gate=0, **options):
        self.image = image
        self.cpu, self.counts = native.create(image, **options)
        self.cpu.mem_write(0x17929c4, bytes([gate]))

    def prepare(self, marker, consumer=0):
        self.cpu.mem_write(native.ROOTPARAM + 0x2e, bytes([marker]))
        self.cpu.mem_write(native.DEV + 0x184,
                           struct.pack('<I', native.MMIOS[consumer]))
        native.call(self.cpu, 0x23d380, native.CONTEXT, native.OUTPUT)

    def consume(self, consumer=0, *, destination=True, copy=False, buffer=0):
        self.cpu.mem_write(native.DEV + 0x184, struct.pack(
            '<I', native.MMIOS[consumer] if destination else 0))
        # Existing native ABI: fifth argument selects the copy route; the
        # sixth supplies its output buffer. These are not named camera modes.
        self.cpu.mem_write(0x3001f000, struct.pack('<II', int(copy), buffer))
        native.call(self.cpu, 0x42cd28, native.DEV, native.DEV,
                    native.CONTROL, native.STATE + 0xc)

    def matches(self, marker, consumer=0):
        hardware = b''.join(bytes(self.cpu.mem_read(
            native.MMIOS[consumer] + offset, length))
            for offset, length in native.CHUNKS)
        start = native.TABLE_FILE + 32 + (marker - 249) * 1215
        return hardware == native.pack_model(self.image, self.image[start:start + 1215])

    def cycle(self, marker, consumer=0):
        self.prepare(marker, consumer)
        self.consume(consumer)

    def state(self):
        return bytes(self.cpu.mem_read(native.STATE, 0x190)), dict(self.counts)


class NativeUploadGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the existing exact fixture checks; never commit firmware.
        native.NativePreviewTests.setUpClass()
        cls.forced = native.NativePreviewTests.new
        cls.restored = uploadgate.restore(cls.forced)

    def test_six_slots_switch_with_native_gate_and_matching_hardware_bytes(self):
        for gate in (0, 0x40):
            replay = Replay(self.restored, gate)
            for marker in (249, 250, 251, 252, 253, 254, 249):
                with self.subTest(gate=gate, marker=marker):
                    replay.cycle(marker)
                    self.assertTrue(replay.matches(marker))

    def test_stable_slot_uploads_once_unless_native_repeat_condition_is_set(self):
        for gate in (0, 0x40):
            forced, restored = Replay(self.forced, gate), Replay(self.restored, gate)
            for _ in range(10):
                for replay in (forced, restored):
                    replay.cycle(249)
                    self.assertTrue(replay.matches(249))
            self.assertEqual(forced.counts['builds'], 1)
            self.assertEqual(restored.counts['builds'], 1)
            self.assertEqual(forced.counts['uploads'], 10)
            self.assertEqual(restored.counts['uploads'], 10 if gate else 1)

    def test_changing_consumer_without_changing_slot_updates_each_destination(self):
        for gate in (0, 0x40):
            replay = Replay(self.restored, gate)
            for consumer in (0, 1, 2, 3, 0):
                replay.cycle(249, consumer)
                self.assertTrue(replay.matches(249, consumer))

    def test_snapshot_direct_and_native_looks_keep_existing_behavior(self):
        custom_and_native = (0, 249, 250, 251, 252, 253, 254, 0, 19, 20)
        scenarios = [({'flag': 1}, custom_and_native),
                     ({'direct': 1}, custom_and_native),
                     ({'flag': 1, 'direct': 1}, custom_and_native),
                     ({}, (0, 1, 2, 3, 5, 13, 15, 16, 17, 18, 19, 20))]
        for options, markers in scenarios:
            for gate in (0, 0x40):
                forced = Replay(self.forced, gate, **options)
                restored = Replay(self.restored, gate, **options)
                for marker in markers:
                    forced.cycle(marker)
                    restored.cycle(marker)
                    self.assertEqual(forced.state(), restored.state())

    def test_missing_consumption_remains_an_explicit_native_gate_limit(self):
        # Execute the real native early-return branches rather than mocking
        # the uploader's result. These are artificial interleavings, not proof
        # that any physical camera calls its routines in this order.
        transitions = ((249, 250), (250, 251), (251, 252),
                       (252, 253), (253, 254), (254, 249))
        for source, target in transitions:
            for gate in (0, 0x40):
                for missed in ('second_controller', 'no_device', 'no_copy_buffer'):
                    for image in (self.forced, self.restored):
                        with self.subTest(source=source, target=target, gate=gate,
                                          missed=missed, native=image is self.restored):
                            replay = Replay(image, gate)
                            replay.cycle(source)
                            self.assertTrue(replay.matches(source))
                            replay.prepare(target)
                            if missed == 'second_controller':
                                replay.prepare(target)
                                replay.consume()
                            elif missed == 'no_device':
                                replay.consume(destination=False)
                            else:
                                replay.consume(copy=True)
                            replay.cycle(target)
                            recovers = image is self.forced or bool(gate)
                            self.assertEqual(replay.matches(target), recovers)
                            if not recovers:
                                self.assertTrue(replay.matches(source))


if __name__ == '__main__':
    unittest.main()
