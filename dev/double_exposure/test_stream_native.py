"""Execute the ARM64 shared stream library through its synthetic SDK harness."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

NATIVE_ERROR = -2147483632


@unittest.skipUnless(os.environ.get('A7C2_STREAM_COMMAND'), 'Set A7C2_STREAM_COMMAND to the native harness argv')
class NativeStream(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.Image = Image
        self.temp = tempfile.TemporaryDirectory(prefix='a7c2-stream-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / 'a.jpg', self.root / 'b.jpg'
        Image.new('RGB', (37, 29), (20, 40, 60)).save(self.a, quality=100, subsampling=0)
        Image.new('RGB', (37, 29), (220, 180, 120)).save(self.b, quality=100, subsampling=0)
        self.command = json.loads(os.environ['A7C2_STREAM_COMMAND'])

    def invoke(self, mode):
        output = self.root / (mode + '.jpg')
        before = self.a.read_bytes(), self.b.read_bytes()
        result = subprocess.run(self.command + [str(self.a), str(self.b), str(output), mode],
                                capture_output=True, timeout=120)
        self.assertEqual((self.a.read_bytes(), self.b.read_bytes()), before)
        self.assertTrue(result.stdout, result.stderr.decode(errors='replace'))
        report = json.loads(result.stdout)
        self.assertEqual(report['backend'], 'synthetic-mpr')
        self.assertEqual(report['foreign_codec_calls'], 0)
        self.assertEqual(result.returncode, 0 if report['status'] == 0 else 1)
        self.assertEqual(output.exists(), report['status'] == 0)
        return report, output

    def test_native_shared_core_with_short_sdk_reads_and_writes(self):
        normal, normal_file = self.invoke('normal')
        short, short_file = self.invoke('short')
        self.assertEqual(normal['status'], 0)
        self.assertEqual(short['status'], 0)
        self.assertEqual(normal_file.read_bytes(), short_file.read_bytes())
        self.assertGreater(short['reads'], normal['reads'])
        self.assertGreater(short['writes'], normal['writes'])
        self.assertEqual((short['closes'], short['flushes']), (3, 1))
        with self.Image.open(short_file) as image:
            self.assertTrue(all(abs(x - y) <= 3 for x, y in zip(image.getpixel((0, 0)), (120, 110, 90))))

    def test_native_read_error_is_not_retried_or_published(self):
        report, _ = self.invoke('read-error')
        self.assertEqual((report['status'], report['io_error']), (-2, NATIVE_ERROR))
        self.assertEqual((report['reads'], report['writes'], report['flushes']), (1, 0, 0))

    def test_native_partial_write_error_preserves_known_prefix_count(self):
        report, _ = self.invoke('write-error')
        self.assertEqual((report['status'], report['io_error']), (-2, NATIVE_ERROR))
        self.assertEqual((report['writes'], report['bytes'], report['flushes']), (2, 11, 0))

    def test_native_zero_write_and_cancel_stop_before_publication(self):
        report, _ = self.invoke('zero-write')
        self.assertEqual((report['status'], report['writes']), (-2, 1))
        report, _ = self.invoke('cancel')
        self.assertEqual(report['status'], -4)
        self.assertEqual(report['flushes'], 0)

    def test_native_partial_open_and_stat_error_keep_ownership_contract(self):
        report, _ = self.invoke('partial-open')
        self.assertEqual((report['status'], report['input0_phase'], report['closes']),
                         (NATIVE_ERROR, 5, 0))
        report, _ = self.invoke('stat-error')
        self.assertEqual((report['status'], report['reads'], report['closes']), (NATIVE_ERROR, 0, 1))

    def test_native_flush_and_close_failures_are_not_success(self):
        report, _ = self.invoke('flush-error')
        self.assertEqual(report['status'], NATIVE_ERROR)
        self.assertEqual((report['codec'], report['flushes']), (0, 1))
        report, _ = self.invoke('close-error')
        self.assertEqual((report['status'], report['input0_phase'], report['closes']),
                         (NATIVE_ERROR, 5, 3))


if __name__ == '__main__':
    unittest.main()
