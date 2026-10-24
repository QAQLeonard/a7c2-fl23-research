"""Native saved vertical-display setting and its three local resource aliases."""
import struct
import sys
from .nativebuild import ROOT

SETTING = 0x02cf1906
DESCRIPTOR = 0x57bbb90


def field(ap, records, enabled):
    row = struct.unpack_from('<8I', ap, DESCRIPTOR)
    if row[:3] != (3, SETTING, 0x10000) or row[6] != 0x7e4:
        raise ValueError('Native vertical setting descriptor differs')
    if records[0][SETTING].data not in (b'\0', b'\1'):
        raise ValueError('Native vertical setting is not a one-byte switch')
    return {SETTING: bytes([0 if enabled else 1])}


class Stage:
    """Use the existing alias/RAM workers inside the combined camera session."""
    def __init__(self, camera, owner, enabled):
        sys.path.insert(0, str(ROOT / 'src/vertical'))
        from verticaltool import device
        self.device, self.camera, self.owner = device, camera, owner
        self.enabled = enabled
        self.report = {}
        if getattr(camera, 'identity_pending', False):device.prepare_camera(camera, self)
        self.workers = device.Workers(camera, self)
        self.workers.allow_writable_recovery = not enabled
        self.before = self.workers.probe()
        self.originals = [camera.read(p) for p in device.SOURCES]
        from verticaltool import nativeportrait
        actual=[camera.read(p,True) for p in device.ALIASES]
        self.native_banks=any(nativeportrait.owned(value) for value in actual)
        if self.native_banks:
            self.portrait_targets=nativeportrait.targets(self.originals)
            if any(value is not None and value!=target for value,target in zip(actual,self.portrait_targets)):
                raise ValueError('Native portrait bank contents differ from this body')
            self.aliases=dict(prior=sum(1<<i for i,value in enumerate(actual) if value is not None),
                source_sizes=list(map(len,self.originals)),readonly=0)
        else:self.aliases = self.alias_result(0)
        if list(map(len, self.originals)) != self.aliases['source_sizes']:
            raise ValueError('Native vertical resource sizes changed')
        self.verify_existing()
        if enabled and self.aliases['prior'] not in (0, 7):
            raise ValueError('Partial vertical aliases need explicit removal before enabling')
        self.needs_change = (self.before['value'] != (0 if enabled else 1) or
            self.aliases['prior'] != (7 if enabled else 0) or bool(self.aliases.get('readonly')))
        self.record('inspected', enabled=enabled, aliases=self.aliases['prior'], running=self.before['value'])

    def record(self, event, **data):
        self.owner.record('vertical_' + event, **data)

    def raw(self, label, data):
        self.owner.raw('vertical-' + label, data)

    def verify_existing(self):
        expected=self.portrait_targets if self.native_banks else self.originals
        for index, (path, original) in enumerate(zip(self.device.ALIASES, expected)):
            value = self.camera.read(path, True)
            if self.aliases['prior'] & (1 << index):
                if value != original:raise ValueError('Vertical alias bytes differ: ' + path)
            elif value is not None:
                raise ValueError('Unaccounted vertical resource: ' + path)

    def alias_result(self, mode):
        if self.native_banks:
            if mode==2:
                from .resourceworker import Resources
                Resources(self.camera,self.owner,'portrait').delete()
                self.aliases=dict(self.aliases,prior=0)
            elif mode!=0:raise ValueError('Native portrait banks are prepared before saving ON')
            return self.aliases
        result=self.workers.aliases(mode)
        busy=(not self.enabled and result.get('source_ok')==7 and result.get('readonly')==-16 and
            ((mode==0 and result.get('phase')==1 and result.get('status')==0) or
             (mode==2 and result.get('phase')==5 and result.get('status')==-16 and
              result.get('rollback')==0 and result.get('created')==0 and result.get('removed')==result.get('prior'))))
        if busy:
            self.owner.state['readonly_deferred_busy']=True
            self.record('resource_readonly_busy',result=result)
            return result
        return self.device.require_aliases(result)

    def prepare(self):
        # Resources must be durable and fully read back before saving ON.
        if self.enabled and self.aliases['prior'] != 7:
            if self.aliases['prior'] != 0:
                raise ValueError('Partial vertical aliases need explicit removal before enabling')
            self.device.require_aliases(self.workers.aliases(1))
            self.aliases = self.device.require_aliases(self.workers.aliases(0))
            if self.aliases['prior'] != 7:raise ValueError('Vertical aliases were not all installed')
            self.verify_existing()
            self.record('resources_fully_verified_before_saved_enable')

    def finish(self):
        wanted = b'\0' if self.enabled else b'\1'
        for memory in (False, True):
            if self.camera.records(self.camera.snapshot(memory))[0][SETTING].data != wanted:
                raise ValueError('Saved/live vertical setting readback differs')
        if not self.enabled:
            from .portraitjob import remove_for_vertical_stage
            result=(None if getattr(self,'frames_handled',False) else
                    remove_for_vertical_stage(self.camera,self.owner,self.originals))
            if result and (result.get('readonly_deferred_busy') or result.get('cleanup',{}).get('readonly_deferred_busy')):
                self.record('portrait_cleanup_readonly_busy')
            # Saved OFF must be confirmed before removing boot-time resources.
            if self.before['value'] != 1:self.workers.ram(1)
            if self.aliases['prior']:self.alias_result(2)
            self.aliases = self.alias_result(0)
            if self.aliases['prior'] or any(self.camera.read(p, True) is not None for p in self.device.ALIASES):
                raise ValueError('Vertical resources remain after disabling')
        self.owner.state['vertical_result'] = dict(saved='ON' if self.enabled else 'OFF',
            running='ON' if self.workers.probe()['value'] == 0 else 'OFF',
            alias_count=(7 if self.enabled else 0).bit_count(), persistent=True, loaded_verified=False,
            resource_layout='native_portrait_banks' if self.native_banks else 'legacy_aliases')
        self.record('saved_setting_verified', result=self.owner.state['vertical_result'])

    def verify_loaded(self):
        self.finish_readonly()
        result = dict(saved='ON' if self.enabled else 'OFF', running='ON' if self.enabled else 'OFF',
            alias_count=self.aliases['prior'].bit_count(), persistent=True, loaded_verified=True)
        self.owner.state['vertical_result'] = result
        self.record('loaded_verified', result=result)
        return result

    def finish_readonly(self):
        if self.aliases.get('readonly'):
            raise ValueError('竖屏资源处理已结束，仍需冷重开恢复 /usr 只读状态；不标记加载成功')
        wanted = b'\0' if self.enabled else b'\1'
        for memory in (False, True):
            if self.camera.records(self.camera.snapshot(memory))[0][SETTING].data != wanted:
                raise ValueError('Reloaded vertical saved/live switch differs')
        if self.before['value'] != wanted[0] or self.aliases['prior'] != (7 if self.enabled else 0):
            raise ValueError('竖屏保存值已读取，但开机运行状态／资源尚不符合目标；不以 RAM 临时开启代替持久化验证')
        if not self.enabled:
            from .portraitjob import remove_for_vertical_stage
            result=remove_for_vertical_stage(self.camera,self.owner,self.originals)
            if result and (result.get('readonly_deferred_busy') or result.get('cleanup',{}).get('readonly_deferred_busy')):
                raise ValueError('线框资源已清理，但只读挂载仍忙；完整断电后再核对恢复')
