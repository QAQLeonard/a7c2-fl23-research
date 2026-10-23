"""Public offline CLI reporting with synthetic plans; no native or device work."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from looktool import six
from looktool.__main__ import main


def manifests(component_sizes):
    forward = {
        'schema': 'a7c2-private-transition/1',
        'status': 'OFFLINE_REVIEW_REQUIRED_NOT_AN_INSTALLER',
        'files': {
            name: {'windows': [{'offset': hex(index * 32), 'bytes': size,
                                'before_hex': bytes(size).hex(),
                                'after_hex': (bytes([1]) * size).hex()}
                               for index, size in enumerate(sizes)]}
            for name, sizes in component_sizes.items()
        },
    }
    reverse = copy.deepcopy(forward)
    for component in reverse['files'].values():
        for window in component['windows']:
            window['before_hex'], window['after_hex'] = window['after_hex'], window['before_hex']
    return forward, reverse, {}


class PreviewGateCliTests(unittest.TestCase):
    def invoke(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = main(args)
        return status, output.getvalue(), errors.getvalue()

    def inputs(self, root):
        ap, cp = root / 'ap', root / 'cp'
        ap.write_bytes(b'Synthetic AP input')
        cp.write_bytes(b'Synthetic CP input')
        return ['prepare-preview-retry', str(ap), str(cp), str(root / 'out')]

    def test_reports_actual_window_total_and_preserves_both_manifests(self):
        cases = [({'appFw.so': [13], 'cpapp-b.bin': [9, 18]}, 40),
                 ({'appFw.so': [2, 7], 'cpapp-b.bin': [5, 11]}, 25)]
        for sizes, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = self.inputs(root)
                forward, reverse, after = manifests(sizes)
                with patch.object(six, 'prepare_preview_retry', return_value=(forward, reverse, after)) as prepare:
                    status, output, errors = self.invoke(args)
                self.assertEqual(status, 0)
                self.assertEqual(errors, '')
                prepare.assert_called_once_with(b'Synthetic AP input', b'Synthetic CP input')
                self.assertEqual(json.loads(output), {
                    'status': forward['status'], 'camera_io': False,
                    'changed_bytes': expected, 'physical_validation_required': True})
                for name, expected_manifest in [('forward', forward), ('reverse', reverse)]:
                    actual = json.loads((root / 'out' / (name + '.private.json')).read_text())
                    self.assertEqual(actual, expected_manifest)

    def test_existing_output_is_rejected_without_overwriting_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.inputs(root)
            with patch.object(six, 'prepare_preview_retry', return_value=manifests(
                    {'appFw.so': [], 'cpapp-b.bin': [18, 22]})):
                self.assertEqual(self.invoke(args)[0], 0)
            original = {path.name: path.read_bytes() for path in (root / 'out').iterdir()}
            with patch.object(six, 'prepare_preview_retry', return_value=manifests(
                    {'appFw.so': [3], 'cpapp-b.bin': [7]})):
                status, output, errors = self.invoke(args)
            self.assertEqual(status, 2)
            self.assertEqual(output, '')
            self.assertIn('Use a new private transition output directory', errors)
            self.assertEqual({path.name: path.read_bytes() for path in (root / 'out').iterdir()}, original)

    def test_help_describes_native_gate_and_keeps_legacy_command(self):
        for args in (['--help'], ['prepare-preview-retry', '--help']):
            output = io.StringIO()
            with self.subTest(args=args), contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
                main(args)
            self.assertEqual(stopped.exception.code, 0)
            text = ' '.join(output.getvalue().split())
            self.assertIn('prepare-preview-retry', text)
            self.assertIn('native LUT-upload gating', text)
            self.assertNotIn('upload-retry-v4', text)

        spec = importlib.util.spec_from_file_location('preview_gate_lut_cli', Path(__file__).resolve().parents[3] / 'lut.py')
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(wrapper.main(['--help']), 0)
        text = output.getvalue()
        self.assertIn('prepare-preview-retry: Prepare native LUT-upload gating', text)
        self.assertNotIn('exact historical preview repair', text)


if __name__ == '__main__':
    unittest.main()
