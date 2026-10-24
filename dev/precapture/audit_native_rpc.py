"""Original UIPC owner/map/direct-RPC boundaries on synthetic RAM only.

Stops before native allocation, remap, locking, copying, scheduling and PCIe
services. Independent post-call inputs do not establish actual API success.
No device access, generated firmware or installation exists in this audit.
"""
import argparse
import json
import struct
from pathlib import Path

from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ
from unicorn import arm64_const as R
from support.kernel import Module, UIPC_SHA, PCIE_SHA, text_literal_dependencies
from support.boundaries import BoundaryRunner
from support.memory import MEM, STACK

STOP=0x50000000

def audit(uipc,pcie):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    a=Module(u,uipc,UIPC_SHA,0x10000000);b=Module(u,pcie,PCIE_SHA,0x18000000)
    for at,size in ((MEM,0x40000),(STACK,0x10000),(STOP,4096)):u.mem_map(at,size)
    A=lambda x:a.at('.text',x);B=lambda x:b.at('.text',x)
    runner=BoundaryRunner(u,(a,b),stop=STOP,stack=STACK,count=4000)
    run,call=runner.run,runner.call
    def putq(at,value):u.mem_write(at,struct.pack('<Q',value))
    def getq(at):return struct.unpack('<Q',bytes(u.mem_read(at,8)))[0]
    def putw(at,value):u.mem_write(at,struct.pack('<I',value))
    def getw(at):return struct.unpack('<I',bytes(u.mem_read(at,4)))[0]

    owner,task,vma,file=MEM+0x1000,MEM+0x2000,MEM+0x4000,MEM+0x5000
    owner_checks=[]
    # The SAME opaque task field is captured on context creation and checked
    # on ioctl. Never infer its semantic type just from the offset.
    for identity in (0x1122334455667788,0x8877665544332211):
        putq(task+0x2d8,identity)
        got=run(A(0x42c),(A(0x444),),[(R.UC_ARM64_REG_X0,task),(R.UC_ARM64_REG_X19,owner)])
        assert got['at']==A(0x444) and getq(owner+0x28)==identity
        owner_checks.append(dict(kind='context-captures-owner',same_opaque_field='task+0x2d8',identity_preserved=True))
    for match in (False,True):
        putq(owner+0x28,0x12345678);putq(task+0x2d8,0x12345678 if match else 0x87654321)
        got=run(A(0x558),(A(0x568),A(0x590)),[(R.UC_ARM64_REG_X0,task),(R.UC_ARM64_REG_X20,owner)])
        assert got['at']==A(0x568 if match else 0x590)
        owner_checks.append(dict(kind='ioctl-owner-comparison',matched=match,accepted=match))

    info_checks=[]
    dispatch=a.at('.rodata',0x3a0)
    assert getq(dispatch+16*8)==A(0xb50)
    got=call(A(0xb50),(0,MEM+0x6000,owner))
    assert got['at']==A(0xb88) and got['call']=='osal_dynamic_id'
    assert got['args'][:2]==[0x2a,0x3f]
    info_frame=u.reg_read(R.UC_ARM64_REG_SP)
    assert bytes(u.mem_read(info_frame+0x30,16))==struct.pack('<4I',0x200000,0x80000,0x20000,0)
    info_checks.append(dict(kind='initial-context-info',mapping_bytes=0x200000,
        local_heap_bytes=0x80000,aux_bytes=0x20000,dynamic_id_service_executed=False))
    for dynamic_id in (1,7):
        # Independent post-dynamic-id/pre-user-copy slice. No successful
        # allocator, user copy or kernel registration is supplied/executed.
        putw(info_frame+0x3c,dynamic_id)
        got=run(A(0xbd0),inputs=[(R.UC_ARM64_REG_X29,info_frame),(R.UC_ARM64_REG_X20,MEM+0x6000)])
        assert got['at']==A(0xbdc) and got['call']=='__arch_copy_to_user'
        assert got['args'][:3]==[MEM+0x6000,info_frame+0x30,16]
        assert getw(info_frame+0x3c)==dynamic_id
        info_checks.append(dict(kind='info-copy-boundary',synthetic_dynamic_id=dynamic_id,
            output_bytes=16,user_copy_or_registration_executed=False,reply_source_encoding_unproved=True))

    map_checks=[]
    for length in (0x1000,0x1ff000,0x200000,0x201000):
        putq(file+8,MEM+0x5800);putq(MEM+0x5800,owner)
        putq(vma,0x60000000);putq(vma+8,0x60000000+length);putq(vma+0x48,0x1234);putq(owner+0x30,0)
        got=call(A(0xd70),(file,vma),(A(0xd9c),A(0xe20)))
        assert got['at']==A(0xd9c if length==0x200000 else 0xe20)
        map_checks.append(dict(kind='mapping-size',bytes=length,accepted=length==0x200000,remap_executed=False))
    for returned in (0,1):
        # Independent post-remap slice. Explicit result0 is NOT a real remap.
        got=run(A(0xe00),(A(0xe0c),),[(R.UC_ARM64_REG_X0,returned),(R.UC_ARM64_REG_X19,vma),
            (R.UC_ARM64_REG_X20,owner)])
        assert got['at']==A(0xe0c)
        assert getq(owner+0x30)==(0 if returned else 0x60000000)
        map_checks.append(dict(kind='post-remap',synthetic_result=returned,user_base_stored=not returned,remap_executed=False))
        putq(owner+0x30,0)

    # Route5 copies24 bytes and handles callback delegation separately.
    frame=STACK+0x8000;user=0x60000000;native=MEM+0x20000
    root=getq(A(0x13b0));putq(root+0x40,native);putq(owner+0x30,user)
    sync_checks=[]
    for offset in (-1,0,64,0x1fffff,0x200000):
        for callback in (0,0x55667788):
            u.mem_write(frame+0x48,struct.pack('<3Q',user+offset,callback,0))
            got=run(A(0x12f0),(A(0x12c0),A(0x134c),A(0x1324)),[
                (R.UC_ARM64_REG_X0,0),(R.UC_ARM64_REG_X19,owner),(R.UC_ARM64_REG_X21,0x908f084b),
                (R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_SP,frame)])
            valid=0<=offset<0x200000
            expected=A(0x1324 if callback else 0x134c) if valid else A(0x12c0)
            assert got['at']==expected
            if valid:
                assert got['args'][:2]==[0x908f084b,native+offset]
                if not callback:
                    assert got['args'][2:]==[A(0x148),frame+0x38]
            sync_checks.append(dict(kind='direct-sync-message-range',offset=offset,callback_input=bool(callback),
                accepted=valid,delegation_finish=valid and bool(callback),whole_message_extent_checked=False,
                copy_or_sync_executed=False))
    # Post-native return without delegation does not copy user callback data.
    for status in (0,-1024):
        u.mem_write(frame,struct.pack('<2Q',0,STOP));putq(frame+0x40,0)
        got=run(A(0x1350),inputs=[(R.UC_ARM64_REG_X0,status),(R.UC_ARM64_REG_X29,frame),(R.UC_ARM64_REG_SP,frame)])
        assert got['at']==STOP and got['args'][0]&0xffffffff==status&0xffffffff
        sync_checks.append(dict(kind='post-native-no-delegation',synthetic_status=status,copy_to_user_executed=False))

    public=b.at('.data',0xb8);assert getq(public+8)==B(0x3c58)
    pubroot=getq(A(0x4158));putq(pubroot+0x458,public)
    got=call(A(0x3f18),(0x908f084b,native+64,0,0),(B(0x3c58),))
    assert got['at']==B(0x3c58) and got['args'][:2]==[0x908f084b,native+64]
    got=run(B(0x3c58));assert got['at']==B(0x34f8) and u.reg_read(R.UC_ARM64_REG_X20)==1
    sync_checks.append(dict(kind='registered-PCIe-sync-route',callback='0x3c58',common_sender_sync_flag=1,
                            debug_or_PCIe_service_executed=False))

    # Original wait budget is MAX_SCHEDULE_TIMEOUT, not the log DMA's3000.
    context=MEM+0x8000
    got=call(B(0x48e0),(context,))
    assert got['at']==B(0x4910) and u.reg_read(R.UC_ARM64_REG_X20)==0x7fffffffffffffff
    wait_checks=[dict(kind='initial-native-wait-budget',ticks='0x7fffffffffffffff',lock_or_schedule_executed=False)]
    for ready in (0,1):
        putw(context+0x10,ready)
        got=run(B(0x4934),(B(0x4900),B(0x4944)),[(R.UC_ARM64_REG_X19,context),
            (R.UC_ARM64_REG_X20,0x7fffffffffffffff)])
        assert got['at']==B(0x4900 if not ready else 0x4944)
        if not ready:assert got['args'][0]==0x7fffffffffffffff
        wait_checks.append(dict(kind='completion-flag',ready=bool(ready),reaches_schedule=not ready,schedule_executed=False))
    got=run(B(0x4904),(B(0x4910),),[(R.UC_ARM64_REG_X0,0x7fffffffffffffff),(R.UC_ARM64_REG_X19,context)])
    assert got['at']==B(0x4910) and u.reg_read(R.UC_ARM64_REG_X20)==0x7fffffffffffffff
    wait_checks.append(dict(kind='independent-post-schedule',synthetic_remaining='0x7fffffffffffffff',reenters_wait=True))

    # Qualify proposed ways around the synchronous stack waiter. These are
    # independent original slices, never a send/receive or successful queue
    # execution. In particular a user callback word is a finish selector,
    # not an asynchronous reply subscription.
    alternatives=[];message=native+64
    for callback in (1,0x55667788):
        u.mem_write(frame+0x48,struct.pack('<3Q',user+64,callback,0))
        got=run(A(0x12f0),inputs=[(R.UC_ARM64_REG_X0,0),(R.UC_ARM64_REG_X19,owner),
            (R.UC_ARM64_REG_X21,0x908f084b),(R.UC_ARM64_REG_X29,frame)])
        assert got['at']==A(0x1324) and got['call']=='__osal_finish_sync_cb'
        assert got['args'][:2]==[0x908f084b,native+64]
        got=call(A(0x3e30),(0x908f084b,native+64),(A(0x3e54),))
        assert got['at']==A(0x3e54) and got['args'][0]==0x908f084b
        alternatives.append(dict(kind='nonzero-callback-selects-finish',callback_input=callback,
            sends_or_installs_callback=False,stopped_before_local_lookup=True))

    for synchronous,entry in ((False,0x3c70),(True,0x3c58)):
        got=call(B(entry),(0x908f084b,message))
        assert got['call']=='pcieif_debug_measure_start'
        assert u.reg_read(R.UC_ARM64_REG_X20)==int(synchronous)
        alternatives.append(dict(kind='original-wrapper-mode',synchronous=synchronous,
            mode=int(synchronous),native_debug_or_send_executed=False))

    # Explicit post-getter state: no actual source/priority getter was run.
    for synchronous in (False,True):
        got=run(B(0x3534),inputs=[(R.UC_ARM64_REG_X0,0x803f6111),
            (R.UC_ARM64_REG_X19,message),(R.UC_ARM64_REG_X20,int(synchronous)),
            (R.UC_ARM64_REG_X25,1),(R.UC_ARM64_REG_X29,frame)])
        expected='pcieif_sleep_init' if synchronous else 'osal_get_msg_pri'
        assert got['call']==expected
        alternatives.append(dict(kind='post-source-getter-mode-branch',synchronous=synchronous,
            boundary=expected,native_service_executed=False))

    # Actual request argument construction. Trace-off is a synthetic input,
    # not a claim about the body's diagnostic switches or task scheduling.
    metadata=message-64
    putq(metadata,0x400001000)
    debug=getq(B(0x3c00));putw(debug,0)
    for synchronous,start in ((False,0x3594),(True,0x3668)):
        got=run(B(start),inputs=[(R.UC_ARM64_REG_X19,message),(R.UC_ARM64_REG_X22,0),
            (R.UC_ARM64_REG_X26,metadata),(R.UC_ARM64_REG_X29,frame)])
        expected_context=frame+0x68 if synchronous else 0
        assert got['call']=='pcieif_send_request' and got['args'][:3]==[0,expected_context,metadata]
        # Independent request-entry slice stops before cache/queue/hardware.
        putw(metadata+8,24)
        got=call(B(0x2c38),(0,expected_context,metadata))
        assert got['call']=='__udif_cache_ctrl' and getq(metadata+0x18)==expected_context
        alternatives.append(dict(kind='request-context-publication',synchronous=synchronous,
            publishes_stack_waiter=synchronous,context_offset='frame+0x68' if synchronous else None,
            cache_queue_send_executed=False))

    # A separate post-send return input is not proof of handoff. On the
    # asynchronous branch, the original caller still loads header words before
    # debug_measure_end. Even context==0 cannot certify message quiescence.
    for synchronous in (False,True):
        reads=[]
        def capture_read(cpu,kind,address,size,value,unused):
            if address < message and metadata < address+size:reads.append((address-metadata,size))
        hook=u.hook_add(UC_HOOK_MEM_READ,capture_read)
        try:
            got=run(B(0x35b8),inputs=[(R.UC_ARM64_REG_X0,0),
                (R.UC_ARM64_REG_X19,message),(R.UC_ARM64_REG_X20,int(synchronous)),
                (R.UC_ARM64_REG_X22,0),(R.UC_ARM64_REG_X29,frame)])
        finally:u.hook_del(hook)
        expected='pcieif_sleep_exec' if synchronous else 'pcieif_debug_measure_end'
        assert got['call']==expected
        assert reads==([] if synchronous else [(12,4),(16,4)]),reads
        alternatives.append(dict(kind='independent-post-send-tail',synchronous=synchronous,
            supplied_send_status=0,message_metadata_reads=reads,boundary=expected,
            real_send_or_wait_executed=False))
    scope=[dict(module=module,begin=begin,end=end) for module,begin,end in (
        ('osal_uipc',0x12f0,0x1324),('osal_uipc',0x3e30,0x3e54),
        ('pcie_if',0x3c58,0x3c88),('pcie_if',0x34c0,0x34f8),
        ('pcie_if',0x3534,0x3544),('pcie_if',0x3608,0x360c),
        ('pcie_if',0x3594,0x35b4),('pcie_if',0x3668,0x3678),
        ('pcie_if',0x2c38,0x2c9c),('pcie_if',0x35b8,0x35dc),
        ('pcie_if',0x36b8,0x36bc))]
    literals=[]
    for name,module,expected in (('osal_uipc',a,{0x13b0:[0x130c]}),
                                 ('pcie_if',b,{0x2d50:[0x2c68],0x3c00:[0x3594,0x3668]})):
        found=text_literal_dependencies(module,[(s['begin'],s['end']) for s in scope if s['module']==name])
        assert {row['begin']:row['readers'] for row in found}==expected
        assert all(row['bytes']==8 and len(row['relocations'])==1 for row in found)
        literals.extend(dict(module=name,**row) for row in found)
    literal_controls=[]
    for begin,end in ((0x12f1,0x1324),(0x12f0,0x1323),(0x13b0,0x13b8),
                      (0x13ac,0x13b8),(-4,0),(0,1<<32),(0x12f0,0x12f0)):
        try:text_literal_dependencies(a,[(begin,end)])
        except ValueError:literal_controls.append(dict(begin=begin,end=end,rejected=True))
        else:raise AssertionError('Invalid code scope accepted')
    return dict(schema='OFFLINE_NATIVE_DIRECT_RPC_BOUNDARIES/1',camera_io=False,uipc_sha256=UIPC_SHA,
        pcie_sha256=PCIE_SHA,owner_checks=owner_checks,info_checks=info_checks,map_checks=map_checks,sync_checks=sync_checks,wait_checks=wait_checks,
        lifetime_alternative_slices=alternatives,
        lifetime_alternative_code_scope=dict(coordinates='ET_REL .text offsets, not FILE offsets or physical addresses',
            spans=scope,loaded_bytes_proven=False),
        direct_literal_dependencies=literals,literal_scope_controls=literal_controls,
        literal_dependency_limits=['Direct literal loads only; not a transitive pointer or whole-function audit',
            'Literal words require exact relocation, fresh loaded bases and independent RAM verification',
            'A valid pointer literal does not establish the identity or lifetime of its referent'],
        alternative_limits=['Nonzero callback selects finish bookkeeping, not a remote send or callback registration',
            'Async request has no stack waiter but caller reads message metadata after supplied send return',
            'No real queue insertion/completion ordering, memory lifetime or transport drain is proven',
            'Keep physical send denied; these slices do not admit an alternative implementation'],
        limits=['All task/map/native results are synthetic; no kernel or device API executed',
                'Opaque owner-field semantics and real standalone context initialization are unproved',
                'The direct synchronous PCIe wait has no short deadline; process lifetime must be preserved',
                'No completion fault/cancel contract, CP response, source load or real pre-capture is established'])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uipc-kernel',type=Path,required=True);p.add_argument('--pcie',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=audit(a.uipc_kernel.read_bytes(),a.pcie.read_bytes())
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
    count=sum(len(report[k]) for k in ('owner_checks','info_checks','map_checks','sync_checks','wait_checks','lifetime_alternative_slices'))
    print(f'{count} original owner/map/direct-RPC/wait boundary slices; no kernel or camera operations.')
if __name__=='__main__':main()
