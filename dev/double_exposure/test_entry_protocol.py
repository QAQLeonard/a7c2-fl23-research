import hashlib
import struct
import unittest
from entry_protocol import device_request, receipt


class EntryProtocol(unittest.TestCase):
    def test_arm_layout_and_nonmutating_query(self):
        instance = b'INSTANCE-0000001'
        arm = device_request(instance, 1, 42, epoch=7, generation=9, media=2, nonce=123)
        self.assertEqual(len(arm), 64)
        self.assertEqual(struct.unpack('<8sIIQQQII16s', arm),
                         (b'A7DEX001', 1, 0, 42, 7, 9, 2, 123, instance))
        query = device_request(instance, 3, 43)
        self.assertEqual(query[24:48], b'\0' * 24)
        auto = device_request(instance, 1, 44, epoch=1, generation=1)
        self.assertEqual(struct.unpack_from('<I', auto, 40)[0], 0xffffffff)
        for kwargs in ({}, {'epoch': 1}, {'epoch': 1, 'generation': 0}):
            with self.assertRaises(ValueError): device_request(instance, 1, 1, **kwargs)
        with self.assertRaises(ValueError): device_request(instance, 3, 1, epoch=1)
        with self.assertRaises(ValueError): device_request(b'\0' * 16, 3, 1)

    def test_completed_receipt_does_not_imply_photo_complete(self):
        request = device_request(b'INSTANCE-0000001', 1, 1, epoch=1, generation=1)
        header = bytearray(64); header[:8] = b'A7ENT001'
        struct.pack_into('<II', header, 8, 1, 2); header[32:64] = hashlib.sha256(request).digest()
        payload = bytearray(2832); struct.pack_into('<IIIIQ', payload, 0, 1, 1, 1, 0, 1)
        data = bytes(header) + struct.pack('<iI', 0, len(payload)) + payload
        data += hashlib.sha256(data).digest() + b'A7DONE01'
        self.assertTrue(receipt(data, request)['command_completed'])
        self.assertFalse(receipt(data, request)['photo_complete'])
        for cut in (0, 7, 64, 72, len(data)-1):
            with self.assertRaises(ValueError): receipt(data[:cut], request)
        changed = bytearray(data); changed[72 + 80] = 7
        with self.assertRaises(ValueError): receipt(changed, request)
        with self.assertRaises(ValueError): receipt(data, device_request(b'INSTANCE-0000001', 3, 2))

    def test_completed_phase_alone_cannot_replace_catalog_and_file_evidence(self):
        from test_device_driver import FakeSession
        session = FakeSession()
        wire = device_request(b'INSTANCE-0000001', 3, 2)
        session.operation = 1; session.request_id = 1
        session.epoch = session.generation = 1
        session.files['a7c2.dex.request'] = wire
        session.temp('libJit.so', b'test-only')
        raw = session.files['a7c2.dex.result']
        self.assertTrue(receipt(raw, wire)['photo_complete'])
        for offset, value in ((32, 0), (2212, 5), (2764, 0), (2232, 1), (2248, 88)):
            with self.subTest(offset=offset):
                changed = bytearray(raw)
                changed[72 + offset] = value
                changed[-40:-8] = hashlib.sha256(changed[:-40]).digest()
                with self.assertRaises(ValueError): receipt(bytes(changed), wire)
