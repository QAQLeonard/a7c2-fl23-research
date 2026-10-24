"""Verify the offline query ownership state contract; no native I/O."""

import unittest

from support.query_session import QuerySession, SessionPhase


class QuerySessionTests(unittest.TestCase):
    def make(self):
        return QuerySession(nonce=7, own_id=0x803F6111)

    def handed(self):
        session = self.make()
        session.handoff(nonce=7, own_id=0x803F6111, message=0x60000040)
        return session

    def test_handoff_keeps_context_open_until_fence(self):
        session = self.handed()
        self.assertFalse(session.can_close())
        self.assertFalse(session.poll(status=-1022))
        self.assertEqual(session.phase, SessionPhase.HANDED_OFF)
        self.assertFalse(session.can_close())

    def test_matched_reply_still_needs_quiescence_fence(self):
        session = self.handed()
        self.assertTrue(session.poll(status=0, message=0x60000100))
        session.reply(matched=True, release_status=0)
        self.assertEqual(session.phase, SessionPhase.REPLY_RELEASED)
        self.assertFalse(session.can_close())
        session.fence(generation=1, observed=True)
        self.assertTrue(session.can_close())

    def test_unknown_reply_cannot_be_reused(self):
        session = self.handed()
        self.assertTrue(session.poll(status=0, message=0x60000100))
        with self.assertRaises(ValueError):
            session.reply(matched=False, release_status=0)
        self.assertEqual(session.phase, SessionPhase.UNKNOWN)
        with self.assertRaises(ValueError):
            session.fence(generation=1, observed=True)

    def test_bad_release_or_fence_never_closes(self):
        for release_status in (-5, 1):
            session = self.handed()
            session.poll(status=0, message=0x60000100)
            with self.assertRaises(ValueError):
                session.reply(matched=True, release_status=release_status)
            self.assertFalse(session.can_close())
        session = self.handed()
        session.poll(status=0, message=0x60000100)
        session.reply(matched=True, release_status=0)
        with self.assertRaises(ValueError):
            session.fence(generation=0, observed=True)
        self.assertFalse(session.can_close())

    def test_reuse_and_wrong_identity_are_rejected(self):
        session = self.make()
        with self.assertRaises(ValueError):
            session.handoff(nonce=8, own_id=0x803F6111, message=1)
        self.assertEqual(session.phase, SessionPhase.UNKNOWN)
        session = self.make()
        session.handoff(nonce=7, own_id=0x803F6111, message=1)
        with self.assertRaises(ValueError):
            session.handoff(nonce=7, own_id=0x803F6111, message=2)
        self.assertEqual(session.phase, SessionPhase.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
