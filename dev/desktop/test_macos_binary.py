"""Reproduce dyld's zero-fill rejection without loading a Mac library."""
import struct
from unittest.mock import patch
import pytest
from macos_binary import normalize, prepare_scipy


def library():
    header = struct.pack('<8I',0xfeedfacf,0x100000c,0,6,1,72+4*80,0,0)
    segment = bytearray(72+4*80)
    struct.pack_into('<II',segment,0,0x19,len(segment))
    struct.pack_into('<I',segment,64,4)
    for i,(name,kind,offset) in enumerate((('__thread_bss',18,0x1c130),
            ('__bss',1,0),('__common',12,77),('__data',0,0x180))):
        at=72+i*80
        segment[at:at+len(name)]=name.encode()
        segment[at+16:at+22]=b'__DATA'
        struct.pack_into('<QQI',segment,at+32,0x3000+i*256,128,offset)
        struct.pack_into('<I',segment,at+64,kind)
    return header+segment+b'unchanged numerical/code payload'


def test_only_zero_fill_offsets_change_and_second_pass_is_noop():
    before=library();after,changes=normalize(before)
    assert len(changes)==2 and changes[0]['section']=='__DATA/__thread_bss'
    expected=bytearray(before)
    for change in changes:struct.pack_into('<I',expected,change['field'],0)
    assert after==bytes(expected)
    assert normalize(after)==(after,[])
    assert struct.unpack_from('<I',after,32+72+3*80+48)[0]==0x180


@pytest.mark.parametrize('fault',['magic','extent','command','sections'])
def test_invalid_load_commands_are_rejected(fault):
    raw=bytearray(library())
    if fault=='magic':raw[:4]=b'BAD!'
    elif fault=='extent':struct.pack_into('<I',raw,20,len(raw)*2)
    elif fault=='command':struct.pack_into('<I',raw,36,0)
    else:struct.pack_into('<I',raw,32+64,1000)
    with pytest.raises(ValueError):normalize(bytes(raw))


def test_resign_library_then_app_then_verify(tmp_path):
    app=tmp_path/'A7C2Tools.app'
    so=app/'Contents/Frameworks/scipy/sparse/linalg/_propack/_spropack.so'
    so.parent.mkdir(parents=True);so.write_bytes(library())
    with patch('macos_binary.subprocess.run') as run:result=prepare_scipy(app)
    assert result['native_libraries_checked']==1 and len(result['repaired'])==1
    assert run.call_args_list[0].args[0][-1]==str(so)
    assert run.call_args_list[1].args[0][-1]==str(app)
    assert '--deep' in run.call_args_list[1].args[0]
    assert run.call_args_list[-1].args[0]==['codesign','--verify','--deep','--strict',str(app)]
    with patch('macos_binary.subprocess.run') as run:assert prepare_scipy(app)['repaired']==[]
    assert run.call_count==1


def test_signing_failure_stops_build(tmp_path):
    app=tmp_path/'A7C2Tools.app';so=app/'Contents/Frameworks/scipy/_test.so'
    so.parent.mkdir(parents=True);so.write_bytes(library())
    with patch('macos_binary.subprocess.run',side_effect=RuntimeError('sign failed')):
        with pytest.raises(RuntimeError,match='sign failed'):prepare_scipy(app)
