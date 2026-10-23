"""Original scheduler class/preemption checks with explicit synthetic tasks.

No task is scheduled/woken and no lock, CPU migration or native callback runs.
These facts support only the existing conditional same-CPU lifetime model.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn import arm64_const as R
from support.boundaries import BoundaryRunner

SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
BASE=0xffffff8008080000
MEM,STACK,STOP=0x30000000,0x40000000,0x50000000
CLASSES={'stop':0x438710,'deadline':0x438658,'FIFO':0x4385a0,'normal':0x4384b0,'idle':0x4382c0}


def audit(raw):
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Exact original kernel required')
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(BASE,(len(raw)+4095)&~4095);u.mem_write(BASE,raw)
    for at,size in ((MEM,65536),(STACK,65536),(STOP,4096)):u.mem_map(at,size)
    A=lambda at:BASE+at
    def putq(at,v):u.mem_write(at,struct.pack('<Q',v))
    def putw(at,v):u.mem_write(at,struct.pack('<I',v))
    calls={A(0x43aac):'resched_curr',A(0x53718):'resched_curr',A(0x53688):'cpupri_find',A(0x536ac):'cpupri_find'}
    runner=BoundaryRunner(u,[SimpleNamespace(calls=calls)],stop=STOP,stack=STACK)
    order=list(CLASSES)
    for i,name in enumerate(order):
        pointer=struct.unpack_from('<Q',raw,CLASSES[name])[0]
        assert pointer==(A(CLASSES[order[i+1]]) if i+1<len(order) else 0)
    # Independently check encoded external call targets, rather than trusting
    # a name placed on an arbitrary stop coordinate.
    for at,target in ((0x43aac,0x43310),(0x53718,0x43310),(0x53688,0x587d0),(0x536ac,0x587d0)):
        word=struct.unpack_from('<I',raw,at)[0];assert word>>26==0b100101
        delta=word&0x3ffffff
        if delta&(1<<25):delta-=1<<26
        assert at+delta*4==target
    rq,current,waking=MEM+0x1000,MEM+0x3000,MEM+0x5000
    cases=[]
    for cur,new,preempt in (('FIFO','normal',False),('FIFO','idle',False),('normal','FIFO',True),
            ('idle','normal',True),('FIFO','deadline',True),('FIFO','stop',True),('deadline','FIFO',False)):
        u.mem_write(rq,bytes(0x1000));u.mem_write(current,bytes(0x400));u.mem_write(waking,bytes(0x400))
        putq(rq+0xbc0,current);putq(current+0x80,A(CLASSES[cur]));putq(waking+0x80,A(CLASSES[new]))
        putw(current+0x6c,1 if cur=='FIFO' else 0)
        got=runner.call(A(0x43a50),(rq,waking,0))
        assert got['at']==(A(0x43aac) if preempt else STOP)
        cases.append(dict(kind='original_class_wakeup_preemption',current_class=cur,waking_class=new,
            reaches_reschedule_service=preempt,reschedule_executed=False))
    for cur_priority,new_priority,expected in ((11,12,'return'),(11,10,'resched'),(11,11,'cpupri')):
        u.mem_write(rq,bytes(0x1000));u.mem_write(current,bytes(0x400));u.mem_write(waking,bytes(0x400))
        putq(rq+0xbc0,current);putq(current+0x80,A(CLASSES['FIFO']));putq(waking+0x80,A(CLASSES['FIFO']))
        putw(current+0x70,cur_priority);putw(waking+0x70,new_priority)
        got=runner.call(A(0x53630),(rq,waking,0))
        at={'return':STOP,'resched':A(0x53718),'cpupri':A(0x53688)}[expected]
        assert got['at']==at
        cases.append(dict(kind='original_equal_class_priority',current_internal_priority=cur_priority,
            waking_internal_priority=new_priority,boundary=expected,service_executed=False))
    # The actual single-allowed-CPU wakeup branch chooses from cpus_allowed,
    # not the sleeping task's historical stat CPU. Execute original pure
    # find_next_bit instructions, stopping BEFORE migration/task operations.
    for mask,online in ((1,15),(2,15),(4,15),(8,15),(4,3),(0,15)):
        u.mem_write(waking,bytes(0x400));putq(waking+0x258,mask)
        putq(A(0x606eb8),online)
        got=runner.run(A(0x456cc),(A(0x455c0),A(0x45760)),inputs=[
            (R.UC_ARM64_REG_X19,waking),(R.UC_ARM64_REG_SP,STACK+0x8000)])
        valid=bool(mask and mask&online)
        assert got['at']==(A(0x455c0) if valid else A(0x45760))
        if valid:assert u.reg_read(R.UC_ARM64_REG_X24)==mask.bit_length()-1
        cases.append(dict(kind='original_single_allowed_CPU_wakeup',allowed_mask=mask,online_mask=online,
            selected_CPU=mask.bit_length()-1 if valid else None,fallback_required=not valid,
            real_migration_or_scheduling=False))
    return dict(schema='OFFLINE_RPC_PREEMPTION_SOURCE/1',cases=cases,kernel_sha256=SHA,
        class_order=order,physical_camera_IO=False,lifetime_proven=False,live_send_admitted=False,
        limits=['Synthetic tasks/class inputs, not an actual kernel scheduling execution',
            'Single-CPU actual caller/worker binding, no throttling and worker-runnable state remain requirements',
            'Single-bit wakeup source is qualified but no live worker invocation CPU is observed',
            'Does not establish live affinity stability or absence of module unload',
            'No actual wakeup, callback or CP receipt; stage2 gate must remain refused'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kernel',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();report=audit(a.kernel.read_bytes())
    with a.output.open('x') as f:json.dump(report,f,indent=2)
    print(len(report['cases']),'original class/priority preemption slices;no real scheduling or send admission')


if __name__=='__main__':main()
