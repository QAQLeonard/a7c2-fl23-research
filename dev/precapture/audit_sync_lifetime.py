"""Original synchronous-wait/scheduler slices; no live RPC or kernel calls.

Establish source facts needed before reviewing a caller's lifetime contract.
Requested worker scheduling/CPU groups are not observed running-thread state.
No concurrency proof, deployment adapter or safe-send admission is supplied.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R
from support.kernel import Module, PCIE_SHA
from support.boundaries import BoundaryRunner
from support.memory import MEM, STACK

UTM_SHA = 'f6679c6481adaa0cffb5e27dbf949f5d8168ca4200f4cb245e900544977b5f1c'
KERNEL_SHA = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
KERNEL_BASE = 0xffffff8008080000
CODE, STOP, MAX_WAIT = 0x20000000, 0x50000000, 0x7fffffffffffffff


def scheduling_interleavings():
    """Abstract event-order control, NOT an execution of the native scheduler.

    Source facts checked below: caller unlock->ready read->cleanup lock->clear
    task->unlock->clear ready->return; waker ready store->lock->task read->wake
    ->unlock. Only the stated hypothetical scheduling regimes are modeled.
    """
    from collections import deque
    def explore(regime):
        # c,w,ready,task pointer,task state,lock owner,caller returned
        initial=(0,0,0,0,0,0,0)
        queue=deque([(initial,())]);visited={initial};violation=None;complete=0
        while queue:
            state,trace=queue.popleft()
            c,w,ready,task,sleep,lock,dead=state
            if dead and w==5:complete+=1;continue
            choices=[]
            caller_runnable=c<10 and not(c==4 and sleep==2)
            if caller_runnable and not(c in (0,5) and lock):choices.append('caller')
            if w<5 and not(w==1 and lock):choices.append('waker')
            if regime!='cross-CPU':
                if lock:
                    owner='caller' if lock==1 else 'waker'
                    choices=[choice for choice in choices if choice==owner]
                elif regime=='same-CPU-FIFO-unthrottled' and 0<w<5:
                    choices=[choice for choice in choices if choice=='waker']
            for actor in choices:
                cc,ww,rr,tt,ss,ll,dd=state
                if actor=='caller':
                    if c==0:ll=1;cc=1;event='caller wait-lock'
                    elif c==1:tt=1;ss=2;cc=2;event='caller publish task/state'
                    elif c==2:ll=0;cc=3;event='caller wait-unlock'
                    elif c==3:cc=5 if ready else 4;event='caller reads ready='+str(ready)
                    elif c==4:cc=0;event='caller resumes schedule'
                    elif c==5:ll=1;cc=6;event='caller cleanup-lock'
                    elif c==6:tt=0;ss=0;cc=7;event='caller clears task/state'
                    elif c==7:ll=0;cc=8;event='caller cleanup-unlock'
                    elif c==8:rr=0;cc=9;event='caller clears ready'
                    elif c==9:dd=1;cc=10;event='caller returns stack context'
                    else:raise AssertionError(c)
                else:
                    if dead:
                        violation=trace+('waker accesses returned context',)
                        return dict(regime=regime,visited_states=len(visited),counterexample=list(violation),
                                    completed_states=complete,abstract_only=True)
                    if w==0:rr=1;ww=1;event='waker stores ready'
                    elif w==1:ll=2;ww=2;event='waker acquires lock'
                    elif w==2:ww=3;event='waker reads task pointer'
                    elif w==3:
                        if task:ss=0
                        ww=4;event='waker wakes published task'
                    elif w==4:ll=0;ww=5;event='waker unlocks: last context access'
                    else:raise AssertionError(w)
                next_state=(cc,ww,rr,tt,ss,ll,dd)
                if next_state not in visited:
                    visited.add(next_state);queue.append((next_state,trace+(event,)))
        return dict(regime=regime,visited_states=len(visited),counterexample=None,
                    completed_states=complete,abstract_only=True)
    controls=[explore(regime) for regime in
        ('cross-CPU','same-CPU-FIFO-unthrottled','same-CPU-worker-can-be-throttled')]
    assert controls[0]['counterexample'] and controls[2]['counterexample']
    assert not controls[1]['counterexample'] and controls[1]['completed_states']
    return dict(controls=controls,native_scheduler_executed=False,physical_race_demonstrated=False,
        same_CPU_is_not_sufficient_without_scheduling_contract=True,
        limits=['States are source-inspired abstract events, not kernel instruction/scheduler execution',
            'No spurious wakes, arbitrary writes, CPU hotplug, migration or IRQ execution is modeled',
            'The FIFO case assumes a single CPU, strict priority and no throttling or task exit',
            'A counterexample exposes a contract gap, not a demonstrated Sony hardware defect',
            'Passing the conditional case is not live RPC or context-cleanup admission'])


def audit(pcie, utm, kernel):
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA:
        raise ValueError('Exact original Sony kernel required')
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    b = Module(u, pcie, PCIE_SHA, 0x10000000)
    t = Module(u, utm, UTM_SHA, 0x18000000)
    u.mem_map(CODE, (len(kernel) + 4095) & ~4095)
    u.mem_write(CODE, kernel)
    for at, size in ((MEM, 0x20000), (STACK, 0x10000), (STOP, 4096)):
        u.mem_map(at, size)
    B = lambda n: b.at('.text', n)
    T = lambda n: t.at('.text', n)
    K = lambda n: CODE + n
    extra = SimpleNamespace(calls={K(0x422fb8): 'schedule', T(0): 'SVC wrapper'})
    runner = BoundaryRunner(u, (b, t, extra), stop=STOP, stack=STACK)
    getq = lambda at: struct.unpack('<Q', bytes(u.mem_read(at, 8)))[0]
    getw = lambda at: struct.unpack('<I', bytes(u.mem_read(at, 4)))[0]

    # Independently cross-check the recovered scheduler entry against syscall119.
    assert struct.unpack_from('<Q', kernel, 0x432000 + 119 * 8)[0] == KERNEL_BASE + 0x46ec0
    wait = []
    for budget, boundary in ((MAX_WAIT, 0x422fb8), (MAX_WAIT - 1, 0x422e60)):
        got = runner.call(K(0x422e18), (budget,), (K(0x422e60),))
        assert got['at'] == K(boundary)
        wait.append(dict(kind='schedule-timeout-entry',budget=hex(budget),
                         boundary='schedule' if budget == MAX_WAIT else 'timer-init',native_call=False))
    # Independent post-schedule entry: its return is an input, not a real wakeup.
    frame = STACK + 0x7000
    u.mem_write(frame, struct.pack('<2Q', 0, STOP))
    got = runner.run(K(0x422fbc), inputs=[(R.UC_ARM64_REG_X19, MAX_WAIT),
        (R.UC_ARM64_REG_SP, frame), (R.UC_ARM64_REG_X29, frame)])
    assert got['at'] == STOP and got['args'][0] == MAX_WAIT
    wait.append(dict(kind='independent-post-schedule',returns=hex(MAX_WAIT),real_schedule=False))

    context = MEM + 0x1000
    u.mem_write(context, bytes(24))
    got = runner.call(B(0x4978), (context,))
    assert got['at'] == B(0x4990) and got['call'] == '_raw_spin_lock_irqsave'
    assert getw(context + 0x10) == 1 and getq(context + 8) == 0
    ordering = dict(ready_stored_before_lock=True,lock_executed=False,
                    inference='Caller lifetime still needs a concurrency contract')

    # Inspect actual unlock tail without executing a lock operation or DAIF.
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    def decoded(blob, start, end):
        return [(i.mnemonic, i.op_str) for i in md.disasm(blob[start:end], start)]
    unlock = decoded(kernel, 0x423c80, 0x423c90)
    assert unlock == [('ldrh','w2, [x0]'),('add','w2, w2, #1'),
                       ('stlrh','w2, [x0]'),('msr','daif, x1')]
    tail = decoded(b.elf.get_section_by_name('.text').data(), 0x49a4, 0x49bc)
    assert b.calls[B(0x49ac)] == '_raw_spin_unlock_irqrestore'
    assert tail == [('mov','x1, x20'),('mov','x0, x19'),('bl','#0x49ac'),
                    ('ldp','x19, x20, [sp, #0x10]'),
                    ('ldp','x29, x30, [sp], #0x20'),('ret','')]
    ordering['last_lock_address_access_precedes_irq_restore'] = True
    ordering['pcie_wakeup_does_not_dereference_context_after_unlock'] = True
    # Pin the model's event order against the actual waiter and waker code.
    original_text=b.elf.get_section_by_name('.text').data()
    assert decoded(original_text,0x4934,0x4948)==[
        ('ldr','w1, [x19, #0x10]'),('mov','x0, x20'),('cbz','w1, #0x4900'),
        ('mov','x0, x19'),('bl','#0x4944')]
    assert decoded(original_text,0x4954,0x4964)==[
        ('mov','x0, x19'),('str','xzr, [x19, #8]'),('bl','#0x495c'),('str','wzr, [x19, #0x10]')]
    assert b.calls[B(0x4944)]==b.calls[B(0x4990)]=='_raw_spin_lock_irqsave'
    assert b.calls[B(0x495c)]==b.calls[B(0x49ac)]=='_raw_spin_unlock_irqrestore'
    assert decoded(original_text,0x498c,0x4994)==[('str','w1, [x0, #0x10]'),('bl','#0x4990')]
    assert b.calls[B(0x49a0)]=='wake_up_process'

    # Trace the actual stack context into request metadata, stopping before
    # init/send/cache services. Message/header contents are synthetic inputs.
    frame, message, metadata = STACK + 0x8000, MEM + 0x5000, MEM + 0x6000
    got = runner.run(B(0x3608),inputs=[(R.UC_ARM64_REG_X29,frame)])
    assert got['call']=='pcieif_sleep_init' and got['args'][0]==frame+0x68
    u.mem_write(message-0x40,struct.pack('<Q',metadata))
    debug_root=getq(B(0x3c00));u.mem_write(debug_root,bytes(4))
    got=runner.run(B(0x3668),inputs=[(R.UC_ARM64_REG_X29,frame),
        (R.UC_ARM64_REG_X19,message),(R.UC_ARM64_REG_X22,0),
        (R.UC_ARM64_REG_X26,metadata)])
    assert got['call']=='pcieif_send_request' and got['args'][:3]==[0,frame+0x68,metadata]
    u.mem_write(metadata+8,struct.pack('<I',24))
    got=runner.call(B(0x2c38),(0,frame+0x68,metadata))
    assert got['call']=='__udif_cache_ctrl' and getq(metadata+0x18)==frame+0x68
    ordering['sender_context_location']='common sender stack frame+0x68'
    ordering['context_stored_in_message_metadata_offset']='0x18'
    ordering['init_send_cache_services_executed']=False

    workers = []
    frame = STACK + 0x8000
    # These are separate descriptor-setup fragments, not post-create successes.
    for index, start, create, affinity, mask in ((0,0x1e8,0x218,0x224,4),
                                               (1,0x34c,0x37c,0x388,8)):
        callback = getq(B(0x3f8))
        assert callback == B(0x3160)
        got = runner.run(B(start), inputs=[(R.UC_ARM64_REG_X19, MEM+0x2000),
            (R.UC_ARM64_REG_X20, callback), (R.UC_ARM64_REG_X29, frame)])
        assert got['at'] == B(create) and got['call'] == 'osal_create_waitable_thread'
        desc = got['args'][0]
        assert getw(desc+8) == 4 and getq(desc+0x10) == callback
        assert getq(desc+0x18) == index and getw(desc+0x24) == 148
        got = runner.run(B(affinity), inputs=[(R.UC_ARM64_REG_X0, 123)])
        assert got['call'] == 'osal_set_cpu' and got['args'][:2] == [123, mask]
        name=bytes(u.mem_read(getq(desc),64)).split(b'\0',1)[0].decode('ascii')
        workers.append(dict(index=index,name=name,proc_comm_prefix=name[:15],
                            descriptor_class=4,priority_request=148,
                            cpu_group_mask_request=mask,created_or_bound=False))

    # UTM class4 dispatches to priority supplied at descriptor+24. Stop BEFORE
    # its current-task/address-limit accesses and before the SVC trampoline.
    table = t.at('.rodata', 0)
    assert bytes(u.mem_read(table+4,1)) == b'F'  # c8 + signed46*4 = 1e0
    wrapper, descriptor = MEM + 0x3000, MEM + 0x3100
    u.mem_write(wrapper, struct.pack('<Q', descriptor))
    u.mem_write(wrapper+0x28, struct.pack('<I', 123))
    u.mem_write(descriptor+0x24, struct.pack('<I', 148))
    got = runner.run(T(0x1e0), (T(0x104),), inputs=[(R.UC_ARM64_REG_X0, descriptor),
        (R.UC_ARM64_REG_X19, wrapper),(R.UC_ARM64_REG_X29,frame)])
    assert got['at'] == T(0x104)
    assert got['args'][:2] == [123, 1] and getw(got['args'][2]) == 148
    got = runner.run(T(0x120))
    assert got['at'] == T(0) and got['args'][3] == 119
    assert decoded(t.elf.get_section_by_name('.text').data(),0,12) == [
        ('mov','w8, w3'),('svc','#0'),('ret','')]
    policy = dict(class4_requests_policy=1,priority=148,syscall_number=119,
                  scheduler_or_current_task_access_executed=False)

    # Sony's cached kernel admits priorities above upstream Linux's usual99.
    # Validate only the original attribute checks, never permissions/locking.
    scheduler = []
    for mode, priority, valid in ((1,148,True),(2,148,True),(1,159,True),
            (1,160,False),(1,0,False),(0,0,True),(0,148,False)):
        u.mem_write(descriptor+0x14, struct.pack('<I', priority))
        got = runner.run(K(0x43d84),(K(0x43dbc),K(0x43d28)),inputs=[
            (R.UC_ARM64_REG_X0,0),(R.UC_ARM64_REG_X20,mode),
            (R.UC_ARM64_REG_X21,descriptor)])
        assert got['at'] == K(0x43dbc if valid else 0x43d28)
        scheduler.append(dict(policy=mode,priority=priority,passes_attribute_checks=valid,
                              real_scheduler_change=False))

    # osal_set_cpu performs a proc-file test, not unconditional affinity.
    # No file, cgroup, kernel scheduler or other service is executed here.
    cpu_paths=[]
    for status, next_at in ((-2,0x5d0),(0x1234,0x5bc),(-13,0x590)):
        got=runner.run(T(0x5a8),(T(0x590),),inputs=[
            (R.UC_ARM64_REG_X0,status),(R.UC_ARM64_REG_X19,123),
            (R.UC_ARM64_REG_X20,4),(R.UC_ARM64_REG_X29,frame),
            (R.UC_ARM64_REG_SP,frame)])
        assert got['at']==T(next_at)
        if status == -13:
            assert got['args'][0] == 0
        cpu_paths.append(dict(synthetic_proc_open_result=status,
            reaches_cpuset_request=status==-2,
            zero_return_without_affinity=status==-13,file_or_affinity_operation=False))

    cached_rt_budget = dict(
        runtime_us=struct.unpack_from('<i',kernel,0x617384)[0],
        period_us=struct.unpack_from('<i',kernel,0x617f40)[0],
        observed_live=False)
    assert cached_rt_budget['runtime_us']==-1 and cached_rt_budget['period_us']==1000000

    # Original Sony cpuset routing. Every format/file/write service remains a
    # BEFORE boundary. Host strings below identify arguments, not executed I/O.
    cpuset_routes=[]
    for mask in range(16):
        got=runner.call(T(0x368),(1522,mask))
        if mask==0:
            assert got['call']=='printk'
            cpuset_routes.append(dict(mask=mask,rejected_before_native_log=True));continue
        assert got['call']=='snprintf' and got['args'][1]==0x23
        format_text=bytes(u.mem_read(got['args'][2],80)).split(b'\0',1)[0].decode('ascii')
        name=bytes(u.mem_read(got['args'][3],80)).split(b'\0',1)[0].decode('ascii')
        assert format_text=='/dev/cgroup/%s/tasks'
        expected={1:'cpu0',2:'cpu1',3:'cpu0_1',4:'cpu2',7:'cpu0_1_2',8:'cpu3rt',12:'cpu3rt'}.get(mask,'cpu0_1_2_3rt')
        assert name==expected
        cpuset_routes.append(dict(mask=mask,group=name,path=format_text%name,
            snprintf_open_write_called=False,exact_CPU_set_not_inferred_from_name=True))
    for mask in (4,7):
        got=runner.call(T(0x368),(1522,mask))
        output=got['args'][0]
        path='/dev/cgroup/'+('cpu2' if mask==4 else 'cpu0_1_2')+'/tasks'
        # Independent post-format state; no successful snprintf return is
        # supplied to the prior slice. File open itself is still unexecuted.
        u.mem_write(output,path.encode()+b'\0')
        got=runner.run(T(0x40c))
        assert got['call']=='filp_open' and got['args'][:3]==[output,2,0x1a4]
        cpuset_routes.append(dict(mask=mask,case='independent-fixed-path-open-boundary',
            flags=2,mode=0x1a4,no_create_or_truncate_flag=True,open_called=False))
    self_token=[]
    assert decoded(kernel,0x9bce0,0x9bcf0)==[
        ('stp','x29, x30, [sp, #-0x10]!'),('mov','w3, #0'),('mov','x29, sp'),('bl','#0x9ba10')]
    assert decoded(kernel,0x9ba84,0x9ba98)==[
        ('ldr','w0, [x29, #0x7c]'),('cbnz','w0, #0x9bbf0'),('mrs','x19, sp_el0'),
        ('cbz','w28, #0x9ba98'),('ldr','x19, [x19, #0x3c0]')]
    for pid_token in (0,1,1522):
        u.mem_write(frame+0x7c,struct.pack('<I',pid_token))
        got=runner.run(K(0x9ba84),(K(0x9ba8c),K(0x9bbf0)),inputs=[(R.UC_ARM64_REG_X29,frame)])
        assert got['at']==K(0x9ba8c if not pid_token else 0x9bbf0)
        self_token.append(dict(explicit_parsed_PID=pid_token,current_task_MRS_boundary=not pid_token,
            current_task_or_other_PID_lookup_executed=False))
    current_task,leader=MEM+0x1000,MEM+0x2000
    u.mem_write(current_task+0x3c0,struct.pack('<Q',leader))
    for threadgroup in (0,1):
        got=runner.run(K(0x9ba90),(K(0x9ba98),),inputs=[
            (R.UC_ARM64_REG_X19,current_task),(R.UC_ARM64_REG_X28,threadgroup)])
        assert got['at']==K(0x9ba98) and u.reg_read(R.UC_ARM64_REG_X19)==(leader if threadgroup else current_task)
        self_token.append(dict(threadgroup_argument=threadgroup,selected_group_leader=bool(threadgroup),
            native_reference_or_attach_executed=False))

    # Original update_curr_rt tests the GLOBAL signed runtime before per-rq
    # bandwidth/lock handling. Missing /proc/config.gz is not needed to locate
    # this guard in the exact cached binary. File identity is still not loaded
    # kernel identity, and these are explicit independent runtime inputs.
    rq,task,statistics=MEM+0x10000,MEM+0x12000,MEM+0x14000
    budget_cases=[]
    assert decoded(kernel,0x545fc,0x54608)==[
        ('adrp','x0, #0x617000'),('ldr','w0, [x0, #0x384]'),('tbnz','w0, #0x1f, #0x54580')]
    for runtime in (-1,0,950000,2147483647):
        u.mem_write(rq+0xbc0,struct.pack('<Q',task));u.mem_write(task+0x80,struct.pack('<Q',K(0x4385a0)))
        u.mem_write(task+0x100,struct.pack('<Q',20));u.mem_write(rq+0xbf8,struct.pack('<Q',100))
        u.mem_write(task+0x108,bytes(8));u.mem_write(task+0x580,struct.pack('<Q',statistics))
        u.mem_write(statistics+0x120,b'\0');u.mem_write(rq+0xc80,bytes(8))
        got=runner.call(K(0x54558),(rq,),(K(0x545f8),))
        assert got['at']==K(0x545f8)
        assert getq(task+0x108)==80 and getq(task+0x100)==100
        u.mem_write(K(0x617384),struct.pack('<i',runtime))
        got=runner.run(K(0x545fc),(K(0x54608),))
        assert got['at']==(STOP if runtime<0 else K(0x54608))
        budget_cases.append(dict(explicit_global_runtime_us=runtime,
            exits_before_per_runqueue_bandwidth=runtime<0,
            per_runqueue_lock_or_throttle_executed=False,cached_kernel_only=True))

    return dict(schema='OFFLINE_SYNC_CALLBACK_SCHEDULING_EVIDENCE/1',camera_io=False,
        pcie_sha256=PCIE_SHA,utm_sha256=UTM_SHA,kernel_sha256=KERNEL_SHA,
        wait=wait,completion_ordering=ordering,worker_requests=workers,
        utm_policy_request=policy,kernel_attribute_checks=scheduler,cpu_paths=cpu_paths,
        cached_rt_budget=cached_rt_budget,global_RT_budget_source_slices=budget_cases,
        original_cpuset_route_slices=cpuset_routes,
        cgroup_self_token_source_slices=self_token,
        scheduling_event_controls=scheduling_interleavings(),
        original_instruction_slices=len(wait)+1+3+2*len(workers)+2+len(scheduler)+len(cpu_paths),
        lifetime_proven=False,live_rpc_admitted=False,
        next_requirements=[
            'Prove standalone file-only exec and current exact device/source ownership first',
            'Observe actual completion worker identity, scheduling class/priority and CPU affinity',
            'Review serialization with a lower-priority same-CPU caller, including early completion',
            'Check actual RT bandwidth/group behavior; cached sysctl defaults do not prove current throttling',
            'Do not infer affinity from osal_set_cpu return0 or a group-mask request',
            'Do not issue synchronous RPC or install CP observer until lifetime admission is established'],
        limits=['All objects and post-call values are independent synthetic inputs',
                'No native create, schedule, affinity, lock, SVC, file I/O or CP send executes',
                'Source ordering exposes a question, not a demonstrated vendor bug or safe concurrency proof',
                'Neither successful pre-capture nor actual callback/boot/recovery safety is established'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pcie','utm','kernel','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    report=audit(a.pcie.read_bytes(),a.utm.read_bytes(),a.kernel.read_bytes())
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('Original wait, worker scheduling and CPU-request boundaries checked; lifetime and live RPC remain unproven.')


if __name__=='__main__':main()
