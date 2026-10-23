"""Complete names + EBUSY pauses before programs and supports cold continuation."""
import copy,json,struct,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from looktool import checkpointworker,direct,lookfile,nameworker,namespause,resources
from test_checkpoint import Camera,values,fake_compile
from test_device_components import resource_fixture
from test_direct import SimDirect


class NamesPauseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.failed=self.root/'failed';(self.failed/'evidence').mkdir(parents=True)
        self.current=values();self.camera=Camera(self.current)
        self.camera.usr_mount_readonly=False;self.camera.boot='boot-old'
        self.target=dict(self.current,**{'appFw.so':b'\7'+self.current['appFw.so'][1:]})
        with patch.object(checkpointworker,'compile_worker',side_effect=fake_compile):
            programs=checkpointworker.build_programs(self.current,self.target,self.failed/'worker')
        self.install_names(self.current['resources/'+nameworker.filenames()[0]],{1:'CC'})
        path=Path(self.build['path'])
        self.raw=nameworker.REPORT.pack(b'A7NMR001',1,1,9,68,-16,0,0,-16,0,0,517,68,0,68,0,0,0,bytes(32))
        (self.failed/'evidence/failed-names-forward-1.bin').write_bytes(self.raw)
        lookfile.write(self.failed/'reference.a7look','CC',bytes(1215),method='fixture',attribution='test')
        self.state=dict(schema='a7c2-direct-job/1',phase='NEEDS_REVIEW',mode='look_import',slot=1,name='CC',
            identity=self.camera.identity,source_boot_id='boot-old',forward_name_build=self.build,inverse_name_build=None,
            program_builds=programs,journal=[dict(event='native_intent',result='a7c2.names.result',mode=1)])
        self.save()
        self.temps={'lut-names-staged.so':path.read_bytes(),'a7c2.names.request':struct.pack('<8sII',b'A7NAM001',1,0),'a7c2.names.result':self.raw}
        self.camera.temp_read=lambda name,missing=False:self.temps.get(name)
        self.camera.temp_remove=lambda name:self.temps.pop(name)

    def save(self):(self.failed/'direct.private.json').write_text(json.dumps(self.state),encoding='utf-8')
    def job(self):return SimDirect(self.root/'resume',factory=self.camera)

    def install_names(self,original,titles,label_ids=resources.LABEL_IDS):
        def compile_names(*args,**kwargs):
            fake_compile(*args,**kwargs)
            return {}
        sources={n:original for n in nameworker.filenames()}
        with patch.object(nameworker,'compile_worker',side_effect=compile_names):
            changed,self.build=nameworker.prepare(sources,titles,self.current['appFw.so'],
                '0123456789abcdef',self.failed/'names',label_ids=label_ids,byte_only=True)
        for name,data in changed.items():self.camera.files['/usr/share/app/'+name]=data

    def bundle_names(self,original,titles,label_ids=resources.LABEL_IDS):
        self.install_names(original,titles,label_ids)
        self.state.update(mode='install_all',forward_name_build=self.build,
            bundle_options=dict(fl23=False,sound=False,reset_slots=[2,5],looks=[]))
        for slot in (1,4):
            if slot not in titles:continue
            path=self.failed/('reference-slot-%d.a7look'%slot)
            lookfile.write(path,titles[slot],bytes(1215),method='fixture',attribution='test')
            self.state['bundle_options']['looks'].append(dict(slot=slot,path=str(path),name=titles[slot]))
        self.save()

    def test_mixed_legacy_write_and_st_reset_survives_resource_reload(self):
        self.bundle_names(resource_fixture(),{1:'CC',2:'ST',4:'夜景',5:'ST'})
        before=dict(self.camera.files);settings=copy.deepcopy((self.camera.ram,self.camera.saved))
        evidence={p:p.read_bytes() for p in self.failed.rglob('*') if p.is_file()}
        job=self.job()
        self.assertEqual(job.prepare_names_reload(self.failed,power_confirmed=True)['phase'],namespause.WAIT)
        self.assertEqual(job.verify_names_reload()['phase'],namespause.WAIT)
        self.camera.boot='boot-new';self.camera.usr_mount_readonly=True
        self.assertEqual(job.verify_names_reload()['phase'],'RESOURCE_RELOAD_VERIFIED')
        self.assertEqual(self.camera.files,before)
        self.assertEqual((self.camera.ram,self.camera.saved),settings)
        self.assertFalse(any(kind in ('program','names') for kind,mode in self.camera.native_calls))
        self.assertEqual(evidence,{p:p.read_bytes() for p in self.failed.rglob('*') if p.is_file()})
        parsed=resources.decode(self.camera.files['/usr/share/app/'+nameworker.filenames()[0]])
        self.assertEqual([parsed['entries'][rid]['text'] for rid in resources.LABEL_IDS],
                         ['CC','ST','Original 3','夜景','ST','Original 6'])

    def test_reset_only_legacy_bundle_uses_recorded_st_titles(self):
        self.bundle_names(resource_fixture(),{2:'ST',5:'ST'})
        self.assertEqual(self.job().prepare_names_reload(self.failed,power_confirmed=True)['phase'],namespause.WAIT)

    def test_modern_resets_do_not_rename_inactive_slots(self):
        ids=tuple(sorted(resources.LABEL_IDS))
        self.bundle_names(resource_fixture(),{1:'CC',4:'夜景'},ids)
        before=dict(self.camera.files)
        self.assertEqual(self.job().prepare_names_reload(self.failed,power_confirmed=True)['phase'],namespause.WAIT)
        self.assertEqual(self.camera.files,before)
        parsed=resources.decode(before['/usr/share/app/'+nameworker.filenames()[0]])
        original=resources.decode(resource_fixture())
        for slot in (2,3,5,6):self.assertEqual(parsed['entries'][ids[slot-1]],original['entries'][ids[slot-1]])

    def test_changed_restored_title_stops_before_cleanup_or_native_operations(self):
        self.bundle_names(resource_fixture(),{1:'CC',2:'ST',4:'夜景',5:'ST'})
        path='/usr/share/app/'+nameworker.filenames()[0]
        raw=bytearray(self.camera.files[path]);parsed=resources.decode(raw)
        at=parsed['data_base']+parsed['entries'][resources.LABEL_IDS[1]]['pointer']*4+4
        raw[at:at+2]=b'SX';self.camera.files[path]=bytes(raw)
        temps=dict(self.temps)
        with self.assertRaisesRegex(ValueError,'Complete name readback differs'):
            self.job().prepare_names_reload(self.failed,power_confirmed=True)
        self.assertFalse(self.camera.native_calls)
        self.assertEqual(self.temps,temps)

    def test_incomplete_or_invalid_name_evidence_stops_before_cleanup(self):
        path=Path(self.build['path']).with_name('names.private.h')
        header=path.read_text(encoding='ascii');temps=dict(self.temps)
        invalid=[header.replace('static const u32 selected_mask=1;',''),
                 header.replace('selected_mask=1;','selected_mask=64;'),
                 header.replace('selected_mask=1;','selected_mask=0;'),
                 header.replace('{67,67,0}','{67,67}'),
                 header.replace('{67,67,0}','{255,0}'),
                 header.replace('{67,67,0}','{67,0,67,0}')]
        for index,text in enumerate(invalid):
            with self.subTest(index=index):
                path.write_text(text,encoding='ascii')
                job=SimDirect(self.root/('invalid-'+str(index)),factory=self.camera)
                with self.assertRaises(ValueError):job.prepare_names_reload(self.failed,power_confirmed=True)
                self.assertFalse(self.camera.native_calls)
                self.assertEqual(self.temps,temps)

    def test_prepare_accounts_actual_report_without_any_program_or_recipe_write(self):
        before={p:p.read_bytes() for p in self.failed.rglob('*') if p.is_file()}
        snapshots=copy.deepcopy((self.camera.ram,self.camera.saved))
        job=self.job();result=job.prepare_names_reload(self.failed,power_confirmed=True)
        self.assertEqual(result['phase'],namespause.WAIT)
        self.assertEqual(self.camera.mode,'0\n')
        self.assertFalse(any(kind in ('program','names') for kind,mode in self.camera.native_calls))
        self.assertEqual((self.camera.ram,self.camera.saved),snapshots)
        self.assertEqual(self.temps,{})
        self.assertEqual(before,{p:p.read_bytes() for p in self.failed.rglob('*') if p.is_file()})
        self.assertEqual(job.verify_names_reload()['phase'],namespause.WAIT)
        self.camera.boot='boot-new';self.camera.usr_mount_readonly=True
        self.assertEqual(job.verify_names_reload()['phase'],'RESOURCE_RELOAD_VERIFIED')

    def test_already_readonly_does_not_force_an_extra_cold_boot(self):
        self.camera.usr_mount_readonly=True
        job=self.job();result=job.prepare_names_reload(self.failed,power_confirmed=True)
        self.assertEqual(result['phase'],'RESOURCE_RELOAD_VERIFIED')
        self.assertTrue(result['resource_reload_not_needed'])
        self.assertFalse(any(kind=='wbi' for kind,mode in self.camera.native_calls))

    def test_changed_name_or_program_or_foreign_temp_does_not_prepare_reload(self):
        for failure in ('name','program','temp'):
            files=dict(self.camera.files);temps=dict(self.temps)
            if failure=='name':self.camera.files['/usr/share/app/'+nameworker.filenames()[0]]+=b'bad!'
            elif failure=='program':self.camera.files['/usr/lib/appFw.so']=b'\1'+self.current['appFw.so'][1:]
            else:self.temps['libJit.so']=b'unknown'
            job=SimDirect(self.root/('stop-'+failure),factory=self.camera)
            with self.assertRaises(ValueError):job.prepare_names_reload(self.failed,power_confirmed=True)
            self.assertFalse(self.camera.native_calls)
            self.camera.files=files;self.temps.clear();self.temps.update(temps)

    def test_read_error_after_completed_cleaned_names_continues_without_name_write(self):
        # Field case: names committed and cleaned up, then "Wrong senser
        # sequence" before the first program stage. Clean and busy reports.
        clean=nameworker.REPORT.pack(b'A7NMR001',1,1,9,68,0,0,0,0,0,0,517,68,0,68,0,0,0,bytes(32))
        done=[dict(event='native_result_verified',stage='lut-names-staged.so',mode=1,result={}),
              dict(event='native_cleanup_verified',stage='lut-names-staged.so',mode=1)]
        for raw in (clean,self.raw):
            with self.subTest(busy=raw is self.raw):
                (self.failed/'evidence/failed-names-forward-1.bin').write_bytes(raw)
                self.state['journal']=[dict(event='native_intent',result='a7c2.names.result',mode=1),*done]
                self.save();self.temps.clear()
                self.assertEqual(namespause.source(self.failed)[2],raw)
                job=SimDirect(self.root/('after-'+str(len(self.camera.native_calls))+str(raw is self.raw)),factory=self.camera)
                job.prepare_names_reload(self.failed,power_confirmed=True)
                self.assertFalse(any(kind in ('program','names') for kind,mode in self.camera.native_calls))
                # Anything that ran after the names is not this checkpoint.
                self.state['journal'].append(dict(event='native_intent',result='a7c2.wbi.result',mode=0))
                self.save()
                with self.assertRaisesRegex(ValueError,'Unknown operation'):namespause.source(self.failed)
        self.build['stream_install']=False;self.state['forward_name_build']=self.build
        self.state['journal']=[dict(event='native_intent',result='a7c2.names.result',mode=1),*done];self.save()
        (self.failed/'evidence/failed-names-forward-1.bin').write_bytes(clean)
        with self.assertRaisesRegex(ValueError,'not fully accounted'):namespause.source(self.failed)

    def test_only_complete_clean_stream_name_busy_is_accepted(self):
        self.assertTrue(nameworker.validate(self.raw,1,self.build,allow_completed_busy=True)['readonly_deferred_busy'])
        with self.assertRaises(ValueError):nameworker.validate(self.raw,1,self.build)
        for index,value in ((3,5),(6,-5),(7,-16),(9,-5),(12,67),(14,67),(15,1)):
            v=list(nameworker.REPORT.unpack(self.raw));v[index]=value
            with self.assertRaises(ValueError):nameworker.validate(nameworker.REPORT.pack(*v),1,self.build,allow_completed_busy=True)

    def test_fresh_writer_pauses_after_full_name_readback_before_programs(self):
        camera=Camera(self.current);camera.usr_mount_readonly=False;camera.boot='boot-old'
        job=SimDirect(self.root/'fresh',factory=camera)
        def plan(current,*args,**kwargs):
            target=dict(current);target['appFw.so']=self.target['appFw.so']
            for n in nameworker.filenames():target['resources/'+n]=self.camera.files['/usr/share/app/'+n]
            return target,[{},{}],({1:'CC'},resources.LABEL_IDS)
        def forward(cam,build,mode):
            if mode==1:
                for n in nameworker.filenames():cam.files['/usr/share/app/'+n]=self.camera.files['/usr/share/app/'+n]
                job.raw('names-forward-1.bin',self.raw)
                return dict(readonly_deferred_busy=True)
        original_call=Camera.__call__
        with patch.object(Camera,'__call__',lambda c,expected=None:c if expected is None else original_call(c,expected)), \
             patch.object(direct,'plan',side_effect=plan),patch.object(checkpointworker,'compile_worker',side_effect=fake_compile), \
             patch.object(nameworker,'prepare',return_value=({n:self.camera.files['/usr/share/app/'+n] for n in nameworker.filenames()},self.build)), \
             patch.object(job,'forward_names',side_effect=forward):
            result=job.run_direct('look_import',version='2.01',power_confirmed=True,slot=1,look_path=self.failed/'reference.a7look')
        self.assertEqual(result['phase'],namespause.WAIT)
        self.assertFalse(any(kind=='program' and mode==1 for kind,mode in camera.native_calls))
        self.assertEqual(camera.files['/usr/lib/appFw.so'],self.current['appFw.so'])
        self.assertEqual(camera.saves,[]);self.assertEqual(camera.mode,'0\n')
