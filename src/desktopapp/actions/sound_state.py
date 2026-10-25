"""Inspect currently loaded sound code without an installation-job prerequisite."""
from pathlib import Path
import sys
import uuid
from ..paths import ROOT,write_json


def verify(args,job):
    sys.path.insert(0,str(ROOT/'src/shutter_sound'))
    import boot_sound,boot_trial,candidate,trial
    from replacement import CurrentRequest
    from looktool.devicesession import invoke
    root=Path(args['workspace'])/('inspect-'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
    state=dict(schema='a7c2-current-sound-check/1',history=[],pending=None,journal=[])
    files_removed=False
    def record(event,**fields):
        state['journal'].append(dict(event=event,**fields))
        write_json(root/'inspection.private.json',state)
    with CurrentRequest(root,state,'verify'):
        with trial.factory() as camera:
            ap=camera.read('/usr/lib/appFw.so');cp=camera.read('/cp/cpapp-b.bin')
            enabled=candidate.is_enabled(cp);candidate.guard(ap,cp,installed=enabled)
            custom=boot_sound.installed(ap)
            probe=boot_trial.current_probe(ap,root/'probe')
            camera.programs_pinned=True
            loaded=invoke(camera,Path(probe).read_bytes(),stage='lut-runtime-staged.so',request=None,
                result='shutter.probe.result',contents=None,mode=0,decode=candidate.parse_probe,
                record=record,save_raw=lambda raw:(root/'report.private.bin').write_bytes(raw),extras=('a7c2.probe.result',))
            candidate.require_registry(loaded)
            size=0
            if custom:
                current=boot_trial.current_sound(camera.read(boot_trial.PATHS[1],True))
                if current is None:raise ValueError('当前自定义声音配置不存在，请重新保存或恢复原厂音效。')
                path,size=current
                if len(camera.read(path))!=size:raise ValueError('当前声音文件长度与配置不同。')
                descriptor=loaded['entries'][2]
                if (descriptor['kind']!=3 or descriptor['length']!=size or
                        descriptor['filename_prefix']!='/usr' or not descriptor['native_handle']&0x8000):
                    raise ValueError('当前声音尚未按磁盘配置加载，请按写入后的提示断电重开。')
            elif candidate.sound_state(cp) in ('muted','mechanical_only'):
                # Finish a current-state sound reset after the original AP loader
                # has reloaded. No old sound job or audition evidence is required.
                from looktool.direct import DirectJob
                owner=DirectJob(root);owner.state=state;owner.state_path=root/'inspection.private.json'
                owner.cleanup_sound_resources(camera);files_removed=True
    return dict(phase='owner_confirmed_working' if args.get('accepted') else 'loaded_owner_confirmation_pending',
        workspace=str(root),camera_io=True,camera_firmware_written=False,camera_settings_written=False,
        sound_support_enabled_on_disk=enabled,custom_sound_on_disk=custom,audio_bytes=size,
        loaded_code_and_current_descriptor_verified=True,private_sound_files_removed=files_removed)
