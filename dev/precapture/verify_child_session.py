"""No USB: reproduce premature source-read bug and enforce terminal gating."""
import copy
import hashlib
import unittest
from support.child_session import verify_sources_after_terminal


class ChildSessionTests(unittest.TestCase):
    def setUp(self):
        self.files = {'/ap': b'ap fixture', '/cp': b'cp fixture'}
        self.sources = {name: (path, hashlib.sha256(raw).hexdigest())
                        for name, (path, raw) in zip(('AP', 'CP'), self.files.items())}
        self.reads = []
        self.terminal = dict(state='ABSENT', terminal=True, success=True, cleanup_allowed=True,
                             journal=dict(has_final_record=True, success_record=True, cleanup_allowed=False))

    def read(self, path):
        self.reads.append(path)
        return self.files[path]

    def test_unknown_first_observation_makes_no_source_read(self):
        self.assertFalse(verify_sources_after_terminal(
            dict(state='UNKNOWN', terminal=False, success=False, cleanup_allowed=False), self.sources, self.read))
        self.assertEqual(self.reads, [])

    def test_running_with_success_looking_file_makes_no_source_read(self):
        observed = dict(self.terminal, state='RUNNING', terminal=False, success=False, cleanup_allowed=False)
        self.assertFalse(verify_sources_after_terminal(observed, self.sources, self.read))
        self.assertEqual(self.reads, [])

    def test_each_incomplete_terminal_proof_blocks_source_io(self):
        for key, value in [('state', 'UNKNOWN'), ('terminal', False), ('success', False),
                           ('cleanup_allowed', False), ('terminal', 1), ('success', 'true')]:
            with self.subTest(key=key, value=value):
                self.assertFalse(verify_sources_after_terminal(dict(self.terminal, **{key: value}), self.sources, self.read))
        self.assertEqual(self.reads, [])

    def test_missing_or_unfinished_journal_blocks_source_io(self):
        for journal in (None, {}, {'has_final_record': False, 'success_record': True},
                        {'has_final_record': True, 'success_record': False}):
            with self.subTest(journal=journal):
                self.assertFalse(verify_sources_after_terminal(dict(self.terminal, journal=journal), self.sources, self.read))
        self.assertEqual(self.reads, [])

    def test_terminal_absence_allows_one_read_per_pinned_source(self):
        self.assertTrue(verify_sources_after_terminal(self.terminal, self.sources, self.read))
        self.assertEqual(self.reads, ['/ap', '/cp'])

    def test_qualified_zombie_is_terminal_without_reap(self):
        self.assertTrue(verify_sources_after_terminal(dict(self.terminal, state='ZOMBIE'), self.sources, self.read))
        self.assertEqual(self.reads, ['/ap', '/cp'])

    def test_source_drift_stops_before_next_file(self):
        self.files['/ap'] += b'changed'
        with self.assertRaisesRegex(ValueError, 'AP'):
            verify_sources_after_terminal(self.terminal, self.sources, self.read)
        self.assertEqual(self.reads, ['/ap'])

    def test_unknown_read_is_not_retried(self):
        def timeout(path):
            self.reads.append(path)
            raise TimeoutError('Unknown USB response')
        with self.assertRaises(TimeoutError):
            verify_sources_after_terminal(self.terminal, self.sources, timeout)
        self.assertEqual(self.reads, ['/ap'])

    def test_all_bindings_validated_before_first_read(self):
        for sources in ({}, {'AP': ('relative', '0' * 64)}, {'AP': ('/ap', 'bad')},
                        dict(self.sources, CP=('/cp', 'X' * 64))):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                verify_sources_after_terminal(self.terminal, sources, self.read)
        self.assertEqual(self.reads, [])

    def test_input_observation_is_not_mutated_into_permission(self):
        original = copy.deepcopy(self.terminal)
        verify_sources_after_terminal(self.terminal, self.sources, self.read)
        self.assertEqual(self.terminal, original)
        self.assertFalse(self.terminal['journal']['cleanup_allowed'])

    def refusal(self):
        observed = copy.deepcopy(self.terminal)
        observed.update(success=False, resolved_refusal=True, request_sent=False)
        observed['journal'].update(success_record=False, resolved_refusal_record=True, request_sent=False)
        return observed

    def test_resolved_never_sent_refusal_verifies_sources_without_claiming_success(self):
        observed = self.refusal()
        before = copy.deepcopy(observed)
        self.assertTrue(verify_sources_after_terminal(observed, self.sources, self.read))
        self.assertEqual(self.reads, ['/ap', '/cp'])
        self.assertEqual(observed, before)
        self.assertFalse(observed['success'])

    def test_refusal_file_with_live_or_unknown_process_performs_no_read(self):
        for state in ('RUNNING', 'UNKNOWN'):
            observed = dict(self.refusal(), state=state, terminal=False, cleanup_allowed=False)
            self.assertFalse(verify_sources_after_terminal(observed, self.sources, self.read))
        self.assertEqual(self.reads, [])

    def test_refusal_requires_independent_matching_no_send_evidence(self):
        for layer in ('observation', 'journal'):
            for key, value in (('request_sent', None), ('request_sent', True), ('request_sent', 0),
                               ('success' if layer == 'observation' else 'success_record', True),
                               ('resolved_refusal' if layer == 'observation' else 'resolved_refusal_record', 1)):
                with self.subTest(layer=layer, key=key, value=value):
                    observed = self.refusal()
                    (observed if layer == 'observation' else observed['journal'])[key] = value
                    self.assertFalse(verify_sources_after_terminal(observed, self.sources, self.read))
        self.assertEqual(self.reads, [])

    def test_conflicting_success_and_refusal_performs_no_read(self):
        for layer, key in (('observation', 'resolved_refusal'), ('journal', 'resolved_refusal_record')):
            observed = copy.deepcopy(self.terminal)
            (observed if layer == 'observation' else observed['journal'])[key] = True
            self.assertFalse(verify_sources_after_terminal(observed, self.sources, self.read))
        self.assertEqual(self.reads, [])


if __name__ == '__main__':
    unittest.main()
