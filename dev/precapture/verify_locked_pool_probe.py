"""Offline original try-lock/sample/unlock composition on synthetic CPU0.

All native lock instructions execute, not a fabricated return. CPU/context,
lock objects and pool words are laboratory inputs. Other original diagnostic
services stop before execution. No deployable image/operator is emitted.
"""
import argparse,hashlib,itertools,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_MEM_WRITE
from unicorn import arm_const as R
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM,CS_MODE_THUMB
from support import cp_locked_pool_probe as p
from support.reference import SPECS

MESSAGE,STACK,STOP=0x30000100,0x40000000,0x50000000
CONTEXT,LOCK=0x31000000,0x31001000
CPU_TABLE,LOCK_TABLE,LOCK_COUNT=0x1b30708,0x1b29194,0xeb576c
SAVED=tuple(getattr(R,f'UC_ARM_REG_R{i}') for i in range(4,12))
BOUNDARIES={p.BASE+x for x in (0x45fcd8,0x4fdd70,0x4fe52c)}


class Fixture:
    def __init__(self,image):
        self.u=u=Uc(UC_ARCH_ARM,UC_MODE_ARM);u.ctl_set_cpu_model(R.UC_CPU_ARM_CORTEX_A9)
        u.mem_map(p.BASE,(len(image)+4095)&~4095);u.mem_write(p.BASE,image)
        for at,n in ((MESSAGE&~4095,8192),(STACK,65536),(STOP,4096),(CONTEXT,8192),
                (CPU_TABLE&~4095,4096),(LOCK_TABLE&~4095,4096),(p.sample.HEAD&~4095,4096),(0x1a7e000,4096)):
            u.mem_map(at,n)
        assert u.cpr_read(15,0,0,0,5,1,False)&3==0
        self.reads=[];self.writes=[];self.calls=[];self.visits=[];self.stops=set(BOUNDARIES);self.fault=False
        self.thumb=Cs(CS_ARCH_ARM,CS_MODE_THUMB);self.arm=Cs(CS_ARCH_ARM,CS_MODE_ARM)
        def code(cpu,at,size,user):
            if at==STOP or at in self.stops:cpu.emu_stop();return
            if p.BASE+p.TRY_FILE<=at<p.BASE+0x4e67cc or p.BASE+p.UNLOCK_FILE<=at<p.BASE+0x4e6988:
                mode='ARM'
            elif p.BASE+p.sample.ENTRY<=at<p.BASE+p.END:mode='Thumb'
            else:raise AssertionError('Unexpected native boundary '+hex(at))
            instruction=next((self.arm if mode=='ARM' else self.thumb).disasm(bytes(cpu.mem_read(at,size)),at,count=1))
            assert instruction.mnemonic!='wfe','Blocking wait in observer'
            self.visits.append(at)
            if at in (p.TRY,p.UNLOCK):
                self.calls.append(at)
                if at==p.UNLOCK and self.fault:
                    # Explicit adversarial fixture, never a real release
                    # result. Original release must reject the changed owner.
                    cpu.mem_write(CONTEXT+0x10,struct.pack('<I',0))
        def access(cpu,kind,at,size,value,user):
            if not any(a<=at<at+size<=a+n for a,n in ((MESSAGE,24),(STACK,65536),(CONTEXT,8192),
                    (CPU_TABLE,16),(LOCK_TABLE,108*4),(LOCK_COUNT,4),(p.sample.HEAD,20),
                    (p.BASE+0x45e704,4),(0x1a7e988,4),(0x30001038,4))):
                raise AssertionError('Access outside qualified synthetic state '+hex(at))
            (self.writes if kind==UC_MEM_WRITE else self.reads).append((at,size,value))
        u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access)
    def prepare(self,mode=0xe2,occupied=0,irq=False,interrupt=0,held=0,values=(0,3,3),nonce=0x157ac713):
        u=self.u;u.mem_write(STACK,b'\xa5'*65536);u.mem_write(CONTEXT,bytes(8192))
        put=lambda at,v:u.mem_write(at,struct.pack('<I',v))
        put(CPU_TABLE,CONTEXT);put(LOCK_COUNT,108);put(LOCK_TABLE+107*4,LOCK)
        put(0x1a7e988,0x30001000);put(0x30001038,4096)
        put(CONTEXT+0x40,interrupt);put(CONTEXT+0x10,held);put(LOCK,occupied);put(LOCK+8,0x55)
        for at,v in zip((p.sample.HEAD,p.sample.TAIL,p.sample.COUNT),values):put(at,v)
        packet=bytearray(24);packet[0]=mode;struct.pack_into('<I',packet,20,nonce);u.mem_write(MESSAGE,bytes(packet))
        u.reg_write(R.UC_ARM_REG_CPSR,0xa8000013|(0x80 if irq else 0))
        for index in range(13):u.reg_write(getattr(R,f'UC_ARM_REG_R{index}'),0xc2000000+index)
        for i,reg in enumerate(SAVED):u.reg_write(reg,0xc1000000+i)
        u.reg_write(R.UC_ARM_REG_R0,MESSAGE);u.reg_write(R.UC_ARM_REG_SP,STACK+0x8000);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        self.reads.clear();self.writes.clear();self.calls.clear();self.visits.clear();self.fault=False
    def run(self):
        self.u.emu_start(p.BASE+p.sample.ENTRY|1,0xffffffff,count=1000)
        pc=self.u.reg_read(R.UC_ARM_REG_PC);assert pc in self.stops|{STOP},'Instruction budget is not terminal'
        if pc==STOP:
            assert self.u.reg_read(R.UC_ARM_REG_SP)==STACK+0x8000
            assert all(self.u.reg_read(reg)==0xc1000000+i for i,reg in enumerate(SAVED))
        return dict(pc=pc,packet=bytes(self.u.mem_read(MESSAGE,24)),
            registers=[self.u.reg_read(getattr(R,f'UC_ARM_REG_R{i}')) for i in range(13)],
            stack_pointer=self.u.reg_read(R.UC_ARM_REG_SP),IRQ=bool(self.u.reg_read(R.UC_ARM_REG_CPSR)&0x80))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--current-cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(exist_ok=False);original=args.cp.read_bytes();current=args.current_cp.read_bytes()
    assert hashlib.sha256(original).hexdigest()==SPECS['a7c2-2.01']['sha256']
    target,windows=p.apply_for_emulator(original,current);old,new=Fixture(current),Fixture(target)
    cases=[]
    for occupied,irq,interrupt in itertools.product((0,1),(False,True),(0,1)):
        new.prepare(occupied=occupied,irq=irq,interrupt=interrupt);before=bytes(new.u.mem_read(CONTEXT,8192));result=new.run()
        rejected=occupied or irq or interrupt
        if not rejected:
            assert result['packet']==struct.pack('<BB6s4I',0xe2,p.STATUS,bytes(6),0,3,3,0x157ac713)
            assert new.calls==[p.TRY,p.UNLOCK] and not result['IRQ']
            assert bytes(new.u.mem_read(CONTEXT,8192))==bytes(8192)
            pool_reads=[(at,n) for at,n,v in new.reads if p.sample.HEAD<=at<=p.sample.COUNT]
            assert pool_reads==[(p.sample.HEAD,4),(p.sample.TAIL,4),(p.sample.COUNT,4)]
        else:
            assert result['packet'][1]==0x81 and new.calls==[p.TRY]
            assert bytes(new.u.mem_read(CONTEXT,8192))==before and result['IRQ']==irq
            assert not any(p.sample.HEAD<=at<=p.sample.COUNT for at,n,v in new.reads)
        cases.append(dict(occupied=occupied,IRQ_input=irq,interrupt_input=interrupt,refused=bool(rejected),native_calls=len(new.calls)))
    mode_cases=[]
    for mode in range(256):
        old.prepare(mode=mode);new.prepare(mode=mode);a,b=old.run(),new.run()
        if mode!=0xe2:assert a==b,mode
        mode_cases.append(dict(mode=mode,new_observer=mode==0xe2))
    # All writes are bounded to lock/context,message,private stack; never pool.
    new.prepare();new.run()
    assert not any(p.sample.HEAD<=at<=p.sample.COUNT for at,n,v in new.writes)
    new.prepare();new.fault=True;failure=new.run()
    assert failure['packet'][1]==0x82 and failure['IRQ']
    assert int.from_bytes(new.u.mem_read(LOCK,4),'little')==1
    # Distinguish the original supported path's cache arguments from the
    # optional observer. Execute the unchanged alignment call boundary over
    # all address/length low bits; no native cache service is stubbed.
    comparisons=0;extra_regs=tuple(getattr(R,f'UC_ARM_REG_R{i}') for i in range(13))+(R.UC_ARM_REG_CPSR,)
    for low,tail in itertools.product(range(64),range(64)):
        compared=[]
        for fixture in (old,new):
            fixture.prepare(mode=0)
            fixture.stops.add(p.BASE+p.sample.CALL)
            fixture.u.reg_write(R.UC_ARM_REG_R1,0x12340000|low)
            fixture.u.reg_write(R.UC_ARM_REG_R2,0xfedcba98)
            fixture.u.reg_write(R.UC_ARM_REG_R3,0xffffffc0|tail)
            fixture.u.emu_start(p.BASE+p.sample.ALIGN|1,0xffffffff,count=500)
            assert fixture.u.reg_read(R.UC_ARM_REG_PC)==p.BASE+p.sample.CALL
            compared.append(tuple(fixture.u.reg_read(r) for r in extra_regs))
        assert compared[0]==compared[1];comparisons+=1
    # Explicit failure evidence: cannot claim a failed native release is safe,
    # nor admit this candidate physically from a successful normal model.
    report=dict(schema='OFFLINE_LOCKED_CP_POOL_PROTOTYPE/1',camera_IO=False,installed=False,
        physical_execution_admitted=False,cases=cases,modes=mode_cases,
        original_cache_register_comparisons=comparisons,
        original_try_and_unlock_instructions_executed=True,modeled_CPU_context=True,
        native_lock_operations_physical=False,blocking_wait_executed=False,
        wrong_owner_release_control=dict(error_reply=True,lock_retained=True,IRQ_retained=True,safe_to_deploy=False),
        changed_window_bytes=sum(len(v) for _,v in windows),actual_changed_bytes=sum(a!=b for a,b in zip(current,target)),
        diagnostic_format_change='Original48-byte format becomes E%x:%x newline NUL plus code; both hexadecimal arguments preserved',
        source_sha256=hashlib.sha256(current).hexdigest(),target_sha256=hashlib.sha256(target).hexdigest(),
        unresolved=['All relevant pool writers must be proved under the same lock',
            'Real callback/task/CPU/IRQ nesting and interrupt-off latency unqualified',
            'Adversarial unlock-owner change retains IRQ/lock; no live recovery claim',
            'Shortened original diagnostic string needs complete reference/format review',
            'New firmware candidate/inverse requires its own explicit review and authorization'])
    (args.output/'report.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Actual original try/sample/release composition:8 context cases,256 modes;failure retention explicit; NO deployment admission')
if __name__=='__main__':main()
