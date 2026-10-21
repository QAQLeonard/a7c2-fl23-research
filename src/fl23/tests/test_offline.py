"""Synthetic, non-device tests shipped with the preview. No camera access."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from collections import namedtuple
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import app

class OfflineTests(unittest.TestCase):
    def test_asset_integrity(self):self.assertEqual(core.assets()['firmware'],'2.01')
    def blank_units(self,salt):
        a=bytearray(8192);b=bytearray(28672)
        a[0x100:0x108]=bytes([salt])*8;b[0x80:0x88]=bytes([salt])*8
        a[0x1250:0x1290]=bytes([salt])*64
        b[0x1e0:0x1e0+576]=bytes([salt])*576
        return bytes(a),bytes(b)
    def test_each_body_keeps_own_calibration(self):
        outputs=[]
        for salt in [7,19]:
            a,b=self.blank_units(salt);x,y=core.merge_colors(a,b);outputs.append((x,y))
            self.assertEqual(x[0x100:0x108],a[0x100:0x108]);self.assertEqual(y[0x80:0x88],b[0x80:0x88])
            self.assertEqual(x[0x1250:0x1290],a[0x1250:0x1290]);self.assertEqual(y[0x1e0:0x1e0+576],b[0x1e0:0x1e0+576])
            with self.assertRaises(ValueError):core.merge_colors(x,y)
        self.assertNotEqual(outputs[0][0][:0x110],outputs[1][0][:0x110])
        self.assertEqual(outputs[0][0][0x1250+23*64:0x1250+24*64],outputs[1][0][0x1250+23*64:0x1250+24*64])
    def test_occupied_slots_are_rejected(self):
        a,b=self.blank_units(4)
        occupied=bytearray(a);occupied[0x1200]=23
        with self.assertRaises(ValueError):core.merge_colors(bytes(occupied),b)
        occupied=bytearray(a);occupied[0x1250+23*64]=1
        with self.assertRaises(ValueError):core.merge_colors(bytes(occupied),b)
        with self.assertRaises(ValueError):core.merge_colors(a[:-1],b)
    def test_wrong_image_and_fixed_window_guards(self):
        with self.assertRaises(ValueError):core.patch_program(b'not firmware',0)
        original=b'abcdef';final=b'aXYdef'
        data=[{'writes':[{'file_offset':'0x1','before_hex':'6263','after_hex':'5859'}]}]
        with patch.object(core,'ORIGINAL',[core.sha(original)]),patch.object(core,'FINAL',[core.sha(final)]),patch.object(core,'read_json',return_value=data):
            self.assertEqual(core.patch_program(original,0),final)
            self.assertEqual(core.patch_program(final,0,True),original)
            data[0]['writes'].append(dict(data[0]['writes'][0]))
            with self.assertRaises(ValueError):core.patch_program(original,0)
    def test_native_frame_rejects_failure_and_foreign_model(self):
        good=struct.pack('<8sIIqqqqQIIII',b'A7PRB001',1,16,0,0,100,0,0x1000,0,0,0,0)
        self.assertEqual(core.parse_native('probe',good)['product_column'],9)
        wrong=bytearray(good);struct.pack_into('<I',wrong,12,17)
        with self.assertRaises(ValueError):core.parse_native('probe',bytes(wrong))
        wrong=bytearray(good);struct.pack_into('<q',wrong,16,-13)
        with self.assertRaises(ValueError):core.parse_native('probe',bytes(wrong))
        with self.assertRaises(ValueError):core.parse_native('installer',b'bad',1)
    def test_unrelated_values_are_not_ignored(self):
        P=namedtuple('Property','data attr resetData')
        before=[{1:P(b'old',96,None),2:P(b'keep',96,None)},{}]
        after=copy.deepcopy(before);after[0][1]=P(b'new',96,None)
        self.assertEqual(core.verify_preservation(before,after,{(0,1):b'new'})['preserved_properties'],1)
        after[0][2]=P(b'changed',96,None)
        with self.assertRaises(ValueError):core.verify_preservation(before,after,{(0,1):b'new'})
    def test_preexisting_temp_is_not_overwritten(self):
        class S:
            def read(self,path,missing=False):return b'foreign' if path.endswith('a7c2.install.result') else None
            def temp(self,*args,**kwargs):raise AssertionError('Must not write')
        with tempfile.TemporaryDirectory(dir=core.BASE) as folder:
            job=app.Job(folder);job.state={}
            with self.assertRaises(RuntimeError):job.module(S(),'installer',0)
    def test_unknown_native_result_sends_no_cleanup(self):
        class S:
            healthy=True
            def __init__(self):self.files={};self.operations=[]
            def read(self,path,missing=False):return self.files.get(path)
            def temp(self,name,data=None,remove=False):
                self.operations.append((name,remove))
                if name=='libJit.so':self.healthy=False;raise TimeoutError('Injected unknown outcome')
                self.files['/tmp/jiritsu/'+name]=data
        with tempfile.TemporaryDirectory(dir=core.BASE) as folder:
            job=app.Job(folder);job.state={};session=S()
            with self.assertRaises(TimeoutError):job.module(session,'installer',0)
            self.assertFalse(any(remove for _,remove in session.operations))

    def test_malformed_native_report_is_preserved_without_cleanup(self):
        class S:
            healthy=True
            def __init__(self):self.files={};self.operations=[]
            def read(self,path,missing=False):return self.files.get(path)
            def temp(self,name,data=None,remove=False):
                self.operations.append((name,remove))
                if remove:self.files.pop('/tmp/jiritsu/'+name,None)
                else:self.files['/tmp/jiritsu/'+name]=data
                if name=='libJit.so':self.files['/tmp/jiritsu/a7c2.install.result']=b'truncated'
        with tempfile.TemporaryDirectory() as folder:
            job=app.Job(folder);session=S()
            with self.assertRaises(ValueError):job.module(session,'installer',1)
            self.assertFalse(session.healthy)
            self.assertFalse(any(remove for _,remove in session.operations))
            self.assertEqual(sum(n=='libJit.so' for n,_ in session.operations),1)
            self.assertIn('/tmp/jiritsu/a7c2.install.result',session.files)

if __name__=='__main__':unittest.main()
