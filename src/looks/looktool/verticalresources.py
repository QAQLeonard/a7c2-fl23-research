"""Release independent portrait banks before restoring the larger voice data."""
import sys
from .nativebuild import ROOT


def release(camera,owner,current,*,wanted=None):
    sys.path.insert(0,str(ROOT/'src/vertical'))
    from verticaltool import nativeportrait,device
    from . import verticalpersist
    from .direct import DirectJob
    from .checkpointjob import Rollback
    from .resourceworker import Resources
    actual=[camera.read(path,True) for path in device.ALIASES]
    if not any(nativeportrait.owned(value) for value in actual):return False
    expected=nativeportrait.targets([camera.read(path) for path in device.SOURCES])
    if any(value is not None and value!=target for value,target in zip(actual,expected)):
        raise ValueError('Unaccounted portrait resource; nothing removed for voice restoration')
    fields=verticalpersist.field(current['appFw.so'],camera.records(current['settings-ram.bin']),False)
    # A factory reset already intends to replace look/shutter fields. Save that
    # same complete set here; a vertical-only save would reject those unsaved
    # look changes or accidentally commit values the reset intends to remove.
    if wanted:fields={**wanted[0],**fields}
    prepared=DirectJob.settings(owner,camera,current,[fields,{}])
    Rollback.restore_settings(owner,camera,prepared)
    workers=device.Workers(camera,owner)
    if workers.probe()['value']!=1:workers.ram(1)
    Resources(camera,owner,'portrait').delete()
    for memory,label in ((True,'ram'),(False,'saved')):
        current['settings-'+label+'.bin']=camera.snapshot(memory)
    owner.record('native_portrait_space_released_before_voice_restore')
    return True
