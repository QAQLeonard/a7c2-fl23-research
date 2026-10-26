"""Operator sequence using fake service sessions; no physical camera."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from experiment import run_trial
from test_device_driver import FakeSession, elf
from staging_model import ReviewRequired


class TrialFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'trial'
        self.session = FakeSession('arm-ready')
        self.session.identity = {'model': 'ILCE-7CM2', 'body': 'synthetic-body'}
        self.open = False
        self.expected = []
        self.prompts = 0

    @contextmanager
    def factory(self, *, expected):
        self.expected.append(expected)
        self.assertFalse(self.open)
        self.open = True
        try: yield self.session
        finally: self.open = False

    def prompt(self, _):
        self.assertFalse(self.open)
        self.prompts += 1
        self.session.fault = None

    def run_trial(self, **kwargs):
        return run_trial(elf(4096), elf(180001), self.root, self.factory,
                         prompt=self.prompt, emit=lambda _: None, pause=lambda _: None,
                         poll_limit=3, **kwargs)

    def test_ready_exit_manual_shots_reconnect_same_body_verify_then_disable(self):
        report = self.run_trial()
        self.assertEqual(self.prompts, 1)
        self.assertEqual(self.expected, [None, self.session.identity])
        self.assertTrue(report['photo_complete'])
        self.assertEqual(report['result_path'], 'A:/DCIM/101A7AVG/A7AV0001.JPG')
        self.assertFalse(self.session.active)
        self.assertTrue(self.session.healthy)
        self.assertFalse(self.open)

    def test_no_ready_state_means_no_shot_prompt_and_no_replay(self):
        self.session.fault = 'busy'
        with self.assertRaises(ReviewRequired): self.run_trial()
        self.assertEqual(self.prompts, 0)
        self.assertEqual(len(self.expected), 1)
        self.assertFalse(self.session.healthy)
        self.assertTrue(self.session.mutating)
        self.assertTrue(list(self.root.glob('*.receipt.private.bin')))

    def test_failed_result_query_never_sends_disable_or_new_arm(self):
        prompt = self.prompt
        def fail(_):
            prompt(_); self.session.fault = 'timeout'
        with patch.object(self, 'prompt', side_effect=fail):
            with self.assertRaises(TimeoutError): self.run_trial()
        self.assertEqual(self.session.operation, 1)
        self.assertFalse(self.session.healthy)
        self.assertTrue(self.session.mutating)
        self.assertIn('libJit.so', self.session.files)

    def test_wrong_reconnected_body_stops_before_any_further_command(self):
        calls = []
        prompt = self.prompt
        def wrong(_):
            prompt(_); calls.extend(self.session.calls)
            self.session.identity = {'model': 'ILCE-7CM2', 'body': 'another-synthetic-body'}
        with patch.object(self, 'prompt', side_effect=wrong):
            with self.assertRaisesRegex(ReviewRequired, 'differs'): self.run_trial()
        self.assertEqual(self.session.calls, calls)
        self.assertFalse(self.session.healthy)

    def test_session_factory_construction_does_not_open_usb(self):
        from experiment import camera_session
        import usb.core
        with patch.object(usb.core, 'find', side_effect=AssertionError('No USB enumeration')):
            session = camera_session(expected=None)
        self.assertTrue(session.healthy)
        self.assertFalse(hasattr(session, 'camera'))
