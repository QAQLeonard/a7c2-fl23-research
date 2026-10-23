"""Synthetic instruction guards, public-asset agreement and exact preservation."""
import importlib.util
import json
from pathlib import Path
import unittest

from looktool import uploadgate


FOLLOWING = bytes.fromhex('c0f27910007d400611d4d8f8080024e0')
STUBS = (
    (0xb2750e, bytes.fromhex('d4bbb5f8880140f20121884234d100f02cb8')),
    (0xb27578, bytes.fromhex('d8f80c00d0f8b00608b10df6f39f42f6b0100df6d89f')),
)
ASSET = Path(__file__).resolve().parents[1] / 'assets/runtime-v1.json'


def synthetic(gate):
    end = uploadgate.OFFSET + 4 + len(FOLLOWING)
    if gate == uploadgate.FORCED:
        end = max(end, *(at + len(raw) for at, raw in STUBS))
    cp = bytearray(end + 16)
    cp[:8] = b'FIXTURE!'
    cp[-8:] = b'NOT-A-CP'
    cp[uploadgate.OFFSET:uploadgate.OFFSET + 4] = gate
    cp[uploadgate.OFFSET + 4:uploadgate.OFFSET + 4 + len(FOLLOWING)] = FOLLOWING
    if gate == uploadgate.FORCED:
        for at, raw in STUBS:
            cp[at:at + len(raw)] = raw
    return bytes(cp)


class UploadGateTests(unittest.TestCase):
    def test_native_gate_needs_no_retired_trampoline_storage(self):
        cp = synthetic(uploadgate.NATIVE)
        self.assertLess(len(cp), STUBS[0][0])
        self.assertIsNone(uploadgate.validate(cp))
        self.assertIs(uploadgate.restore(cp), cp)

    def test_exact_historical_gate_and_trampolines_are_accepted(self):
        self.assertIsNone(uploadgate.validate(synthetic(uploadgate.FORCED)))

    def test_restore_changes_only_four_bytes_and_keeps_source(self):
        original = synthetic(uploadgate.FORCED)
        cp = bytearray(original)
        result = uploadgate.restore(cp)
        self.assertIs(type(result), bytes)
        self.assertEqual(bytes(cp), original)
        self.assertEqual(result[:uploadgate.OFFSET], original[:uploadgate.OFFSET])
        self.assertEqual(result[uploadgate.OFFSET:uploadgate.OFFSET + 4], uploadgate.NATIVE)
        self.assertEqual(result[uploadgate.OFFSET + 4:], original[uploadgate.OFFSET + 4:])
        self.assertEqual(sum(a != b for a, b in zip(original, result)), 4)
        self.assertIs(uploadgate.restore(result), result)
        self.assertEqual(uploadgate.legacy_hash_source(result), original)

    def test_legacy_normalization_is_only_a_four_byte_hash_input(self):
        cp = synthetic(uploadgate.NATIVE)
        normalized = uploadgate.legacy_hash_source(cp)
        self.assertEqual(normalized[:uploadgate.OFFSET], cp[:uploadgate.OFFSET])
        self.assertEqual(normalized[uploadgate.OFFSET:uploadgate.OFFSET + 4], uploadgate.FORCED)
        self.assertEqual(normalized[uploadgate.OFFSET + 4:], cp[uploadgate.OFFSET + 4:])
        forced = synthetic(uploadgate.FORCED)
        self.assertIs(uploadgate.legacy_hash_source(forced), forced)

    def test_bytearray_native_input_is_not_modified(self):
        cp = bytearray(synthetic(uploadgate.NATIVE))
        original = bytes(cp)
        self.assertEqual(uploadgate.restore(cp), original)
        uploadgate.legacy_hash_source(cp)
        self.assertEqual(bytes(cp), original)

    def test_unknown_entry_rejected_by_every_helper(self):
        cp = bytearray(synthetic(uploadgate.NATIVE))
        cp[uploadgate.OFFSET:uploadgate.OFFSET + 4] = b'????'
        for helper in (uploadgate.validate, uploadgate.restore, uploadgate.legacy_hash_source):
            with self.subTest(helper=helper.__name__), self.assertRaisesRegex(ValueError, 'instruction'):
                helper(cp)

    def test_each_native_context_byte_is_guarded_in_both_states(self):
        for gate in (uploadgate.NATIVE, uploadgate.FORCED):
            cp = bytearray(synthetic(gate))
            for index in range(len(FOLLOWING)):
                at = uploadgate.OFFSET + 4 + index
                cp[at] ^= 1
                with self.subTest(gate=gate.hex(), index=index), self.assertRaisesRegex(ValueError, 'context'):
                    uploadgate.validate(cp)
                cp[at] ^= 1

    def test_truncated_gate_and_context_rejected(self):
        cp = synthetic(uploadgate.NATIVE)
        for end in (0, uploadgate.OFFSET, uploadgate.OFFSET + 3,
                    uploadgate.OFFSET + 4, uploadgate.OFFSET + 4 + len(FOLLOWING) - 1):
            with self.subTest(end=end), self.assertRaises(ValueError):
                uploadgate.validate(cp[:end])

    def test_forced_gate_requires_complete_both_trampolines(self):
        cp = synthetic(uploadgate.FORCED)
        for at, raw in STUBS:
            with self.subTest(at=at), self.assertRaisesRegex(ValueError, 'trampoline'):
                uploadgate.validate(cp[:at + len(raw) - 1])

    def test_each_reachable_trampoline_byte_is_guarded(self):
        cp = bytearray(synthetic(uploadgate.FORCED))
        for at, raw in STUBS:
            for index in range(len(raw)):
                cp[at + index] ^= 1
                with self.subTest(at=at, index=index), self.assertRaisesRegex(ValueError, 'trampoline'):
                    uploadgate.restore(cp)
                cp[at + index] ^= 1

    def test_native_validation_does_not_claim_ownership_of_retired_bytes(self):
        cp = bytearray(synthetic(uploadgate.FORCED))
        cp[uploadgate.OFFSET:uploadgate.OFFSET + 4] = uploadgate.NATIVE
        cp[STUBS[0][0]] ^= 1
        self.assertIsNone(uploadgate.validate(cp))
        self.assertEqual(uploadgate.restore(cp), bytes(cp))
        self.assertEqual(uploadgate.legacy_hash_source(cp)[STUBS[0][0]], cp[STUBS[0][0]])

    def test_non_binary_inputs_rejected(self):
        for cp in (None, '', [], 100):
            with self.subTest(type=type(cp).__name__), self.assertRaises(TypeError):
                uploadgate.validate(cp)

    def test_public_runtime_sources_agree_with_reviewed_instructions(self):
        value = json.loads(ASSET.read_text(encoding='utf-8'))
        self.assertEqual({row['kind'] for row in value['cp_sources']}, {'stock', 'fl23'})
        for row in value['cp_sources']:
            entry = [w for w in row['windows'] if w['offset'] == uploadgate.OFFSET]
            self.assertEqual(len(entry), 1)
            self.assertEqual(bytes.fromhex(entry[0]['before']), uploadgate.NATIVE)
            self.assertIn(bytes.fromhex(entry[0]['after']), (uploadgate.NATIVE, uploadgate.FORCED))
            for at, expected in STUBS:
                window = next(w for w in row['windows'] if w['offset'] <= at
                              and at + len(expected) <= w['offset'] + len(bytes.fromhex(w['after'])))
                raw = bytes.fromhex(window['after'])
                self.assertEqual(raw[at - window['offset']:at - window['offset'] + len(expected)], expected)

    @unittest.skipUnless(importlib.util.find_spec('keystone'), 'Optional research assembler unavailable')
    def test_constants_match_independent_public_assembly(self):
        from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
        ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
        assemble = lambda text, at: bytes(ks.asm(text, addr=at)[0])
        self.assertEqual(assemble('movw r0,#0x29b0', 0x23d53a), uploadgate.NATIVE)
        self.assertEqual(assemble('b.w 0xc2f50e', 0x23d53a), uploadgate.FORCED)
        self.assertEqual(assemble('movt r0,#0x179;ldrb r0,[r0,#0x14];lsls r0,r0,#25;'
                                  'bmi 0x23d56c;ldr.w r0,[r8,#8];b 0x23d598', 0x23d53e), FOLLOWING)
        self.assertEqual(assemble('cbnz r4,0xc2f586;ldrh.w r0,[r5,#0x188];'
                                  'movw r1,#0x201;cmp r0,r1;bne 0xc2f586;b.w 0xc2f578',
                                  0xc2f50e), STUBS[0][1])
        self.assertEqual(assemble('ldr.w r0,[r8,#0xc];ldr.w r0,[r0,#0x6b0];'
                                  'cbz r0,0xc2f586;b.w 0x23d56c;movw r0,#0x29b0;b.w 0x23d53e',
                                  0xc2f578), STUBS[1][1])


if __name__ == '__main__':
    unittest.main()
