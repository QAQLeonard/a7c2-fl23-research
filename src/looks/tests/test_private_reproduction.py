"""Optional real-file reproduction. Local fixtures stay outside the repository."""
import json,os,unittest
from pathlib import Path
from looktool import six,firmware

FIXTURES=os.environ.get('A7C2_RESEARCH_FIXTURES')

@unittest.skipUnless(FIXTURES,'Set A7C2_RESEARCH_FIXTURES to a private fixture-index JSON')
class PrivateReproductionTests(unittest.TestCase):
    def setUp(self):
        self.index=Path(FIXTURES);self.paths=json.loads(self.index.read_text());self.base=self.index.parent
    def read(self,key):return (self.base/self.paths[key]).read_bytes()
    def test_public_six_builder_reproduces_current_complete_files(self):
        from looktool.sixbuild import build
        tables=[(self.base/path).read_bytes() for path in self.paths['tables']]
        after,f,r,report=build(self.read('three_ap'),self.read('three_cp'),tables,self.read('native_fl23_cp'))
        self.assertEqual(firmware.sha(after['appFw.so']),six.AP_SHA)
        self.assertEqual(firmware.sha(six.uploadgate.legacy_hash_source(after['cpapp-b.bin'])),six.CP_SHA)
        self.assertEqual(after['cpapp-b.bin'],six.uploadgate.restore(self.read('v4_cp')))
        self.assertEqual(firmware.apply(firmware.apply({'appFw.so':self.read('three_ap'),'cpapp-b.bin':self.read('three_cp')},f),r),{'appFw.so':self.read('three_ap'),'cpapp-b.bin':self.read('three_cp')})
    def test_public_retry_reproduces_current_complete_cp(self):
        f,r,after=six.prepare_preview_retry(self.read('six_ap'),self.read('switch_cp'))
        self.assertEqual(after['cpapp-b.bin'],six.uploadgate.restore(self.read('v4_cp')))
        self.assertEqual(sum(w['bytes'] for w in f['files']['cpapp-b.bin']['windows']),40)
        self.assertEqual(firmware.apply(after,r)['cpapp-b.bin'],self.read('switch_cp'))
    def test_actual_full7_replacement_preserves_programs_other_slots(self):
        ap,cp=self.read('six_ap'),self.read('v4_cp');old=six.read_tables(cp);raw=bytes([1])*1215
        f,r,after=six.replace_tables(ap,cp,{6:raw});new=six.read_tables(after['cpapp-b.bin'])
        self.assertEqual(old[:5],new[:5]);self.assertEqual(new[5],raw)
        self.assertEqual(after['appFw.so'],ap)
        self.assertEqual(firmware.apply(after,r),{'appFw.so':ap,'cpapp-b.bin':cp})

if __name__=='__main__':unittest.main()
