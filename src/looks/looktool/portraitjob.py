"""Explicit manual-test entry for data-only portrait frame references."""
from pathlib import Path
import sys
import uuid

from .direct import DirectJob
from .power import require_power
from .nativebuild import ROOT
from .checkpointjob import Rollback


def vertical_modules():
    sys.path.insert(0,str(ROOT/'src/vertical'))
    from verticaltool import portraitbank,portraitlayout,portraitstage
    return portraitbank,portraitlayout,portraitstage


class PortraitJob(DirectJob):
    def run_frames(self,enabled,*,version,power_confirmed,combined=False):
        require_power(confirmed=power_confirmed)
        if version!='2.01':raise ValueError('Portrait frame test supports ILCE-7CM2 2.01')
        if self.root.exists() and any(self.root.iterdir()):raise ValueError('Use a fresh portrait transaction folder')
        self.root.mkdir(parents=True,exist_ok=True)
        self.state=dict(schema='a7c2-direct-job/1',mode='vertical_enable' if enabled else 'vertical_disable',
                        journal=[],job_id=uuid.uuid4().hex[:16],backup_created=False)
        self.save('READING')
        _,_,portraitstage=vertical_modules()
        try:
            with self.factory() as camera:
                ap=camera.read('/usr/lib/appFw.so')
                # This action edits only the AP reference data and two image
                # banks. Its native worker checks the actual C2 model index;
                # the planner checks each edited layout/record byte below.
                camera.byte_checks=True;camera.programs_pinned=True
                if camera.identity_pending:
                    from verticaltool.device import prepare_camera
                    prepare_camera(camera,self)
                self.state['identity']=camera.identity
                # Start a new, current-byte plan. Archive former inert workers;
                # never replay their request or infer their write outcome.
                from .requestcleanup import supersede_temporary
                supersede_temporary(camera,self.root/'evidence/prior-temporary',self.record)
                before={'appFw.so':ap,
                        'settings-ram.bin':camera.snapshot(True),'settings-saved.bin':camera.snapshot(False)}
                frames=portraitstage.Stage(camera,self,ap=ap)
                frames.reconcile()
                runtime=self.native(camera,'runtime',0)
                self.state['source_boot_id']=runtime.get('boot_id','').strip()
                if runtime['image_mode'].strip() not in ('0','2'):
                    raise ValueError('Camera reload state is unavailable; no portrait write started')
                from .verticalpersist import field
                wanted=[field(ap,camera.records(before['settings-ram.bin']),enabled),{}]
                prepared=self.settings(camera,before,wanted)
                self.prepare_vertical(camera)
                changed=(ap!=(frames.target_ap if enabled else frames.original_ap) or
                         frames.sources!=(frames.targets if enabled else frames.restored) or
                         bool(prepared and (prepared[1]!=prepared[3] or prepared[2]!=prepared[4])) or
                         bool(self.vertical_stage and self.vertical_stage.needs_change))
                self.save('PLANNED')
                if changed:
                    self.save('WRITING')
                    if self.vertical_stage:self.vertical_stage.prepare()
                    if not enabled:
                        # Save OFF and turn the running display OFF before any
                        # frame/reference removal, as requested by the owner.
                        Rollback.restore_settings(self,camera,prepared)
                        self.vertical_stage.workers.ram(1)
                    if enabled:
                        native=frames.invoke(1)
                        frames.verify(True)
                    else:native=frames.restore()
                    self.state['portrait_result']=native
                    if native.get('readonly_deferred_busy'):self.state['readonly_deferred_busy']=True
                    if enabled:self.restore_settings(camera,prepared)
                    else:
                        self.vertical_stage.frames_handled=True
                        self.vertical_stage.finish()
                    if runtime['image_mode'].strip()=='2':
                        self.native(camera,'wbi',0);self.native(camera,'wbi',1)
                elif not enabled:
                    self.state['portrait_result']=frames.restore()
                    changed=bool(self.state['portrait_result'].get('cleanup',{}).get('cleanup_deferred'))
            self.save('AWAITING_RELOAD' if changed else 'LOADED')
            message=('所有读写已结束。按弹窗完整断电重开后，检查横握／两侧竖握的 Fn 网格、创意外观选择页和参数调整页。'
                     if changed else '当前内容已符合所选状态，没有重复写入。')
            print('竖屏开关和线框步骤已写好，继续安装其余所选功能。' if combined else message,flush=True)
            return dict(workspace=str(self.root),phase=self.state['phase'],mode=self.state['mode'],
                        reload_required=changed,
                        frame_assets=12,shared_gauge_assets_changed=7,message=message)
        except BaseException as error:
            self.save('NEEDS_REVIEW',error=str(error))
            print('请保留日志。下次点击同一操作会重新读取当前资源和机内撤销记录，不重放旧任务。',flush=True)
            raise


def remove_for_vertical_stage(camera,owner,sources):
    portraitbank,_,portraitstage=vertical_modules()
    if not any(source.endswith(portraitbank.MAGIC) for source in sources[:2]):return None
    print('恢复本测试版的原线框引用和资源索引。',flush=True)
    result=portraitstage.Stage(camera,owner,sources=sources[:2]).restore()
    owner.state['portrait_restore_result']=result
    if result.get('readonly_deferred_busy') or result.get('cleanup',{}).get('readonly_deferred_busy'):
        owner.state['readonly_deferred_busy']=True
    return result
