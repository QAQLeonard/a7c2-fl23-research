"""Target isolation, native reader windows and transaction boundaries; no USB."""
from pathlib import Path
import json
import os
import sys
from unittest.mock import patch

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'src/shutter_sound'),str(ROOT/'dev/shutter_sound')]
import targeted_sound as sound
import boot_sound
import boot_trial
import candidate


def ap_fixture():
    ap=bytearray(boot_sound.PATH+len(boot_sound.OLD_PATH)+8);ap[:4]=b'\x7fELF'
    for at,old,new in boot_sound.expected_windows()+list(sound.EXTRA):ap[at:at+len(old)]=old
    ap[0x286cde8:0x286cdfc]=bytes.fromhex('20af029000601391008c409100800391c0035fd6')
    ap[0x2885488:0x288549c]=bytes.fromhex('40ae02f0006013910004429100002f91c0035fd6')
    return bytes(ap)


def cp_fixture():
    cp=bytearray(max(at+len(raw) for at,raw in candidate.CP_GUARDS)+8)
    for at,raw in candidate.CP_GUARDS:cp[at:at+len(raw)]=raw
    for at,old,new in candidate.WINDOWS:cp[at:at+len(old)]=old
    return bytes(cp)


@pytest.mark.parametrize('selection,keys',[('electronic',{3}),('mechanical',{1,2}),('both',{1,2,3})])
def test_selected_rows_only_and_silent_second_mechanical_phase(selection,keys):
    audio,csv,name,rows=sound.configuration(b'',bytes(128),selection)
    assert set(sound.decode(csv))==keys
    for kind,value in rows.items():
        assert value['name']==name
        assert value['offset']+value['size']<=len(audio)
    if 2 in rows:assert audio[rows[2]['offset']:]==bytes(64)


def test_sequential_updates_keep_the_other_audio_reference_and_use_an_inactive_file():
    _,first,mname,rows=sound.configuration(b'',bytes(64),'mechanical')
    _,second,ename,rows=sound.configuration(first,b'\1'*128,'electronic',installed=True)
    assert mname!=ename
    assert sound.decode(second)[1]==sound.decode(first)[1]
    _,third,new_mname,rows=sound.configuration(second,b'\2'*64,'mechanical',installed=True)
    assert new_mname not in (mname,ename)
    assert sound.decode(third)[3]==sound.decode(second)[3]


def test_legacy_single_row_is_preserved_when_adding_mechanical_audio():
    legacy=boot_sound.CSV.replace(b'0xEC0',b'0x40')
    _,csv,_,rows=sound.configuration(legacy,bytes(128),'mechanical',installed=True)
    assert rows[3]==sound.decode(legacy)[3]


def test_loaded_previous_filename_is_not_used_as_the_next_inactive_slot():
    _,first,one,_=sound.configuration(b'',bytes(64),'mechanical')
    _,second,two,_=sound.configuration(first,bytes(64),'electronic')
    third=next(name for name in sound.FILES if name not in (one,two))
    with pytest.raises(ValueError,match='暂无空闲音频位置'):
        sound.configuration(second,bytes(64),'mechanical',reserved_names={third})


@pytest.mark.parametrize('bad',[b'garbage',b'',boot_sound.CSV+b'junk'])
def test_invalid_installed_configuration_is_not_discarded(bad):
    with pytest.raises(ValueError):sound.configuration(bad,bytes(64),'both',installed=True)


def test_unknown_target_rejects_before_camera_access(tmp_path):
    with patch('trial.factory') as factory:
        with pytest.raises(ValueError):sound.run(dict(sound_target='invalid',workspace=str(tmp_path)))
        factory.assert_not_called()


@pytest.mark.parametrize('mechanical',[False,True])
@pytest.mark.parametrize('electronic',[False,True])
@pytest.mark.parametrize('selection',sound.TARGETS)
def test_all_switch_combinations_preserve_the_unselected_switch(mechanical,electronic,selection):
    ap=ap_fixture();cp=candidate.patch(ap,cp_fixture(),mechanical=mechanical,electronic=electronic)['cpapp-b.bin']
    programs,edits=sound.program_plan(ap,cp,selection)
    assert candidate.switches(programs['cpapp-b.bin'])==dict(
        mechanical=True if selection in ('mechanical','both') else mechanical,
        electronic=True if selection in ('electronic','both') else electronic)
    assert edits[-1][0]==boot_sound.BOOT
    assert boot_sound.installed(programs['appFw.so'])
    assert boot_sound.restore_plan(programs['appFw.so'])[0]==ap


def test_reader_instruction_conflict_is_rejected():
    ap=bytearray(ap_fixture());ap[sound.EXTRA[0][0]]^=1
    with pytest.raises(ValueError,match='reader instruction conflict'):
        sound.program_plan(bytes(ap),cp_fixture(),'mechanical')


@pytest.mark.skipif(not os.environ.get('A7C2_SOUND_ORIGINAL_AP'),reason='Optional private original AP')
def test_actual_native_reader_sparse_rows_and_bounded_invalid_kind():
    from verify_beeplist import execute
    ap=Path(os.environ['A7C2_SOUND_ORIGINAL_AP']).read_bytes()
    programs,_=sound.program_plan(ap,cp_fixture(),'both')
    for selection in sound.TARGETS:
        _,csv,_,rows=sound.configuration(b'',bytes(128),selection)
        actual=execute(programs['appFw.so'],csv,boot_block=True,expected_path=boot_sound.NEW_PATH[:-1],
                       csv_limit=2048,expected_kinds=tuple(rows))
        for kind,value in rows.items():
            got=actual['descriptors'][kind-1]
            assert (got['kind'],got['bytes'],got['offset'],got['filename'])==(
                kind,value['size'],value['offset'],sound.ROOT+value['name'])
        assert actual['maximum_native_reader_stack_bytes']<=0xa90
    for missing,data in ((True,b''),(False,b'x'*2048),(False,sound.encode({3:dict(name=sound.FILES[0],size=64,offset=0)}).replace(b',6,3,',b',6,4,'))):
        got=execute(programs['appFw.so'],data,missing=missing,boot_block=True,
            expected_path=boot_sound.NEW_PATH[:-1],csv_limit=2048,expected_kinds=())
        assert not got['output_changed']


def test_unknown_write_keeps_pending_and_never_replays(tmp_path):
    import sound_cli
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    conversion=root/'converted';conversion.mkdir();(conversion/'custom-native.private.bin').write_bytes(bytes(64))
    state['conversion']=str(conversion);state['pending']=dict(command='install',job=str(root/'missing'))
    sound_cli.save(root,state)
    with patch('trial.factory') as factory:
        with pytest.raises(ValueError,match='结果还没确认'):
            sound.run(dict(workspace=str(root),firmware='2.01',sound_target='both',power_confirmed=True))
        factory.assert_not_called()


def test_new_request_keeps_its_own_unknown_intent_during_session_preparation(tmp_path):
    import sound_cli
    from contextlib import nullcontext
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    conversion=root/'converted';conversion.mkdir();(conversion/'custom-native.private.bin').write_bytes(bytes(64))
    state['conversion']=str(conversion);sound_cli.save(root,state)
    with patch('trial.factory',return_value=nullcontext(object())), \
         patch.object(sound,'install_connected',side_effect=TimeoutError('unknown acknowledgement')):
        with pytest.raises(TimeoutError):
            sound.run(dict(workspace=str(root),firmware='2.01',sound_target='both',power_confirmed=True))
    saved=json.loads((root/'sound.private.json').read_text())
    assert saved['pending']['command']=='install' and saved['pending']['outcome']=='needs_review'
    failed=json.loads((Path(saved['pending']['job'])/'job.private.json').read_text())
    assert failed['phase']=='needs_review'


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('fault',[None,'resource-readback','program-ack'])
def test_files_before_new_hook_legacy_disarm_and_unknown_ack_stop(tmp_path,legacy,fault):
    import trial
    ap=ap_fixture();cp=cp_fixture()
    if legacy:ap=boot_sound.patch(ap,boot_sound.expected_windows())
    old_csv=boot_sound.CSV.replace(b'0xEC0',b'0x40') if legacy else b''
    data={'/usr/lib/appFw.so':ap,'/cp/cpapp-b.bin':cp}
    if old_csv:data.update({sound.ROOT+'custom.txt':old_csv,sound.ROOT+sound.FILES[0]:bytes(64)})
    calls=[];programs={};file_plan={}
    class Camera:
        identity=dict(model='ILCE-7CM2',serial_sha256='fixture')
        def read(self,path,missing=False):return data.get(path) if missing else data[path]
        def snapshot(self,ram):return b'unchanged settings'
    camera=Camera()
    root=tmp_path/'job';root.mkdir();state=dict(phase='preparing',journal=[])
    def program_worker(ap,cp,edits,out,zig=None,*,cp_edits=()):
        key=str(out);programs[key]=(edits,cp_edits)
        return dict(path=key,windows=len(edits)+len(cp_edits),sizes=[len(ap),len(cp)])
    def build(audio,csv,out,zig=None,**kwargs):
        file_plan.update(audio=audio,csv=csv,**kwargs);return out/'files.so'
    def files(camera,root,state,worker,mode):
        calls.append(('files',mode))
        if mode==1:
            data[file_plan['audio_path']]=file_plan['audio']
            data[sound.ROOT+'custom.txt']=file_plan['csv']+(b'corrupt' if fault=='resource-readback' else b'')
    def native(camera,root,state,path,kind,mode=None,plan=None):
        calls.append((Path(path).name,mode))
        if kind!='program' or mode!=1:return
        if Path(path).name=='program':
            assert data[sound.ROOT+'custom.txt']==file_plan['csv']
            if legacy:assert data['/usr/lib/appFw.so'][boot_sound.BOOT:boot_sound.BOOT+16]==boot_sound.expected_windows()[-1][1]
        edits,cp_edits=programs[path]
        for file,changes in (('/usr/lib/appFw.so',edits),('/cp/cpapp-b.bin',cp_edits)):
            current=bytearray(data[file])
            for at,old,new in changes:
                assert current[at:at+len(old)]==old
                current[at:at+len(old)]=new
            data[file]=bytes(current)
        if fault=='program-ack':raise TimeoutError('unknown program acknowledgement')
    with patch.object(boot_trial,'current_probe',return_value=root/'probe.so'), \
         patch.object(boot_trial,'probe',return_value=dict(image_mode='0',entries=[])), \
         patch.object(boot_trial,'program_worker',side_effect=program_worker), \
         patch.object(boot_trial,'invoke_files',side_effect=files), \
         patch.object(boot_trial,'check_settings'),patch.object(trial,'backup',return_value='backup'), \
         patch.object(trial,'run_native',side_effect=native),patch('looktool.nativebuild.compile_worker'), \
         patch('files_worker.build',side_effect=build):
        if fault:
            with pytest.raises((ValueError,TimeoutError)):
                sound.install_connected(camera,root,state,bytes(128),'mechanical',tmp_path/'backup')
            if fault=='resource-readback':assert ('program',1) not in calls
            if fault=='program-ack':
                assert calls[-1][1]==1
                assert ('files',1) not in calls if legacy else ('files',1) in calls
        else:
            result=sound.install_connected(camera,root,state,bytes(128),'mechanical',tmp_path/'backup')
            assert result['phase']=='installed_cold_test_pending'
            assert calls.index(('files',1))<calls.index(('program',1))
            if legacy:assert calls.index(('disarm',1))<calls.index(('files',1))
            rows=sound.decode(data[sound.ROOT+'custom.txt'])
            if legacy:assert rows[3]==sound.decode(old_csv)[3]
            assert candidate.switches(data['/cp/cpapp-b.bin'])==dict(mechanical=True,electronic=False)
