"""Native sound-mode regression using small stock instruction fragments only.

Synthetic capture inputs; no USB, native playback, or physical boot proof.
"""
import json
from pathlib import Path
import sys
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'src/shutter_sound'),str(ROOT/'dev/shutter_sound')]
import candidate
import trial
import sound_cli
from trace_selector import execute
from verify_selector_inputs import cp_selector

# Only the small original routines executed by these tests, not a firmware image.
CP_CODE = {
    0x49b538: "b0b502af046845f61040205818b194f8b80b00285fd046f2e8602058022804d146f2ec602058013055d041f298602158042914d8dfe801f01b2603440300d4f81002012807d1d4f8b40b042803d194f8ed09002841d045f61c4003210fe02ea0a8f2eff745f61c416018615814e094f8d7090321002845f61c4018bf0221215020440ae0dbf33afc0321002845f61c4018bf002121502044b1b145f24461c0f2ac1191f8812091f8821041ea022159b14ff48f52a25a8a4206d20121016003e045f61c4000212150b4f8860818b9204601217ef227f40020b0bd",
    0x876e34: "80b56f464ff009ff002818bf012080bd",
    0x8c6c4e: "f1f701ba",
    0x8b8054: "d0b502af84b06c462046bef1b0fa204613f0befc04b0d0bd",
    0xa765c2: "80b56f4649f25021c0f29f11096891e80c5080e80c5080bd",
    0x8cb9e4: "c1680020032918bf01207047",
    0x877b02: "4af6d070c0f201207047",
    0x8b8004: "d0f8c85441f21901012d18bf0025049c6554",
    0x358ac4: "017a4af22070c0f26510c0f8801343f2a430c0f2a51090f83200c00706d080b56f4603a0ebf347f5bde8804001207047",
    0x328998: "d8f80020d2f88033cbf8c834",
    0x351a48: "b0b502afa0b0d7f810c0bd68bcf1000f01d004240ce020b10324002908bf022406e00ab1012403e00024002b08bf0124002d5ad0fc68052c57d8dfe804f0185603031b3044f64a30c0f2aa10808800284bd14af21b126d468021c0f2f7022846d5f2c0ff2846cdf2dceac2b237e043b300243ae0bcf1000f0fd16c462da280212046d5f2afff2046cdf2caeac2b24ff420300021234626f115f0042425e06c461aa280212046d5f29dff2046cdf2b8eac2b24ff420300021234626f103f0052413e04af2df026d468021c0f2f7022846d5f288ff2846cdf2a4eac2b200244ff4203000212b4625f1edf744f27020c0f2ad10007810f0800f04d000f07f04042c28bf0424204620b0b0bd",
    0x4a09f4: "45f61c4141580a290ad80320dfe801f021062117062121211406160001200ee04cf61c6042f2827140f2f162c0f2f500c0f2fc01a3f2a7b5072000e0092080b5",
    0x4a0a34: "6f4669f2faf20146481c0228bde8804000d27047",
    0x4a0a74: "80b56f46014645f61c400a580a2a0ed80220dfe802f021060621211b1a0a210a2100084679f2bcf110e007200ee04cf61c6042f2827140f22772c0f2f500c0f2fc01bde88040a3f25eb5012069f2b5f20146481c022800d280bd",
    0xb19e14: "80b56f4645f61c4146f68472002350f801c0c0f2e702083252f8081c8c450bd112f804ec90f82217714505d1d2f800e0d0f89c10714505d010320133082bebd3022080bd506880bd",
}

@pytest.fixture(scope='module')
def stock():
    ap=bytearray(0x288549c);ap[:4]=b'\x7fELF'
    ap[0x286cde8:0x286cdfc]=bytes.fromhex('20af029000601391008c409100800391c0035fd6')
    ap[0x2885488:0x288549c]=bytes.fromhex('40ae02f0006013910004429100002f91c0035fd6')
    cp=bytearray(0x970000)
    for va,raw in CP_CODE.items():
        raw=bytes.fromhex(raw);cp[va-0x108000:va-0x108000+len(raw)]=raw
    return bytes(ap),bytes(cp)


def test_native_mechanical_leak_reproduces_before_fix(stock):
    _,cp=stock
    selector=cp_selector(cp,0)
    assert selector==0
    assert execute(cp,selector,0,trial=True,capture_request=0)['mode']==3


def test_real_capture_flag_and_all_selector_paths(stock):
    ap,cp=stock;fixed=candidate.patch(ap,cp)['cpapp-b.bin']
    cases=0
    for request in (0,1,2):
        for selector in range(5):
            for descriptor in (0,3):
                for guard in ('none','policy','pending','defer'):
                    for limit,count in ((0,0),(3,0),(3,3)):
                        options=dict(skip_policy=guard=='policy',skip_pending=guard=='pending',
                            defer_dispatch=guard=='defer',counter_limit=limit,capture_count=count,
                            capture_request=request)
                        before=execute(cp,selector,descriptor,**options)
                        after=execute(cp,selector,descriptor,patched_cp=fixed,**options)
                        assert before['at_dispatch']==after['at_dispatch']
                        assert before['returned']==after['returned']
                        if guard in ('policy','pending'):
                            assert before==after
                        else:
                            wanted=(1 if limit and count<limit else 3) if request==1 and selector==1 else 0
                            assert after['mode']==wanted,(request,selector,descriptor,guard,limit,count,after)
                        cases+=1
    assert cases==360


@pytest.mark.parametrize('capture_input,front,sub',[(0,0,0),(1,0,0),(0,1,0),(0,1,1)])
def test_mechanical_electronic_and_front_policy_inputs(stock,capture_input,front,sub):
    ap,cp=stock;fixed=candidate.patch(ap,cp)['cpapp-b.bin']
    selector=cp_selector(cp,capture_input,front_policy=front,front_subpolicy=sub)
    mode=execute(cp,selector,0,patched_cp=fixed,capture_request=capture_input)['mode']
    assert mode==(3 if capture_input==1 and front==0 else 0)


def test_upgrade_idempotence_partial_states_and_factory_inverse(stock):
    ap,cp=stock
    legacy=bytearray(cp);legacy[candidate.OFFSET:candidate.OFFSET+2]=candidate.AFTER
    target=candidate.patch(ap,cp)['cpapp-b.bin']
    assert candidate.patch(ap,bytes(legacy))['cpapp-b.bin']==target
    assert candidate.patch(ap,target)['cpapp-b.bin']==target
    assert candidate.patch(ap,target,restore=True)['cpapp-b.bin']==cp
    for table in (candidate.TABLE_BEFORE,candidate.TABLE_AFTER):
        for gate in (candidate.CONTEXT,candidate.LEGACY_GATE,candidate.GATE_AFTER,candidate.GATE_MUTED):
            mixed=bytearray(cp)
            mixed[candidate.SELECTOR_TABLE:candidate.SELECTOR_TABLE+len(table)]=table
            mixed[candidate.GATE:candidate.GATE+len(gate)]=gate
            assert candidate.patch(ap,bytes(mixed))['cpapp-b.bin']==target
            assert candidate.patch(ap,bytes(mixed),restore=True)['cpapp-b.bin']==cp
    from looktool.direct import plan
    current={'appFw.so':ap,'cpapp-b.bin':bytes(legacy)}
    enabled,settings,_=plan(current,[{},{}],'sound_enable')
    assert enabled['cpapp-b.bin']==target and settings==[{},{}]
    assert plan(enabled,[{},{}],'sound_enable')[0]==enabled
    disabled=plan(enabled,[{},{}],'sound_disable')[0]
    assert candidate.sound_state(disabled['cpapp-b.bin'])=='muted'
    assert plan(disabled,[{},{}],'sound_disable')[0]==disabled
    assert plan(disabled,[{},{}],'sound_enable')[0]==enabled


def test_disabled_switch_keeps_mechanical_and_electronic_silent_with_custom_registration(stock):
    ap,cp=stock;muted=candidate.disable(ap,cp)['cpapp-b.bin']
    for capture_request in (0,1,2):
        for selector in range(5):
            assert execute(cp,selector,0,patched_cp=muted,capture_request=capture_request)['mode']==0


def test_factory_reference_contains_inverse_for_both_sound_windows(stock):
    import base64,zlib
    reference=json.loads((ROOT/'src/looks/assets/factory-layout-2.01.json').read_text())
    rows=reference['programs']['cpapp-b.bin']['regions']
    for at,before,after in candidate.WINDOWS:
        row=next(r for r in rows if r['offset']<=at and at+len(before)<=r['offset']+r['bytes'])
        assert 'zlib_base64' not in row and len(row['sha256'])==64


@pytest.mark.parametrize('legacy',[False,True])
def test_native_worker_writes_and_rolls_back_both_windows(stock,tmp_path,legacy):
    from verify_worker import verify,CP
    ap,cp=stock
    if legacy:
        prior=bytearray(cp);prior[candidate.OFFSET:candidate.OFFSET+2]=candidate.AFTER
        cp=bytes(prior)
    plan,target=candidate.build(ap,cp,tmp_path/'worker')
    spans=[(CP,w['offset'],bytes.fromhex(w['before_hex']),bytes.fromhex(w['after_hex']))
           for w in plan['windows']]
    result=verify(plan['native_program']['path'],plan['native_program']['sizes'],spans)
    assert result['compiled_worker_cases']==18
    assert result['camera_io'] is False


def test_wrong_capture_flag_producer_is_rejected_before_planning(stock):
    ap,cp=stock;changed=bytearray(cp);changed[0x7b0004]^=1
    with pytest.raises(ValueError,match='electronic-flag source'):
        candidate.patch(ap,bytes(changed))


def sound_calls(cp,mode,start):
    from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
    import struct
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    cpu.mem_map(0x4a0000,4096)
    cpu.mem_write(0x4a09f4,cp[0x3989f4:0x3989f4+0x40])
    cpu.mem_write(0x4a0a34,cp[0x398a34:0x398a34+0x14])
    cpu.mem_write(0x4a0a74,cp[0x398a74:0x398a74+0x5a])
    cpu.mem_map(0xb19000,4096);cpu.mem_write(0xb19e14,cp[0xa11e14:0xa11e14+0x48])
    cpu.mem_map(0xb0a000,4096);cpu.mem_map(0xe76000,4096)
    cpu.mem_map(0x30000000,0x7000);cpu.mem_write(0x30005c1c,struct.pack('<I',mode))
    cpu.mem_map(0x20000000,0x4000);cpu.mem_map(0x50000000,4096)
    cpu.reg_write(UC_ARM_REG_R0,0x30000000);cpu.reg_write(UC_ARM_REG_SP,0x20003000)
    cpu.reg_write(UC_ARM_REG_LR,0x50000001)
    calls=[];returned=[]
    def observe(uc,at,size,data):
        if at==0xb0a02e:
            calls.append(uc.reg_read(UC_ARM_REG_R0))
            uc.reg_write(UC_ARM_REG_R0,0);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
        elif at==0x50000000:
            returned.append(True);uc.emu_stop()
    cpu.hook_add(UC_HOOK_CODE,observe)
    cpu.emu_start(start|1,0x50000002,count=256)
    assert returned and cpu.reg_read(UC_ARM_REG_SP)==0x20003000
    return calls


def test_native_silent_mode_sends_nothing_in_both_exposure_phases(stock):
    _,cp=stock
    assert sound_calls(cp,0,0x4a09f4)==[]
    assert sound_calls(cp,0,0x4a0a74)==[]
    assert sound_calls(cp,3,0x4a09f4)==[3]
    assert sound_calls(cp,3,0x4a0a74)==[]


def test_save_prepares_support_from_the_current_body_without_a_separate_on_step(tmp_path):
    import boot_trial
    root,state=sound_cli.workspace(tmp_path/'sound',True,tmp_path/'backup')
    identity=dict(model='ILCE-7CM2',serial_sha256='synthetic')
    old=root/'old';old.mkdir();trial.save(old,dict(phase='written',identity=identity,complete_readback_and_settings_verified=True))
    converted=root/'converted';converted.mkdir();(converted/'custom-native.private.bin').write_bytes(bytes(64))
    state.update(native_job=str(old),conversion=str(converted))
    fresh=root/'fresh'
    def adopt(root_,state_,*args,**kwargs):
        assert kwargs.get('defer_reload') is True
        fresh.mkdir();trial.save(fresh,dict(phase='written',identity=identity,complete_readback_and_settings_verified=True))
        state_['native_job']=str(fresh)
    with patch.object(sound_cli,'on',side_effect=adopt) as on,patch.object(boot_trial,'require_dependencies'),\
         patch.object(boot_trial,'install',return_value={'phase':'installed_cold_test_pending'}) as install:
        sound_cli.install(root,state,100)
        # Save itself prepares or upgrades support from the current camera;
        # the old enable record is archived, not required or reused.
        on.assert_called_once()
        install.assert_called_once()
        assert install.call_args.args[2]==fresh
    assert any(h.get('job')==str(old) and h.get('phase')=='refresh_from_current_camera' for h in state['history'])


@pytest.mark.parametrize('selected',[False,True])
@pytest.mark.parametrize('prior',['stock','legacy','muted','current'])
def test_combined_install_upgrades_legacy_in_its_existing_plan(stock,selected,prior):
    from looktool import bundle
    ap,cp=stock
    if prior=='legacy':
        modified=bytearray(cp);modified[candidate.OFFSET:candidate.OFFSET+2]=candidate.AFTER;cp=bytes(modified)
    elif prior=='muted':cp=candidate.disable(ap,cp)['cpapp-b.bin']
    elif prior=='current':cp=candidate.patch(ap,cp)['cpapp-b.bin']
    before={'appFw.so':ap,'cpapp-b.bin':cp}
    options=dict(fl23=False,sound=selected)
    target,settings,_=bundle.plan(before,[{},{}],options,[])
    assert settings==[{},{}]
    assert target['appFw.so']==ap
    if selected or prior=='legacy':assert candidate.is_current(target['cpapp-b.bin'])
    else:assert target==before
    assert bundle.plan(target,[{},{}],options,[])[0]==target


def test_save_program_contains_selector_upgrade_before_the_audio_boot_hook(stock,tmp_path):
    import boot_trial
    from verify_worker import verify,AP,CP
    ap,cp=stock
    modified=bytearray(cp);modified[candidate.OFFSET:candidate.OFFSET+2]=candidate.AFTER;cp=bytes(modified)
    target_ap=bytearray(ap);target_ap[0x100:0x104]=b'test';target_ap=bytes(target_ap)
    edits=[(0x100,ap[0x100:0x104],b'test')]
    with patch.object(boot_trial.boot_sound,'plan',return_value=(target_ap,b'CSV',edits,{})):
        target,parts=boot_trial.prepare(ap,cp,bytes(64),tmp_path/'save')
    assert candidate.is_current(target['cpapp-b.bin'])
    assert len(parts['cp_windows'])==2
    spans=[(CP,w['offset'],bytes.fromhex(w['before_hex']),bytes.fromhex(w['after_hex'])) for w in parts['cp_windows']]
    spans += [(AP,*edit) for edit in edits]
    result=verify(parts['program']['path'],parts['program']['sizes'],spans)
    assert result['compiled_worker_cases']==18
    assert result['cases'][1]['pwrite_offsets']==[w[1] for w in spans]
