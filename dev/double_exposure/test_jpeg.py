"""Exercise the native file processor, using synthetic JPEGs only.

Set A7C2_JPEG_COMMAND to a JSON argv list: either the host executable, or a
runner plus the actual static ARM64 executable. No shell or camera access.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('A7C2_JPEG_COMMAND'),
                     'Set A7C2_JPEG_COMMAND to the built JPEG processor argv')
class JpegMean(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.Image = Image
        self.temp = tempfile.TemporaryDirectory(prefix='a7c2-jpeg-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.command = json.loads(os.environ['A7C2_JPEG_COMMAND'])
        if not isinstance(self.command, list) or not all(isinstance(x, str) for x in self.command):
            self.fail('A7C2_JPEG_COMMAND must be a JSON argv list')
        self.left, self.right, self.output = [self.root / n for n in ('left.jpg', 'right.jpg', 'mean.jpg')]

    def image(self, path, color, *, size=(37, 29), orientation=1, **kwargs):
        image = self.Image.new('RGB', size, color)
        exif = self.Image.Exif()
        exif[274] = orientation
        exif[270] = 'Source description must not become result metadata'
        image.save(path, quality=100, subsampling=0, exif=exif, **kwargs)

    def invoke(self, expected=0, *, output=None):
        inputs = [self.left.read_bytes(), self.right.read_bytes()]
        result = subprocess.run(self.command + [str(self.left), str(self.right), str(output or self.output)],
                                capture_output=True, timeout=120)
        self.assertEqual([self.left.read_bytes(), self.right.read_bytes()], inputs)
        if expected == 0:
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            status = json.loads(result.stdout)
            self.assertEqual(status['status'], 'saved')
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr)
        self.assertEqual(list(self.root.glob('*.part')), [])
        return result

    def test_two_uniform_images_and_new_metadata(self):
        self.image(self.left, (20, 40, 60))
        self.image(self.right, (220, 180, 120))
        self.invoke()
        with self.Image.open(self.output) as result:
            self.assertEqual(result.size, (37, 29))
            self.assertEqual(result.format, 'JPEG')
            data = result.tobytes()
            for offset in range(0, len(data), 3):
                pixel = data[offset:offset + 3]
                self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(pixel, (120, 110, 90))))
            exif = result.getexif()
            self.assertEqual(exif[274], 1)
            self.assertNotIn(270, exif)
            self.assertEqual(exif.get_ifd(0x8769)[0xa001], 1)

    def test_black_white_mean_is_128(self):
        self.image(self.left, 'black', size=(1, 1))
        self.image(self.right, 'white', size=(1, 1))
        self.invoke()
        with self.Image.open(self.output) as image:
            self.assertTrue(all(abs(v - 128) <= 1 for v in image.getpixel((0, 0))))

    def test_full_resolution_baseline_pair(self):
        size = (7008, 4672)
        self.image(self.left, (20, 40, 60), size=size)
        self.image(self.right, (220, 180, 120), size=size)
        self.invoke()
        with self.Image.open(self.output) as image:
            self.assertEqual(image.size, size)
            for point in ((0, 0), (3504, 2336), (7007, 4671)):
                self.assertTrue(all(abs(x - y) <= 3
                                    for x, y in zip(image.getpixel(point), (120, 110, 90))))

    def test_spatial_mean_matches_independent_decoding(self):
        for index, path in enumerate((self.left, self.right)):
            image = self.Image.new('RGB', (193, 79))
            image.putdata([((x + index * 40) % 256, (y * 2 + index * 50) % 256,
                            (x + y + index * 30) % 256)
                           for y in range(79) for x in range(193)])
            image.save(path, quality=100, subsampling=0)
        with self.Image.open(self.left) as a, self.Image.open(self.right) as b:
            expected = bytes((x + y + 1) // 2 for x, y in zip(a.tobytes(), b.tobytes()))
        # Compare with an independent complete JPEG round trip. Quality-95
        # quantization can move sharp transitions by more than 16 levels;
        # comparing the saved file directly to uncompressed RGB conflates
        # codec loss with an incorrect mean or scanline mapping.
        reference = self.root / 'reference.jpg'
        self.Image.frombytes('RGB', (193, 79), expected).save(reference, quality=95, subsampling=0)
        self.invoke()
        with self.Image.open(self.output) as image, self.Image.open(reference) as ref:
            errors = [abs(x - y) for x, y in zip(ref.tobytes(), image.tobytes())]
        self.assertLess(sum(errors) / len(errors), 0.2)
        self.assertLessEqual(max(errors), 3)

    def test_matching_rotated_images_retain_orientation(self):
        for orientation in (2, 3, 6, 8):
            with self.subTest(orientation=orientation):
                self.image(self.left, 'red', orientation=orientation)
                self.image(self.right, 'blue', orientation=orientation)
                self.output.unlink(missing_ok=True)
                self.invoke()
                with self.Image.open(self.output) as result:
                    self.assertEqual(result.getexif()[274], orientation)

    def test_dimension_and_orientation_mismatch_rejected(self):
        self.image(self.left, 'red')
        for size, orientation in (((38, 29), 1), ((37, 29), 6)):
            with self.subTest(size=size, orientation=orientation):
                self.image(self.right, 'blue', size=size, orientation=orientation)
                self.invoke(1)
                self.assertFalse(self.output.exists())

    def test_existing_output_and_inputs_never_replaced(self):
        self.image(self.left, 'red')
        self.image(self.right, 'blue')
        self.output.write_bytes(b'existing result')
        self.invoke(1)
        self.assertEqual(self.output.read_bytes(), b'existing result')
        self.invoke(1, output=self.left)
        self.invoke(1, output=self.right)
        self.output.unlink()
        os.link(self.left, self.output)
        self.invoke(1)
        self.assertEqual(self.output.read_bytes(), self.left.read_bytes())

    def test_truncated_jpeg_does_not_publish_or_keep_staging(self):
        self.image(self.left, 'red', size=(640, 480))
        self.image(self.right, 'blue', size=(640, 480))
        original = self.right.read_bytes()
        for remove in (2, 50, len(original) // 2):
            with self.subTest(remove=remove):
                self.right.write_bytes(original[:-remove])
                self.invoke(1)
                self.assertFalse(self.output.exists())

    def test_progressive_cmyk_and_icc_rejected(self):
        self.image(self.left, 'red')
        for kind in ('progressive', 'CMYK', 'ICC'):
            with self.subTest(kind=kind):
                if kind == 'CMYK':
                    self.Image.new('CMYK', (37, 29)).save(self.right)
                else:
                    self.image(self.right, 'blue', **({'progressive': True} if kind == 'progressive'
                                                     else {'icc_profile': b'test profile'}))
                self.invoke(1)
                self.assertFalse(self.output.exists())

    def test_adobe_rgb_exif_rejected(self):
        self.image(self.left, 'red')
        exif = self.Image.Exif()
        exif[0x8769] = {0xa001: 0xffff}
        self.Image.new('RGB', (37, 29), 'blue').save(self.right, exif=exif)
        self.invoke(1)
        self.assertFalse(self.output.exists())

    def test_multiscan_header_rejected_before_decode(self):
        self.image(self.left, 'red')
        self.image(self.right, 'blue')
        data = self.right.read_bytes()
        sos = data.index(b'\xff\xda')
        old_length = struct.unpack('>H', data[sos + 2:sos + 4])[0]
        # A valid non-interleaved scan header. Its entropy body is deliberately
        # not rebuilt: the processor must reject this header before decoding
        # or requesting frame-sized coefficient storage.
        scan = b'\xff\xda\0\x08\x01' + data[sos + 5:sos + 7] + b'\0\x3f\0'
        self.right.write_bytes(data[:sos] + scan + data[sos + 2 + old_length:])
        result = self.invoke(1)
        self.assertIn(b'interleaved baseline', result.stderr)
        self.assertFalse(self.output.exists())

    def test_exif_directory_out_of_range_rejected(self):
        self.image(self.left, 'red')
        self.image(self.right, 'blue')
        data = self.right.read_bytes()
        exif = b'Exif\0\0II*\0' + struct.pack('<I', 0xfffffff0)
        self.right.write_bytes(data[:2] + b'\xff\xe1' + struct.pack('>H', len(exif) + 2) + exif + data[2:])
        self.invoke(1)
        self.assertFalse(self.output.exists())

    def test_competing_publish_has_one_winner(self):
        self.image(self.left, 'red', size=(640, 480))
        self.image(self.right, 'blue', size=(640, 480))
        command = self.command + [str(self.left), str(self.right), str(self.output)]
        before = [hashlib.sha256(p.read_bytes()).digest() for p in (self.left, self.right)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(subprocess.run, command, capture_output=True, timeout=120)
                     for _ in range(2)]
            results = [task.result() for task in tasks]
        self.assertEqual(sorted(result.returncode for result in results), [0, 1])
        self.assertEqual([hashlib.sha256(p.read_bytes()).digest() for p in (self.left, self.right)], before)
        self.assertEqual(list(self.root.glob('*.part')), [])
        with self.Image.open(self.output) as image:
            image.load()


if __name__ == '__main__':
    unittest.main()
