"""Retained history must not bypass privacy, links or bilingual inventory."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'check_publication.py'
spec=importlib.util.spec_from_file_location('publication_check',SCRIPT)
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.history='src/fl23/README.zh-TW.md'
        self.policy={'schema':'a7c2-publication-layout/1','guide_pair_count':1,
                     'retained_markdown':{self.history:'Historical instructions'},
                     'historical_language_files':[self.history]}
        self.write('dev/release/documentation-layout.json',json.dumps(self.policy))
        for name in ['README.md','README.zh-CN.md','AGENTS.md','src/looks/AGENTS.md',
                     'docs/en/development.md','docs/zh-CN/development.md',self.history]:
            self.write(name,'# Documentation\n')
        self.write('lut.py','# offline entry\n');self.write('FL23.cmd','@echo off\n')
        self.write('docs/profiles/manifest.json',json.dumps({'profiles':[{}]*18}))

    def write(self,name,text):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(text,encoding='utf-8')

    def run_check(self):
        with patch.object(checker,'ROOT',self.root),redirect_stdout(io.StringIO()) as output:
            checker.main()
        return json.loads(output.getvalue())

    def test_exact_inventoried_history_is_accepted(self):
        report=self.run_check()
        self.assertEqual(report['bilingual_guide_pairs'],1)
        self.assertFalse(report['camera_io'])

    def test_unlisted_history_is_rejected(self):
        self.write('src/fl23/unreviewed.zh-TW.md','# Unreviewed\n')
        with self.assertRaisesRegex(ValueError,'Unlisted Markdown'):self.run_check()

    def test_missing_inventoried_file_is_rejected(self):
        (self.root/self.history).unlink()
        with self.assertRaisesRegex(ValueError,'Missing inventoried'):self.run_check()

    def test_missing_translation_is_rejected(self):
        (self.root/'docs/zh-CN/development.md').unlink()
        with self.assertRaisesRegex(ValueError,'matching English'):self.run_check()

    def test_retained_history_still_receives_privacy_scan(self):
        self.write(self.history,'# History\n'+'C:'+ '/Users/'+'example/private-location\n')
        with self.assertRaisesRegex(ValueError,'Private marker'):self.run_check()

    def test_retained_history_still_receives_link_check(self):
        self.write(self.history,'# History\n[Missing](not-present.md)\n')
        with self.assertRaisesRegex(ValueError,'Missing link'):self.run_check()


if __name__=='__main__':unittest.main()
