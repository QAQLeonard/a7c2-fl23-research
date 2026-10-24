"""Migrate legacy portrait edits to independent, same-ID native image banks."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sys
from .paths import ROOT,write_json


def enable_current(camera,owner,job):
    """Only the saved display switch changes; no name-resource capture."""
    from looktool import verticalpersist
    from looktool.checkpointjob import Rollback
    from looktool.resourceworker import Resources
    from verticaltool import device
    before={'appFw.so':camera.read('/usr/lib/appFw.so'),
        'settings-ram.bin':camera.snapshot(True),'settings-saved.bin':camera.snapshot(False)}
    prepared=owner.settings(camera,before,[verticalpersist.field(before['appFw.so'],camera.records(before['settings-ram.bin']),True),{}])
    running=device.Workers(camera,owner).probe()['value']
    Resources(camera,owner,'portrait').inspect()
    changed=prepared[1]!=prepared[3] or prepared[2]!=prepared[4] or running!=0
    runtime=owner.native(camera,'runtime',0)
    if runtime['image_mode'].strip() not in ('0','2') or not runtime.get('boot_id','').strip():
        raise ValueError('Camera reload state is unavailable; vertical switch not saved')
    owner.state['source_boot_id']=runtime['boot_id'].strip()
    owner.state['native_portrait']=True
    if changed:
        owner.save('RESTORING_SETTINGS')
        Rollback.restore_settings(owner,camera,prepared)
        if runtime['image_mode'].strip()=='2':owner.native(camera,'wbi',0);owner.native(camera,'wbi',1)
    owner.save('AWAITING_RELOAD' if changed else 'LOADED')
    write_json(Path(job)/'backend-workspace.private.json',dict(action='vertical_enable',workspace=str(owner.root)))
    return dict(workspace=str(owner.root),phase=owner.state['phase'],mode='vertical_enable',
        native_portrait=True,reload_required=changed)


def run(args,job,*,factory=None):
    from looktool.checkpointjob import CheckpointCamera
    from looktool.direct import DirectJob
    from looktool.portraitjob import PortraitJob
    from looktool.resourceworker import Resources,PORTRAIT_NAMES
    from looktool import checkpoint,verticalpersist
    from looktool.power import require_power
    require_power(confirmed=args.get('power_confirmed',False))
    if args['firmware']!='2.01':raise ValueError('Native portrait display supports ILCE-7CM2 2.01 only')
    sys.path.insert(0,str(ROOT/'src/vertical'))
    from verticaltool import nativeportrait,device
    root=Path(args['workspace'])
    with (factory or CheckpointCamera)() as camera:
        @contextmanager
        def reuse(expected=None):
            if expected:checkpoint.same_body(expected,camera.identity)
            yield camera
        owner=DirectJob(root/'resources',factory=reuse)
        owner.root.mkdir(parents=True,exist_ok=True)
        owner.state=dict(schema='a7c2-direct-job/1',mode='vertical_native_resources',journal=[],identity=camera.identity)
        owner.save('READING')
        from looktool.requestcleanup import supersede_temporary
        supersede_temporary(camera,owner.root/'evidence/prior-temporary',owner.record)
        camera.programs_pinned=True;camera.byte_checks=True
        if camera.identity_pending:device.prepare_camera(camera,owner)
        owner.state['identity']=camera.identity
        existing=[camera.read(path,True) for path in device.ALIASES]
        is_native=[nativeportrait.owned(value) for value in existing]
        if all(is_native):
            expected=nativeportrait.targets([camera.read(path) for path in device.SOURCES])
            if existing!=expected:raise ValueError('Native portrait banks differ from this body')
            return enable_current(camera,owner,job)
        if not any(is_native):
            legacy=PortraitJob(root/'retire-legacy',factory=reuse)
            write_json(Path(job)/'backend-workspace.private.json',dict(action='vertical_enable',workspace=str(legacy.root)))
            result=legacy.run_frames(False,version='2.01',power_confirmed=True)
            if result['phase']=='AWAITING_RELOAD':
                return dict(result,mode='vertical_native_prepare',native_portrait=False,
                    migration_pending=True,message='旧竖屏补偿已撤回，尚未安装原生资源。按提示完整断电重开，再点击“开启竖屏显示”继续。')
        write_json(Path(job)/'backend-workspace.private.json',dict(action='vertical_enable',workspace=str(owner.root)))
        try:
            for memory in (True,False):
                if camera.records(camera.snapshot(memory))[0][verticalpersist.SETTING].data!=b'\1':
                    raise ValueError('原生竖屏资源准备前必须先关闭竖屏；本次未复制资源')
            sources=[camera.read(path) for path in device.SOURCES]
            targets=nativeportrait.targets(sources)
            existing=[camera.read(path,True) for path in device.ALIASES]
            if any(value is not None and value!=target for value,target in zip(existing,targets)):
                raise ValueError('Unaccounted portrait resource; no file was overwritten')
            folder=root/'prepared';folder.mkdir(parents=True,exist_ok=True)
            manifest={}
            for name,value in zip(PORTRAIT_NAMES,targets):
                (folder/name).write_bytes(value)
                manifest[name]=dict(bytes=len(value),sha256=sha256(value).hexdigest())
            # Native worker checks old layout references/gauge code and OFF in
            # loaded RAM before every chunk; no new AP code or image IDs.
            Resources(camera,owner,'portrait').restore(folder,manifest)
            owner.record('native_portrait_banks_fully_verified',files=manifest)
            return dict(enable_current(camera,owner,job),resource_bytes=sum(r['bytes'] for r in manifest.values()))
        except BaseException as error:
            owner.save('NEEDS_REVIEW',error=str(error));raise
