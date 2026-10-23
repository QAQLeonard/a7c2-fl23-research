"""Standalone archive smoke test; no USB access or external application calls."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('collector_bundle', ROOT/'dev/release/build_cr_reference.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class StandaloneBundle(unittest.TestCase):
    def test_extracted_package_runs_without_repo_imports_and_contains_no_body_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            output = folder/'collector.zip'
            names = builder.build(output)
            self.assertIn('vendor/pmca/usb/sony.py', names)
            self.assertFalse(any(name.endswith(('.bin', '.so', '.ARW', '.HIF', '.dcp')) for name in names))
            extracted = folder/'unpacked'
            with zipfile.ZipFile(output) as archive:
                archive.extractall(extracted)
            environment = dict(os.environ, PYTHONPATH='')
            script = str(extracted/'collect_cr_reference.py')
            command = [sys.executable, script, 'init', 'data', '--firmware', '2.01']
            result = subprocess.run(command, cwd=extracted, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            result = subprocess.run([sys.executable, script, 'check', 'data'], cwd=extracted,
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout+result.stderr)
            self.assertIn('INCOMPLETE', result.stdout)
            for language in ('en', 'zh-CN'):
                readme = (extracted/('README.'+language+'.md')).read_text(encoding='utf-8')
                self.assertNotIn('(../', readme)
                self.assertIn('CP', readme)


if __name__ == '__main__':
    unittest.main()
