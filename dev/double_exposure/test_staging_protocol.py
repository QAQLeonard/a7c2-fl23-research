import struct
import unittest
from staging_model import CHUNK_BYTES, Plan
from staging_protocol import CREATE, PUT, ASSEMBLE, QUERY, HEADER, request


class StagingProtocol(unittest.TestCase):
    def test_fixed_little_endian_layout_and_manifest(self):
        plan = Plan.from_bytes(b'A' * (CHUNK_BYTES + 1))
        transaction = bytes(range(16))
        wire = request(plan, transaction, CREATE)
        self.assertEqual(HEADER.size, 80)
        self.assertEqual(len(wire), 144)
        self.assertEqual(wire[:8], b'A7STG001')
        self.assertEqual(struct.unpack_from('<II', wire, 8), (CREATE, 0))
        self.assertEqual(wire[16:32], transaction)
        self.assertEqual(struct.unpack_from('<QII', wire, 32), (CHUNK_BYTES + 1, 2, 0))
        self.assertEqual(wire[48:80].hex(), plan.sha256)
        self.assertEqual(wire[80:112].hex(), plan.chunks[0])
        self.assertEqual(wire[112:144].hex(), plan.chunks[1])
        for operation in (PUT, ASSEMBLE, QUERY):
            self.assertEqual(len(request(plan, transaction, operation)), 80)

    def test_invalid_request_cannot_be_encoded(self):
        plan, transaction = Plan.from_bytes(b'x'), b'T' * 16
        for operation, index in ((True, 0), (0, 0), (5, 0), (PUT, 1), (PUT, -1),
                                 (CREATE, 1), (QUERY, True), (ASSEMBLE, 7)):
            with self.assertRaises(ValueError): request(plan, transaction, operation, index)
        for identity in (b'', b'x', b'\0' * 16, 'T' * 16, b'T' * 17):
            with self.assertRaises(ValueError): request(plan, identity, CREATE)
