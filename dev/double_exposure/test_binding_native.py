"""Actual ARM64 dlopen lifecycle with test-only SDK shared libraries."""
import json
import os
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('A7C2_BINDING_COMMAND'), 'Set A7C2_BINDING_COMMAND to the loader harness argv')
class NativeBinding(unittest.TestCase):
    def run_mode(self, mode):
        command = json.loads(os.environ['A7C2_BINDING_COMMAND'])
        result = subprocess.run(command + [mode], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        report = json.loads(result.stdout)
        self.assertEqual(report['backend'], 'synthetic-sdk-libraries')
        return report

    def test_missing_sdk_is_not_loaded(self):
        self.assertTrue(self.run_mode('missing')['missing_not_loaded'])

    def test_partial_sdk_binding_preserves_original_reference(self):
        self.assertTrue(self.run_mode('partial')['partial_balanced'])

    def test_job_and_callback_refs_retain_then_unload_real_shared_module(self):
        report = self.run_mode('lifetime')
        self.assertTrue(all(report[key] for key in
                            ('self_pin', 'leases_guarded', 'sdk_refs_preserved', 'core_unloaded')))

    def test_old_lease_cannot_release_restarted_runtime(self):
        self.assertTrue(self.run_mode('repeat')['core_unloaded'])


if __name__ == '__main__':
    unittest.main()
