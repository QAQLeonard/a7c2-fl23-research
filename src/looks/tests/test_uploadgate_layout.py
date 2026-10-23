"""Synthetic LUT layouts and migration contracts; no private files or device I/O."""
import base64
import copy
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import zlib

from looktool import device_layout, firmware, photobasis, photobuild
from looktool import photoformat, photoio, six, uploadgate, worker
from test_photoformat import curve


ASSETS = Path(__file__).resolve().parents[1] / 'assets'
FOLLOWING = bytes.fromhex('c0f27910007d400611d4d8f8080024e0')
AP = b'Synthetic legacy AP, never executable'


def legacy_identity(_):
    return {'kind': 'legacy-six', 'mask': 63, 'label_ids': list(range(6))}


def synthetic_layout(asset):
    """Build native-photo prerequisites entirely from public code and curves."""
    cp = bytearray(0x1101fa0)
    for hook in photoio.template()['hooks']:
        at, raw = hook['offset'], bytes.fromhex(hook['before'])
        cp[at:at + len(raw)] = raw
    for window in next(row for row in asset['cp_sources'] if row['kind'] == 'fl23')['windows']:
        if window['offset'] in (0xb27490, 0xb27f10):
            at, raw = window['offset'], bytes.fromhex(window['after'])
            cp[at:at + len(raw)] = raw
    for row in range(50):
        struct.pack_into('<7I', cp, 0x1209480 - photobuild.BASE + row * 28,
                         *([0x180000] * 7))
    cp[0x180000 - photobuild.BASE:0x180000 - photobuild.BASE + 576] = curve()
    struct.pack_into('<3I', cp, 0x20124, 0, 0xb27fb0 - 0x20000, 0x128000)
    struct.pack_into('<3I', cp, 0x2013c, 0x1101ae0 - 0x20000, 1216, 0x1209ae0)
    payload = six.prefix([bytes([i]) * six.TABLE_BYTES for i in range(6)])
    cp[six.TABLE_FILE:six.TABLE_FILE + len(payload)] = payload
    cp[uploadgate.OFFSET:uploadgate.OFFSET + 4] = uploadgate.FORCED
    cp[uploadgate.OFFSET + 4:uploadgate.OFFSET + 4 + len(FOLLOWING)] = FOLLOWING
    return bytes(cp)


class UploadGateLayoutTests(unittest.TestCase):
    def test_runtime_rejects_an_unknown_hash_canonical_entry(self):
        for value in (None, uploadgate.NATIVE.hex(), '00000000'):
            asset=copy.deepcopy(self.asset)
            asset['cp_hash_canonical_upload_entry']=value
            with self.subTest(value=value), \
                    patch.object(Path, 'read_text', return_value=json.dumps(asset)), \
                    self.assertRaisesRegex(ValueError, 'canonical CP upload entry'):
                device_layout.runtime()

    @classmethod
    def setUpClass(cls):
        cls.asset = json.loads((ASSETS / 'runtime-v1.json').read_text(encoding='utf-8'))
        cls.a = synthetic_layout(cls.asset)
        cls.b = uploadgate.restore(cls.a)
        cls.tables = six.read_tables(cls.a)
        cls.bank = photoformat.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        cls.delta1 = photobasis.pack(cls.bank, tone=(16, 0, 0))[1]
        cls.delta6 = photobasis.pack(cls.bank, tone=(-16, 8, 0))[1]
        cls.photo_a = photoio.update(cls.a, {1: cls.delta1, 6: cls.delta6}, cls.bank,
                                     allocation_proved=True)

    def assert_only_gate_changed(self, before, after):
        self.assertEqual(after[:uploadgate.OFFSET], before[:uploadgate.OFFSET])
        self.assertEqual(after[uploadgate.OFFSET:uploadgate.OFFSET + 4], uploadgate.NATIVE)
        self.assertEqual(after[uploadgate.OFFSET + 4:], before[uploadgate.OFFSET + 4:])
        self.assertEqual(sum(a != b for a, b in zip(
            before[uploadgate.OFFSET:uploadgate.OFFSET + 4],
            after[uploadgate.OFFSET:uploadgate.OFFSET + 4])), 4)

    def test_stock_and_fl23_first_import_plan_native_gate(self):
        for kind in ('stock', 'fl23'):
            with self.subTest(kind=kind):
                spec = next(row for row in self.asset['cp_sources'] if row['kind'] == kind)
                cp = bytearray(spec['bytes'])
                for window in spec['windows']:
                    raw, at = bytes.fromhex(window['before']), window['offset']
                    cp[at:at + len(raw)] = raw
                cp[uploadgate.OFFSET + 4:uploadgate.OFFSET + 4 + len(FOLLOWING)] = FOLLOWING
                asset = copy.deepcopy(self.asset)
                # AP recognition/templates are an independent large component;
                # keep this test on the real public CP bootstrap windows.
                for row in asset['ap_sources']:
                    row['restore'] = []
                imported_ap = b'Synthetic imported AP'

                def identity(ap):
                    return ({'kind': kind, 'mask': 0, 'first_install': True, 'label_ids': list(range(6))}
                            if ap == AP else
                            {'kind': kind + '-lut', 'mask': 1, 'label_ids': list(range(6))})

                with patch.object(device_layout, 'runtime', return_value=asset), \
                        patch.object(device_layout, 'structural_ap', side_effect=identity), \
                        patch.object(device_layout, '_ap_target', return_value=imported_ap):
                    _, _, result = device_layout.replace(AP, bytes(cp), {1: bytes([8]) * 1215},
                                                          hash_checks=False, transitions=False)
                self.assertEqual(result['cpapp-b.bin'][uploadgate.OFFSET:uploadgate.OFFSET + 4],
                                 uploadgate.NATIVE)
                uploadgate.validate(result['cpapp-b.bin'])
                self.assertEqual(six.read_tables(result['cpapp-b.bin'])[0], bytes([8]) * 1215)

    def test_legacy_without_photo_declares_exact_gate_window_and_inverse(self):
        self.assertFalse(photoio.present(self.a))
        with patch.object(device_layout, 'structural_ap', side_effect=legacy_identity):
            forward, reverse, after = device_layout.replace(
                AP, self.a, {1: self.tables[0]}, hash_checks=False)
        self.assertEqual(after['appFw.so'], AP)
        self.assert_only_gate_changed(self.a, after['cpapp-b.bin'])
        self.assertEqual(forward['files']['appFw.so']['windows'], [])
        self.assertEqual(forward['files']['cpapp-b.bin']['windows'], [{
            'offset': hex(uploadgate.OFFSET), 'bytes': 4,
            'before_hex': uploadgate.FORCED.hex(), 'after_hex': uploadgate.NATIVE.hex()}])
        self.assertEqual(firmware.apply(after, reverse), {'appFw.so': AP, 'cpapp-b.bin': self.a})
        self.assertEqual(firmware.apply({'appFw.so': AP, 'cpapp-b.bin': self.a}, forward), after)

    def test_native_gate_repeat_same_table_is_complete_noop(self):
        with patch.object(device_layout, 'structural_ap', side_effect=legacy_identity):
            forward, reverse, after = device_layout.replace(
                AP, self.b, {1: self.tables[0]}, hash_checks=False)
        self.assertEqual(after, {'appFw.so': AP, 'cpapp-b.bin': self.b})
        for manifest in (forward, reverse):
            self.assertTrue(all(not spec['windows'] for spec in manifest['files'].values()))

    def test_photo_fastpath_rejects_unknown_gate_and_native_neighbor(self):
        self.assertTrue(photoio.present(self.photo_a))
        for offset in (uploadgate.OFFSET, uploadgate.OFFSET + 4):
            cp = bytearray(self.photo_a)
            cp[offset] ^= 1
            # Prove this reaches the real photo inspector before the gate
            # guard, rather than failing on a fabricated photo magic word.
            self.assertEqual(photoio.inspect(bytes(cp))['mask'], 33)
            with self.subTest(offset=offset), \
                    patch.object(device_layout, 'structural_ap', side_effect=legacy_identity), \
                    self.assertRaisesRegex(ValueError, 'upload gate'):
                device_layout.identify(AP, bytes(cp))

    def test_photo_migration_preserves_selected_and_other_native_parameters(self):
        before = photoio.inspect(self.photo_a)
        with patch.object(device_layout, 'structural_ap', side_effect=legacy_identity):
            forward, reverse, after = device_layout.replace(
                AP, self.photo_a, {1: self.tables[0]}, hash_checks=False,
                native_photo={1: self.delta1}, native_bank=self.bank)
            identity = device_layout.identify(AP, after['cpapp-b.bin'])
        self.assert_only_gate_changed(self.photo_a, after['cpapp-b.bin'])
        self.assertEqual(identity['native_photo'], before)
        for slot in (1, 6):
            self.assertEqual(photoio.slot_bytes(after['cpapp-b.bin'], slot),
                             photoio.slot_bytes(self.photo_a, slot))
        self.assertEqual(six.read_tables(after['cpapp-b.bin']), self.tables)
        self.assertEqual(len(forward['files']['cpapp-b.bin']['windows']), 1)
        self.assertEqual(firmware.apply(after, reverse),
                         {'appFw.so': AP, 'cpapp-b.bin': self.photo_a})

    def test_code_hash_normalizes_only_gate_and_keeps_other_code_strict(self):
        # Do not replace CODE_SHA or adjust an expected hash to admit damage.
        # Compare the real hash function against a fixed synthetic baseline.
        expected = device_layout.code_hash(self.a)
        self.assertEqual(device_layout.code_hash(self.b), expected)
        changed = bytearray(self.b)
        changed[0x40000] ^= 1  # Outside table payload/checksums and FL23 fields.
        self.assertNotEqual(device_layout.code_hash(bytes(changed)), expected)
        changed = bytearray(self.b)
        changed[uploadgate.OFFSET] ^= 1
        with self.assertRaises(ValueError):
            device_layout.code_hash(bytes(changed))

    def test_legacy_table_adapter_and_worker_keep_migration_in_exact_contract(self):
        # Fixed known synthetic identities replace real firmware fixtures.
        # They stay fixed for the subsequent tampered-source rejection.
        with patch.object(six, 'AP_SHA', firmware.sha(AP)), \
                patch.object(six, 'CP_SHA', firmware.sha(self.a)):
            forward, reverse, after = six.replace_tables(AP, self.a, {1: self.tables[0]})
            forward['slot_plan'] = {'model': 'ILCE-7CM2', 'firmware': '2.01', 'selected_slots': [1]}
            _, contract = worker.prepare_table_worker(AP, self.a, forward, reverse, {'1': 'ST'})
            self.assertEqual(contract['window_writes'], 1)
            self.assertEqual(contract['before']['cpapp-b.bin'], firmware.sha(self.a))
            self.assertEqual(contract['after']['cpapp-b.bin'], firmware.sha(self.b))
            self.assertEqual(after['cpapp-b.bin'], self.b)
            damaged = bytearray(self.a)
            damaged[0x40000] ^= 1
            with self.assertRaises(ValueError):
                worker.prepare_table_worker(AP, bytes(damaged), forward, reverse, {'1': 'ST'})
            # A native-entry source remains admitted by the historical exact
            # source hash, but is never planned back to the forced entry.
            f2, r2, after2 = six.replace_tables(AP, self.b, {6: bytes([7]) * 1215})
            f2['slot_plan'] = {'model': 'ILCE-7CM2', 'firmware': '2.01', 'selected_slots': [6]}
            _, c2 = worker.prepare_table_worker(AP, self.b, f2, r2, {'6': 'ST'})
            self.assertEqual(c2['window_writes'], 2)
            self.assertEqual(after2['cpapp-b.bin'][uploadgate.OFFSET:uploadgate.OFFSET + 4],
                             uploadgate.NATIVE)

    def test_factory_reference_and_public_noop_window_retain_entry_ownership(self):
        factory = json.loads((ASSETS / 'factory-regions-2.01.json').read_text(encoding='utf-8'))
        covering = [row for row in factory['programs']['cpapp-b.bin']['regions']
                    if row['offset'] <= uploadgate.OFFSET and
                    uploadgate.OFFSET + 4 <= row['offset'] + row['bytes']]
        self.assertEqual(len(covering), 1)
        row = covering[0]
        raw = zlib.decompress(base64.b64decode(row['zlib_base64']))
        self.assertEqual(len(raw), row['bytes'])
        start = uploadgate.OFFSET - row['offset']
        self.assertEqual(raw[start:start + 4], uploadgate.NATIVE)
        for spec in self.asset['cp_sources']:
            # build_factory_reference collects these window offsets and their
            # before lengths. A no-op must remain listed for old A recovery.
            matches = [w for w in spec['windows'] if w['offset'] == uploadgate.OFFSET]
            self.assertEqual(len(matches), 1)
            self.assertEqual(bytes.fromhex(matches[0]['before']), uploadgate.NATIVE)
            self.assertEqual(bytes.fromhex(matches[0]['after']), uploadgate.NATIVE)
            self.assertEqual(len(bytes.fromhex(matches[0]['before'])), 4)


if __name__ == '__main__':
    unittest.main()
