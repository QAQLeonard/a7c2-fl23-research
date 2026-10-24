"""Two-button host workflow: combined enable, OFF-before-removal, and repeats."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from looktool import portraitjob,verticalpersist
from looktool.checkpointjob import Rollback


class Camera:
    identity={'model':'ILCE-7CM2','serial_sha256':'fixture'}
    identity_pending=False
    def __init__(self):
        self.ap=b'original AP';self.banks=[b'original bank 0',b'original bank 1']
        self.saved=False;self.running=False;self.aliases=False;self.events=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,path):
        assert path=='/usr/lib/appFw.so'
        return self.ap
    def snapshot(self,memory):return b'ram' if memory else b'saved'
    def records(self,raw):return [{},{}]


class Frames:
    def __init__(self,camera,owner,*,ap):
        self.camera=camera;self.ap=ap;self.original_ap=b'original AP';self.target_ap=b'portrait AP'
        self.sources=list(camera.banks);self.restored=[b'original bank 0',b'original bank 1']
        self.targets=[b'portrait bank 0',b'portrait bank 1']
    def reconcile(self):pass
    def invoke(self,mode):
        assert mode==1 # No separate mode-0 or image-size gate in user flow.
        self.camera.events.append('frames_enable')
        self.camera.ap=self.target_ap;self.camera.banks=list(self.targets)
        return {'writes':1}
    def verify(self,enabled):
        assert self.camera.ap==(self.target_ap if enabled else self.original_ap)
        self.camera.events.append('readback')
    def restore(self):
        assert not self.camera.running and not self.camera.saved
        changed=self.camera.ap!=self.original_ap or self.camera.banks!=self.restored
        if changed:self.camera.events.append('frames_restore')
        self.camera.ap=self.original_ap;self.camera.banks=list(self.restored)
        return {'writes':int(changed)}


class Job(portraitjob.PortraitJob):
    def settings(self,camera,before,wanted):
        self.desired=wanted[0]['fixture'];self.vertical_stage=None
        return ([],{'v':self.desired},{'v':self.desired},{'v':camera.saved},{'v':camera.saved})
    def prepare_vertical(self,camera):
        job=self
        class Vertical:
            needs_change=(camera.saved!=job.desired or camera.aliases!=job.desired or camera.running!=job.desired)
            def prepare(self):
                if job.desired:camera.aliases=True;camera.events.append('aliases_enable')
            def finish(self):
                if not job.desired:
                    assert not camera.saved and not camera.running
                    camera.aliases=False;camera.events.append('aliases_remove')
            class Workers:
                def ram(self,value):camera.running=value==0;camera.events.append('running_off' if value else 'running_on')
            workers=Workers()
        self.vertical_stage=Vertical()
    def restore_settings(self,camera,prepared):
        camera.saved=self.desired;camera.events.append('saved_on' if self.desired else 'saved_off')
        self.vertical_stage.finish()
    def native(self,camera,kind,mode,build=None):
        camera.events.append((kind,mode))
        return {'image_mode':'0','boot_id':'fixture-boot'} if kind=='runtime' else {}


@contextmanager
def dependencies():
    modules=SimpleNamespace(Stage=Frames)
    def save_off(job,camera,prepared):camera.saved=False;camera.events.append('saved_off')
    with patch.object(portraitjob,'vertical_modules',return_value=(None,None,modules)), \
         patch.object(verticalpersist,'field',side_effect=lambda ap,r,enabled:{'fixture':enabled}), \
         patch('looktool.requestcleanup.supersede_temporary',return_value=0), \
         patch.object(Rollback,'restore_settings',save_off):yield


def test_enable_writes_frames_then_saved_on_and_repeat_does_not_write(tmp_path):
    camera=Camera()
    with dependencies():
        first=Job(tmp_path/'on',factory=lambda:camera).run_frames(True,version='2.01',power_confirmed=True)
        assert first['phase']=='AWAITING_RELOAD'
        assert camera.events.index('frames_enable')<camera.events.index('readback')<camera.events.index('saved_on')
        camera.running=True # Model the owner's subsequent cold boot.
        camera.events=[]
        again=Job(tmp_path/'on-again',factory=lambda:camera).run_frames(True,version='2.01',power_confirmed=True)
    assert again['phase']=='LOADED' and camera.events==[('runtime',0)]


def test_disable_saves_off_and_disables_running_before_removing_frames(tmp_path):
    camera=Camera();camera.ap=b'portrait AP';camera.banks=[b'portrait bank 0',b'portrait bank 1']
    camera.saved=camera.running=camera.aliases=True
    with dependencies():
        result=Job(tmp_path/'off',factory=lambda:camera).run_frames(False,version='2.01',power_confirmed=True)
        assert result['phase']=='AWAITING_RELOAD'
        assert camera.events.index('saved_off')<camera.events.index('running_off')<camera.events.index('frames_restore')<camera.events.index('aliases_remove')
        camera.events=[]
        again=Job(tmp_path/'off-again',factory=lambda:camera).run_frames(False,version='2.01',power_confirmed=True)
    assert again['phase']=='LOADED' and camera.events==[('runtime',0)]


def test_frame_write_error_does_not_save_enabled_or_report_completion(tmp_path):
    camera=Camera();job=Job(tmp_path/'failed',factory=lambda:camera)
    with dependencies(),patch.object(Frames,'invoke',side_effect=TimeoutError('unknown native outcome')):
        with pytest.raises(TimeoutError):job.run_frames(True,version='2.01',power_confirmed=True)
    assert not camera.saved and job.state['phase']=='NEEDS_REVIEW'
