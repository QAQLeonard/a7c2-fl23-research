"""Official 2.01 components + synthetic settings; no USB or camera execution."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from looktool import checkpoint,checkpointworker,device_layout,firmware,fl23compat,nativebuild,resources,six
import test_device_job as f
from test_checkpoint import stock_names,SimRollback

sys.path.insert(0,str(f.ROOT/'src/fl23'))
import core,compat,workflow,transport

COMPONENTS=os.environ.get('A7C2_STOCK_COMPONENTS')


class Rig(f.SimCamera):
    """Program bytes are real; all hardware, calibration and settings are fake."""
    def __init__(self,ap,cp):
        super().__init__(ap,cp)
        for key in core.AP_KEYS:self.properties[key]=f.Prop(b'\0',0)
        for key,n in zip(core.CP_KEYS,(8192,28672)):self.cp[key]=f.Prop(bytes(n),0)
        self.saved=copy.deepcopy(self.properties)
        for name in f.nameworker.filenames():self.files['/usr/share/app/'+name]=stock_names()
        self.camera=self;self.link=self;self.healthy=True;self.native_calls=[]
    def read(self,path,missing=False):
        path=path.removeprefix('/tmp/jiritsu/../..')
        return self.files.get(path)
    def call(self,method,*args):return method(*args)
    def getBackupPresetData(self,memory):return self.snapshot(memory)
    def readBackup(self,key):return self.property_read(key)
    def cp_read(self,key):return self.cp[key].data
    def cp_write(self,key,value):self.cp[key]=f.Prop(value,self.cp[key].attr)
    def ap_write(self,key,value):self.properties[key]=f.Prop(value,self.properties[key].attr)
    def saveBackup(self,group):
        if group==0x02cf:self.save_settings()
        if getattr(self,'changing_telemetry',False):
            value=int.from_bytes(self.properties[0x02770015].data,'little')+60
            self.properties[0x02770015]=f.Prop(value.to_bytes(4,'little'),2)
    def save_group(self,group):self.saveBackup(group)


def simulated_module(job,rig,name,mode=None,byte_build=None):
    rig.native_calls.append((name,mode))
    if name=='installer' and mode==1:
        for n,p in f.devicejob.PROGRAM_PATHS.items():rig.files[p]=(job.root/'candidate'/n).read_bytes()
    elif name=='wbi' and mode==1:rig.mode='0\n'
    elif name=='runtime':
        ap=rig.files['/usr/lib/appFw.so'];at=0x3528804;raw=ap[at:at+112].hex()
        return {'spans':[{'offset':at,'length':112,'memory':raw,'disk':raw}]}
    return {'simulated':True}


@unittest.skipUnless(COMPONENTS,'Set A7C2_STOCK_COMPONENTS to official 2.01 components')
class CurrentFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original={n:(Path(COMPONENTS)/n).read_bytes() for n in core.PROGRAMS}
        if [firmware.sha(cls.original[n]) for n in core.PROGRAMS]!=core.ORIGINAL:
            raise ValueError('Official 2.01 fixture fingerprints differ')
        cls.fl23={n:core.patch_program(cls.original[n],i) for i,n in enumerate(core.PROGRAMS)}
        cls.raw=bytes([1])*1215
        cls.forward,cls.reverse,cls.both=device_layout.replace(cls.fl23['appFw.so'],cls.fl23['cpapp-b.bin'],{5:cls.raw})
        _,_,cls.lut=device_layout.replace(cls.original['appFw.so'],cls.original['cpapp-b.bin'],{5:cls.raw})

    def test_current_pair_is_accepted_and_unrelated_byte_is_rejected(self):
        self.assertTrue(device_layout.identify(*self.fl23.values())['first_install'])
        bad=bytearray(self.fl23['cpapp-b.bin']);bad[0x30000]^=1
        with self.assertRaises(ValueError):device_layout.identify(self.fl23['appFw.so'],bytes(bad))

    def test_both_install_orders_and_complete_inverse(self):
        _,_,after,_,_=compat.plan(*self.lut.values(),transitions=False)
        self.assertEqual(after,self.both)
        self.assertEqual(firmware.apply(self.both,self.reverse),self.fl23)
        self.assertTrue(compat.plan(*self.both.values(),transitions=False)[1])

    def test_gamma_data_and_lut_dispatch_both_survive(self):
        cp=self.both['cpapp-b.bin'];native=self.fl23['cpapp-b.bin']
        for at,n in [(0x138832,26),(0x1100b80,3872)]:
            self.assertEqual(cp[at:at+n],native[at:at+n])
        fl23compat.preserve_lut_dispatch(cp)
        for color,pair in [(19,(48,46)),(20,(49,47))]:
            self.assertEqual(struct.unpack_from('<II',cp,0x1100b80+0xe78+color*8),pair)
        self.assertEqual(six.read_tables(cp)[4],self.raw)

    def test_native_gamma_dispatch_all_markers_photo_and_movie(self):
        from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
        from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R4,UC_ARM_REG_LR
        cp=self.both['cpapp-b.bin'];base=0x108000
        cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB);cpu.mem_map(base,(len(cp)+4095)&~4095);cpu.mem_write(base,cp)
        stop=0x31000000;cpu.mem_map(stop,4096)
        for movie in (0,1):
            for color in range(256):
                cpu.reg_write(UC_ARM_REG_R0,color);cpu.reg_write(UC_ARM_REG_R4,movie);cpu.reg_write(UC_ARM_REG_LR,stop|1)
                cpu.emu_start(0xc2f501,stop,count=40)
                expected=0 if 249<=color<=254 else color
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R0),expected,(color,movie))
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R1),0x12099f8)

    def test_legacy_standalone_update_and_later_fl23_keep_tables(self):
        old=device_layout.runtime();spec=next(s for s in old['cp_sources'] if s['kind']=='stock')
        cp=bytearray(self.original['cpapp-b.bin'])
        for w in spec['windows']:
            raw=bytes.fromhex(w['after']);cp[w['offset']:w['offset']+len(raw)]=raw
        cp[six.TABLE_FILE:six.TABLE_FILE+32+6*1215]=six.prefix([bytes([n])*1215 for n in range(6)])
        ap=device_layout._ap_target(self.original['appFw.so'],63)
        _,_,updated=device_layout.replace(ap,bytes(cp),{3:bytes([17])*1215})
        _,_,after,_,_=compat.plan(*updated.values(),transitions=False)
        self.assertEqual(six.read_tables(after['cpapp-b.bin']),six.read_tables(updated['cpapp-b.bin']))
        self.assertEqual(device_layout.code_hash(after['cpapp-b.bin']),fl23compat.runtime()['cp_code_sha256'])
        self.assertEqual(device_layout.identify(*after.values())['mask'],63)

    def test_slot_undo_keeps_other_slot_and_current_fl23(self):
        _,_,two=device_layout.replace(*self.both.values(),{6:bytes([2])*1215})
        old=device_layout.before_first_table(*self.fl23.values(),5)
        forward,reverse,after=device_layout.deactivate(*two.values(),5,old)
        self.assertEqual(firmware.apply(after,reverse),two)
        self.assertTrue(compat.plan(*after.values(),transitions=False)[1])
        self.assertEqual(device_layout.identify(*after.values())['mask'],32)
        self.assertEqual(six.read_tables(after['cpapp-b.bin'])[5],bytes([2])*1215)

    def test_runtime_asset_is_reproducible_from_official_components(self):
        spec=importlib.util.spec_from_file_location('rebuild_adapter',f.ROOT/'dev/build_lut_compat.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module.build(COMPONENTS),fl23compat.runtime())

    def test_merge_conflict_is_not_silently_overwritten(self):
        cp=bytearray(self.lut['cpapp-b.bin']);cp[0x138832]^=1
        with self.assertRaisesRegex(ValueError,'0x138832'):compat.plan(self.lut['appFw.so'],bytes(cp),transitions=False)

    def test_real_native_worker_compilation_includes_checkpoint_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            builds=checkpointworker.build_programs(self.fl23,self.both,folder)
            self.assertTrue(builds)
            for build in builds:
                blob=Path(build['path']).read_bytes()
                self.assertIn(b'/tmp/jiritsu/checkpoint.program.request\0',blob)
                self.assertIn(b'/tmp/jiritsu/checkpoint.program.result\0',blob)
                self.assertLessEqual(len(blob),65536)
            # Also compile the hash-checked first-import worker, whose branch
            # must continue to work alongside byte-only recovery workers.
            regions={n:[(at,len(a)) for at,a,b in checkpointworker.differences(self.original[n],self.lut[n])] for n in core.PROGRAMS}
            forward=firmware.transition(self.original,self.lut,regions)
            reverse=firmware.transition(self.lut,self.original,regions)
            build=nativebuild.build_program(self.original,forward,reverse,Path(folder)/'import')
            self.assertFalse(build['contract']['byte_only'])
            self.assertEqual(build['contract']['after'],{n:firmware.sha(v) for n,v in self.lut.items()})
            self.assertLessEqual(build['bytes'],65536)

    def test_fl23_prepare_install_verify_over_existing_lut(self):
        rig=Rig(*self.lut.values())
        rig.changing_telemetry=True
        rig.properties[0x02770015]=f.Prop((100).to_bytes(4,'little'),2)
        rig.saved=copy.deepcopy(rig.properties)
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
            root=Path(folder);job=workflow.Job(root/'work')
            with patch.object(transport,'Session',side_effect=lambda expected=None:rig(expected)),patch.object(core,'backup_records',side_effect=rig.records),patch.object(workflow.Job,'module',simulated_module):
                job.prepare(root/'second','2.01')
                self.assertEqual(job.state['phase'],'prepared')
                self.assertEqual({n:rig.files[p] for n,p in f.devicejob.PROGRAM_PATHS.items()},self.lut)
                self.assertTrue(job.state['compatibility']['byte_builds'])
                workflow.Job(job.root).install(90)
                self.assertEqual({n:rig.files[p] for n,p in f.devicejob.PROGRAM_PATHS.items()},self.both)
                self.assertGreater(int.from_bytes(rig.properties[0x02770015].data,'little'),100)
                workflow.Job(job.root).verify()
                with self.assertRaisesRegex(ValueError,'重跑'):workflow.Job(job.root).install(90)
            meta,values=checkpoint.read(root/'second/checkpoint.private.zip')
            self.assertEqual(values['cpapp-b.bin'],self.lut['cpapp-b.bin'])
            self.assertEqual(meta['identity'],rig.identity)

    def test_full_checkpoint_rollback_after_both_features(self):
        rig=Rig(*self.original.values())
        initial=dict(self.original,**{'settings-ram.bin':rig.snapshot(True),'settings-saved.bin':rig.snapshot(False)})
        initial.update({'resources/'+n:rig.files['/usr/share/app/'+n] for n in f.nameworker.filenames()})
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
            root=Path(folder);archive=root/'initial.private.zip'
            checkpoint.write(archive,initial,rig.identity,provenance={'type':'official-programs-synthetic-settings'})
            for n,p in f.devicejob.PROGRAM_PATHS.items():rig.files[p]=self.both[n]
            for n in f.nameworker.filenames():
                path='/usr/share/app/'+n
                rig.files[path]=resources.rename(rig.files[path],{5:'Synthetic look'},list(range(0x0200ab2c,0x0200ab32)))[0]
            for i,k in enumerate(core.AP_KEYS):rig.ap_write(k,bytes([10+i]))
            for k,v in zip(core.CP_KEYS,core.merge_colors(*(rig.cp[k].data for k in core.CP_KEYS))):rig.cp_write(k,v)
            rig.save_settings()
            rollback=SimRollback(root/'rollback',factory=rig)
            rollback.run(archive,90,'2.01')
            self.assertEqual({n:rig.files[p] for n,p in f.devicejob.PROGRAM_PATHS.items()},self.original)
            self.assertEqual(rig.properties,rig.records(initial['settings-ram.bin'])[0])
            for n in f.nameworker.filenames():
                self.assertEqual(rig.files['/usr/share/app/'+n],initial['resources/'+n])

    def test_lut_job_after_current_fl23_then_slot_undo_and_fl23_verify(self):
        rig=Rig(*self.original.values())
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
            root=Path(folder);fl=workflow.Job(root/'fl23')
            with patch.object(transport,'Session',side_effect=lambda expected=None:rig(expected)),patch.object(core,'backup_records',side_effect=rig.records),patch.object(workflow.Job,'module',simulated_module):
                fl.prepare(root/'fl23-backup','2.01');fl.install(90)
                self.assertEqual({n:rig.files[p] for n,p in f.devicejob.PROGRAM_PATHS.items()},self.fl23)
                protected=copy.deepcopy(rig.cp)
                reference=root/'synthetic.cube';reference.write_text('LUT_3D_SIZE 2\n'+'\n'.join(f'{r} {g} {b}' for b in (0,1) for g in (0,1) for r in (0,1)))
                model=root/'synthetic.json';model.write_text(json.dumps({'schema':'a7c2-look-calibration/1','coordinate_model':'bt601-limited-provisional','response_matrix':[[1,0,0],[0,1,0],[0,0,1]],'evidence':'SYNTHETIC TEST ONLY'}))
                with patch.object(nativebuild,'build_program',side_effect=f.fake_program),patch.object(f.nameworker,'prepare',side_effect=f.fake_names):
                    job=f.SimJob(root/'lut',factory=rig)
                    job.create(reference,'Synthetic five',5,model,root/'lut-backup',write=True,battery=90,input_space='sony-st-srgb')
                    rig.reboot();self.assertEqual(job.verify(True)['phase'],'COMPLETE')
                    self.assertEqual({n:rig.files[p] for n,p in f.devicejob.PROGRAM_PATHS.items()},self.both)
                    workflow.Job(fl.root).verify()
                    undo=f.SimJob(root/'undo',factory=rig)
                    undo.restore_slot(job,90,root/'undo-backup')
                    rig.reboot();self.assertEqual(undo.verify(True)['phase'],'COMPLETE')
                    workflow.Job(fl.root).verify()
                self.assertEqual(rig.cp,protected)
                self.assertEqual(device_layout.identify(rig.files['/usr/lib/appFw.so'],rig.files['/cp/cpapp-b.bin'])['mask'],0)


if __name__=='__main__':unittest.main()
