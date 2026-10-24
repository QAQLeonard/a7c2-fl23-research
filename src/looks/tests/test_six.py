"""Synthetic full7 guards, checksum ownership and exact reversibility."""
import contextlib,io,json,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from looktool import six,firmware,project
from looktool.__main__ import main

class SixTests(unittest.TestCase):
    def setUp(self):
        self.ap=b'synthetic AP fixture, not camera firmware'
        self.cp=bytearray(0xb27590)
        from looktool import uploadgate
        self.cp[uploadgate.OFFSET:uploadgate.OFFSET+20]=uploadgate.NATIVE+bytes.fromhex('c0f27910007d400611d4d8f8080024e0')
        self.tables=[bytes([i])*1215 for i in range(6)]
        payload=six.prefix(self.tables);self.cp[six.TABLE_FILE:six.TABLE_FILE+len(payload)]=payload;self.cp=bytes(self.cp)
    def source(self):
        stack=contextlib.ExitStack();stack.enter_context(patch.object(six,'AP_SHA',firmware.sha(self.ap)));stack.enter_context(patch.object(six,'CP_SHA',firmware.sha(six.uploadgate.legacy_hash_source(self.cp))));return stack
    def test_prefix_roundtrip_and_corrupt_each_slot(self):
        self.assertEqual(six.read_tables(self.cp),self.tables)
        for i in range(6):
            bad=bytearray(self.cp);bad[six.TABLE_FILE+32+i*1215]^=1
            with self.assertRaisesRegex(ValueError,'checksum'):six.read_tables(bytes(bad))
    def test_prefix_checks_header_size_and_signed_range(self):
        with self.assertRaises(ValueError):six.prefix(self.tables[:5])
        with self.assertRaises(ValueError):six.prefix([bytes([127])*1215]*6)
        with self.assertRaises(ValueError):six.read_tables(bytes(10))
        bad=bytearray(self.cp);bad[six.TABLE_FILE+4]^=1
        with self.assertRaises(ValueError):six.read_tables(bytes(bad))
    def test_unknown_source_and_slots_rejected(self):
        with self.assertRaisesRegex(ValueError,'exact documented'):six.replace_tables(self.ap,self.cp,{1:bytes(1215)})
        for replacements in [{},{True:bytes(1215)},{0:bytes(1215)},{7:bytes(1215)}]:
            with self.assertRaises(ValueError):six.replace_tables(self.ap,self.cp,replacements)
    def test_selected_payload_and_checksum_only_preserve_unselected(self):
        replacements={2:bytes([63])*1215,6:bytes([192])*1215}
        with self.source():f,r,after=six.replace_tables(self.ap,self.cp,replacements)
        self.assertEqual(f['files']['appFw.so']['windows'],[])
        tables=six.read_tables(after['cpapp-b.bin'])
        for i in range(6):self.assertEqual(tables[i],replacements.get(i+1,self.tables[i]))
        changed={i for i,(a,b) in enumerate(zip(self.cp,after['cpapp-b.bin'])) if a!=b}
        allowed=set()
        for slot in replacements:
            allowed.update(range(six.TABLE_FILE+8+(slot-1)*4,six.TABLE_FILE+12+(slot-1)*4))
            allowed.update(range(six.TABLE_FILE+32+(slot-1)*1215,six.TABLE_FILE+32+slot*1215))
        self.assertTrue(changed<=allowed)
        self.assertEqual(firmware.apply(firmware.apply({'appFw.so':self.ap,'cpapp-b.bin':self.cp},f),r),{'appFw.so':self.ap,'cpapp-b.bin':self.cp})
    def test_cli_prepares_slot6_and_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);candidate=root/'candidate';candidate.mkdir()
            data={'schema':'a7c2-look-project/1','model':'ILCE-7CM2','firmware':'2.01','slots':[{'slot':6,'name':'Example','base':'ST','source':{'type':'dcp','path':'private.dcp','attribution':'synthetic'}}]}
            plan=project.slot_plan(data);raw=bytes([1])*1215
            report={'schema':'a7c2-look-candidate/1','slot_plan':plan,'looks':[{'slot':6,'required_base':'ST','raw_sha256':firmware.sha(raw),'fit':{'convergence':{'converged':True}}}]}
            (candidate/'candidate.json').write_text(json.dumps(report));(candidate/'slot6.raw-s8.bin').write_bytes(raw)
            (root/'ap').write_bytes(self.ap);(root/'cp').write_bytes(self.cp);(root/'bindings.json').write_text('{"6":"ST"}')
            args=['prepare-transition',str(candidate),str(root/'ap'),str(root/'cp'),str(root/'bindings.json'),str(root/'out'),'--layout','full7-v4']
            with self.source(),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),0);first=(root/'out/forward.private.json').read_bytes();self.assertEqual(main(args),2)
            self.assertEqual(first,(root/'out/forward.private.json').read_bytes())
    def test_retired_bootstrap_and_unknown_preview_source_rejected(self):
        from looktool.bootstrap6 import build
        with self.assertRaisesRegex(ValueError,'Retired'):build(b'',b'',[],b'')
        with self.assertRaises(ValueError):six.prepare_preview_retry(self.ap,self.cp)

if __name__=='__main__':unittest.main()
