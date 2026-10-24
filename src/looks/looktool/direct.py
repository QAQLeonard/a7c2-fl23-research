"""Backup-free project operations over fresh camera bytes.

Original firmware is a reference, not another body's backup. Only transaction
windows and target settings are retained; no complete body backup is created.
"""
import copy
import base64
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import struct
import uuid
import zlib
from . import checkpoint, checkpointworker, device_layout, devicesettings, nameworker, resources
from . import nativebuild, photoformat, photoio, six
from .checkpointjob import CheckpointCamera, Rollback, program_difference
from .devicesession import invoke, modules
from .power import require_power
from .backupstore import write_json

MENU_FLAGS = (0x59892ca, 0x5989382)
ST_ADJUSTMENTS = (0, 0, 0, 0, 0, 4, 3, 1)


class ContentChanged(ValueError):
    """The camera bytes no longer match a finished transaction's target."""


def recipe_defaults(ap, slots):
    result = {}
    def key(attribute):
        row = struct.unpack_from('<8I', ap, 0x57c6710 + (attribute - 0x14ea) * 32)
        if row[6] != attribute or row[1] >> 16 != 0x02cf:
            raise ValueError('Creative Look descriptor differs')
        return row[1]
    for slot in slots:
        if slot not in range(1, 7):
            raise ValueError('Select custom slots 1..6')
        selector = slot + 9
        result[key(0x14ea + selector)] = b'\0'
        for index, value in enumerate(ST_ADJUSTMENTS):
            result[key(0x1520 + index * 18 + selector)] = struct.pack('<I', value)
    return result


def color_regions():
    result = {checkpoint.CP_KEYS[0]: [], checkpoint.CP_KEYS[1]: []}
    for parameter, slot in ((55, 23), (56, 25)):
        result[checkpoint.CP_KEYS[0]] += [(0x1200 + parameter, 1), (0x1250 + slot * 64, 64)]
        result[checkpoint.CP_KEYS[1]] += [(0x196 + parameter, 1), (0x1e0 + slot * 768, 576)]
    return result


def plan(current, records, mode, *, factory=None, slot=None, look=None, name=None):
    """Pure planning: preserve every field outside the declared project scope."""
    _, core = modules()
    ap, cp = current['appFw.so'], current['cpapp-b.bin']
    target = dict(current)
    wanted = [{}, {}]
    rename = None
    if mode in ('factory_reset', 'fl23_enable'):
        for key, start, count in ((0x02a40001, 0x1200, 80), (0x02a4000d, 0x196, 74)):
            mapping = records[1][key].data[start:start + count]
            if len(mapping) != count or any(value in (23, 25) for index, value in enumerate(mapping) if index not in (55, 56)):
                raise ValueError('FL23 color positions are referenced by another native look; calibration was not changed')
    if mode == 'factory_reset':
        if factory is None:
            raise ValueError('Prepare the original Sony 2.01 reference first')
        regional = factory.get('schema') == 'a7c2-factory-regions/1'
        for program in checkpoint.PROGRAM_PATHS:
            if regional:
                spec = factory['programs'][program]
                if factory['model'] != 'ILCE-7CM2' or factory['version'] != '2.01' or len(current[program]) != spec['bytes']:
                    raise ValueError('Original reference model/version/program size differs')
                result = bytearray(current[program])
                for region in spec['regions']:
                    raw = zlib.decompress(base64.b64decode(region['zlib_base64']))
                    at, size = region['offset'], region['bytes']
                    if len(raw) != size or not 0 <= at <= at + size <= len(result):
                        raise ValueError('Invalid original reference region')
                    result[at:at + size] = raw
                target[program] = bytes(result)
            else:
                if len(current[program]) != len(factory[program]):
                    raise ValueError('Original and current program sizes differ')
                target[program] = factory[program]
        wanted[0] = recipe_defaults(target['appFw.so'], range(1, 7))
        wanted[0].update({key: b'\0' for key in checkpoint.AP_KEYS})
        # The current selection must not keep pointing at a removed FL23 entry.
        row=struct.unpack_from('<8I',target['appFw.so'],0x57c6710-32)
        if row[:3]!=(3,0x02cf0cbb,0x10000) or row[6]!=0x14e9:
            raise ValueError('Current Creative Look descriptor differs')
        wanted[0][row[1]]=b'\0'
        from . import verticalpersist
        if verticalpersist.SETTING in records[0]:
            wanted[0].update(verticalpersist.field(ap, records, False))
        original_records = None if regional else core.backup_records(factory['CX89700_ALLLANG.bin'])
        for key, spans in color_regions().items():
            value = bytearray(records[1][key].data)
            for start, size in spans:
                if regional:
                    region = next(r for r in factory['color_units'][str(key)] if r['offset'] == start and r['bytes'] == size)
                    raw = zlib.decompress(base64.b64decode(region['zlib_base64']))
                    if len(raw) != size:
                        raise ValueError('Original color-region length differs')
                    value[start:start + size] = raw
                else:
                    value[start:start + size] = original_records[1][key].data[start:start + size]
            wanted[1][key] = bytes(value)
        for filename in nameworker.filenames():
            key = 'resources/' + filename
            target[key] = resources.before_custom(current[key])
    elif mode in ('preview_native', 'preview_legacy', 'preview_pending'):
        from . import uploadgate, uploadpending
        base = uploadpending.normalize(cp) if mode == 'preview_pending' or uploadpending.active(cp) else cp
        identity = device_layout.structural(ap, base)
        if identity.get('first_install') or not identity['mask']:
            raise ValueError('本测试只用于已安装自定义 LUT 的相机；本次没有写入。')
        change = {'preview_native': uploadgate.restore, 'preview_legacy': uploadgate.restore_legacy_for_test,
                  'preview_pending': uploadpending.install}[mode]
        target['cpapp-b.bin'] = change(base)
    elif mode in ('vertical_enable', 'vertical_disable'):
        from .verticalpersist import field
        wanted[0].update(field(ap, records, mode == 'vertical_enable'))
    elif mode=='sound_restore':
        import sys
        sys.path.insert(0,str(nativebuild.ROOT/'src/shutter_sound'))
        import boot_sound
        target['appFw.so']=boot_sound.restore_plan(ap)[0]
    elif mode in ('sound_enable','sound_disable'):
        import sys
        sys.path.insert(0,str(nativebuild.ROOT/'src/shutter_sound'))
        import candidate
        desired=mode=='sound_enable'
        target.update(candidate.patch(ap,cp) if desired else candidate.disable(ap,cp))
    elif mode == 'fl23_enable':
        import compat
        target.update(compat.plan(ap, cp, '2.01', transitions=False)[2])
        wanted[0] = dict(zip(checkpoint.AP_KEYS, (b'\x0a', b'\x0b')))
        units = {key: bytearray(records[1][key].data) for key in checkpoint.CP_KEYS}
        for row in core.read_json(core.BASE / 'assets/colors.json'):
            parameter, index = row['parameter'], row['slot']
            chroma, matrix = core.colour_record(row)
            a, b = units[checkpoint.CP_KEYS[0]], units[checkpoint.CP_KEYS[1]]
            if a[0x1200 + parameter] not in (0, index) or b[0x196 + parameter] not in (0, index):
                raise ValueError('FL23 parameter positions are used by another mapping')
            a[0x1200 + parameter] = b[0x196 + parameter] = index
            a[0x1250 + index * 64:0x1250 + (index + 1) * 64] = chroma
            b[0x1e0 + index * 768:0x1e0 + index * 768 + 576] = matrix
        wanted[1] = {key: bytes(value) for key, value in units.items()}
    elif mode == 'fl23_disable':
        result = bytearray(ap)
        for at in MENU_FLAGS:
            if ap[at:at + 2] not in (b'\0\0', b'\1\0'):
                raise ValueError('FL23 menu field conflicts at ' + hex(at))
            result[at:at + 2] = b'\0\0'
        target['appFw.so'] = bytes(result)
    elif mode in ('slot_default', 'look_import'):
        identity = device_layout.structural(ap, cp)
        wanted[0] = recipe_defaults(ap, [slot])
        bank = photoformat.extract_bank(cp, records[1][0x02a40001].data,
            records[1][0x02a4000d].data, gamma_table_va=0x1209480,
            regular_row=0, still_row=10, color_parameter=0)[0] if photoio.present(cp) else None
        if mode == 'slot_default':
            raw = bytes(six.TABLE_BYTES)
            if identity['kind'] != 'legacy-six' and not identity.get('first_install'):
                target.update(device_layout.deactivate(ap, cp, slot, raw, hash_checks=False, native_bank=bank, transitions=False)[2])
            elif identity['kind'] == 'legacy-six':
                target.update(device_layout.replace(ap, cp, {slot: raw}, hash_checks=False, native_bank=bank, transitions=False)[2])
                rename = ({slot: 'ST'}, identity['label_ids'])
        else:
            from . import lookfile
            raw = lookfile.writer_document(look)
            stage = look.get('native_photo')
            base_cp = device_layout.replace(ap, cp, {slot: raw}, hash_checks=False, transitions=False)[2]['cpapp-b.bin'] if identity.get('first_install') else cp
            bank = photoformat.extract_bank(base_cp, records[1][0x02a40001].data,
                records[1][0x02a4000d].data, gamma_table_va=0x1209480,
                regular_row=0, still_row=10, color_parameter=0)[0] if stage is not None or photoio.present(cp) else None
            target.update(device_layout.replace(ap, cp, {slot: raw}, hash_checks=False,
                native_photo={slot: stage}, native_bank=bank, transitions=False)[2])
            rename = ({slot: name or look['name']}, identity['label_ids'])
        if rename:
            for filename in nameworker.filenames():
                key = 'resources/' + filename
                parsed = resources.decode(current[key])
                if any(parsed['entries'].get(rename[1][s - 1], {}).get('text') != title for s, title in rename[0].items()):
                    target[key] = resources.rename(current[key], *rename)[0]
    else:
        raise ValueError('Unknown direct operation: ' + mode)
    if mode in ('vertical_disable','factory_reset'):
        import sys
        sys.path.insert(0,str(nativebuild.ROOT/'src/vertical'))
        from verticaltool import portraitlayout
        if portraitlayout.active(target['appFw.so']):
            target['appFw.so']=portraitlayout.references(target['appFw.so'],False)[0]
    return target, wanted, rename


class DirectJob(Rollback):
    def __init__(self, folder, *, factory=CheckpointCamera, zig=None):
        super().__init__(folder, factory=factory, zig=zig)
        self.state_path = self.root / 'direct.private.json'
        self.vertical_stage = None

    def capture(self, camera):
        current=super().capture(camera)
        self._runtime_binding_ap=current['appFw.so']
        self._synced_look_bases={}
        return current

    def sync_look_bases(self, camera, prepared, selected=None):
        from . import runtimebindings
        keys,ram,saved,_,_=prepared
        fields={key:ram[0][key].data for key in (keys if selected is None else selected)}
        return runtimebindings.sync(camera,self,fields,expected=(ram,saved))

    def after_settings_write(self,camera,prepared):
        self.sync_look_bases(camera,prepared)

    def settings_readback_expected(self,before,after,expected):
        from .runtimebindings import setting_array_changes
        derived=setting_array_changes(before,after,getattr(self,'_synced_look_bases',{}))
        return expected|{(0,key):value for key,value in derived.items()}

    def save(self, phase, **values):
        if phase=='NEEDS_REVIEW' and self.state.get('phase')!='NEEDS_REVIEW':
            values.setdefault('failed_during',self.state.get('phase'))
        self.state.update(values, phase=phase)
        write_json(self.state_path, self.state)
        restoring = self.state.get('mode') == 'factory_reset'
        labels = {'READING': '读取当前状态', 'PLANNED': '恢复计划已生成' if restoring else '所选操作的写入计划已生成',
                  'RESTORING_NAMES': '恢复并核对名称资源' if restoring else '核对名称资源',
                  'RESTORING_SETTINGS': '恢复原厂外观设置' if restoring else '应用并核对所选设置',
                  'PREPARING_RELOAD': '准备重新加载', 'PREFLIGHT_VERIFIED': '写入前检查通过，接下来应用更改',
                  'WRITING': '正在应用所选操作', 'AWAITING_RELOAD': '读回完成，等待断电重开',
                  'LOADED': '加载状态符合目标', 'COMPLETE': '完成', 'NEEDS_REVIEW': '已停止，请保留日志核对结果'}
        labels.update(AWAITING_RESOURCE_RELOAD='名称已写好；请按提示断电重开，再继续程序安装',
                      RESOURCE_RELOAD_VERIFIED='名称及只读挂载已确认，可以继续程序安装')
        if phase=='AWAITING_RELOAD' and self.state.get('mode') in ('fl23_enable','fl23_disable'):
            labels[phase] = 'FL23 操作完成：已写入并完整读回；重开后生效，无需再点核对。'
        elif phase=='AWAITING_RELOAD' and restoring:
            labels[phase]='恢复尚未完成：写入与读回已结束，等待重启后核对'
        print(labels.get(phase, phase), flush=True)

    def settings(self, camera, before, wanted):
        self.vertical_stage = None
        self.vertical_target = None
        ram, saved = [camera.records(before['settings-' + kind + '.bin']) for kind in ('ram', 'saved')]
        new_ram, new_saved = copy.deepcopy(ram), copy.deepcopy(saved)
        for chip in (0, 1):
            for key, value in wanted[chip].items():
                for records in (new_ram, new_saved):
                    if len(records[chip][key].data) != len(value):
                        raise ValueError('Default setting length differs')
                    records[chip][key] = records[chip][key]._replace(data=value)
                if chip == 1:
                    stored = bytearray(saved[1][key].data)
                    for at, size in color_regions()[key]:
                        stored[at:at + size] = value[at:at + size]
                    new_saved[1][key] = saved[1][key]._replace(data=bytes(stored))
        keys = list(wanted[0])
        if any(saved[0][key].data != value for key, value in wanted[0].items()):
            devicesettings.require_save_preserves_unsaved(ram, saved, set(keys))
        if any(saved[1][key].data != new_saved[1][key].data for key in wanted[1]):
            for key, value in ram[1].items():
                if key >> 16 == 0x02a4 and key not in wanted[1] and value != saved[1].get(key):
                    raise ValueError('Unrelated unsaved CP settings must be saved first')
        from . import verticalpersist
        if verticalpersist.SETTING in wanted[0]:
            self.vertical_target = wanted[0][verticalpersist.SETTING] == b'\0'
        return keys, new_ram, new_saved, ram, saved

    def prepare_vertical(self, camera):
        if getattr(self,'vertical_target',None) is not None:
            from .verticalpersist import Stage
            self.vertical_stage = Stage(camera,self,self.vertical_target)

    def restore_settings(self, camera, prepared):
        # Reuse the reviewed group-save/preservation algorithm, restricted to
        # selected units; a menu-only operation never changes look settings.
        keys, ram, saved, old_ram, old_saved = prepared
        # Existing rollback always considers both CP units, so unchanged ones
        # must remain represented; no factory unit replaces calibration data.
        if keys or ram != old_ram or saved != old_saved:
            super().restore_settings(camera, (keys, ram, saved, old_ram, old_saved))
        self.sync_look_bases(camera,prepared)
        if getattr(self, 'vertical_stage', None):self.vertical_stage.finish()

    def purge_stale_backups(self, camera):
        """Factory restore: remove name backups that earlier project jobs left.

        Unfinished or abandoned jobs can leave whole sets of 68 resource copies
        in /usr/share/app, filling /usr until name writes fail with ENOSPC. The
        restore supersedes those jobs, so their backups have no further use.
        Old temporary files are accounted for before this point.
        """
        build = checkpointworker.build_purge(self.root / 'purge', self.state['job_id'], self.zig)
        self.state['purge_build'] = build; write_json(self.state_path, self.state)
        result = self.native(camera, 'purge', 5, build)
        self.record('stale_name_backups_removed', matched=result['matched'], removed=result['removed'])
        if result['removed']:
            print('已清理旧任务遗留的名称备份 %d 个，释放相机 /usr 空间。' % result['removed'], flush=True)
        return result

    def resume_install_settings(self,failed_workspace,*,power_confirmed):
        """Finish a known completed-program install, without a program writer."""
        from . import settingsresume,bundle
        require_power(confirmed=power_confirmed)
        prior_root,prior=settingsresume.source(failed_workspace)
        if self.root.exists() and any(self.root.iterdir()):
            raise ValueError('Use a fresh settings continuation directory')
        self.root.mkdir(parents=True,exist_ok=True)
        self.state=dict(schema='a7c2-direct-job/1',mode='install_all',slot=None,name=None,
            job_id=uuid.uuid4().hex[:16],journal=[],backup_created=False,
            bundle_options=prior['bundle_options'],settings_resume_from=str(prior_root),program_builds=[],
            power_confirmation=require_power(confirmed=True))
        if prior.get('names_cleanup_pending'):
            self.state.update(names_cleanup_pending=True,forward_name_build=prior['forward_name_build'])
            header=self.root/'names/names.private.h';header.parent.mkdir()
            header.write_bytes((prior_root/'names/names.private.h').read_bytes())
        self.save('READING')
        try:
            with self.recovery_session(prior['identity']) as camera:
                self.state['identity']=camera.identity
                current=self.capture(camera)
                options,rows=bundle.documents(prior['bundle_options'])
                target,wanted,_=bundle.plan(current,camera.records(current['settings-ram.bin']),options,rows)
                # Plan from the current body and require every program/name to
                # already match. This method has no program/name write path.
                for name in checkpoint.PROGRAM_PATHS:
                    if current[name]!=target[name]:
                        raise ContentChanged('Saved install programs changed; settings-only continuation stopped: '+name)
                for filename in nameworker.filenames():
                    name='resources/'+filename
                    if current[name]!=target[name]:
                        raise ContentChanged('Saved install names changed; settings-only continuation stopped: '+filename)
                self.record('complete_program_and_name_bytes_verified')
                prepared=self.settings(camera,current,wanted)
                runtime=self.native(camera,'runtime',0)
                if runtime['image_mode'].strip() not in ('0','2') or not runtime.get('boot_id','').strip():
                    raise ValueError('Camera reload state unavailable; no settings continuation started')
                self.state['source_boot_id']=runtime['boot_id'].strip()
                self.prepare_vertical(camera)
                if self.vertical_stage:self.vertical_stage.verify_existing()
                self.save('RESTORING_SETTINGS')
                self.restore_settings(camera,prepared)
                self.save('PREPARING_RELOAD')
                if runtime['image_mode'].strip()=='2':
                    self.native(camera,'wbi',0);self.native(camera,'wbi',1)
            self.save('AWAITING_RELOAD',raw_profile_effective_since=datetime.now().isoformat(timespec='microseconds'))
            print('已核对程序和名称均符合原安装计划，只续做设置与重新加载准备；没有重复刷写程序。',flush=True)
            return self.state
        except BaseException as exc:
            self.save('NEEDS_REVIEW',error=str(exc));raise

    def prepare_factory_settings(self, camera, prepared):
        """Save ST recipes before removing code that their old bases require.

        Keep CP color data and vertical resource aliases until their normal
        restoration steps. A later name-space failure can then be resumed
        without leaving a saved FL23 recipe on stock programs.
        """
        return self.prepare_ap_settings(camera,prepared,prepared[0],'factory_look_settings_safe')

    def prepare_look_settings(self, camera, prepared):
        from .verticalpersist import SETTING
        keys=[key for key in prepared[0] if key not in (*checkpoint.AP_KEYS,SETTING)]
        if not keys:return prepared
        result=self.prepare_ap_settings(camera,prepared,keys,'look_slots_st')
        print('所选槽位已保存为 ST。',flush=True)
        return result

    def prepare_ap_settings(self, camera, prepared, selected, event):
        keys,ram,saved,before_ram,before_saved=prepared
        ready_ram,ready_saved=copy.deepcopy(before_ram),copy.deepcopy(before_saved)
        for key in selected:
            ready_ram[0][key]=ram[0][key]
            ready_saved[0][key]=saved[0][key]
        if ready_ram!=before_ram or ready_saved!=before_saved:
            # Do not run vertical_stage.finish() before the program/name steps.
            # Only the early AP targets are ready here; FL23 is applied later.
            ready=(list(selected),ready_ram,ready_saved,before_ram,before_saved)
            Rollback.restore_settings(self,camera,ready)
        # Backup readback alone does not update the AP menu/preview model.
        # Synchronize even when the backup already said ST but the model is stale.
        self.sync_look_bases(camera,(keys,ready_ram,ready_saved,before_ram,before_saved),selected)
        self.record(event)
        return keys,ram,saved,ready_ram,ready_saved

    def forward_names(self, camera, build, mode):
        if build.get('unchanged'):
            return
        return invoke(camera, Path(build['path']).read_bytes(), stage='lut-names-staged.so',
            request='a7c2.names.request', result='a7c2.names.result',
            contents=struct.pack('<8sII', b'A7NAM001', mode, 0), mode=mode,
            decode=lambda raw: nameworker.validate(raw, mode, build,allow_completed_busy=True), record=self.record,
            save_raw=lambda raw: self.raw('names-forward-' + str(mode) + '.bin', raw))

    def resume_factory_names(self, failed_workspace, *, power_confirmed, factory_values):
        """A new, user-selected continuation; completed program batches never run."""
        from . import directresume
        require_power(confirmed=power_confirmed)
        prior_root, prior, raw = directresume.source(failed_workspace)
        if self.root.exists() and any(self.root.iterdir()):
            raise ValueError('Use a fresh continuation directory')
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = dict(schema='a7c2-direct-job/1', mode='factory_reset', slot=None, name=None,
            factory_path=prior['factory_path'], identity=prior['identity'], job_id=uuid.uuid4().hex[:16],
            resume_from=str(prior_root), journal=[], backup_created=False,
            power_confirmation=require_power(confirmed=True))
        self.save('READING')
        try:
            with self.factory(prior['identity']) as camera:
                current = self.capture(camera)
                directresume.program_bytes(current, prior_root, prior)
                target, wanted, _ = plan(current, camera.records(current['settings-ram.bin']),
                    'factory_reset', factory=factory_values)
                if any(current[p] != target[p] for p in checkpoint.PROGRAM_PATHS):
                    raise ValueError('Factory program regions differ; continuation will not write programs')
                prepared = self.settings(camera, current, wanted)
                names = checkpointworker.build_names(current, target, self.root / 'worker', self.state['job_id'], self.zig)
                directresume.cleanup(camera, prior_root, prior, raw, self.record)
                from .factoryrecover import supersede_temporary
                supersede_temporary(camera,self.root/'evidence/superseded-temporary',self.record)
                self.prepare_vertical(camera)
                runtime = self.native(camera, 'runtime', 0)
                if runtime['image_mode'].strip() not in ('0', '2') or not runtime.get('boot_id', '').strip():
                    raise ValueError('Runtime state is unavailable; no restoration started')
                previous = next(r['result'] for r in prior['journal'] if r.get('event') == 'native_result_verified'
                    and 'spans' in r.get('result', {}))
                old_spans = {(s['offset'], s['length']): s['memory'] for s in previous['spans']}
                for span in runtime['spans']:
                    target_bytes = target['appFw.so'][span['offset']:span['offset'] + span['length']].hex()
                    if span['disk'] != target_bytes or span['memory'] not in (target_bytes, old_spans.get((span['offset'], span['length']))):
                        raise ValueError('Unexpected loaded application state; no restoration started')
                self.state['source_boot_id'] = runtime['boot_id'].strip()
                self.purge_stale_backups(camera)
                if names:
                    self.native(camera, 'names', 4, names)
                self.save('PREFLIGHT_VERIFIED', program_builds=[], inverse_name_build=names, forward_name_build=None)
                print('只继续名称、设置与重新加载准备，不重复写入程序。', flush=True)
                self.save('WRITING')
                prepared=self.prepare_factory_settings(camera,prepared)
                if names:
                    self.native(camera, 'names', 2, names)
                self.readback(camera, target)
                self.restore_settings(camera, prepared)
                if runtime['image_mode'].strip() == '2':
                    self.native(camera, 'wbi', 0)
                    self.native(camera, 'wbi', 1)
            self.save('AWAITING_RELOAD')
            print('续接写入和读回已结束，恢复尚未完成：请拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、接回 USB，点击“重启后核对并完成恢复”。', flush=True)
            return self.state
        except BaseException as exc:
            self.save('NEEDS_REVIEW', error=str(exc))
            raise

    def run_direct(self, mode, *, version, power_confirmed, factory_values=None,
                   factory_path=None, slot=None, look_path=None, name=None, bundle_options=None,
                   recovery_identity=None,recovery_source=None):
        require_power(confirmed=power_confirmed)
        if version != '2.01':
            raise ValueError('Direct operations support ILCE-7CM2 2.01 only')
        if self.root.exists() and any(self.root.iterdir()):
            raise ValueError('Use a fresh transaction; preserve unknown outcomes')
        self.root.mkdir(parents=True, exist_ok=True)
        bundle_rows = []
        if mode == 'install_all':
            from . import bundle
            bundle_options, bundle_rows = bundle.documents(bundle_options or {}, self.root)
        look = None
        if look_path:
            from . import lookfile
            look = lookfile.read(look_path)
            lookfile.writer_document(look)
            (self.root / 'reference.a7look').write_bytes(Path(look_path).read_bytes())
        self.state = dict(schema='a7c2-direct-job/1', mode=mode, slot=slot, name=name,
            factory_path=factory_path, job_id=uuid.uuid4().hex[:16], journal=[], backup_created=False,
            power_confirmation=require_power(confirmed=True))
        if mode=='factory_reset' and recovery_source:self.state['supersedes_workspace']=str(recovery_source)
        if mode == 'install_all':self.state['bundle_options'] = bundle_options
        self.save('READING')
        resource_pause=False
        try:
            context=(self.recovery_session(recovery_identity) if mode=='factory_reset' and recovery_identity else self.factory())
            with context as camera:
                self.state['identity'] = camera.identity
                if mode in ('sound_enable','sound_disable','sound_restore'):
                    import sys
                    sys.path.insert(0,str(nativebuild.ROOT/'src/shutter_sound'))
                    from replacement import prepare_current
                    prepare_current(camera,self.root/'evidence/sound-current',mode)
                if mode=='factory_reset':
                    from .factoryrecover import supersede_temporary
                    supersede_temporary(camera,self.root/'evidence/superseded-temporary',self.record)
                current = self.capture(camera)
                if mode in ('preview_native', 'preview_legacy', 'preview_pending'):
                    from . import uploadgate
                    self.state['preview_source_entry'] = current['cpapp-b.bin'][uploadgate.OFFSET:uploadgate.OFFSET + 4].hex()
                if mode == 'install_all':
                    target, wanted, rename = bundle.plan(current, camera.records(current['settings-ram.bin']), bundle_options, bundle_rows)
                else:
                    target, wanted, rename = plan(current, camera.records(current['settings-ram.bin']), mode,
                        factory=factory_values, slot=slot, look=look, name=name)
                # Preserve the independent saved calibration when reconstructing
                # CP units; only the declared FL23 subranges use factory data.
                prepared = self.settings(camera, current, wanted)
                priority=(lambda row:(row[0],row[1])) if mode=='factory_reset' else None
                if mode=='sound_restore':
                    import boot_sound
                    priority=boot_sound.restore_priority
                programs = checkpointworker.build_programs(current, target, self.root / 'worker', self.zig,
                    window_priority=priority)
                inverse_names = None
                forward = None
                if rename:
                    sources = {n: current['resources/' + n] for n in nameworker.filenames()}
                    changed, forward = nameworker.prepare(sources, rename[0], current['appFw.so'],
                        self.state['job_id'], self.root / 'names', self.zig,
                        target_ap=target['appFw.so'], label_ids=rename[1], byte_only=True)
                    for n, value in changed.items():
                        target['resources/' + n] = value
                else:
                    inverse_names = checkpointworker.build_names(current, target,
                        self.root / 'worker', self.state['job_id'], self.zig,
                        defer_busy_readonly=mode == 'factory_reset')
                # Retain the plan before staging even a read-only worker, so
                # a host interruption can be accounted for on the next run.
                self.save('PLANNED', program_builds=programs,
                          inverse_name_build=inverse_names, forward_name_build=forward)
                runtime = self.native(camera, 'runtime', 0)
                if runtime['image_mode'].strip() not in ('0', '2'):
                    raise ValueError('Unsupported retained image state')
                self.prepare_vertical(camera)
                planned_change = bool(mode=='sound_restore' or programs or inverse_names or (forward and not forward.get('unchanged'))
                    or (self.vertical_stage and self.vertical_stage.needs_change)
                    or (mode == 'factory_reset' and runtime.get('usr_mount_readonly') is not True)
                    or prepared[1] != prepared[3] or prepared[2] != prepared[4])
                if planned_change and not runtime.get('boot_id', '').strip():
                    raise ValueError('Read-only boot identity is unavailable; no program/settings writes started')
                self.state['source_boot_id'] = runtime.get('boot_id', '').strip()
                for span in runtime['spans']:
                    expected = current['appFw.so'][span['offset']:span['offset'] + span['length']].hex()
                    allowed={expected}
                    if mode=='factory_reset':
                        allowed.add(target['appFw.so'][span['offset']:span['offset'] + span['length']].hex())
                    if span['memory'] not in allowed or span['disk'] != expected:
                        if mode == 'factory_reset':
                            raise ValueError('相机仍在运行上次写入前加载的程序，本次没有写入。请先拔 USB、关机，取下电池至少一分钟，'
                                             '再开机接回 USB，点击“重启后核对并完成恢复”或再次点击恢复。')
                        raise ValueError('Finish the previous cold reload before changing another feature')
                for build in programs:
                    self.native(camera, 'program', 0, build)
                if mode == 'factory_reset':
                    self.purge_stale_backups(camera)
                if inverse_names:
                    self.native(camera, 'names', 4, inverse_names)
                if forward:
                    self.forward_names(camera, forward, 0)
                self.save('PREFLIGHT_VERIFIED', program_builds=programs,
                          inverse_name_build=inverse_names, forward_name_build=forward)
                self.save('WRITING')
                if self.vertical_stage:self.vertical_stage.prepare()
                if mode=='factory_reset':prepared=self.prepare_factory_settings(camera,prepared)
                # Original native records are preserved by appended titles.
                # Finish the resource transaction before any program edits;
                # ENOSPC here must leave the previous program executable.
                if forward and not forward.get('unchanged'):
                    print('正在逐文件更新名称（共 %d 项）；名称完成后才写入程序。' % forward['count'] if forward.get('stream_install') else
                          '先写入名称资源，成功后才写入程序。', flush=True)
                    name_result=self.forward_names(camera, forward, 1)
                    self.state['names_cleanup_pending'] = not forward.get('stream_install',False)
                    self.save('WRITING')
                    if name_result and name_result.get('readonly_deferred_busy'):
                        names_only=dict(current)
                        for filename in nameworker.filenames():names_only['resources/'+filename]=target['resources/'+filename]
                        self.readback(camera,names_only)
                        self.record('names_complete_programs_unchanged_verified')
                        self.state['readonly_deferred_busy']=True
                        if runtime['image_mode'].strip()=='2':
                            self.native(camera,'wbi',0);self.native(camera,'wbi',1)
                        resource_pause=True
                if not resource_pause:
                    if mode in ('look_import','install_all','slot_default'):
                        prepared=self.prepare_look_settings(camera,prepared)
                    for index, build in enumerate(programs):
                        print('正在写入程序窗口批次 %d/%d' % (index + 1, len(programs)), flush=True)
                        self.native(camera, 'program', 1, build)
                    for program, path in checkpoint.PROGRAM_PATHS.items():
                        if camera.read(path) != target[program]:
                            raise ValueError('Complete program readback differs: ' + program)
                    self.record('complete_program_bytes_verified')
                    self.save('RESTORING_NAMES')
                    if inverse_names:
                        name_result = self.native(camera, 'names', 2, inverse_names)
                        if name_result and name_result.get('readonly_deferred_busy'):
                            self.state['readonly_deferred_busy'] = True
                            print('名称内容已完成；只读挂载忙碌。完成设置与重新加载准备后，需要断电重开核对挂载状态。', flush=True)
                    self.readback(camera, target)
                    self.save('RESTORING_SETTINGS')
                    self.restore_settings(camera, prepared)
                    changed = planned_change
                    self.save('PREPARING_RELOAD')
                    if changed and runtime['image_mode'].strip() == '2':
                        self.native(camera, 'wbi', 0)
                        self.native(camera, 'wbi', 1)
                    if not changed and self.vertical_stage:self.vertical_stage.verify_loaded()
                    if not changed and mode=='factory_reset':
                        self.state['readonly_after_reload_verified']=True
            if resource_pause:
                self.save('AWAITING_RESOURCE_RELOAD')
                print('所有读写已结束。68 个名称已完整核对，程序和配方尚未写入。旧资源仍被占用，需要断电重开释放后，再点同一按钮继续；不重复写名称。',flush=True)
                return self.state
            self.save('AWAITING_RELOAD' if changed else 'LOADED', raw_profile_effective_since=datetime.now().isoformat(timespec='microseconds'))
            if changed and mode in ('fl23_enable','fl23_disable'):
                print('安装／关闭任务已结束，没有后续待写入步骤。以下断电仅用于让相机加载已写入的程序，电脑端核对可选。',flush=True)
            print('所有读写已结束。拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、检查功能并核对。' if changed else '磁盘与设置已符合目标，本次没有重复写入；实际预览、照片和声音仍需在机身检查。', flush=True)
            return self.state
        except BaseException as exc:
            self.save('NEEDS_REVIEW', error=str(exc))
            raise

    def prepare_names_reload(self,failed_workspace,*,power_confirmed):
        """Recover the completed-name/RO-busy boundary without program writes."""
        from . import namespause
        require_power(confirmed=power_confirmed)
        prior_root,prior,raw=namespause.source(failed_workspace)
        if prior['phase']!='NEEDS_REVIEW':raise ValueError('Use the saved resource reload checkpoint')
        if self.root.exists() and any(self.root.iterdir()):raise ValueError('Use a fresh recovery directory')
        self.root.mkdir(parents=True,exist_ok=True)
        self.state={k:v for k,v in prior.items() if k not in ('journal','phase','error','job_id')}
        self.state.update(job_id=uuid.uuid4().hex[:16],journal=[],resume_from=str(prior_root),
            program_source_workspace=str(prior_root),readonly_deferred_busy=True,names_cleanup_pending=False,
            power_confirmation=require_power(confirmed=True))
        if prior['mode']=='look_import':
            (self.root/'reference.a7look').write_bytes((prior_root/'reference.a7look').read_bytes())
        self.save('READING');self.raw('names-forward-1.bin',raw)
        try:
            with self.recovery_session(prior['identity']) as camera:
                images=namespause.verify_files(camera,prior_root,prior)
                namespause.cleanup(camera,prior,raw)
                runtime=self.native(camera,'runtime',0)
                for span in runtime['spans']:
                    expected=images['appFw.so'][span['offset']:span['offset']+span['length']].hex()
                    if span['disk']!=expected or span['memory']!=expected:raise ValueError('Old program state differs; stop continuation')
                ready=runtime.get('usr_mount_readonly') is True
                self.record('completed_names_current_programs_verified',readonly=ready)
                if not ready and runtime['image_mode'].strip()=='2':
                    self.native(camera,'wbi',0);self.native(camera,'wbi',1)
                elif runtime['image_mode'].strip() not in ('0','2'):raise ValueError('Unknown retained image state')
            self.save('RESOURCE_RELOAD_VERIFIED' if ready else namespause.WAIT,
                resource_reload_not_needed=ready,resource_reload_verified=ready)
            print('所有读写已结束。名称已核对，程序未写入。'+('只读挂载已恢复，无需额外重开。' if ready else '请按弹窗断电重开后接回，继续剩余程序安装。'),flush=True)
            return self.state
        except BaseException as exc:
            self.save('NEEDS_REVIEW',error=str(exc));raise

    def verify_names_reload(self):
        from . import namespause
        root,self.state,raw=namespause.source(self.root)
        if self.state['phase'] not in (namespause.WAIT,'RESOURCE_RELOAD_VERIFIED'):raise ValueError('First prepare resource reload')
        with self.recovery_session(self.state['identity']) as camera:
            namespause.verify_files(camera,root,self.state)
            runtime=self.native(camera,'runtime',0)
            ready=(runtime.get('usr_mount_readonly') is True and
                (self.state.get('resource_reload_not_needed') or runtime['boot_id'].strip()!=self.state.get('source_boot_id')))
        if not ready:
            print('尚未确认新的冷启动与只读挂载；没有重复写入。请按弹窗完成断电重开、接回。',flush=True)
            return self.state
        self.save('RESOURCE_RELOAD_VERIFIED',resource_reload_verified=True,resource_boot_id=runtime['boot_id'].strip())
        return self.state

    def continue_factory(self, failed_workspace, *, power_confirmed, factory_values):
        """Re-plan an interrupted factory reset from fresh bytes, stage by stage."""
        from . import factoryrecover
        require_power(confirmed=power_confirmed)
        history = factoryrecover.chain(failed_workspace)
        prior_root, prior = history[-1]
        if prior['phase'] in factoryrecover.FINISHED:
            raise ValueError('恢复写入已结束，请核对重新加载状态，不重复写入')
        if self.root.exists() and any(self.root.iterdir()):
            raise ValueError('Use a new continuation directory; keep earlier evidence')
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = dict(schema='a7c2-direct-job/1', mode='factory_reset', slot=None, name=None,
            factory_path=prior['factory_path'], identity=prior['identity'], job_id=uuid.uuid4().hex[:16],
            resume_from=str(prior_root), journal=[], backup_created=False,
            power_confirmation=require_power(confirmed=True))
        self.save('READING')
        try:
            with self.recovery_session(prior['identity']) as camera:
                current = self.capture(camera)
                factoryrecover.known_programs(current, history)
                target, wanted, _ = plan(current, camera.records(current['settings-ram.bin']),
                    'factory_reset', factory=factory_values)
                prepared = self.settings(camera, current, wanted)
                programs = checkpointworker.build_programs(current, target, self.root / 'worker', self.zig,
                    window_priority=lambda row:(row[0],row[1]))
                names = checkpointworker.build_names(current, target, self.root / 'worker', self.state['job_id'], self.zig,
                                                     defer_busy_readonly=True)
                self.save('PLANNED', program_builds=programs, inverse_name_build=names, forward_name_build=None)
                content_complete = not programs and names is None
                if content_complete:
                    self.readback(camera, target)
                recovered = factoryrecover.cleanup(camera, history, self.record, self.raw,
                    allow_completed_name_mount_busy=content_complete) or {}
                if recovered.get('readonly_deferred_busy'):
                    self.state['readonly_deferred_busy'] = True
                    print('已完整读回确认程序与名称均符合原厂目标；只继续设置和重新加载准备，只读挂载将在新开机后核对。', flush=True)
                factoryrecover.supersede_temporary(camera,self.root/'evidence/superseded-temporary',self.record)
                runtime = self.native(camera, 'runtime', 0)
                self.prepare_vertical(camera)
                if runtime['image_mode'].strip() not in ('0', '2') or not runtime.get('boot_id', '').strip():
                    raise ValueError('无法确认当前加载状态；尚未开始续接写入')
                earlier = [r['result']['spans'] for _, state in history for r in state.get('journal', [])
                    if r.get('event') == 'native_result_verified' and 'spans' in r.get('result', {})]
                for span in runtime['spans']:
                    at, size = span['offset'], span['length']
                    allowed = {s['memory'] for spans in earlier for s in spans if s['offset'] == at and s['length'] == size}
                    allowed.add(target['appFw.so'][at:at + size].hex())
                    if span['disk'] != current['appFw.so'][at:at + size].hex() or span['memory'] not in allowed:
                        raise ValueError('运行中程序与已记录的原状态／目标不符；保留日志，不自动重试')
                self.state['source_boot_id'] = runtime['boot_id'].strip()
                for build in programs:
                    self.native(camera, 'program', 0, build)
                self.purge_stale_backups(camera)
                if names:
                    self.native(camera, 'names', 4, names)
                self.save('PREFLIGHT_VERIFIED')
                print('续接计划：剩余程序批次 %d，剩余名称文件 %d；已符合目标的内容不重复写入。' %
                      (len(programs), names['count'] if names else 0), flush=True)
                self.save('WRITING')
                prepared=self.prepare_factory_settings(camera,prepared)
                for build in programs:
                    self.native(camera, 'program', 1, build)
                for program, path in checkpoint.PROGRAM_PATHS.items():
                    if camera.read(path) != target[program]:
                        raise ValueError('Complete program readback differs: ' + program)
                self.record('complete_program_bytes_verified')
                self.save('RESTORING_NAMES')
                if names:
                    name_result = self.native(camera, 'names', 2, names)
                    if name_result and name_result.get('readonly_deferred_busy'):
                        self.state['readonly_deferred_busy'] = True
                        print('名称内容已完成；只读挂载忙碌，待完成设置后断电重开核对。', flush=True)
                self.readback(camera, target)
                self.save('RESTORING_SETTINGS')
                self.restore_settings(camera, prepared)
                self.save('PREPARING_RELOAD')
                if runtime['image_mode'].strip() == '2':
                    self.native(camera, 'wbi', 0)
                    self.native(camera, 'wbi', 1)
            self.save('AWAITING_RELOAD')
            print('恢复完成，所有读写已结束。拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、检查并核对。', flush=True)
            return self.state
        except BaseException as exc:
            self.save('NEEDS_REVIEW', error=str(exc))
            raise

    @contextmanager
    def recovery_session(self, expected):
        context = (self.factory(expected, allow_service_resume=True) if self.factory is CheckpointCamera
                   else self.factory(expected))
        with context as camera:
            try:
                yield camera
            except BaseException:
                # An ambiguous prior operation must not be followed by an
                # automatic auth.stop during context-manager teardown.
                mark_unknown = getattr(camera, 'mark_unknown', None)
                if mark_unknown:
                    mark_unknown()
                raise

    def verify_direct(self, *, factory_values=None, accepted=False):
        self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
        if self.state['phase'] not in ('AWAITING_RELOAD', 'LOADED', 'COMPLETE'):
            raise ValueError('Inspect the unfinished transaction before another write')
        look = None
        if (self.root / 'reference.a7look').exists():
            from . import lookfile
            look = lookfile.read(self.root / 'reference.a7look')
        with self.factory(self.state['identity']) as camera:
            current = self.capture(camera)
            if self.state['mode'] == 'install_all':
                from . import bundle
                options, selected = bundle.documents(self.state['bundle_options'])
                target, wanted, _ = bundle.plan(current, camera.records(current['settings-ram.bin']), options, selected)
            else:
                target, wanted, _ = plan(current, camera.records(current['settings-ram.bin']), self.state['mode'],
                    factory=factory_values, slot=self.state['slot'], look=look, name=self.state['name'])
            for program in checkpoint.PROGRAM_PATHS:
                difference=program_difference(target[program],current[program])
                if difference:
                    self.record('verification_plan_diff',result=dict(program=program,**difference))
            try:
                self.readback(camera, target)
            except ValueError as exc:
                if 'readback differs' not in str(exc):raise
                raise ContentChanged(str(exc)) from exc
            for memory in (False, True):
                records = camera.records(camera.snapshot(memory))
                for chip in (0, 1):
                    for key, value in wanted[chip].items():
                        actual = records[chip][key].data
                        differs = (any(actual[at:at + size] != value[at:at + size] for at, size in color_regions()[key])
                                   if chip == 1 else actual != value)
                        if differs:
                            raise ContentChanged('Reloaded default setting differs')
            from . import verticalpersist
            if verticalpersist.SETTING in wanted[0]:
                verticalpersist.Stage(camera, self, wanted[0][verticalpersist.SETTING] == b'\0').verify_loaded()
            runtime = self.native(camera, 'runtime', 0)
            if self.state['mode'] == 'factory_reset':
                if runtime.get('usr_mount_readonly') is not True:
                    raise ValueError('原厂恢复后的 /usr 只读挂载尚未确认；不标记恢复完成，请保留日志')
                self.state['readonly_after_reload_verified'] = True
            if self.state['phase'] == 'AWAITING_RELOAD':
                before_boot = self.state.get('source_boot_id')
                current_boot = runtime.get('boot_id', '').strip()
                if not before_boot or not current_boot or before_boot == current_boot:
                    raise ValueError('尚未确认新的冷启动。完成断电重开后再核对，不要重复写入。')
            for span in runtime['spans']:
                expected = target['appFw.so'][span['offset']:span['offset'] + span['length']].hex()
                if span['memory'] != expected or span['disk'] != expected:
                    raise ValueError('Old application remains loaded; complete the cold restart')
            if self.state.get('names_cleanup_pending'):
                if runtime.get('usr_mount_readonly') is not True:
                    raise ValueError('名称写入已完成，但尚未确认新开机后的只读挂载；不清理旧资源')
                old = self.state['forward_name_build']
                actual = {n: current['resources/' + n] for n in nameworker.filenames()}
                build = nameworker.prepare_cleanup(old, self.root / 'names/names.private.h', actual,
                    self.root / 'names-cleanup', self.zig)
                self.forward_names(camera, build, 3)
                self.state['names_cleanup_pending'] = False
                self.record('name_backups_removed_after_new_boot')
        self.save('COMPLETE' if accepted else 'LOADED', physical_checks_accepted=accepted)
        if accepted and self.state['mode'] in ('look_import', 'slot_default', 'factory_reset', 'install_all'):
            from .rawidentity import after_verified
            slots = list(range(1, 7)) if self.state['mode'] == 'factory_reset' else [self.state['slot']]
            documents = [dict(name='ST', raw_profile=None) for _ in slots]
            if look:
                documents = [dict(name=self.state['name'] or look['name'], raw_profile=look.get('raw_profile'))]
            if self.state['mode'] == 'install_all':
                slots = [row['slot'] for row in selected]
                documents = [dict(name=row['name'], raw_profile=row['document'].get('raw_profile')) for row in selected]
                resets=options.get('reset_slots',[])
                slots+=resets
                documents+=[dict(name='ST',raw_profile=None) for _ in resets]
            if slots:after_verified(self.state, self.save, self.state['job_id'], documents, slots)
        return self.state
