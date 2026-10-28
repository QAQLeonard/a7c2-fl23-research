"""Issue49: Sony's AF display resizing must not invalidate a look install."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
FOCUS_KEYS=(0x02cf1492,0x02cf1494,0x02cf1496,0x02cf1498,0x02cf149a,0x02cf149c)


@pytest.fixture(params=('camera_runtime','fl23'))
def core(request):
    spec=importlib.util.spec_from_file_location('focus49_'+request.param,ROOT/'src'/request.param/'core.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def prop(value,attr=0x60):
    return SimpleNamespace(data=struct.pack('<I',value),attr=attr)


@pytest.mark.parametrize('key',FOCUS_KEYS)
def test_native_display_resize_preserves_registration_arrays_and_other_settings(core,key):
    before=[{key:prop(230),key+1:SimpleNamespace(data=struct.pack('<13I',*([230]*13)),attr=0xc0),
             0x02cf0cd0:SimpleNamespace(data=b'\0',attr=0x60)},
            {0x02a40001:SimpleNamespace(data=b'unchanged calibration',attr=8)}]
    after=deepcopy(before);after[0][key]=prop(173)
    result=core.verify_preservation(before,after,{})
    assert result['native_focus_dimensions']==[hex(key)]
    assert result['runtime_counters']==[]
    for chip,other,value in ((0,key+1,SimpleNamespace(data=bytes(52),attr=0xc0)),
                             (0,0x02cf0cd0,SimpleNamespace(data=b'\1',attr=0x60)),
                             (1,0x02a40001,SimpleNamespace(data=b'changed calibration',attr=8))):
        changed=deepcopy(after);changed[chip][other]=value
        with pytest.raises(ValueError,match='額外設定變動'):
            core.verify_preservation(before,changed,{})


@pytest.mark.parametrize('fault',('chip','neighbor','attr_changed','wrong_attr','short','long'))
def test_other_fields_and_altered_focus_layouts_are_still_rejected(core,fault):
    chip=1 if fault=='chip' else 0;key=0x02cf1490 if fault=='neighbor' else FOCUS_KEYS[0]
    a,b=prop(230),prop(173)
    if fault=='attr_changed':b.attr=0x40
    if fault=='wrong_attr':a.attr=b.attr=0
    if fault=='short':a.data=b'\1';b.data=b'\2'
    if fault=='long':a.data=bytes(8);b.data=b'\1'+bytes(7)
    before=[{},{}];after=[{},{}];before[chip][key]=a;after[chip][key]=b
    with pytest.raises(ValueError,match='額外設定變動'):
        core.verify_preservation(before,after,{})


def test_explicit_target_readback_takes_precedence_over_native_resize(core):
    key=FOCUS_KEYS[0];before=[{key:prop(230)},{}];after=[{key:prop(173)},{}]
    core.verify_preservation(before,after,{(0,key):struct.pack('<I',173)})
    with pytest.raises(ValueError,match='目標設定讀回不符'):
        core.verify_preservation(before,after,{(0,key):struct.pack('<I',230)})
