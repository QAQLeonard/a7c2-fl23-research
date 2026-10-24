"""Explicit backup/fit/write/readback/reload/restore job, with durable evidence.

No device is opened at import time. Unknown native outcomes are never replayed.
"""
from datetime import datetime,timezone
import gzip,json,os,shutil,struct,uuid
from pathlib import Path
from . import backupstore,calibration,device_layout,devicesettings,firmware,nameworker,native,nativebuild,project,resources,six,uploadgate,worker
from .devicesession import Camera,invoke
from .devicelock import serialized

PROGRAM_PATHS={'appFw.so':'/usr/lib/appFw.so','cpapp-b.bin':'/cp/cpapp-b.bin'}

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.new')
    with temporary.open('w',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)

class Job:
    def __init__(self,folder,*,factory=Camera,zig=None):
        self.root=Path(folder).resolve();self.factory=factory;self.zig=zig;self.state_path=self.root/'job.private.json'
    def _hashes(self):return getattr(self,'hash_checks',True) and not self.state.get('byte_checks',False)
    def save(self,phase,**values):
        if phase in ('AWAITING_RELOAD','RESTORED_AWAITING_RELOAD') and self.state.get('phase')!=phase:
            values.setdefault('raw_profile_effective_since',datetime.now().isoformat(timespec='microseconds'))
        self.state.update(values);self.state['phase']=phase;write_json(self.state_path,self.state)
        print('LUT:',phase,flush=True)
    def record(self,phase,**values):
        self.state.setdefault('journal',[]).append({'time':datetime.now(timezone.utc).isoformat(),'event':phase,**values})
        write_json(self.state_path,self.state)
    def raw(self,name,data):
        if self.state.get('backup_format')==2 and len(data)>=4096:
            name+='.gz';data=gzip.compress(data,mtime=0)
        path=self.root/'evidence'/(str(len(self.state.get('journal',[]))).zfill(5)+'-'+uuid.uuid4().hex[:8]+'-'+name);path.parent.mkdir(exist_ok=True)
        with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    def _stores(self):
        if len(self.state['backup_stores'])!=2:raise ValueError('Two compressed backup stores required')
        return [backupstore.Store(p,self.state['backup_body'],hash_checks=self._hashes()) for p in self.state['backup_stores']]
    def source(self,name):
        if self.state.get('backup_format')!=2:return (self.root/'source'/name).read_bytes()
        return self._stores()[0].read(self.state['backup_objects'][name])
    def resource_target(self,name):
        if self.state['name_build'].get('unchanged'):return self.source('resources/'+name)
        raw,_=resources.rename(self.source('resources/'+name),{self.state['slot']:self.state['name']},self.state['layout']['label_ids'])
        spec=next(s for s in self.state['name_build']['files'] if s['file']==name)
        if len(raw)!=spec['after_bytes'] or (self._hashes() and firmware.sha(raw)!=spec['after_sha256']):raise ValueError('Reconstructed name target differs')
        return raw
    def _planned_settings(self,ap,ram,saved):
        fields=devicesettings.plan(ap,ram,saved,[self.state['slot']],hash_checks=self._hashes())
        recipe=self.state.get('restore_recipe')
        if recipe is not None:
            if json.loads((self.root/'candidate/restore-recipe.private.json').read_text(encoding='utf-8'))!=recipe:raise ValueError('Restoration recipe artifact differs')
            if set(recipe)!={str(f['key']) for f in fields}:raise ValueError('Restoration recipe fields differ')
            for f in fields:
                value=bytes.fromhex(recipe[str(f['key'])])
                if len(value)!=len(bytes.fromhex(f['after'])):raise ValueError('Restoration recipe size differs')
                f['after']=value.hex()
        return fields
    def load(self,*,hash_checks=True):
        self.state=json.loads(self.state_path.read_text(encoding='utf-8'))
        self.hash_checks=hash_checks
        if self.state.get('schema')!='a7c2-lut-device-job/1':raise ValueError('Unknown device job')
        if self.state.get('backup_format') not in (None,2):raise ValueError('Unknown device backup format')
        if not self._hashes():return self
        second=Path(self.state['backup_copy'])
        if second==self.root or self.root in second.parents or second in self.root.parents:raise ValueError('Independent backup folders required')
        if self.state.get('backup_format')==2:
            if self.state['backup_body']!=backupstore.body_key(self.state['identity']):raise ValueError('Compressed backups belong to a different body')
            inventories=[self.state['backup_objects'],self.state['backup_mirror_objects']]
            for path,inventory,key in zip([self.root/'source/snapshot.private.json',second/'snapshot.private.json'],inventories,['backup_manifest_sha256','backup_mirror_manifest_sha256']):
                if firmware.sha(path.read_bytes())!=self.state[key]:raise ValueError('Compressed backup manifest differs')
                manifest=json.loads(path.read_text(encoding='utf-8'))
                if manifest!={'schema':'a7c2-lut-backup/2','body':self.state['backup_body'],'files':inventory}:raise ValueError('Compressed backup references differ')
            stores=self._stores()
            if stores[0].root==stores[1].root:raise ValueError('Separate compressed backup stores required')
            if any(set(inv)!=set(self.state['backup_files']) for inv in inventories):raise ValueError('Compressed backup inventory differs')
            for name,expected in self.state['backup_files'].items():
                for store,inventory in zip(stores,inventories):
                    if firmware.sha(store.read(inventory[name]))!=expected:raise ValueError('Body backup differs: '+name)
            if 'slot_checkpoint_sha256' in self.state:
                for base,key in zip([self.root,second],['slot_checkpoint_sha256','slot_checkpoint_mirror_sha256']):
                    if firmware.sha((base/f'slot-{self.state["slot"]}-before.private.json').read_bytes())!=self.state[key]:raise ValueError('Slot checkpoint differs')
        else:
            for name,expected in self.state['backup_files'].items():
                for base in [self.root/'source',second]:
                    if firmware.sha((base/name).read_bytes())!=expected:raise ValueError('Body backup differs: '+name)
        for name,expected in self.state.get('artifacts',{}).items():
            if firmware.sha((self.root/name).read_bytes())!=expected:raise ValueError('Job artifact changed: '+name)
        return self
    def artifacts(self):
        result={}
        for folder in ['input','candidate','transition','worker','resource-target']:
            for path in (self.root/folder).rglob('*'):
                if path.is_file() and not any(p.startswith('zig-') for p in path.relative_to(self.root/folder).parts):
                    result[path.relative_to(self.root).as_posix()]=firmware.sha(path.read_bytes())
        self.state['artifacts']=result
    def _invoke(self,camera,kind,mode):
        if kind=='program':
            build=self.state['program_build']
            if build['unchanged']:return {'unchanged':True}
            blob=(self.root/'worker/program/program.so').read_bytes();stage='lut-program-staged.so';request='a7c2.install.request';result='a7c2.install.result';magic=b'A7INS001'
            decode=lambda raw:worker.validate_worker_report(raw,mode,build['contract'])
        elif kind=='names':
            build=self.state['name_build']
            if build.get('unchanged'):
                self.record('name_resources_already_match_no_native_operation',mode=mode)
                return {'unchanged':True}
            cleanup=mode==3 and 'name_cleanup_build' in self.state
            if cleanup:build=self.state['name_cleanup_build']
            blob=(self.root/('worker/names-cleanup/names.so' if cleanup else 'worker/names/names.so')).read_bytes();stage='lut-names-staged.so';request='a7c2.names.request';result='a7c2.names.result';magic=b'A7NAM001'
            decode=lambda raw:nameworker.validate(raw,mode,build)
        elif kind=='wbi':
            camera.core.assets();blob=(nativebuild.ROOT/'src/fl23/assets/wbi.so').read_bytes();stage='lut-program-staged.so';request='a7c2.wbi.request';result='a7c2.wbi.result';magic=b'A7WBI001'
            decode=lambda raw:camera.core.parse_native('wbi',raw,mode)
        elif kind=='runtime':
            camera.core.assets();blob=(nativebuild.ROOT/'src/fl23/assets/runtime.so').read_bytes();stage='lut-runtime-staged.so';request=None;result='a7c2.runtime.result';magic=None
            def decode(raw):
                value=camera.core.parse_native('runtime',raw)
                value.update(image_dev=raw[1608:1640].split(b'\0')[0].decode('ascii'),boot_id=raw[1768:1832].split(b'\0')[0].decode('ascii'),model_index=struct.unpack_from('<I',raw,48)[0])
                return value
        else:raise ValueError('Unknown native operation')
        if kind in ['program','names'] and self._hashes() and firmware.sha(blob)!=build['sha256']:raise ValueError('Compiled worker changed')
        return invoke(camera,blob,stage=stage,request=request,result=result,contents=struct.pack('<8sII',magic,mode,0) if request else None,mode=mode,decode=decode,record=self.record,save_raw=lambda raw:self.raw(kind+'-'+str(mode)+'.bin',raw),extras=('a7c2.probe.result',) if kind=='runtime' else ())
    def _read_programs(self,camera,expected,*,allow_later_slots=False):
        actual={}
        self._later_fl23=False
        self._later_slot_updates=False
        self._later_upload_gate=False
        camera.byte_checks=not self._hashes()
        if not self._hashes():
            wanted={n:self.source(n) for n in PROGRAM_PATHS}
            if expected!=self.state['source_hashes']:
                wanted=firmware.apply(wanted,json.loads((self.root/'transition/forward.private.json').read_text(encoding='utf-8')),hash_checks=False)
        for name,path in PROGRAM_PATHS.items():actual[name]=camera.read(path)
        if self._hashes():
            differs=any(firmware.sha(raw)!=expected[name] for name,raw in actual.items())
            if differs and expected==self.state['target_hashes']:
                # FL23 may be installed after a completed LUT import. Accept
                # only its concrete transformation over this exact target.
                source={n:self.source(n) for n in PROGRAM_PATHS}
                target=firmware.apply(source,json.loads((self.root/'transition/forward.private.json').read_text(encoding='utf-8')))
                from .devicesession import modules
                modules();import compat
                _,_,with_fl23,_,_=compat.plan(target['appFw.so'],target['cpapp-b.bin'],transitions=False)
                self._later_fl23=actual==with_fl23
                if allow_later_slots and not self._later_fl23:
                    # Old hash-based jobs remain strict about other slot data.
                    # Accept only the complete target with an exact reviewed
                    # forward migration, never rewrite its recorded hashes.
                    from . import uploadpending
                    upgrades=[uploadgate.restore]
                    if uploadpending.active(actual['cpapp-b.bin']):
                        upgrades.append(uploadpending.install)
                    for candidate,later_fl23 in ((target,False),(with_fl23,True)):
                        for upgrade in upgrades:
                            try:
                                upgraded=dict(candidate)
                                upgraded['cpapp-b.bin']=upgrade(candidate['cpapp-b.bin'])
                            except ValueError:
                                continue
                            if upgraded!=candidate and actual==upgraded:
                                self._later_upload_gate=True;self._later_fl23=later_fl23
                                break
                        if self._later_upload_gate:break
                differs=not (self._later_fl23 or self._later_upload_gate)
            if differs:raise ValueError('Complete host readback differs from the job and its FL23-compatible target')
        elif actual!=wanted:
            if expected==self.state['target_hashes']:
                from .devicesession import modules
                modules();import compat
                _,_,with_fl23,_,_=compat.plan(wanted['appFw.so'],wanted['cpapp-b.bin'],transitions=False)
                self._later_fl23=actual==with_fl23
                if allow_later_slots and not self._later_fl23:
                    self._later_slot_updates=device_layout.same_selected_programs(wanted,actual,self.state['slot'])
                    if not self._later_slot_updates and device_layout.same_selected_programs(with_fl23,actual,self.state['slot']):
                        self._later_fl23=True;self._later_slot_updates=True
            if not self._later_fl23 and not self._later_slot_updates:raise ValueError('Complete host readback differs from planned bytes')
        self.record('complete_host_program_readback_verified',hashes={n:firmware.sha(b) for n,b in actual.items()} if self._hashes() else None,
            comparison='complete-bytes-with-native-upload-entry' if self._later_upload_gate else
                'file-digest' if self._hashes() else 'complete-bytes-with-later-unselected-slot-data' if self._later_slot_updates else 'complete-bytes',full_readback_files_saved=False)
        if hasattr(camera,'pin_programs'):camera.pin_programs(actual['appFw.so'],actual['cpapp-b.bin'])
        return actual
    def _resource_readback(self,camera,after,*,allow_later_slots=False):
        actual={};self._later_name_updates=False
        for spec in self.state['name_build']['files']:
            raw=camera.read('/usr/share/app/'+spec['file']);which='after' if after else 'before'
            desired=None if self._hashes() else (self.resource_target(spec['file']) if after else self.source('resources/'+spec['file']))
            if len(raw)!=spec[which+'_bytes'] or ((firmware.sha(raw)!=spec[which+'_sha256']) if self._hashes() else (raw!=desired)):
                if not (allow_later_slots and after and not self._hashes() and resources.later_unselected_names(desired,raw,self.state['slot'],self.state['layout']['label_ids'])):
                    raise ValueError('Complete name readback differs: '+spec['file'])
                self._later_name_updates=True
            actual[spec['file']]=raw
        self.record('complete_name_resources_readback_verified',after=after,count=68,later_unselected_name_records=self._later_name_updates)
        return actual
    def _capture(self,camera,second):
        print('Reading full programs, saved/live settings and 68 name resources; keep USB connected.',flush=True)
        self.state['identity']=camera.identity
        values={name:camera.read(path) for name,path in PROGRAM_PATHS.items()}
        from . import photoio
        if photoio.present(values['cpapp-b.bin']):self.state['byte_checks']=True
        camera.byte_checks=not self._hashes()
        self.state['layout']=(camera.pin_programs(values['appFw.so'],values['cpapp-b.bin']) if hasattr(camera,'pin_programs')
            else (device_layout.identify if self._hashes() else device_layout.structural)(values['appFw.so'],values['cpapp-b.bin']))
        self.record('complete_source_identity_verified_before_native_execution' if self._hashes() else 'source_model_and_converter_bytes_checked_before_native_execution',programs=self.state['layout'])
        runtime=self._invoke(camera,'runtime',0)
        if getattr(camera,'identity_pending',False):camera.confirm_identity(runtime)
        self.state['identity']=camera.identity
        if not runtime['boot_id'].strip():raise ValueError('Read-only boot identity unavailable')
        self.state['source_runtime']=runtime
        ram,saved=camera.snapshot(True),camera.snapshot(False)
        self.state['settings_preservation_scope']=devicesettings.PRESERVATION_SCOPE
        values['settings-ram.bin']=ram;values['settings-saved.bin']=saved
        for filename in nameworker.filenames():values['resources/'+filename]=camera.read('/usr/share/app/'+filename)
        # One initial self-contained checkpoint per body/store, never one
        # extra full archive for every later slot update.
        from . import checkpoint
        initial=second.parent/'initial-checkpoints'/backupstore.body_key(camera.identity)/'checkpoint.private.zip'
        if not initial.exists():
            checkpoint.write(initial,values,camera.identity,provenance={'type':'before-first-lut-import','source_layout':self.state['layout']['kind'] if 'kind' in self.state['layout'] else self.state['layout']})
        self.state['initial_checkpoint']=str(initial)
        values['boot-id.bin']=runtime['boot_id'].encode('ascii')
        self.state.update(backup_format=2,backup_body=backupstore.body_key(camera.identity),
            backup_stores=[str(self.root.parent/'.a7c2-lut-work-store'),str(second.parent/'.a7c2-lut-backup-store')],backup_objects={},backup_mirror_objects={},backup_files={})
        stores=self._stores()
        for name,raw in values.items():
            specs=[store.put(name,raw) for store in stores]
            self.state['backup_objects'][name]=specs[0]
            self.state['backup_mirror_objects'][name]=specs[1]
            self.state['backup_files'][name]=firmware.sha(raw)
        for path,inventory in zip([self.root/'source/snapshot.private.json',second/'snapshot.private.json'],[self.state['backup_objects'],self.state['backup_mirror_objects']]):
            backupstore.write_json(path,{'schema':'a7c2-lut-backup/2','body':self.state['backup_body'],'files':inventory})
        self.state['backup_manifest_sha256']=firmware.sha((self.root/'source/snapshot.private.json').read_bytes())
        self.state['backup_mirror_manifest_sha256']=firmware.sha((second/'snapshot.private.json').read_bytes())
        self.state['backup_storage_summary']={'raw_source_bytes':sum(map(len,values.values())),
            'new_primary_compressed_bytes':stores[0].new_bytes,'new_independent_compressed_bytes':stores[1].new_bytes,
            'new_primary_objects':stores[0].new_objects,'full_readback_copies_saved':False}
        self.record('compressed_incremental_backups_verified',**self.state['backup_storage_summary'])
        self.state['identity']=camera.identity;self.save('BACKUPS_VERIFIED')
        return values
    def _fit(self,source,name,slot,model,attribution):
        source=Path(source).resolve()
        if source.suffix.lower()=='.a7look':
            from . import lookfile
            compiled=lookfile.read(source);raw=lookfile.writer_document(compiled)
            input_dir=self.root/'input';input_dir.mkdir()
            (input_dir/'reference.a7look').write_bytes(source.read_bytes())
            candidate=self.root/'candidate';candidate.mkdir()
            (candidate/f'slot{slot}.bin').write_bytes(raw)
            write_json(candidate/'fit.private.json',{'compiled_look':lookfile.inventory(compiled),'refitted':False})
            self.record('compiled_look_loaded_without_refitting',slot=slot,method=compiled.get('method'))
            self.state['raw_profile_binding']=compiled.get('raw_profile')
            self.state['native_photo_binding']=compiled.get('native_photo')
            if compiled.get('native_photo') is not None:self.state['byte_checks']=True
            return raw
        model=calibration.validate(model,source.suffix.lower()=='.dcp')
        input_dir=self.root/'input';input_dir.mkdir();stored=input_dir/('reference'+source.suffix.lower());stored.write_bytes(source.read_bytes())
        write_json(input_dir/'calibration.json',model)
        entry={'slot':slot,'name':name,'base':'ST','source':{'type':'dcp' if source.suffix.lower()=='.dcp' else 'cube','path':stored.name,'attribution':attribution}}
        if entry['source']['type']=='cube':
            contract=self.state['reference_contract'];entry['source'].update(input_space=contract['input_space'],output_space='srgb')
            if contract.get('bridge'):
                bridge=input_dir/'bridge.cube';bridge.write_bytes(Path(contract['bridge']).read_bytes())
                entry['source']['bridge']={'path':bridge.name,'input_space':'sony-st-srgb','output_space':contract['input_space'],'evidence':'Explicit user-supplied input-space bridge; independent color validation still required'}
        if entry['source']['type']=='dcp':entry['source']['exposure_stops']=model.get('reference_exposure_stops',0)
        if entry['source']['type']=='dcp':
            from .rawidentity import descriptor
            self.state['raw_profile_binding']=descriptor(source,name)
        render,provenance=project.reference(entry,input_dir,model)
        raw,report=native.fit_reference(render,model['response_matrix'],seed=201+slot)
        if not report['convergence']['converged']:raise ValueError('Table fit did not converge')
        candidate=self.root/'candidate';candidate.mkdir();(candidate/f'slot{slot}.bin').write_bytes(raw)
        write_json(candidate/'fit.private.json',{'source':provenance,'calibration_sha256':firmware.sha((input_dir/'calibration.json').read_bytes()),'fit':report})
        self.record('reference_converted',slot=slot,table_sha256=firmware.sha(raw),fit_error=report['synthetic_holdout'])
        return raw
    def _native_bank(self,program,settings,camera):
        from . import photoformat
        records=camera.records(settings)
        return photoformat.extract_bank(program,records[1][0x02a40001].data,
            records[1][0x02a4000d].data,gamma_table_va=0x1209480,
            regular_row=0,still_row=10,color_parameter=0)[0]
    def _prepare(self,camera,name,slot,second,raw):
        values=self._capture(camera,second)
        ap,cp=values['appFw.so'],values['cpapp-b.bin'];self.state['layout']=(device_layout.identify if self._hashes() else device_layout.structural)(ap,cp)
        for span in self.state['source_runtime']['spans']:
            expected=ap[span['offset']:span['offset']+span['length']].hex()
            if span['memory']!=expected or span['disk']!=expected:raise ValueError('Source AP RAM/disk differ; finish the previous reload before importing')
        from . import photoio
        photo_active=photoio.present(cp) or self.state.get('native_photo_binding') is not None
        baseline_program=cp
        if photo_active and self.state['layout'].get('first_install'):
            # First build the existing reviewed table runtime: stock does not
            # yet contain its relocated fifty-row gamma table.
            baseline_program=device_layout.replace(ap,cp,{slot:raw},hash_checks=self._hashes())[2]['cpapp-b.bin']
        bank=self._native_bank(baseline_program,values['settings-ram.bin'],camera) if photo_active else None
        self.state['native_photo_before']=photoio.slot_delta(cp,slot,bank) if photoio.present(cp) else None
        if self.state['layout']['mask']&(1<<(slot-1)):
            from . import rawidentity
            try:self.state['raw_profile_before']=rawidentity.previous(slot,photoio.signature(cp,slot))
            except (OSError,ValueError,KeyError) as error:
                self.state['raw_profile_before']=None;self.record('prior_source_DCP_unavailable',error=str(error))
        f,r,after=(device_layout.deactivate(ap,cp,slot,raw,hash_checks=self._hashes()) if self.state.get('deactivate_slot') else device_layout.replace(ap,cp,{slot:raw},hash_checks=self._hashes(),
            native_photo={slot:self.state.get('native_photo_binding')},native_bank=bank))
        if photo_active:
            from . import photobuild
            self.state['native_photo_runtime_revision']=photobuild.REVISION
        write_json(self.root/'transition/forward.private.json',f);write_json(self.root/'transition/reverse.private.json',r)
        self.state['source_hashes']={n:firmware.sha(values[n]) for n in PROGRAM_PATHS};self.state['target_hashes']={n:firmware.sha(after[n]) for n in PROGRAM_PATHS}
        self.state['settings_plan']=self._planned_settings(ap,camera.records(values['settings-ram.bin']),camera.records(values['settings-saved.bin']))
        self.state['program_build']=nativebuild.build_program({n:values[n] for n in PROGRAM_PATHS},f,r,self.root/'worker/program',self.zig,byte_only=not self._hashes(),
            **({'window_priority':photoio.window_priority} if photo_active else {}))
        renamed,self.state['name_build']=nameworker.prepare({n:values['resources/'+n] for n in nameworker.filenames()},{slot:name},ap,self.state['job_id'],self.root/'worker/names',self.zig,target_ap=after['appFw.so'],label_ids=self.state['layout']['label_ids'],byte_only=not self._hashes())
        del renamed
        # Targets are reproducible from the verified source and selected name;
        # do not keep another complete set of 68 resources on the host.
        checkpoint={'schema':'a7c2-lut-slot-backup/1','slot':slot,'job_id':self.state['job_id'],
            'body':self.state['backup_body'],'source_manifest_sha256':self.state['backup_manifest_sha256'],
            'settings_before':self.state['settings_plan'],'before_table_hex':(six.read_tables(cp) if self._hashes() else device_layout.tables(cp))[slot-1].hex() if self.state['layout']['mask']&(1<<(slot-1)) else None,
            'native_photo_before':self.state['native_photo_before'],
            'name_records_before':{n:resources.decode(values['resources/'+n])['entries'].get(self.state['layout']['label_ids'][slot-1],{}).get('text') for n in nameworker.filenames()}}
        filename=f'slot-{slot}-before.private.json'
        for base,key in zip([self.root,second],['backup_manifest_sha256','backup_mirror_manifest_sha256']):
            backupstore.write_json(base/filename,dict(checkpoint,source_manifest_sha256=self.state[key]))
        self.state['slot_checkpoint_sha256']=firmware.sha((self.root/filename).read_bytes())
        self.state['slot_checkpoint_mirror_sha256']=firmware.sha((second/filename).read_bytes())
        self.artifacts();self.save('PREPARED')
        self._read_programs(camera,self.state['source_hashes'])
        self._invoke(camera,'program',0);self._invoke(camera,'names',0)
        self.save('PREFLIGHT_VERIFIED')
    def _settings(self,camera,restore=False,resume=False):
        self._validate_settings_plan(camera)
        self.save('SETTINGS_RESTORE_INTENT' if restore else 'SETTINGS_WRITE_INTENT')
        before_ram=camera.snapshot(True);before_saved=camera.snapshot(False)
        ram,saved=camera.records(before_ram),camera.records(before_saved);fields=self.state['settings_plan'];changed=False
        if any(ram[0][f['key']].data!=bytes.fromhex(f['before_ram'] if restore else f['after']) for f in fields):
            devicesettings.require_save_preserves_unsaved(ram,saved,{f['key'] for f in fields})
        expected_ram={};expected_saved={}
        for field in fields:
            key=field['key'];want=bytes.fromhex(field['before_ram'] if restore else field['after'])
            current=bytes.fromhex(field['after'] if restore else field['before_ram'])
            current_saved=bytes.fromhex(field['after'] if restore else field['before_saved'])
            allowed_ram=[current,want] if resume else [current]
            allowed_saved=[current_saved,want] if resume else [current_saved]
            if ram[0][key].data not in allowed_ram or saved[0][key].data not in allowed_saved:raise ValueError('Selected settings changed since preparation')
            current=ram[0][key].data
            expected_ram[key]=want.hex();expected_saved[key]=want.hex()
            if camera.property_read(key)!=current:raise ValueError('Independent setting read differs')
            if current!=want:
                self.record('setting_write_intent',key=key,restore=restore,before=current.hex(),after=want.hex())
                camera.property_write(key,want,{f['key'] for f in fields})
                if camera.property_read(key)!=want:raise ValueError('Selected setting readback differs')
                changed=True
        if changed or any(saved[0][f['key']].data!=bytes.fromhex(expected_saved[f['key']]) for f in fields):
            self.record('setting_save_intent',restore=restore);camera.save_settings()
        after_ram=camera.snapshot(True);after_saved=camera.snapshot(False)
        devicesettings.compare(ram,camera.records(after_ram),expected_ram,camera.core)
        devicesettings.compare(saved,camera.records(after_saved),expected_saved,camera.core)
        devicesettings.protected_equal(ram,camera.records(after_ram));devicesettings.protected_equal(saved,camera.records(after_saved))
        self.raw(('restore-' if restore else '')+'settings-ram.bin',after_ram);self.raw(('restore-' if restore else '')+'settings-saved.bin',after_saved)
        self.record('settings_preservation_verified',restore=restore,fields=len(fields));self.save('SETTINGS_RESTORED' if restore else 'SETTINGS_VERIFIED')
    def _validate_settings_plan(self,camera):
        expected=self._planned_settings(self.source('appFw.so'),camera.records(self.source('settings-ram.bin')),camera.records(self.source('settings-saved.bin')))
        if expected!=self.state['settings_plan']:raise ValueError('Selected settings plan differs from the original verified descriptors')
    def _reload(self,camera):
        runtime=self._invoke(camera,'runtime',0)
        if not runtime['boot_id'].strip():raise ValueError('Read-only boot identity unavailable')
        self.state['reload_before_boot_id_sha256']=firmware.sha(runtime['boot_id'].encode('ascii'))
        self.state['reload_before_boot_id']=runtime['boot_id']
        mode=runtime['image_mode'];backend=runtime['image_dev']
        if backend!='*wbi4\n':raise ValueError('Unknown retained-image backend')
        if mode=='2\n':self._invoke(camera,'wbi',1)
        elif mode=='0\n':self.record('retained_image_already_invalidated')
        else:raise ValueError('Unknown retained-image mode; inspect before power changes')
        if self._invoke(camera,'runtime',0)['image_mode']!='0\n':raise ValueError('Retained-image invalidation not verified')
        self.record('reload_prepared');self.save('AWAITING_RELOAD')
    def _install(self,camera):
        if self.state['phase']!='PREFLIGHT_VERIFIED':raise ValueError('New preflight is required; unknown operations cannot be repeated')
        if self.state.get('native_photo_runtime_revision'):
            from .photobuild import REVISION
            if self.state['native_photo_runtime_revision']!=REVISION:raise ValueError('Native-photo runtime changed since prepare; prepare a new job')
        self.state['active_operation']='install'
        self._validate_settings_plan(camera)
        self._read_programs(camera,self.state['source_hashes'])
        self._resource_readback(camera,False)
        for memory,label in [(True,'settings-ram.bin'),(False,'settings-saved.bin')]:
            baseline=camera.records(self.source(label));snapshot=camera.snapshot(memory)
            self.raw('preinstall-'+label,snapshot);fresh=camera.records(snapshot)
            devicesettings.compare(baseline,fresh,{},camera.core)
        self.save('NAME_WRITE_INTENT');self._invoke(camera,'names',1);self._resource_readback(camera,True);self.save('NAMES_VERIFIED')
        self.save('PROGRAM_WRITE_INTENT');self._invoke(camera,'program',1);self._read_programs(camera,self.state['target_hashes']);self.save('PROGRAMS_VERIFIED')
        self._settings(camera);self._reload(camera)
    @serialized
    def create(self,source,name,slot,calibration_path,backup_copy,*,write=False,battery=None,attribution='User-selected reference; original rights apply',input_space=None,bridge=None):
        source=Path(source).resolve()
        if source.suffix.lower() not in ['.dcp','.cube','.a7look'] or not source.is_file():raise ValueError('Select an existing DCP, CUBE or compiled A7LOOK file')
        if not 1<=len(name.encode('utf-8'))<=63 or any(ord(c)<32 for c in name):raise ValueError('Name needs 1..63 UTF-8 bytes without controls')
        if type(slot) is not int or slot not in range(1,7):raise ValueError('Choose custom slot 1..6')
        compiled=source.suffix.lower()=='.a7look'
        if compiled:
            from . import lookfile
            lookfile.writer_document(lookfile.read(source))
            model=None
        else:
            model=json.loads(Path(calibration_path).read_text(encoding='utf-8-sig'));calibration.validate(model,Path(source).suffix.lower()=='.dcp')
        # Reject an invalid reference before USB, including prepare-only jobs.
        from .references import DcpLook,Cube
        if not compiled:(DcpLook if source.suffix.lower()=='.dcp' else Cube)(source)
        if source.suffix.lower()=='.cube':
            if not input_space:raise ValueError('CUBE requires --input-space sony-st-srgb, or a named input space plus --bridge. Log LUT input is not Sony ST.')
            if (input_space=='sony-st-srgb')==bool(bridge):raise ValueError('Direct ST CUBE uses no bridge; other CUBE input spaces require --bridge')
            if bridge:Cube(bridge)
        elif input_space is not None or bridge is not None:raise ValueError('DCP uses the ST rendering bridge; CUBE space options do not apply')
        if write and (type(battery) is not int or not 50<=battery<=100):raise ValueError('Actual battery percentage 50..100 is required for writes')
        second=Path(backup_copy).resolve()
        if second==self.root or second in self.root.parents or self.root in second.parents:raise ValueError('Separate original backup locations required')
        for path in [self.root,second]:
            if path.exists() and (not path.is_dir() or any(path.iterdir())):raise ValueError('Use new empty job and backup directories')
        self.root.mkdir(parents=True,exist_ok=True);second.mkdir(parents=True,exist_ok=True)
        self.state={'schema':'a7c2-lut-device-job/1','job_id':uuid.uuid4().hex[:16],'backup_copy':str(second),'name':name,'slot':slot,'journal':[],'backup_files':{},'camera_writes_requested':write}
        self.state['reference_contract']={'input_space':input_space,'bridge':str(Path(bridge).resolve()) if bridge else None}
        self.save('CREATED')
        try:
            raw=self._fit(source,name,slot,model,attribution);self.save('CONVERTED',conversion_table_sha256=firmware.sha(raw))
            with self.factory() as camera:
                self._prepare(camera,name,slot,second,raw)
                if write:self._install(camera)
        except BaseException as exc:
            prior=self.state['phase'];self.save('NEEDS_REVIEW',failed_during=prior,error=str(exc));raise
        return self.state
    @serialized
    def restore_slot(self,original,battery,backup_copy,*,power_confirmed=False):
        """New transaction restoring one previously imported slot over fresh state.

        First activation returns to the native base picker/recipe. Shared code
        remains available for other slots; complete removal is Recovery's job.
        """
        original.load(hash_checks=False)
        from .power import require_power
        power=require_power(battery,confirmed=power_confirmed)
        if original.state['phase'] not in ['COMPLETE','RELOAD_VERIFIED']:raise ValueError('Verify the original completed installation before slot restoration')
        slot=original.state['slot'];ap=original.source('appFw.so');cp=original.source('cpapp-b.bin')
        old_layout=device_layout.structural(ap,cp)
        deactivate=not old_layout['mask']&(1<<(slot-1))
        raw=device_layout.before_first_table(ap,cp,slot,hash_checks=False) if deactivate else device_layout.tables(cp)[slot-1]
        if deactivate:name='ST'  # Unused project label; native getter follows the restored base recipe.
        else:
            titles={resources.decode(original.source('resources/'+n))['entries'][old_layout['label_ids'][slot-1]]['text'] for n in nameworker.filenames()}
            if len(titles)!=1:raise ValueError('Slot restoration needs one consistent previous imported name across languages')
            name=titles.pop()
        second=Path(backup_copy).resolve()
        if second==self.root or second in self.root.parents or self.root in second.parents:raise ValueError('Separate original backup locations required')
        for path in [self.root,second]:
            if path.exists() and (not path.is_dir() or any(path.iterdir())):raise ValueError('Use new empty job and backup directories')
        self.root.mkdir(parents=True,exist_ok=True);second.mkdir(parents=True,exist_ok=True)
        self.state={'schema':'a7c2-lut-device-job/1','job_id':uuid.uuid4().hex[:16],'backup_copy':str(second),
            'name':name,'slot':slot,'journal':[],'backup_files':{},'camera_writes_requested':True,
            'restore_recipe':{str(f['key']):f['before_saved'] for f in original.state['settings_plan']},
            'deactivate_slot':deactivate,'byte_checks':True,'power_confirmation':power,
            'raw_profile_binding':original.state.get('raw_profile_before'),
            'slot_restore_of':original.state['job_id'],'conversion_table_sha256':firmware.sha(raw)}
        candidate=self.root/'candidate';candidate.mkdir();(candidate/f'slot{slot}.bin').write_bytes(raw)
        write_json(candidate/'restore-recipe.private.json',self.state['restore_recipe'])
        self.save('CONVERTED')
        try:
            with self.factory(original.state['identity']) as camera:
                original_fields=original._planned_settings(ap,camera.records(original.source('settings-ram.bin')),camera.records(original.source('settings-saved.bin')))
                if original_fields!=original.state['settings_plan']:raise ValueError('Original recipe plan differs from its backup')
                prior_table=(original.root/f'candidate/slot{slot}.bin').read_bytes()
                # Guard just the original job's selected result, so later
                # updates to other slots do not block this new transaction.
                current={n:camera.read(p) for n,p in PROGRAM_PATHS.items()}
                layout=device_layout.structural(current['appFw.so'],current['cpapp-b.bin'])
                if (not layout['mask']&(1<<(slot-1)) or device_layout.tables(current['cpapp-b.bin'])[slot-1]!=prior_table):
                    raise ValueError('This selected slot was changed later; preserve it and select its latest job')
                from . import photoio
                previous={n:original.source(n) for n in PROGRAM_PATHS}
                accepted=firmware.apply(previous,json.loads((original.root/'transition/forward.private.json').read_text(encoding='utf-8')),hash_checks=False)
                if photoio.slot_bytes(current['cpapp-b.bin'],slot)!=photoio.slot_bytes(accepted['cpapp-b.bin'],slot):
                    raise ValueError('This selected slot native stages were changed later; select its latest job')
                if photoio.present(cp):
                    old_bank=self._native_bank(cp,original.source('settings-ram.bin'),camera)
                    self.state['native_photo_binding']=photoio.slot_delta(cp,slot,old_bank)
                for n in nameworker.filenames():
                    title=resources.decode(camera.read('/usr/share/app/'+n))['entries'][layout['label_ids'][slot-1]]['text']
                    if title!=original.state['name']:raise ValueError('Selected slot title was changed later')
                for memory in [True,False]:
                    records=camera.records(camera.snapshot(memory))
                    if any(records[0][f['key']].data.hex()!=f['after'] for f in original.state['settings_plan']):raise ValueError('Selected slot recipe was changed later')
                self._prepare(camera,name,slot,second,raw);self._install(camera)
        except BaseException as exc:
            prior=self.state['phase'];self.save('NEEDS_REVIEW',failed_during=prior,error=str(exc));raise
        return self.state
    @serialized
    def install(self,battery=None,*,power_confirmed=False):
        self.load()
        from .power import require_power
        self.state['power_confirmation']=require_power(battery,confirmed=power_confirmed)
        if self.state['phase']!='PREFLIGHT_VERIFIED':raise ValueError('Inspect existing transaction; do not replay')
        try:
            with self.factory(self.state['identity']) as camera:self._install(camera)
        except BaseException as exc:self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=str(exc));raise
        return self.state
    @serialized
    def verify(self,accept_photos=False):
        self.load()
        if self.state['phase'] not in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','RESTORED_AWAITING_RELOAD','RESTORED']:raise ValueError('A completed install/reload preparation is required')
        restore=self.state['phase'] in ['RESTORED_AWAITING_RELOAD','RESTORED']
        prior=self.state['phase']
        self._verify_runtime_ok=False
        try:return self._verify(restore,accept_photos)
        except BaseException as exc:
            if self._verify_runtime_ok:self.record('read_only_verification_rejected',error=str(exc))
            else:self.save('NEEDS_REVIEW',failed_during=prior,error=str(exc))
            raise
    def _verify(self,restore,accept_photos):
        with self.factory(self.state['identity']) as camera:
            programs=self._read_programs(camera,self.state['source_hashes'] if restore else self.state['target_hashes'],allow_later_slots=not restore)
            runtime=self._invoke(camera,'runtime',0);boot=runtime['boot_id'].encode('ascii')
            self._verify_runtime_ok=True
            same_boot=(firmware.sha(boot)==self.state['reload_before_boot_id_sha256']) if self._hashes() else (runtime['boot_id']==self.state['reload_before_boot_id'])
            if not boot.strip() or same_boot:raise ValueError('New boot not observed; do not repeat installation')
            current_names=self._resource_readback(camera,not restore,allow_later_slots=not restore)
            for span in runtime['spans']:
                expected=programs['appFw.so'][span['offset']:span['offset']+span['length']].hex()
                if span['memory']!=expected or span['disk']!=expected:raise ValueError('Loaded AP spans do not match expected source')
            ram=camera.records(camera.snapshot(True));saved=camera.records(camera.snapshot(False))
            for f in self.state['settings_plan']:
                if ram[0][f['key']].data!=bytes.fromhex(f['before_ram'] if restore else f['after']) or saved[0][f['key']].data!=bytes.fromhex(f['before_saved'] if restore else f['after']):raise ValueError('Reloaded selected recipe differs')
            for snapshot,actual in [('settings-ram.bin',ram),('settings-saved.bin',saved)]:
                before=camera.records(self.source(snapshot))
                if not self._later_fl23:devicesettings.protected_equal(before,actual)
                else:
                    for key in (0x02a40000,0x02a40002):
                        if before[1][key]!=actual[1][key]:raise ValueError('Protected CP unit changed')
                    keys=(0x02a40001,0x02a4000d)
                    old=tuple(before[1][k].data for k in keys);new=tuple(actual[1][k].data for k in keys)
                    if old!=new and camera.core.merge_colors(*old)!=new:raise ValueError('CP changes exceed the native FL23 color addition')
            self.record('postreload_storage_and_settings_verified',boot_id_sha256=firmware.sha(boot),CP_running_memory_directly_read=False)
            if accept_photos and not restore and self.state['phase']!='COMPLETE':
                self.record('physical_acceptance_reported_by_user')
                self._verify_runtime_ok=False
                if self._later_name_updates:
                    self.state['name_cleanup_build']=nameworker.prepare_cleanup(self.state['name_build'],
                        self.root/'worker/names/names.private.h',current_names,self.root/'worker/names-cleanup',self.zig)
                    self.artifacts();self.record('name_cleanup_retargeted_after_proved_other_slot_records')
                elif self._later_fl23:
                    # FL23 leaves resources intact; update only the cleanup
                    # worker's AP target before removing this job's old links.
                    _,self.state['name_build']=nameworker.prepare(
                        {n:self.source('resources/'+n) for n in nameworker.filenames()},
                        {self.state['slot']:self.state['name']},self.source('appFw.so'),self.state['job_id'],
                        self.root/'worker/names',self.zig,target_ap=programs['appFw.so'],
                        label_ids=self.state['layout']['label_ids'],byte_only=not self._hashes())
                    self.artifacts();self.record('name_cleanup_retargeted_after_native_fl23')
                self._invoke(camera,'names',3);self._resource_readback(camera,True,allow_later_slots=True)
                self._verify_runtime_ok=True
        self.save(('RESTORED' if restore else 'COMPLETE') if accept_photos else ('RESTORED_AWAITING_RELOAD' if restore else 'RELOAD_VERIFIED'),user_photos_and_preview_confirmed=bool(accept_photos))
        if accept_photos:
            from .rawidentity import after_verified
            from . import photoio
            document={'name':self.state['name'],'raw_profile':self.state.get('raw_profile_before' if restore else 'raw_profile_binding')}
            if document['raw_profile'] is not None:document['camera_signature']=photoio.signature(programs['cpapp-b.bin'],self.state['slot'])
            after_verified(self.state,self.save,self.state['job_id']+('-restore' if restore else ''),
                [document],[self.state['slot']])
        return self.state
    @serialized
    def restore(self,battery):
        self.load()
        if type(battery) is not int or not 50<=battery<=100:raise ValueError('Actual battery percentage 50..100 required')
        if self.state['phase'] not in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','PARTIAL_SETTINGS_VERIFIED','PROGRAMS_VERIFIED','NAMES_VERIFIED']:raise ValueError('Unknown/partial transactions need inspection before restoration')
        phase=self.state['phase'];partial=phase in ['PARTIAL_SETTINGS_VERIFIED','PROGRAMS_VERIFIED']
        self.state['active_operation']='restore'
        try:
            with self.factory(self.state['identity']) as camera:
                if phase=='NAMES_VERIFIED':
                    self._read_programs(camera,self.state['source_hashes']);self._resource_readback(camera,True)
                    self.save('NAME_RESTORE_INTENT');self._invoke(camera,'names',2);self._resource_readback(camera,False);self.save('NAMES_RESTORED')
                    self._reload(camera);self.save('RESTORED_AWAITING_RELOAD');return self.state
                self._read_programs(camera,self.state['target_hashes']);self._resource_readback(camera,True)
                self._settings(camera,True,resume=partial);self.save('PROGRAM_RESTORE_INTENT');self._invoke(camera,'program',2);self._read_programs(camera,self.state['source_hashes']);self.save('PROGRAMS_RESTORED')
                self.save('NAME_RESTORE_INTENT');self._invoke(camera,'names',2);self._resource_readback(camera,False);self.save('NAMES_RESTORED')
                self._reload(camera);self.save('RESTORED_AWAITING_RELOAD')
        except BaseException as exc:self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=str(exc));raise
        return self.state
    @serialized
    def recover(self):
        """Recover evidence, never execute a loader or repeat a write."""
        self.load()
        if self.state['phase']!='NEEDS_REVIEW':return self.state
        if self.state.get('failed_during') in ['SETTINGS_WRITE_INTENT','SETTINGS_RESTORE_INTENT']:
            with self.factory(self.state['identity']) as camera:
                self._read_programs(camera,self.state['target_hashes']);self._resource_readback(camera,True)
                samples=[]
                for _ in range(3):samples.append((camera.records(camera.snapshot(True)),camera.records(camera.snapshot(False))))
                values=[]
                for ram,saved in samples:
                    row=[]
                    for f in self.state['settings_plan']:
                        key=f['key'];a,b=ram[0][key].data,saved[0][key].data
                        if a not in [bytes.fromhex(f['before_ram']),bytes.fromhex(f['after'])] or b not in [bytes.fromhex(f['before_saved']),bytes.fromhex(f['after'])]:raise ValueError('Settings recovery found a value outside this job')
                        row.append((a,b))
                    values.append(row)
                if values[0]!=values[1] or values[1]!=values[2]:raise ValueError('Selected settings still changing; do not write')
                devicesettings.protected_equal(camera.records(self.source('settings-ram.bin')),samples[-1][0])
                for memory,baseline,actual in [(True,'settings-ram.bin',samples[-1][0]),(False,'settings-saved.bin',samples[-1][1])]:
                    expected={f['key']:actual[0][f['key']].data.hex() for f in self.state['settings_plan']}
                    devicesettings.compare(camera.records(self.source(baseline)),actual,expected,camera.core)
                self.record('stable_partial_settings_observed_without_writes')
                self.save('PARTIAL_SETTINGS_VERIFIED')
            return self.state
        intent=next((event for event in reversed(self.state.get('journal',[])) if event['event']=='native_intent'),None)
        if intent is None:
            self.record('recovery_no_native_intent');return self.state
        result=intent['result'];kind='program' if 'install.result' in result else 'names' if 'names.result' in result else 'wbi' if 'wbi.result' in result else 'runtime' if 'runtime.result' in result else None
        if kind is None:raise ValueError('Inspect unsupported pending native operation without executing')
        mode=intent['mode'];build=self.state.get('program_build' if kind=='program' else 'name_build',{})
        if kind=='names' and mode==3:build=self.state.get('name_cleanup_build',build)
        blob_path=self.root/('worker/program/program.so' if kind=='program' else 'worker/names/names.so') if kind in ['program','names'] else nativebuild.ROOT/('src/fl23/assets/'+kind+'.so')
        if kind=='names' and mode==3 and 'name_cleanup_build' in self.state:blob_path=self.root/'worker/names-cleanup/names.so'
        blob=blob_path.read_bytes()
        if self._hashes() and firmware.sha(blob)!=intent['worker_sha256']:raise ValueError('Pending worker differs; preserve original evidence')
        with self.factory(self.state['identity']) as camera:
            raw=camera.temp_read(result,True)
            if raw is None:
                # A clean read-only invocation may have finished before a host
                # verification (e.g. unchanged boot) failed. Never replay it.
                tail=self.state['journal'][self.state['journal'].index(intent)+1:]
                cleaned=any(e['event']=='native_cleanup_verified' and e['stage']==intent['stage'] and e['mode']==mode for e in tail)
                prior=self.state.get('failed_during')
                if cleaned and prior in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','RESTORED_AWAITING_RELOAD','RESTORED']:
                    self.record('read_only_check_finished_no_write_replayed');self.save(prior);return self.state
                self.record('pending_result_not_available');return self.state
            self.raw('recovered-'+kind+'-'+str(mode)+'.bin',raw)
            recovered_failure=False
            if kind in ['program','names']:
                try:
                    if kind=='program':worker.validate_worker_report(raw,mode,build['contract'])
                    else:nameworker.validate(raw,mode,build)
                except ValueError:
                    self._known_native_failure(camera,kind,mode,raw,build);recovered_failure=True
            elif kind=='wbi':camera.core.parse_native('wbi',raw,mode)
            else:camera.core.parse_native('runtime',raw)
            if 'source_hashes' in self.state and not recovered_failure:
                before=(kind=='program' and mode in [0,2]) or (kind=='names' and mode!=3) or (self.state.get('active_operation')=='restore' and kind in ['wbi','runtime'])
                # Names preflight occurs before a new program install.
                if kind=='names' and mode==0:before=True
                self._read_programs(camera,self.state['source_hashes'] if before else self.state['target_hashes'])
            if kind=='names' and not recovered_failure:self._resource_readback(camera,mode!=2 and mode!=0,allow_later_slots=mode==3)
            expected={intent['stage']:blob,'libJit.so':blob,result:raw}
            if kind=='runtime':
                extra=camera.temp_read('a7c2.probe.result');camera.core.parse_native('probe',extra);expected['a7c2.probe.result']=extra
            else:
                magic=b'A7INS001' if kind=='program' else b'A7NAM001' if kind=='names' else b'A7WBI001'
                expected[result.replace('.result','.request')]=struct.pack('<8sII',magic,mode,0)
            for name,value in expected.items():
                current=camera.temp_read(name,True)
                if current is not None and current!=value:raise ValueError('Unexpected pending contents; recovery will not delete them')
            for name in reversed(list(expected)):
                if camera.temp_read(name,True) is not None:camera.temp_remove(name)
                if camera.temp_read(name,True) is not None:raise ValueError('Recovery cleanup incomplete')
            self.record('existing_result_recovered_without_reexecution',kind=kind,mode=mode)
        if recovered_failure:
            if kind=='program':self.save('NAMES_VERIFIED' if mode==1 else 'SETTINGS_RESTORED')
            elif mode==1:self.save('PREFLIGHT_VERIFIED')
            else:self.save('PARTIAL_NAMES_RESTORE_VERIFIED')
            return self.state
        # Later phases require fresh explicit continuation, never run here.
        if mode==1 and kind=='program':self.save('PROGRAMS_VERIFIED')
        elif mode==1 and kind=='names':self.save('NAMES_VERIFIED')
        elif mode==2:self.save('PROGRAMS_RESTORED' if kind=='program' else 'NAMES_RESTORED')
        elif mode==1 and kind=='wbi':
            self.save('RESTORED_AWAITING_RELOAD' if self.state.get('active_operation')=='restore' else 'AWAITING_RELOAD')
        elif mode==3 and kind=='names':
            accepted=any(e['event']=='physical_acceptance_reported_by_user' for e in self.state['journal'])
            self.save('COMPLETE' if accepted else 'RELOAD_VERIFIED',user_photos_and_preview_confirmed=accepted)
        elif kind=='runtime':
            prior=self.state.get('failed_during')
            if prior in ['AWAITING_RELOAD','RELOAD_VERIFIED','COMPLETE','RESTORED_AWAITING_RELOAD','RESTORED']:self.save(prior)
            elif prior in ['SETTINGS_VERIFIED','SETTINGS_RESTORED','PROGRAMS_RESTORED','NAMES_RESTORED']:self.save(prior)
        return self.state
    @serialized
    def resume(self,battery):
        self.load()
        if type(battery) is not int or not 50<=battery<=100:raise ValueError('Actual battery percentage 50..100 required')
        if self.state['phase'] not in ['PROGRAMS_VERIFIED','NAMES_VERIFIED','SETTINGS_VERIFIED','PARTIAL_SETTINGS_VERIFIED','SETTINGS_RESTORED','PROGRAMS_RESTORED','NAMES_RESTORED','PARTIAL_NAMES_RESTORE_VERIFIED']:
            raise ValueError('Recover the existing result first; unknown/partial settings cannot be replayed')
        try:
            with self.factory(self.state['identity']) as camera:
                if self.state.get('active_operation')=='restore':
                    self._resume_restore(camera);return self.state
                if self.state['phase']=='NAMES_VERIFIED':
                    self._read_programs(camera,self.state['source_hashes']);self._resource_readback(camera,True)
                    self.save('PROGRAM_WRITE_INTENT');self._invoke(camera,'program',1);self._read_programs(camera,self.state['target_hashes']);self.save('PROGRAMS_VERIFIED')
                else:self._read_programs(camera,self.state['target_hashes'])
                if self.state['phase'] in ['PROGRAMS_VERIFIED','PARTIAL_SETTINGS_VERIFIED']:self._settings(camera,resume=self.state['phase']=='PARTIAL_SETTINGS_VERIFIED')
                self._reload(camera)
        except BaseException as exc:self.save('NEEDS_REVIEW',failed_during=self.state['phase'],error=str(exc));raise
        return self.state
    def _resume_restore(self,camera):
        phase=self.state['phase']
        if phase in ['PARTIAL_SETTINGS_VERIFIED','SETTINGS_RESTORED']:
            self._read_programs(camera,self.state['target_hashes']);self._resource_readback(camera,True)
            if phase=='PARTIAL_SETTINGS_VERIFIED':self._settings(camera,True,resume=True)
            self.save('PROGRAM_RESTORE_INTENT');self._invoke(camera,'program',2);self._read_programs(camera,self.state['source_hashes']);self.save('PROGRAMS_RESTORED')
        if self.state['phase'] in ['PROGRAMS_RESTORED','PARTIAL_NAMES_RESTORE_VERIFIED']:
            self._read_programs(camera,self.state['source_hashes'])
            if self.state['phase']=='PROGRAMS_RESTORED':self._resource_readback(camera,True)
            self.save('NAME_RESTORE_INTENT');self._invoke(camera,'names',2);self._resource_readback(camera,False);self.save('NAMES_RESTORED')
        if self.state['phase']!='NAMES_RESTORED':raise ValueError('No proven remaining restoration phase')
        self._read_programs(camera,self.state['source_hashes']);self._resource_readback(camera,False)
        self._reload(camera);self.save('RESTORED_AWAITING_RELOAD')
    def _known_native_failure(self,camera,kind,mode,raw,build):
        """A failed, authenticated report is different from an unknown outcome.

        Advance only after full source/target classification. Recovery itself
        performs no loader invocation; a later explicit resume is required.
        """
        if mode not in [1,2]:raise ValueError('A failed preflight requires inspection')
        if kind=='program':
            if len(raw)!=240:raise ValueError('Unknown failed program ABI')
            v=worker.REPORT.unpack_from(raw)
            if v[:3]!=(b'A7IRP001',1,mode) or v[5]>=0 or any(v[i] for i in [6,8,9,10]):raise ValueError('Unverified program rollback/read-only state')
            self._read_programs(camera,self.state['source_hashes'] if mode==1 else self.state['target_hashes'])
            self._resource_readback(camera,True)
        else:
            if len(raw)!=nameworker.REPORT.size:raise ValueError('Unknown failed names ABI')
            v=nameworker.REPORT.unpack(raw)
            if v[:3]!=(b'A7NMR001',1,mode) or v[4]!=build['count'] or v[5]>=0 or any(v[i] for i in [6,8,9,10]):raise ValueError('Unverified resource rollback/read-only state')
            wanted=build['AP']
            if self._hashes() and v[18].hex()!=wanted:raise ValueError('Failed names report AP differs')
            self._read_programs(camera,self.state['source_hashes'])
            classes=[]
            for spec in build['files']:
                blob=camera.read('/usr/share/app/'+spec['file'])
                candidates=['before'] if mode==1 else ['before','after']
                if self._hashes():which=next((k for k in candidates if len(blob)==spec[k+'_bytes'] and firmware.sha(blob)==spec[k+'_sha256']),None)
                else:which=next((k for k in candidates if blob==(self.source('resources/'+spec['file']) if k=='before' else self.resource_target(spec['file']))),None)
                if which is None:raise ValueError('Failed resource outcome is outside this job')
                classes.append(which)
            self.record('known_resource_failure_classified',files=classes)
        self.record('known_native_failure_verified_without_reexecution',kind=kind,mode=mode)
