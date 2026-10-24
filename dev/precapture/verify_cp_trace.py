"""Compile/exercise the bounded recorder on both ISAs, strictly offline.

This tests new component code, not original sensor services or physical camera
safety. Native task/IRQ/placement/clock/export admission is not established.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB

from unicorn import UC_HOOK_MEM_WRITE,UC_HOOK_CODE
from unicorn import arm_const as A,arm64_const as B
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM,STACK,STOP
from support.trace import decode,BYTES,HEADER,RECORD,BINDING
from support.reference import SPECS

LANE,OTHER,EVENT,BIND=0x31001000,0x31003000,MEM+0x100,MEM+0x200
NAMES=('precapture_trace_initialize','precapture_trace_append','precapture_trace_freeze')
EXPECTED=dict(zip(BINDING,(0x58389855,0x12345678,0xabcdef01,0x88,4,1,0x139753ab)))


def exercise(elf,arch,folder,cp=None):
    native=('precapture_trace_native_event','precapture_trace_after_task',
        'precapture_trace_native_edge','precapture_trace_native_pool',
        'precapture_trace_pool_after_task') if arch=='thumb' else ()
    hooks=('precapture_trace_begin_hook','precapture_trace_begin_after',
        'precapture_trace_end_hook','precapture_trace_end_after') if arch=='thumb' and cp else ()
    u,symbols=image_loader(elf,arch,NAMES+native+hooks)
    u.mem_map(0x31000000,0x5000)
    registers=A if arch=='thumb' else B
    args=tuple(getattr(registers,('UC_ARM_REG_R' if arch=='thumb' else 'UC_ARM64_REG_X')+str(i)) for i in range(4))
    sp,lr,pc=(A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_PC) if arch=='thumb' else (B.UC_ARM64_REG_SP,B.UC_ARM64_REG_LR,B.UC_ARM64_REG_PC)
    publication=[];recording=False
    def writes(cpu,kind,at,size,value,user):
        if recording and LANE<=at<LANE+BYTES:
            publication.append(dict(offset=at-LANE,size=size,value=value))
    u.hook_add(UC_HOOK_MEM_WRITE,writes)
    def call(which,*values):
        for reg,value in zip(args,values):u.reg_write(reg,value)
        u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP|int(arch=='thumb'))
        u.emu_start(symbols[NAMES[which] if type(which)==int else which],STOP,count=50000)
        assert u.reg_read(pc)==STOP,'Exhausted recorder instruction budget'
        result=u.reg_read(args[0])&0xffffffff
        return result if result<0x80000000 else result-0x100000000
    def raw():return bytes(u.mem_read(LANE,BYTES))
    def prepare(capacity=4):
        u.mem_write(0x31000000,b'\xa5'*0x5000);u.mem_write(LANE,bytes(BYTES));u.mem_write(OTHER,bytes(BYTES))
        values=list(EXPECTED.values());values[4]=capacity
        u.mem_write(BIND,struct.pack('<8I',*values,0))
        return dict(zip(BINDING,values))
    expected=prepare();assert call(0,LANE,BIND)==1
    baseline=raw();assert call(0,LANE,BIND)==-16 and raw()==baseline
    assert call(1,LANE,0x89,EVENT)==-22  # Zero/invalid event is rejected first.
    u.mem_write(EVENT,struct.pack('<10I',5,7,11,0x8403,0xfffffff0,19,1,2,3,4))
    assert call(1,LANE,0x89,EVENT)==-1 and raw()==baseline
    assert call(1,LANE,expected['owner'],LANE+64)==-22 and raw()==baseline
    assert call(2,LANE,0x89)==-1 and raw()==baseline
    recording=True
    assert call(1,LANE,expected['owner'],EVENT)==1
    recording=False
    # Actual generated stores publish guard -> sequence -> count -> busy0.
    offsets=[item['offset'] for item in publication]
    assert offsets.index(HEADER+44)<offsets.index(HEADER)<offsets.index(40)
    busy=[item['value'] for item in publication if item['offset']==52]
    assert busy==[1,0]
    u.mem_write(EVENT,struct.pack('<10I',6,7,11,0x8403,0x10,19,5,6,7,8))
    assert call(1,LANE,expected['owner'],EVENT)==1
    unfrozen=raw()
    try:decode(unfrozen,expected)
    except ValueError:pass
    else:raise AssertionError('Unfrozen recording admitted')
    assert call(2,LANE,expected['owner'])==1
    completed=raw();decoded=decode(completed,expected)
    assert decoded['complete_recording'] and not decoded['physical_capture_proven']
    assert [r['clock_raw'] for r in decoded['records']]==[0xfffffff0,0x10]
    assert call(2,LANE,expected['owner'])==0 and raw()==completed
    assert call(1,LANE,expected['owner'],EVENT)==-30 and raw()==completed
    assert bytes(u.mem_read(LANE-16,16))==b'\xa5'*16
    assert bytes(u.mem_read(LANE+BYTES,16))==b'\xa5'*16
    # Same configured owner ID in a separate lane does not grant a shared
    # writer context; the second lane has independent storage and evidence.
    assert call(0,OTHER,BIND)==1 and raw()==completed
    assert call(1,OTHER,expected['owner'],EVENT)==1 and raw()==completed
    assert call(2,OTHER,expected['owner'])==1 and raw()==completed
    peer=decode(bytes(u.mem_read(OTHER,BYTES)),expected)
    assert len(peer['records'])==1
    # Every committed record word is independently corrupted, plus each
    # immutable header word, count, ownership flags and uncommitted tail.
    corruptions=[]
    for offset in (*range(0,64,4),*range(64,64+96,4),64+96, BYTES-1):
        bad=bytearray(completed);bad[offset]^=1
        try:changed=decode(bytes(bad),expected)
        except ValueError:corruptions.append(offset)
        else:
            assert offset==48 and changed['overflow'] and not changed['complete_recording'], 'Corrupt lane admitted: '+hex(offset)
    # Overflow is retained forensic data, never a complete capture trace.
    small=prepare(1);assert call(0,LANE,BIND)==1
    assert call(1,LANE,small['owner'],EVENT)==1
    first=raw()[64:112]
    assert call(1,LANE,small['owner'],EVENT)==-28
    assert call(1,LANE,small['owner'],EVENT)==-28 and raw()[64:112]==first
    assert call(2,LANE,small['owner'])==1
    overflow=decode(raw(),small)
    assert overflow['overflow'] and not overflow['complete_recording']
    # A nested/paused owner must preserve evidence; no synthetic cleanup.
    expected=prepare();assert call(0,LANE,BIND)==1
    u.mem_write(LANE+52,struct.pack('<I',1));paused=raw()
    assert call(1,LANE,expected['owner'],EVENT)==-16 and raw()==paused
    assert call(2,LANE,expected['owner'])==-16 and raw()==paused
    # A nonzero future record is corruption, never reusable ring capacity.
    expected=prepare();assert call(0,LANE,BIND)==1
    u.mem_write(LANE+64,struct.pack('<I',9))
    assert call(1,LANE,expected['owner'],EVENT)==-84
    assert raw()[64:68]==struct.pack('<I',9)
    assert call(2,LANE,expected['owner'])==1
    try:decode(raw(),expected)
    except ValueError:pass
    else:raise AssertionError('Uncommitted preoccupied slot admitted')
    # Invalid bindings leave even a fresh region exactly unchanged.
    invalid=[]
    for index,value in ((0,0),(3,0),(4,0),(4,65),(5,0),(6,0),(7,1)):
        prepare();values=[*EXPECTED.values(),0];values[index]=value
        u.mem_write(BIND,struct.pack('<8I',*values));before=raw()
        assert call(0,LANE,BIND)==-22 and raw()==before
        invalid.append(index)
    owner_cases=[];hook_cases=[]
    if arch=='thumb':
        expected=prepare();assert call(0,LANE,BIND)==1
        before=raw()
        for status,task in ((-25,0),(1,0x88),(0,0),(0,0x89)):
            assert call('precapture_trace_after_task',LANE,EVENT,status,task)==-1
            assert raw()==before
            owner_cases.append(dict(status=status,task=task,recorder_called=False))
        u.mem_write(EVENT,struct.pack('<10I',1,0,0,0,0,0,0,0,0,0))
        assert call('precapture_trace_after_task',LANE,EVENT,0,0x88)==1
        # Native wrapper stops BEFORE get_tid; its output starts0, and the
        # recorder does not change while that actual service is outstanding.
        u.mem_map(0x5f1000,4096);observed=[]
        def native_boundary(cpu,at,size,user):
            if at==0x5f1f24:
                pointer=cpu.reg_read(A.UC_ARM_REG_R0)
                assert bytes(cpu.mem_read(pointer,4))==bytes(4)
                observed.append(pointer);cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE,native_boundary)
        before=raw()
        u.reg_write(args[0],LANE);u.reg_write(args[1],EVENT)
        u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP|1)
        u.emu_start(symbols['precapture_trace_native_event'],0xffffffff,count=2000)
        assert len(observed)==1 and u.reg_read(pc)==0x5f1f24 and raw()==before
        owner_cases.append(dict(native_get_tid_entry_observed=True,
            output_initialized_zero=True,native_query_executed=False))
        # New actual wrappers are only run up to their FIRST real get_tid.
        # The clock/MMIO access and CP pool reads are never reached here.
        for name,kind in (('precapture_trace_native_edge',5),('precapture_trace_native_pool',0)):
            expected=prepare();expected['owner']=256 if not kind else 0x88
            u.mem_write(BIND,struct.pack('<8I',*expected.values(),0))
            assert call(0,LANE,BIND)==1;before=raw();observed.clear()
            u.reg_write(args[0],LANE);u.reg_write(args[1],kind);u.reg_write(args[2],0x12345678)
            u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP|1)
            u.emu_start(symbols[name],0xffffffff,count=2000)
            assert len(observed)==1 and u.reg_read(pc)==0x5f1f24 and raw()==before
            owner_cases.append(dict(wrapper=name,native_query_executed=False,
                clock_and_pool_access_not_reached=True))
        # The selected task-local pool reader runs against explicit synthetic
        # addresses derived from original setup, after independent task metadata.
        u.mem_map(0x1a8c000,4096);u.mem_map(0x22b4000,4096)
        pool_cases=[]
        for h,t,n,head_pointer in ((0,5,5,0x22b4720),(1022,1,3,0x22b4720),
                (1024,5,5,0x22b4720),(0,5,6,0x22b4720),
                (0,5,1024,0x22b4720),(0,5,5,0xf48300e0)):
            expected=prepare();expected['owner']=256
            u.mem_write(BIND,struct.pack('<8I',*expected.values(),0));assert call(0,LANE,BIND)==1
            binding=struct.pack('<4I',0x22a4760,head_pointer,0x22b4728,0x22b4730)
            u.mem_write(0x1a8c558,binding)
            u.mem_write(0x22b4720,struct.pack('<I',h));u.mem_write(0x22b4728,struct.pack('<I',t))
            u.mem_write(0x22b4730,struct.pack('<I',n));before=raw()
            accepted=head_pointer==0x22b4720 and h<=1023 and n<=1023 and ((t-h)&1023)==n
            result=call('precapture_trace_pool_after_task',LANE,256,0,100)
            assert result==(1 if accepted else -95 if head_pointer!=0x22b4720 else -84)
            assert bytes(u.mem_read(0x1a8c558,16))==binding
            assert bytes(u.mem_read(0x22b4720,4))==struct.pack('<I',h)
            assert bytes(u.mem_read(0x22b4728,4))==struct.pack('<I',t)
            assert bytes(u.mem_read(0x22b4730,4))==struct.pack('<I',n)
            if accepted:
                assert call(2,LANE,256)==1
                item=decode(raw(),expected)['records'][0]
                assert item['kind']=='pool' and item['detail']==[h,t,n,0x22a4760]
                assert item['clock_raw']==100 and item['generation']==0
            else:assert raw()==before
            pool_cases.append(dict(head=h,tail=t,count=n,pointer=head_pointer,
                accepted_on_synthetic_memory=accepted,native_pool_or_clock_verified=False))
        owner_cases.append(dict(pool_snapshot_cases=pool_cases,
            selected_pointer_corruption_refused_before_MMIO_access=True))
        for offset,value in ((12,0),(36,0),(44,1),(48,1),(52,1),(56,1)):
            expected=prepare();expected['owner']=256
            u.mem_write(BIND,struct.pack('<8I',*expected.values(),0));assert call(0,LANE,BIND)==1
            u.mem_write(LANE+offset,struct.pack('<I',value));before=raw();observed.clear()
            assert call('precapture_trace_native_pool',LANE)==-22
            assert call('precapture_trace_native_edge',LANE,5,0)==-22
            assert not observed and raw()==before
        owner_cases.append(dict(invalid_native_bindings_refused_before_task_query=6))
        if cp:
            codebase=0x108000;u.mem_map(codebase+0x396000,4096)
            u.mem_write(codebase+0x396000,cp[0x396000:0x397000])
            md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
            for which,at,value in (('begin',0x3967f4,0),('end',0x396878,4)):
                instructions=list(md.disasm(cp[at:at+6],at))
                assert [(i.mnemonic,i.op_str) for i in instructions]==[
                    ('push','{r4, r6, r7, lr}'),('add','r7, sp, #8'),('movs','r0, #'+str(value))]
                start,resume=codebase+at,codebase+at+6
                expected=prepare();assert call(0,LANE,BIND)==1 and call(0,OTHER,BIND)==1
                before=raw();observed.clear()
                u.reg_write(args[0],0x76543210);u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP|1)
                u.emu_start(symbols['precapture_trace_'+which+'_hook'],0xffffffff,count=5000)
                assert len(observed)==1 and u.reg_read(pc)==0x5f1f24 and raw()==before
                for flags in (0,0xf80f0000,0xa0050000,0x500a0000):
                    initial=[0xc1000000+i for i in range(13)]
                    caller_sp=STACK+0x3000;caller_lr=STOP|1
                    for i,v in enumerate(initial):u.reg_write(getattr(A,'UC_ARM_REG_R'+str(i)),v)
                    u.reg_write(sp,caller_sp);u.reg_write(lr,caller_lr)
                    u.reg_write(A.UC_ARM_REG_CPSR,flags|0x1f3)
                    u.emu_start(start|1,resume,count=50)
                    assert u.reg_read(pc)==resume
                    expected_regs=[u.reg_read(getattr(A,'UC_ARM_REG_R'+str(i))) for i in range(13)]
                    expected_flags=u.reg_read(A.UC_ARM_REG_CPSR)&0xf80f0000
                    expected_stack=bytes(u.mem_read(caller_sp-16,16))
                    # Independent AFTER-observer input. No native query or
                    # timer return is fabricated, and no camera job is resumed.
                    saved=struct.pack('<16I',flags,caller_lr,*initial,caller_lr)
                    u.mem_write(caller_sp-64,saved)
                    for i in range(13):u.reg_write(getattr(A,'UC_ARM_REG_R'+str(i)),0xdead0000+i)
                    u.reg_write(sp,caller_sp-64);u.reg_write(lr,0xdeadbeef)
                    u.reg_write(A.UC_ARM_REG_CPSR,0x1f3)
                    u.emu_start(symbols['precapture_trace_'+which+'_after'],resume,count=100)
                    assert u.reg_read(pc)==resume
                    assert [u.reg_read(getattr(A,'UC_ARM_REG_R'+str(i))) for i in range(13)]==expected_regs
                    assert u.reg_read(sp)==caller_sp-16 and u.reg_read(lr)==caller_lr
                    assert u.reg_read(A.UC_ARM_REG_CPSR)&0xf80f0000==expected_flags
                    assert bytes(u.mem_read(caller_sp-16,16))==expected_stack
                    hook_cases.append(dict(edge=which,flags=hex(flags),
                        exact_original_prefix_replayed=True,register_flags_stack_match=True,
                        observer_call_not_supplied_as_success=True))
    folder.mkdir()
    (folder/'completed-lane.private.bin').write_bytes(completed)
    report=dict(arch=arch,publication=publication,corruptions_rejected=corruptions,
        invalid_binding_cases=len(invalid),decoded=decoded,overflow=overflow,
        native_owner_cases=owner_cases,
        native_exposure_wrapper_cases=hook_cases,
        no_camera_IO=True,no_native_hooks_or_services=True,
        task_placement_export_and_physical_safety_unverified=True)
    (folder/'trace.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report,completed


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cp',type=Path,help='Pinned original CP for exposure-entry wrapper comparisons')
    p.add_argument('--current-cp',type=Path,help='Compare selected native binding FILE spans; not loaded-RAM admission')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).parent;results={};lanes=[]
    cp=a.cp.read_bytes() if a.cp else None
    if cp and hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Exact original CP required for exposure wrappers')
    binding_spans=((0x4e9f24,0x9c),(0x69f488,4),(0x69f266,0x12),
        (0xc67eec,12),(0xb13994,14),(0xb16314,0x82),
        (0xb16686,0x58),(0xb1671a,0x5e),(0x3967f4,0x5e),(0x396878,0x50))
    current=a.current_cp.read_bytes() if a.current_cp else None
    if current is not None and (cp is None or len(current)!=len(cp) or
            any(current[at:at+size]!=cp[at:at+size] for at,size in binding_spans)):
        raise ValueError('Current CP differs in selected trace-binding spans')
    for arch in ('thumb','aarch64'):
        elf=a.output/(arch+'-trace.elf')
        sources=[root/'cp_trace.c',*([root/'cp_trace_native.c'] if arch=='thumb' else [])]
        if arch=='thumb' and cp:
            wrapper=a.output/'EXPOSURE-HOOK-EMULATOR-ONLY.S'
            wrapper.write_text('#define PRECAPTURE_TRACE_BEGIN_LANE '+hex(LANE)+'\n#define PRECAPTURE_TRACE_END_LANE '+hex(OTHER)+'\n#include "'+(root/'cp_trace_hooks.S').resolve().as_posix()+'"\n',encoding='ascii')
            sources.append(wrapper)
        compile_shared(a.zig,arch,elf,sources)
        results[arch],raw=exercise(elf,arch,a.output/arch,cp);lanes.append(raw)
    assert lanes[0]==lanes[1]
    inputs=(Path(__file__),root/'cp_trace.c',root/'cp_trace_native.c',root/'cp_trace_hooks.S',root/'cp_trace.h',root/'support/trace.py',root/'decode_cp_trace.py')
    report=dict(camera_IO=False,results=results,cross_ISA_lane_bytes_identical=True,
        deployed=False,physical_precapture_complete=False,
        physical_deployment_allowed=False,
        native_binding_source_pins=[dict(file_offset=hex(at),bytes=size,
            sha256=hashlib.sha256(cp[at:at+size]).hexdigest()) for at,size in binding_spans] if cp else [],
        current_source_selected_spans_match=current is not None,
        current_CP_sha256=hashlib.sha256(current).hexdigest() if current else None,
        unbound_native_requirements=['Allocated code/lane placement and loader/export/inverse',
            'Loaded source/boot identity and hook task/IRQ/stack admission',
            'Actual clock read timing and binding of native context to a real image',
            'Consistent pixel-pool provenance and native asynchronous completion'],
        sources={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs})
    (a.output/'report.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Trace core and uninstalled owner/pool/exposure wrappers checked; no native hook installation, hardware access or camera deployment.')


if __name__=='__main__':main()
