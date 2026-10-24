"""Offline name/layout/invocation guards; no USB access or camera writes."""
import copy,json,os,struct,tempfile,unittest,importlib.util,subprocess,sys
from pathlib import Path
from looktool import device_layout,firmware,resources,six
from looktool.devicesession import invoke,Camera
from looktool import nameworker
from looktool.devicelock import DeviceLock

def resource_fixture():
    count=2866;base=(16+2*count+3)&~3
    result=bytearray(b'uxc\x07\0\0\0\0'+struct.pack('<HHI',8,5,count|(((count+1)&~1)<<12)))
    result.extend(b'\xff\xff'*count);result.extend(bytes(base-len(result)))
    for slot,rid in enumerate(resources.LABEL_IDS,1):
        at=16+2*((rid&0xffffff)-0xa000);struct.pack_into('<H',result,at,(len(result)-base)//4)
        result.extend(struct.pack('<I',0x1e000000|(rid&0xffffff))+('Original '+str(slot)).encode()+b'\0');result.extend(bytes((-len(result))%4))
    return bytes(result)

class ResourceTests(unittest.TestCase):
    def test_stock_resource_extension_and_inverse_preserve_native_records(self):
        count=2860;base=16+2*count
        raw=bytearray(b'uxc\x07\0\0\0\0'+struct.pack('<HHI',8,5,count|(count<<12))+b'\xff\xff'*count)
        struct.pack_into('<H',raw,16,0);raw.extend(struct.pack('<I',0x1e00a000)+b'Native\0\0')
        before=bytes(raw);ids=list(range(0x0200ab2c,0x0200ab32))
        after,plan=resources.rename(before,{5:'GR Positive'},ids)
        a,b=resources.decode(before),resources.decode(after)
        self.assertEqual(b['entries'][0x0200a000],a['entries'][0x0200a000])
        self.assertEqual(b['entries'][ids[4]]['text'],'GR Positive')
        self.assertEqual(resources.inverse(after,plan),before)
    def test_selected_unicode_name_and_exact_inverse_preserve_other_records(self):
        before=resource_fixture();after,plan=resources.rename(before,{2:'怀旧负片 🎞'})
        a,b=resources.decode(before),resources.decode(after)
        self.assertEqual(b['entries'][resources.LABEL_IDS[1]]['text'],'怀旧负片 🎞')
        for slot,rid in enumerate(resources.LABEL_IDS,1):
            if slot!=2:self.assertEqual(a['entries'][rid],b['entries'][rid])
        self.assertEqual(resources.inverse(after,plan),before)
    def test_invalid_names_slots_and_corrupt_indices_stop(self):
        raw=resource_fixture()
        for names in [{1:''},{1:'x'*64},{1:'a\0b'},{7:'a'}]:
            with self.assertRaises(ValueError):resources.rename(raw,names)
        bad=bytearray(raw);struct.pack_into('<H',bad,16+2*((resources.LABEL_IDS[0]&0xffffff)-0xa000),0xfffe)
        with self.assertRaises(ValueError):resources.rename(bytes(bad),{1:'New'})

@unittest.skipUnless(importlib.util.find_spec('keystone'),'Optional research assembler required')
class TemplateSourceTests(unittest.TestCase):
    def test_every_bundled_mask_matches_its_assembler_source(self):
        from looktool.standalone import assemble
        asset=device_layout.runtime()
        for mask in range(64):
            code,branch,mapping=assemble(mask)
            self.assertEqual(code.hex(),asset['ap_templates'][mask])
            self.assertEqual(branch.hex(),asset['title_branch'])
            self.assertEqual(mapping.hex(),asset['map'])

class NativeInvocationTests(unittest.TestCase):
    class Camera:
        def __init__(self):self.files={};self.writes=[];self.healthy=True;self.result=b'valid report'
        def temp_read(self,name,missing=False):return self.files.get(name)
        def temp_write(self,name,data):
            self.writes.append(name);self.files[name]=data
            if name=='libJit.so':self.files.pop(name);self.files['a7c2.install.result']=self.result
        def temp_remove(self,name):self.files.pop(name,None)
        def read(self,path,missing=False):return None
        def mark_unknown(self):self.healthy=False
    def run_native(self,camera,decode):
        events=[];raw=[]
        result=invoke(camera,b'worker',stage='lut-program-staged.so',request='a7c2.install.request',result='a7c2.install.result',contents=b'request',mode=1,decode=decode,record=lambda e,**kw:events.append(e),save_raw=raw.append)
        return result,events,raw
    def test_single_invocation_cleans_only_verified_owned_temporaries(self):
        camera=self.Camera();result,events,raw=self.run_native(camera,lambda raw:{'valid':True})
        self.assertEqual(camera.writes.count('libJit.so'),1);self.assertEqual(camera.files,{})
        self.assertLess(events.index('native_intent'),events.index('native_result_verified'));self.assertEqual(raw,[b'valid report'])
    def test_unknown_result_is_preserved_without_retry_or_cleanup(self):
        camera=self.Camera()
        def invalid(raw):raise ValueError('unknown')
        with self.assertRaises(ValueError):self.run_native(camera,invalid)
        self.assertFalse(camera.healthy);self.assertEqual(camera.writes.count('libJit.so'),1)
        self.assertIn('a7c2.install.request',camera.files);self.assertIn('a7c2.install.result',camera.files)
    def test_invalid_auxiliary_result_marks_session_unknown_and_preserves_all_files(self):
        from types import SimpleNamespace
        camera=self.Camera();write=camera.temp_write
        def launch(name,data):
            write(name,data)
            if name=='libJit.so':camera.files['a7c2.probe.result']=b'incomplete auxiliary report'
        camera.temp_write=launch
        camera.core=SimpleNamespace(parse_native=lambda *args:(_ for _ in ()).throw(ValueError('bad auxiliary report')))
        with self.assertRaisesRegex(ValueError,'bad auxiliary report'):
            invoke(camera,b'worker',stage='lut-program-staged.so',request='a7c2.install.request',
                result='a7c2.install.result',contents=b'request',mode=1,decode=lambda raw:{'valid':True},
                record=lambda *args,**kwargs:None,save_raw=lambda raw:None,extras=('a7c2.probe.result',))
        self.assertFalse(camera.healthy)
        self.assertEqual(set(camera.files),{'lut-program-staged.so','a7c2.install.request',
            'a7c2.install.result','a7c2.probe.result'})
        self.assertEqual(camera.writes.count('libJit.so'),1)
    def test_changed_worker_preserves_report_and_request_before_any_cleanup(self):
        camera=self.Camera();write=camera.temp_write
        def launch(name,data):
            write(name,data)
            if name=='libJit.so':camera.files['lut-program-staged.so']=b'unexpected worker'
        camera.temp_write=launch
        with self.assertRaisesRegex(ValueError,'unexpected temporary contents'):
            self.run_native(camera,lambda raw:{'valid':True})
        self.assertFalse(camera.healthy)
        self.assertEqual(camera.files,{'lut-program-staged.so':b'unexpected worker',
            'a7c2.install.request':b'request','a7c2.install.result':b'valid report'})
        self.assertEqual(camera.writes.count('libJit.so'),1)
    def test_cleanup_disconnect_stops_before_removing_reports(self):
        camera=self.Camera();removed=[]
        def disconnect(name):
            removed.append(name)
            raise TimeoutError('cleanup disconnected')
        camera.temp_remove=disconnect
        with self.assertRaisesRegex(TimeoutError,'cleanup disconnected'):
            self.run_native(camera,lambda raw:{'valid':True})
        self.assertFalse(camera.healthy)
        self.assertEqual(removed,['lut-program-staged.so'])
        self.assertIn('a7c2.install.result',camera.files)
        self.assertIn('a7c2.install.request',camera.files)
    def test_existing_foreign_temporary_blocks_before_invocation(self):
        camera=self.Camera();camera.files['a7c2.install.result']=b'foreign'
        with self.assertRaises(ValueError):self.run_native(camera,lambda raw:{})
        self.assertFalse(camera.writes)

class NameReportTests(unittest.TestCase):
    def test_settings_allowlist_cannot_authorize_protected_cp_groups(self):
        from unittest.mock import Mock
        camera=Camera();camera.service_only=False;camera.programs_pinned=True;camera.link=Mock()
        with self.assertRaises(ValueError):camera.property_write(0x02a40000,b'\0',{0x02a40000})
        camera.link.call.assert_not_called()
    def test_valid_modes_and_unsafe_preflight_pid_or_hash_are_rejected(self):
        build={'count':2,'files':[{},{}],'AP':'11'*32,'target_AP':'22'*32}
        for mode,counts in [(0,[0,0,0,0,0]),(1,[2,2,2,0,0]),(2,[0,0,0,2,0]),(3,[0,0,0,0,2])]:
            sha=build['target_AP'] if mode==3 else build['AP']
            values=[b'A7NMR001',1,mode,9,2,*([0]*6+[123]),*counts,0,bytes.fromhex(sha)]
            self.assertTrue(nameworker.validate(nameworker.REPORT.pack(*values),mode,build)['native_verified'])
            for index,value in [(11,0),(18,bytes(32)),(5,-1),(8,-30)]:
                invalid=values.copy();invalid[index]=value
                with self.assertRaises(ValueError):nameworker.validate(nameworker.REPORT.pack(*invalid),mode,build)
            if mode==0:
                values[12]=1
                with self.assertRaises(ValueError):nameworker.validate(nameworker.REPORT.pack(*values),mode,build)

class LockTests(unittest.TestCase):
    def test_other_process_is_blocked_and_lock_releases(self):
        script="import sys\nfrom looktool.devicelock import DeviceLock\ntry:\n with DeviceLock(sys.argv[1]):print('acquired')\nexcept ValueError:print('blocked')"
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'device.lock'
            def child():
                result=subprocess.run([sys.executable,'-c',script,str(path)],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr);return result.stdout.strip()
            with DeviceLock(path):self.assertEqual(child(),'blocked')
            self.assertEqual(child(),'acquired')

@unittest.skipUnless(os.environ.get('A7C2_RESEARCH_FIXTURES'),'Needs private complete source files')
class LayoutTests(unittest.TestCase):
    def test_stock_and_fl23_first_imports_then_arbitrary_additions_and_inverse(self):
        root=Path(os.environ['A7C2_RESEARCH_FIXTURES']).parents[2]
        for ap_path,cp_path in [('live/program-files/appFw.so.original.bin','live/program-files/cpapp-b.bin.original.bin'),('live/installed-program-files/appFw.so','live/installed-program-files/cpapp-b.bin')]:
            ap,cp=(root/ap_path).read_bytes(),(root/cp_path).read_bytes()
            self.assertTrue(device_layout.identify(ap,cp)['first_install'])
            f,r,one=device_layout.replace(ap,cp,{6:bytes([1])*1215})
            self.assertEqual(device_layout.identify(one['appFw.so'],one['cpapp-b.bin'])['mask'],32)
            f2,r2,two=device_layout.replace(one['appFw.so'],one['cpapp-b.bin'],{1:bytes([2])*1215,3:bytes([3])*1215})
            self.assertEqual(device_layout.identify(two['appFw.so'],two['cpapp-b.bin'])['mask'],37)
            self.assertEqual(firmware.apply(two,r2),one)
            self.assertEqual(firmware.apply(one,r),{'appFw.so':ap,'cpapp-b.bin':cp})
            # Adding imports does not replace original recipes/defaults or FL23 caps.
            for at,n in [(0x4b4a564,18*8),(0x4b2ed19,2),(0x59892b8,40),(0x5989370,40)]:
                self.assertEqual(two['appFw.so'][at:at+n],ap[at:at+n])
    def test_repeat_table_updates_retain_reviewed_code_identity(self):
        index=Path(os.environ['A7C2_RESEARCH_FIXTURES']);paths=json.loads(index.read_text())
        ap=(index.parent/paths['six_ap']).read_bytes();cp=(index.parent/paths['v4_cp']).read_bytes()
        self.assertEqual(device_layout.identify(ap,cp)['CP'],six.CP_SHA)
        f,r,after=device_layout.replace(ap,cp,{1:bytes([1])*1215})
        second_f,second_r,second=device_layout.replace(ap,after['cpapp-b.bin'],{6:bytes([2])*1215})
        self.assertEqual(six.read_tables(second['cpapp-b.bin'])[0],bytes([1])*1215)
        self.assertEqual(firmware.apply(second,second_r),after)
        bad=bytearray(second['cpapp-b.bin']);bad[0x13553a]^=1
        with self.assertRaises(ValueError):device_layout.identify(ap,bytes(bad))
        with self.assertRaises(ValueError):device_layout.identify(b'other body',cp)

if __name__=='__main__':unittest.main()
