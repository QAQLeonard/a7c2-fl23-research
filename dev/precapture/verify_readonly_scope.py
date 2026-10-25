"""Host-only fixed-read scope controls; fake transport, no USB imports or I/O."""
import struct
import types
import unittest

from support.readonly_session import session_class


class Camera:
    def __init__(self):
        self.calls = []
        self.reply = bytes(8)
        self.error = None

    def _sendAdjustControlPacket(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.reply


class Session:
    def __init__(self, expected):
        self.camera = Camera()
        self.channel = object()

    def call(self, method, *args):
        return method(*args)


TRANSPORT = types.SimpleNamespace(Session=Session,
    SonySenserDevice=types.SimpleNamespace(RESPONSE_FRAMING='length-delimited-zlp/3'))


class ScopeTests(unittest.TestCase):
    def session(self, enabled=True):
        return session_class(TRANSPORT, policy_scalar=enabled)(['/tmp/jiritsu/test'])

    def test_exact_read_is_single_use(self):
        session = self.session()
        self.assertEqual(session.read_cp_policy_value(), bytes(8))
        self.assertEqual(session.camera.calls, [(0x603, 0x40, struct.pack('<II', 0xfa0182, 1))])
        with self.assertRaises(ValueError): session.read_cp_policy_value()
        self.assertEqual(len(session.camera.calls), 1)

    def test_default_scope_rejects_cp_query(self):
        session = self.session(False)
        with self.assertRaises(ValueError): session.read_cp_policy_value()
        self.assertEqual(session.camera.calls, [])

    def test_write_other_key_route_or_flags_never_reach_transport(self):
        for args in ((0x603, 0x41, struct.pack('<II', 0xfa0182, 1)),
                     (0x603, 0x40, struct.pack('<II', 0xfa0183, 1)),
                     (0x603, 0x40, struct.pack('<II', 0xfa0182, 0)),
                     (0x602, 0x40, struct.pack('<II', 0xfa0182, 1))):
            with self.subTest(args=args):
                session = self.session()
                with self.assertRaises(ValueError): session.call(session.camera._sendAdjustControlPacket, *args)
                self.assertEqual(session.camera.calls, [])

    def test_timeout_or_wrong_reply_never_replays(self):
        for reply, error in ((b'', None), (bytes(7), None), (bytes(9), None),
                             (None, None), (bytes(8), TimeoutError('unknown read'))):
            with self.subTest(reply=reply, error=error):
                session = self.session()
                session.camera.reply, session.camera.error = reply, error
                with self.assertRaises((ValueError, TimeoutError)): session.read_cp_policy_value()
                with self.assertRaises(ValueError): session.read_cp_policy_value()
                self.assertEqual(len(session.camera.calls), 1)


if __name__ == '__main__': unittest.main()
