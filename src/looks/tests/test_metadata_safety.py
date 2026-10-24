"""ExifTool argument-file safety, using synthetic metadata and no camera access."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from looktool import rawprofiles as raw


class MetadataSafetyTests(unittest.TestCase):
    def test_rejects_entire_batch_before_starting_exiftool(self):
        for control in ('\n', '\r', '\r\n', '\0'):
            with self.subTest(control=repr(control)):
                with patch.object(raw.subprocess, 'run') as run:
                    with self.assertRaises(ValueError):
                        raw.metadata(iter([Path('valid.ARW'), 'photo'+control+'-execute']), 'exiftool')
                run.assert_not_called()

    def test_serializes_relative_names_as_absolute_utf8_paths(self):
        files=[Path('-overwrite_original'), Path('#photo.ARW'), Path('照片/my photo.ARW')]
        result=subprocess.CompletedProcess([], 0, '[]', '')
        with patch.object(raw.subprocess, 'run', return_value=result) as run:
            self.assertEqual(raw.metadata(files, 'exiftool'), [])
        self.assertEqual(run.call_args.kwargs['input'],
                         ''.join(str(path.absolute())+'\n' for path in files))
        self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')
        self.assertEqual(run.call_args.args[0][-2:], ['-@', '-'])

    def test_rejects_control_characters_in_absolute_path(self):
        with patch.object(os, 'getcwd', return_value=str(Path.cwd()/'unsafe\ncwd')):
            with patch.object(raw.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    raw.metadata(['photo.ARW'], 'exiftool')
            run.assert_not_called()

    def test_empty_batch_does_not_start_exiftool(self):
        with patch.object(raw.subprocess, 'run') as run:
            self.assertEqual(raw.metadata(iter([]), 'exiftool'), [])
        run.assert_not_called()


@unittest.skipUnless(shutil.which('exiftool'), 'ExifTool is not installed')
class ExifToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.exiftool=shutil.which('exiftool')
        self.xmp=(b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
                  b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                  b'<rdf:Description rdf:about="" xmlns:tiff="http://ns.adobe.com/tiff/1.0/" '
                  b'tiff:Model="ILCE-7CM2"/></rdf:RDF></x:xmpmeta>')

    @unittest.skipIf(os.name=='nt', 'Windows disallows newline filenames')
    def test_injected_write_options_cannot_modify_another_input(self):
        target=self.root/'target.xmp'
        target.write_bytes(self.xmp)
        injected=self.root/'photo\n-overwrite_original\n-XMP-dc:Title=injected\n-execute\n.xmp'
        injected.write_bytes(self.xmp)
        before={path.name:path.read_bytes() for path in self.root.iterdir()}
        with self.assertRaises(ValueError):
            raw.metadata([target, injected], self.exiftool)
        self.assertEqual({path.name:path.read_bytes() for path in self.root.iterdir()}, before)

    def test_reads_unicode_spaces_and_option_like_names_without_writes(self):
        names=['照片 sample.xmp', '-overwrite_original.xmp', '#comment.xmp']
        for name in names:
            (self.root/name).write_bytes(self.xmp)
        # Exercise relative paths without changing the test process's directory.
        with patch.object(os, 'getcwd', return_value=str(self.root)):
            files=[Path(name) for name in names]
            rows=raw.metadata(files, self.exiftool)
        self.assertEqual(len(rows), len(files))
        self.assertEqual({Path(row['SourceFile']).name for row in rows}, set(names))
        self.assertTrue(all(row['Model']=='ILCE-7CM2' for row in rows))
        self.assertEqual({path.name:path.read_bytes() for path in self.root.iterdir()},
                         {name:self.xmp for name in names})


if __name__=='__main__':
    unittest.main()
