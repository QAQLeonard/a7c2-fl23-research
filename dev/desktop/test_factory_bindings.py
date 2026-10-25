"""A failed restore must not leave custom FL23 bindings without its runtime."""
import copy
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from looktool import checkpoint,checkpointworker,direct,nameworker,resources
from test_checkpoint import Camera,KEYS,values,fake_compile
from test_direct import SimDirect
from test_fl23_native_photo import original_camera_inputs


@pytest.fixture
def restoration(tmp_path):
    before=values()
    for filename in nameworker.filenames():
        key='resources/'+filename
        before[key]=resources.rename(before[key],{1:'FL2'})[0]
    camera=Camera(before)
    for key in KEYS[:8]:
        for records in (camera.ram,camera.saved):
            records[0][key]=records[0][key]._replace(data=b'\x0a')
    def plan(current,*args,**kwargs):
        target=dict(current)
        target['appFw.so']=b'X'+current['appFw.so'][1:]
        target['cpapp-b.bin']=b'Y'+current['cpapp-b.bin'][1:]
        for filename in nameworker.filenames():
            key='resources/'+filename;target[key]=resources.before_custom(current[key])
        return target,[dict.fromkeys(KEYS[:8],b'\0'),dict.fromkeys(checkpoint.CP_KEYS,b'\0\0')],None
    class Restore(SimDirect):
        fail_names=False
        chips=[]
        def native(self,camera,kind,mode,build=None):
            if kind=='program' and mode==1:
                assert all(records[0][key].data==b'\0'
                    for records in (camera.ram,camera.saved) for key in KEYS[:8])
                text=Path(build['path']).with_suffix('.private.h').read_text()
                self.chips.extend(int(chip) for chip in re.findall(r'\{\d+UL,\d+,([01]),old_\d+,new_\d+\}',text))
            if kind=='names' and mode==2:
                if self.fail_names:raise OSError('ENOSPC during name restoration')
                for filename in build['files']:
                    path='/usr/share/app/'+filename
                    camera.files[path]=resources.before_custom(camera.files[path])
                return {}
            return super().native(camera,kind,mode,build)
    job=Restore(tmp_path/'restore',factory=lambda expected=None:camera)
    job.chips=[]
    with patch.object(direct,'plan',side_effect=plan),patch.object(checkpointworker,'compile_worker',side_effect=fake_compile):
        yield camera,job


@pytest.mark.parametrize('ram_value',[b'\0',b'\x0a',b'\x0b'],ids=['ram_st','ram_fl2','ram_fl3'])
def test_name_failure_leaves_saved_and_running_custom_bases_safe(restoration,ram_value):
    camera,job=restoration;job.fail_names=True
    for key in KEYS[:8]:camera.ram[0][key]=camera.ram[0][key]._replace(data=ram_value)
    with pytest.raises(OSError,match='ENOSPC'):
        job.run_direct('factory_reset',version='2.01',power_confirmed=True,factory_values={})
    for records in (camera.ram,camera.saved):
        assert all(records[0][key].data==b'\0' for key in KEYS[:8])
        assert all(records[1][key].data==b'\x01\x02' for key in checkpoint.CP_KEYS)
    assert job.state['phase']=='NEEDS_REVIEW'


def test_factory_ap_is_restored_before_removing_cp_support(restoration):
    camera,job=restoration
    state=job.run_direct('factory_reset',version='2.01',power_confirmed=True,factory_values={})
    assert state['phase']=='AWAITING_RELOAD'
    assert job.chips==[0,1]
    assert camera.saves.count(0x02cf)==1
    assert any(e['event']=='factory_look_settings_safe' for e in state['journal'])


def test_base_save_failure_keeps_old_program_support(restoration):
    camera,job=restoration
    programs={path:camera.files[path] for path in checkpoint.PROGRAM_PATHS.values()}
    with patch.object(camera,'property_write',side_effect=OSError('AP save failed')):
        with pytest.raises(OSError,match='AP save failed'):
            job.run_direct('factory_reset',version='2.01',power_confirmed=True,factory_values={})
    assert all(camera.files[path]==raw for path,raw in programs.items())
    assert not job.chips


def test_actual_factory_descriptors_reset_all_six_fl_bases_and_current_selection(original_camera_inputs):
    import struct
    from types import SimpleNamespace
    from desktopapp import official
    from test_checkpoint import stock_names
    programs,original=original_camera_inputs
    ram,saved=copy.deepcopy(original),copy.deepcopy(original)
    ap=programs['appFw.so']
    keys=[]
    for slot in range(1,7):
        key=struct.unpack_from('<8I',ap,0x57c6710+(slot+9)*32)[1];keys.append(key)
        ram[0][key]=ram[0][key]._replace(data=bytes([10+slot%2]))
        saved[0][key]=saved[0][key]._replace(data=bytes([11-slot%2]))
    for records in (ram,saved):
        records[0][0x02cf0cbb]=records[0][0x02cf0cbb]._replace(data=b'\x11')
    for key in checkpoint.CP_KEYS:
        for records,marker in ((ram,b'RAM-CAL!'),(saved,b'SAV-CAL!')):
            data=bytearray(records[1][key].data);data[0x80:0x88]=marker
            records[1][key]=records[1][key]._replace(data=bytes(data))
    current=dict(programs,**{'resources/'+n:stock_names() for n in nameworker.filenames()})
    from looktool.devicesession import modules
    with patch.object(modules()[1],'backup_records',return_value=original):
        reference=official.regions(programs,settings=b'fixture')
    target,wanted,_=direct.plan(current,ram,'factory_reset',factory=reference)
    assert all(wanted[0][key]==b'\0' for key in keys+[0x02cf0cbb,*checkpoint.AP_KEYS])
    camera=SimpleNamespace(records=lambda raw:ram if raw==b'ram' else saved)
    prepared=direct.DirectJob('unused-offline-job').settings(camera,
        {'settings-ram.bin':b'ram','settings-saved.bin':b'saved'},wanted)
    for fields,marker in ((prepared[1],b'RAM-CAL!'),(prepared[2],b'SAV-CAL!')):
        assert all(fields[0][key].data==b'\0' for key in keys+[0x02cf0cbb,*checkpoint.AP_KEYS])
        assert all(fields[1][key].data[0x80:0x88]==marker for key in checkpoint.CP_KEYS)

