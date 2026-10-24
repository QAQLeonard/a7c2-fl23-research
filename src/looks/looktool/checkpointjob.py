"""Restore an initial checkpoint over the current FL23/LUT state."""
import json
from pathlib import Path
import struct
import uuid
from . import checkpoint, checkpointworker, devicesettings, nameworker, nativebuild
from .devicesession import Camera, invoke
from .backupstore import write_json

TEMPS={'checkpoint.staged.so','checkpoint.program.request','checkpoint.program.result',
       'checkpoint.names.request','checkpoint.names.result','shutter.staged.so','shutter.probe.result'}


def program_difference(expected, actual):
    """Describe a byte mismatch without exporting programs or body data."""
    if expected == actual:return None
    common=min(len(expected),len(actual))
    first=common
    for start in range(0,common,4096):
        end=min(start+4096,common)
        if expected[start:end]!=actual[start:end]:
            first=next(at for at in range(start,end) if expected[at]!=actual[at])
            break
    return dict(expected_bytes=len(expected),actual_bytes=len(actual),first_difference=hex(first))


class CheckpointCamera(Camera):
    """Same body-bound service session, narrow checkpoint temporary namespace."""
    def _connect(self):
        if self.allow_service_resume:return super()._connect()
        if not self.expected or self.expected.get('usb_serial_sha256'):return super()._connect()
        # Original FL23 workspaces have the normal Sony body serial only.
        # Use that existing identity rather than rejecting legacy backup2.
        from .devicesession import modules
        transport,self.core=modules()
        self.link=transport.Session({k:self.expected[k] for k in ('model','serial_sha256')})
        self.link.__enter__();self.identity=self.link.identity;self.service_only=False
        return self
    def temp_read(self,name,missing=False):
        if name in TEMPS:return self.link.read('/tmp/jiritsu/'+name,missing)
        return super().temp_read(name,missing)
    def temp_write(self,name,data):
        if name in TEMPS:
            if self.identity_pending or not self.programs_pinned or self.service_only:raise ValueError('Body identity required before checkpoint execution')
            if not data or len(data)>65536:raise ValueError('Checkpoint staging limit exceeded')
            self.link.select('/tmp/jiritsu/'+name);return self.link.jiritsu(16,b'\0\xff\0'+data)
        return super().temp_write(name,data)
    def temp_remove(self,name):
        if name in TEMPS:
            self.link.select('/tmp/jiritsu/'+name);return self.link.jiritsu(18,b'\0\xff')
        return super().temp_remove(name)

class Rollback:
    def __init__(self,folder,*,factory=CheckpointCamera,zig=None):
        self.root=Path(folder).resolve();self.factory=factory;self.zig=zig
        self.state_path=self.root/'rollback.private.json'
    def save(self,phase,**values):
        self.state.update(values,phase=phase);write_json(self.state_path,self.state)
        print('Rollback:',phase,flush=True)
    def record(self,event,**values):
        self.state.setdefault('journal',[]).append({'event':event,**values});write_json(self.state_path,self.state)
    def raw(self,name,raw):
        folder=self.root/'evidence';folder.mkdir(exist_ok=True)
        (folder/(uuid.uuid4().hex[:8]+'-'+name)).write_bytes(raw)
    def native(self,camera,kind,mode,build=None):
        extras=()
        if kind=='program':
            path=Path(build['path']);magic=b'A7INS001'
            request,result='checkpoint.program.request','checkpoint.program.result'
            decode=lambda raw:checkpointworker.program_report(raw,mode,build)
        elif kind in ('names','purge'):
            path=Path(build['path']);magic=b'A7NAM001'
            request,result='checkpoint.names.request','checkpoint.names.result'
            decode=((lambda raw:checkpointworker.purge_report(raw,build)) if kind=='purge' else
                    (lambda raw:checkpointworker.names_report(raw,mode,build)))
        elif kind=='wbi':
            path=nativebuild.ROOT/'src/fl23/assets/wbi.so';magic=b'A7WBI001'
            request,result='a7c2.wbi.request','a7c2.wbi.result'
            decode=lambda raw:camera.core.parse_native('wbi',raw,mode)
        else:
            path=nativebuild.ROOT/'src/fl23/assets/runtime.so';magic=None
            request,result=None,'a7c2.runtime.result';extras=('a7c2.probe.result',)
            decode=lambda raw:camera.core.parse_native('runtime',raw)
        return invoke(camera,path.read_bytes(),stage='checkpoint.staged.so',request=request,result=result,
            contents=struct.pack('<8sII',magic,mode,0) if request else None,mode=mode,decode=decode,
            record=self.record,save_raw=lambda raw:self.raw(kind+'-'+str(mode)+'.bin',raw),extras=extras)
    def capture(self,camera):
        print('Reading current programs, look settings and names.',flush=True)
        values={name:camera.read(path) for name,path in checkpoint.PROGRAM_PATHS.items()}
        # Body and user-confirmed 2.01, no firmware origin/hash admission.
        camera.programs_pinned=True
        values['settings-ram.bin']=camera.snapshot(True);values['settings-saved.bin']=camera.snapshot(False)
        for name in nameworker.filenames():values['resources/'+name]=camera.read('/usr/share/app/'+name)
        return values
    def readback(self,camera,target):
        for name,path in checkpoint.PROGRAM_PATHS.items():
            actual=camera.read(path)
            difference=program_difference(target[name],actual)
            if difference:
                self.record('program_readback_mismatch',result=dict(program=name,**difference))
                raise ValueError('Full program readback differs: '+name+
                    '; first difference='+difference['first_difference']+
                    '; expected bytes='+str(difference['expected_bytes'])+
                    '; actual bytes='+str(difference['actual_bytes']))
        for name in nameworker.filenames():
            if camera.read('/usr/share/app/'+name)!=target['resources/'+name]:raise ValueError('Full name readback differs: '+name)
        self.record('complete_program_and_name_bytes_verified')
    def settings_plan(self,camera,current,target):
        keys=checkpoint.recipe_keys(target['appFw.so'])
        ram,saved=[camera.records(target['settings-'+n+'.bin']) for n in ('ram','saved')]
        live,stored=[camera.records(current['settings-'+n+'.bin']) for n in ('ram','saved')]
        for chip,selected in [(0,keys),(1,checkpoint.CP_KEYS)]:
            for key in selected:
                if any(key not in r[chip] for r in [ram,saved,live,stored]):raise ValueError('Checkpoint look field missing: '+hex(key))
                if len({len(r[chip][key].data) for r in [ram,saved,live,stored]})!=1:raise ValueError('Checkpoint look field layout differs')
        if any(stored[0][k].data!=saved[0][k].data for k in keys):
            devicesettings.require_save_preserves_unsaved(live,stored,set(keys))
        # Group save must not overwrite other unsaved CP color/calibration data.
        if any(stored[1][k].data!=saved[1][k].data for k in checkpoint.CP_KEYS):
            for key,value in live[1].items():
                if key>>16==0x02a4 and key not in checkpoint.CP_KEYS:
                    other=stored[1].get(key)
                    if other is None or (value.data,value.attr)!=(other.data,other.attr):raise ValueError('Save current CP settings before rollback')
        return keys,ram,saved,live,stored
    def restore_settings(self,camera,plan):
        keys,ram,saved,before_ram,before_saved=plan
        for chip,selected in [(1,checkpoint.CP_KEYS),(0,keys)]:
            read=(camera.link.cp_read if chip else camera.property_read)
            write=(camera.link.cp_write if chip else lambda k,v:camera.property_write(k,v,set(keys)))
            if any(before_saved[chip][k].data!=saved[chip][k].data for k in selected):
                for key in selected:
                    value=saved[chip][key].data
                    if read(key)!=value:write(key,value)
                    if read(key)!=value:raise ValueError('Look field readback differs: '+hex(key))
                camera.link.call(camera.link.camera.saveBackup,0x02a4 if chip else 0x02cf)
            for key in selected:
                value=ram[chip][key].data
                if read(key)!=value:write(key,value)
        self.after_settings_write(camera,plan)
        actual_ram,actual_saved=camera.records(camera.snapshot(True)),camera.records(camera.snapshot(False))
        for previous,actual,wanted in [(before_ram,actual_ram,ram),(before_saved,actual_saved,saved)]:
            expected={(0,k):wanted[0][k].data for k in keys}
            expected.update({(1,k):wanted[1][k].data for k in checkpoint.CP_KEYS})
            expected=self.settings_readback_expected(previous,actual,expected)
            # Restrict comparison to writable AP02cf and CP02a4; skip telemetry.
            scope=lambda r:[{k:v for k,v in r[0].items() if k>>16==0x02cf and k!=devicesettings.SAVED_TELEMETRY},
                            {k:v for k,v in r[1].items() if k>>16==0x02a4}]
            camera.core.verify_preservation(scope(previous),scope(actual),expected)
        self.record('saved_and_live_look_settings_restored')
    def after_settings_write(self,camera,plan):
        """Direct jobs synchronize the native model before the final snapshots."""
        pass
    def settings_readback_expected(self,before,after,expected):
        return expected
    def run(self,archive,battery,firmware_version,*,power_confirmed=False):
        if firmware_version!='2.01':raise ValueError('Read the camera version page: rollback supports 2.01 only')
        from .power import require_power
        power=require_power(battery,confirmed=power_confirmed)
        manifest,target=checkpoint.load_target(archive)
        if self.root.exists() and any(self.root.iterdir()):raise ValueError('Use a new rollback work directory; preserve previous results')
        self.root.mkdir(parents=True,exist_ok=True)
        print('Rollback work:',self.root,flush=True)
        self.state={'schema':'a7c2-checkpoint-rollback/1','identity':manifest['identity'],'journal':[],
            'target':str(Path(archive).resolve()),'limitations':manifest['limitations'],'power_confirmation':power}
        self.save('READING')
        try:
            with self.factory(manifest['identity']) as camera:
                checkpoint.same_body(manifest['identity'],camera.identity)
                from .requestcleanup import supersede_temporary
                supersede_temporary(camera,self.root/'evidence/superseded-temporary',self.record)
                current=self.capture(camera)
                checkpoint.write(self.root/'before.private.zip',current,camera.identity,provenance={'type':'before-full-rollback'})
                # Old FL23 backups carry their own body serial/programs/settings.
                # Reconstruct appended names from current native records; never
                # ask for a LUT job or an unrelated working directory.
                if manifest.get('legacy_raw'):
                    target=checkpoint.complete_legacy_names(target,current)
                    checkpoint.write(self.root/'target.private.zip',target,manifest['identity'],
                        provenance=manifest['provenance'],limitations=manifest['limitations'])
                    self.record('legacy_fl23_target_completed_without_lut_job')
                else:checkpoint.copy(checkpoint.archive_path(archive),self.root/'target.private.zip')
                settings=self.settings_plan(camera,current,target)
                self.save('BUILDING')
                programs=checkpointworker.build_programs(current,target,self.root/'worker',self.zig)
                names=checkpointworker.build_names(current,target,self.root/'worker',uuid.uuid4().hex[:16],self.zig)
                for build in programs:self.native(camera,'program',0,build)
                if names:self.native(camera,'names',4,names)
                runtime=self.native(camera,'runtime',0)
                if runtime['image_mode'].strip() not in ('0','2'):raise ValueError('Unsupported retained image state')
                self.save('PREFLIGHT_VERIFIED',programs=programs,names=names,runtime=runtime)
                self.save('WRITING_PROGRAMS')
                for index,build in enumerate(programs):
                    self.record('program_batch_intent',batch=index);self.native(camera,'program',1,build)
                # A fresh transaction over current files; no comparison to an
                # old LUT job's output, and no need to reverse jobs in order.
                for name,path in checkpoint.PROGRAM_PATHS.items():
                    if camera.read(path)!=target[name]:raise ValueError('Complete program readback differs: '+name)
                self.save('RESTORING_NAMES')
                if names:self.native(camera,'names',2,names)
                self.readback(camera,target)
                self.save('RESTORING_LOOK_SETTINGS');self.restore_settings(camera,settings)
                runtime=self.native(camera,'runtime',0)
                if runtime['image_mode'].strip()=='2':
                    self.native(camera,'wbi',0);self.native(camera,'wbi',1)
                elif runtime['image_mode'].strip()!='0':raise ValueError('Unsupported retained image state')
            self.save('RESTORED_AWAITING_RELOAD')
            print('All I/O ended. Disconnect USB/power, shut down normally, wait for the access lamp, remove battery for ≥1 minute. Restart and check preview/photos/playback, then run: python recovery.py verify "'+str(self.root)+'" --accept-photos',flush=True)
            return self.state
        except BaseException as exc:
            self.save('NEEDS_REVIEW',error=str(exc));raise
    def verify(self,accept_photos=False):
        self.state=json.loads(self.state_path.read_text(encoding='utf-8'))
        if self.state['phase'] not in ('RESTORED_AWAITING_RELOAD','LOADED','COMPLETE'):raise ValueError('Rollback did not finish; inspect evidence before further actions')
        manifest,target=checkpoint.read(self.root/'target.private.zip')
        with self.factory(manifest['identity']) as camera:
            checkpoint.same_body(manifest['identity'],camera.identity);camera.programs_pinned=True
            self.readback(camera,target)
            wanted=camera.records(target['settings-saved.bin'])
            for memory in (False,True):
                actual=camera.records(camera.snapshot(memory))
                for chip,selected in [(0,checkpoint.recipe_keys(target['appFw.so'])),(1,checkpoint.CP_KEYS)]:
                    if any(actual[chip][k].data!=wanted[chip][k].data for k in selected):raise ValueError('Reloaded look settings differ')
            runtime=self.native(camera,'runtime',0)
            for span in runtime['spans']:
                expected=target['appFw.so'][span['offset']:span['offset']+span['length']].hex()
                if span['memory']!=expected or span['disk']!=expected:raise ValueError('Old AP is still loaded; complete a cold restart')
        self.save('COMPLETE' if accept_photos else 'LOADED',physical_checks_accepted=accept_photos,
            loaded_state_scope='AP probe spans; CP RAM and physical behavior require user checks')
        return self.state
