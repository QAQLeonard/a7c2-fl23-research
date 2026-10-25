"""Original CP try-lock/release on synthetic ARM state, strictly offline.

Executes original CP15/LDREX/STREX on a configured Cortex-A9 emulator with
explicit CPU-context/table/lock objects. This is neither actual RTOS ownership
nor physical CPU/IRQ qualification. Native blocking helpers are not executed.
"""
import argparse,hashlib,itertools,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_MEM_WRITE
from unicorn import arm_const as R
from support.reference import SPECS,CP_LOAD_BASE

BASE=CP_LOAD_BASE
TRY,TRY_END=0x4e66f0,0x4e67cc
UNLOCK,UNLOCK_END=0x4e68a8,0x4e6988
TASK_LOCK,IRQ_LOCK=0x4e6450,0x4e65a0
TASK_UNLOCK,IRQ_UNLOCK=0x4e68a8,0x4e6988
CONTEXT_QUERY=0x4ea67c
CPU_TABLE=0x1b30708
LOCK_TABLE=0x1b29194
COUNT=0xeb576c
CONTEXT,LOCK,STACK,STOP=0x31000000,0x31001000,0x40000000,0x50000000
LOCK_ID=0x6c
SPANS=((TRY,TRY_END-TRY),(UNLOCK,UNLOCK_END-UNLOCK),
       (CONTEXT_QUERY,0x30),(0xb1788a,0x1a),(0x498034,0x1a))


def audit(original,current):
    if hashlib.sha256(original).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Exact original CP2.01 required')
    if len(current)!=len(original) or any(current[a:a+n]!=original[a:a+n] for a,n in SPANS):
        raise ValueError('Current native synchronization source differs')
    u=Uc(UC_ARCH_ARM,UC_MODE_ARM);u.ctl_set_cpu_model(R.UC_CPU_ARM_CORTEX_A9)
    u.mem_map(BASE,(len(original)+4095)&~4095);u.mem_write(BASE,original)
    for at,n in ((CPU_TABLE&~4095,4096),(LOCK_TABLE&~4095,4096),
            (CONTEXT,8192),(STACK,4096),(STOP,4096)):u.mem_map(at,n)
    # Explicit emulator CPU selection. It is never substituted into a live
    # MPIDR result or used as a physical camera mapping/ownership claim.
    assert u.cpr_read(15,0,0,0,5,1,False)&3==0
    writes=[];reads=[];steps=[];allowed=set();region=(0,0);boundaries=set();ISA=CS_MODE_ARM
    def code(cpu,at,size,user):
        if at==STOP or at in boundaries:cpu.emu_stop();return
        if not region[0]<=at<region[1]:raise AssertionError('Unexpected native boundary')
        ins=next(Cs(CS_ARCH_ARM,ISA).disasm(bytes(cpu.mem_read(at,size)),at,count=1))
        if ins.mnemonic=='wfe':raise AssertionError('No blocking wait permitted')
        if ins.mnemonic in ('bl','blx') and (not ins.op_str.startswith('#') or int(ins.op_str[1:],16) not in boundaries):
            raise AssertionError('No unqualified service call permitted')
        steps.append(ins.mnemonic)
    def access(cpu,kind,at,size,value,user):
        if not any(a<=at<at+size<=a+n for a,n in allowed):raise AssertionError('Unqualified data address '+hex(at))
        (writes if kind==UC_MEM_WRITE else reads).append((at,size,value))
    u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access)
    put=lambda at,v:u.mem_write(at,struct.pack('<I',v))
    get=lambda at:struct.unpack('<I',u.mem_read(at,4))[0]
    def prepare(interrupt=0,held=0,occupied=0,irq=False):
        u.mem_write(CONTEXT,bytes(8192));u.mem_write(STACK,b'\xa5'*4096)
        put(CPU_TABLE,CONTEXT);put(COUNT,108);put(LOCK_TABLE+(LOCK_ID-1)*4,LOCK)
        put(CONTEXT+0x40,interrupt);put(CONTEXT+0x10,held);put(LOCK,occupied)
        put(LOCK+8,0x55)
        u.reg_write(R.UC_ARM_REG_CPSR,0xa8000013|(0x80 if irq else 0))
        for index in range(4,12):u.reg_write(getattr(R,f'UC_ARM_REG_R{index}'),0xc1000000+index)
        u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP)
        return bytes(u.mem_read(CONTEXT,8192))
    def run(entry,finish,lock_id):
        nonlocal region,allowed,ISA
        ISA=CS_MODE_ARM;boundaries.clear()
        region=(BASE+entry,BASE+finish)
        allowed={(STACK,4096),(CPU_TABLE,16),(COUNT,4),(CONTEXT,8192),(LOCK_TABLE,108*4)}
        writes.clear();reads.clear();steps.clear();u.reg_write(R.UC_ARM_REG_R0,lock_id&0xffffffff)
        u.reg_write(R.UC_ARM_REG_LR,STOP)
        u.emu_start(BASE+entry,0xffffffff,count=1000)
        assert u.reg_read(R.UC_ARM_REG_PC)==STOP,'Bounded instruction budget exhausted'
        assert u.reg_read(R.UC_ARM_REG_SP)==STACK+0xf00
        assert all(u.reg_read(getattr(R,f'UC_ARM_REG_R{i}'))==0xc1000000+i for i in range(4,12))
        value=u.reg_read(R.UC_ARM_REG_R0);return value if value<0x80000000 else value-0x100000000
    cases=[]
    for irq,interrupt,occupied in itertools.product((False,True),(0,1),(0,1)):
        before=prepare(interrupt=interrupt,occupied=occupied,irq=irq)
        result=run(TRY,TRY_END,LOCK_ID)
        rejected=interrupt!=0 or irq or occupied!=0
        if rejected:
            assert result==(-25 if interrupt else -41 if occupied and not irq else -25)
            assert bytes(u.mem_read(CONTEXT,8192))==before
            assert bool(u.reg_read(R.UC_ARM_REG_CPSR)&0x80)==irq
            assert not any(CONTEXT<=at<CONTEXT+8192 for at,_,_ in writes)
        else:
            assert result==0 and get(LOCK)==1 and get(LOCK+8)==1 and get(CONTEXT+0x10)==LOCK_ID
            assert u.reg_read(R.UC_ARM_REG_CPSR)&0x80 and 'ldrex' in steps and 'strexeq' in steps
            locked=bytes(u.mem_read(CONTEXT,8192))
            # Actual original release is executed in the SAME synthetic CPU
            # state after that actual original acquisition, no success stub.
            result_release=run(UNLOCK,UNLOCK_END,LOCK_ID)
            assert result_release==0 and not(get(LOCK) or get(LOCK+8) or get(CONTEXT+0x10))
            assert not u.reg_read(R.UC_ARM_REG_CPSR)&0x80
            expected=bytearray(locked)
            for at in (LOCK,LOCK+8,CONTEXT+0x10):struct.pack_into('<I',expected,at-CONTEXT,0)
            assert bytes(u.mem_read(CONTEXT,8192))==bytes(expected)
        cases.append(dict(case='original_try_then_release' if not rejected else 'original_try_refused',
            IRQ_masked_input=irq,interrupt_nesting=interrupt,occupied=occupied,return_status=result,
            native_camera_lock_executed=False,synthetic_LDREX_STREX=True,blocking_wait_executed=False))
    for lock_id in (0,109,0xffffffff):
        before=prepare();result=run(TRY,TRY_END,lock_id)
        assert result==-18 and bytes(u.mem_read(CONTEXT,8192))==before
        cases.append(dict(case='invalid_lock_id',lock_id=lock_id,status=result))
    for held in (0,LOCK_ID-1):
        before=prepare(held=held,occupied=1,irq=True);result=run(UNLOCK,UNLOCK_END,LOCK_ID)
        assert result==-28 and bytes(u.mem_read(CONTEXT,8192))==before
        assert u.reg_read(R.UC_ARM_REG_CPSR)&0x80
        cases.append(dict(case='wrong_release_owner',held_id=held,status=result))
    routes=[]
    # Original worker and synchronous-direct path use these common wrappers.
    # The context query is a pre-call boundary; independent after-query
    # selectors do not claim it returned successfully on any real CPU.
    ISA=CS_MODE_THUMB
    for wrapper,after,end,targets in ((0xb1788a,0xb17892,0xb178a4,(TASK_LOCK,IRQ_LOCK)),
            (0x498034,0x49803c,0x49804e,(TASK_UNLOCK,IRQ_UNLOCK))):
        prepare();region=(BASE+wrapper,BASE+end);boundaries.clear();boundaries.add(BASE+CONTEXT_QUERY)
        u.reg_write(R.UC_ARM_REG_LR,STOP);u.emu_start(BASE+wrapper|1,0xffffffff,count=100)
        assert u.reg_read(R.UC_ARM_REG_PC)==BASE+CONTEXT_QUERY
        for selector in (0,1):
            prepare();region=(BASE+after,BASE+end);boundaries.clear();boundaries.update(BASE+x for x in targets)
            u.reg_write(R.UC_ARM_REG_R0,selector);u.reg_write(R.UC_ARM_REG_LR,STOP)
            u.emu_start(BASE+after|1,0xffffffff,count=100)
            expected=targets[int(selector==1)]
            assert u.reg_read(R.UC_ARM_REG_PC)==BASE+expected and u.reg_read(R.UC_ARM_REG_R0)==LOCK_ID
            routes.append(dict(wrapper_file=hex(wrapper),independent_context_selector=selector,
                selected_service_file=hex(expected),lock_id=LOCK_ID,selected_service_executed=False,context_query_executed=False))
    return dict(schema='OFFLINE_CP_POOL_TRYLOCK/1',cases=cases,camera_IO=False,live_lock_admitted=False,
        original_wrapper_routes=routes,
        original_source_sha256=hashlib.sha256(original).hexdigest(),current_source_sha256=hashlib.sha256(current).hexdigest(),
        exact_spans=[dict(file_offset=hex(a),bytes=n,sha256=hashlib.sha256(original[a:a+n]).hexdigest()) for a,n in SPANS],
        conditional_findings=['Task try-lock success leaves IRQ masked until matching native unlock',
            'Contended try-lock returns without waiting or changing the synthetic lock/owner',
            'Wrong unlock ownership preserves synthetic lock state and current IRQ mask'],
        unresolved=['Prove every relevant pool writer obeys the same lock,including interrupts/other CPUs',
            'Qualify actual callback context,CPU,existing lock nesting and bounded interrupt-off cost',
            'Prove native loaded routines/table identity and source-specific install/inverse',
            'Original try-lock can fail exclusives and reports refusal; do not loop/retry it in a live observer'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--current-cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.cp.read_bytes(),args.current_cp.read_bytes())
    with args.output.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(len(report['cases']),'original try-lock/release cases; synthetic CPU/exclusives only; no camera admission')
if __name__=='__main__':main()
