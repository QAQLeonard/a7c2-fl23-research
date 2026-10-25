"""Three native capture-admission boundaries; source evidence, no device I/O.

Pool provisioning, resource notification and exposure callbacks are distinct
contracts. Original instruction execution never establishes live CP RAM or an
exposure interval. Missing physical observations must remain missing.
"""
import struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4,
    UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR)
from .capture_native import NativeCapture, BASE, OWNER, STACK, STOP, words

SPANS=((0xb15d32,0x6e),(0xb13994,14),(0xb16314,0x82),(0xb14220,0xf8),
    (0xb173e0,0x80),(0xb12cd8,0x12),(0x496044,0xc0),
    (0xb1746c,0x32),(0xb174d0,0x288),(0xb1452c,0x28),
    (0x69f266,0x12),(0x69f488,4),(0xc67eec,12),
    (0x3967f4,0x5e),(0x396878,0x50),(0x397afc,0x22))


def audit(cp):
    n=NativeCapture(cp);u=n.u
    for at,size in ((0x1a8b000,8192),(0x1a50000,4096),(0x1b20000,4096),
            (0x174e000,4096)):
        u.mem_map(at,size)
    put=lambda at,v:u.mem_write(at,words(v))
    get=lambda at:struct.unpack('<I',u.mem_read(at,4))[0]
    packet=OWNER+0x1000
    # Original provisioning message to the AP-facing route. Allocate/send
    # are boundaries, never successful returns supplied to the native code.
    got=n.run(0xb15d32,(0x45d204,),[(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['args'][0]==0x8f013a and got['args'][2:]==[16,1]
    put(STACK+0x8004,packet);u.mem_write(packet,b'\xa5'*16)
    got=n.run(0xb15d54,(0xae401c,),[(UC_ARM_REG_R6,0),
        (UC_ARM_REG_SP,STACK+0x8000)])
    assert got['args'][:2]==[0x8f013a,packet]
    assert bytes(u.mem_read(packet,16))==struct.pack('<2H3I',11,0x61,0,0,0)
    # Exact original metadata arena arithmetic; no physical arena is mapped.
    got=n.run(0xb13994,(0xb16314,),[(UC_ARM_REG_R4,0),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['args'][:2]==[0,0x22a4760]
    got=n.run(0xb16314,(0xb14220,))
    assert got['args'][:2]==[0,0x22b4f40]
    n.run(0xb14220,(0xb1579a,))
    pointers={hex(at):hex(get(at)) for at in (0x1a8c558,0x1a8c55c,0x1a8c568,
        0x1a8c0ac,0x1a8c0cc,0x1a8c0d4,0x1a8c0e0)}
    assert get(0x1a8c558)==0x22a4760 and get(0x1a8c0cc)==0x22d3368
    # Resource-type policy reads originate in a native configuration read,
    # not in the fixed arena constants or in a successful metadata allocation.
    got=n.run(0xb173e0,(0x496044,),[(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['args'][:2]==[0x25b7ee8,8]
    got=n.run(0x496044,(0xae133a,),[(UC_ARM_REG_R0,0x25b7ee8),
        (UC_ARM_REG_R1,8),(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['args'][0]==0xfa0182
    pool=dict(original_metadata_arena='0x22a4760',derived_metadata_pointers=pointers,
        AP_provisioning_route='0x8f013a',provisioning_command=11,subcommand=0x61,
        AP_provisioning_role='shared bookkeeping; not itself a pixel lease',
        resource_policy_destination='0x25b7ee8',configuration_reader_file='0x496044',
        native_configuration_selector='0xfa0182',
        physical_pool_provenance_verified=False,
        missing=['Fresh CP runtime pointers/region ownership and consistent allocator state',
            'Actual AP-provided shared-block binding and resource-type configuration',
            'Loaded-code/boot identity and address/extent admission for the same observation'])

    # Both notification paths call the real synchronization helper first.
    # Separate post-helper inputs do not claim that it completed.
    u.mem_write(0x1b200f4,b'\1')
    sync=[]
    selector,categories=OWNER+0x2000,OWNER+0x2100
    put(0x1a8c0d4,selector);put(0x1a8c0d8,categories)
    u.mem_write(selector,bytes(4));u.mem_write(categories,b'\1\0')
    for command in (0x20,0x23):
        got=n.run(0xb1746c,(0xb176a4,),[(UC_ARM_REG_R0,command),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0xb176a4
        for state in (0,1,2):
            put(0x11f7330,state)
            start=0xb1753e if command==0x20 else 0xb175c2
            got=n.run(start,(0x45d204,0xb1788a))
            sends=(command==0x20 and state==0) or (command==0x23 and state==1)
            assert got['address']==BASE+(0x45d204 if sends else 0xb1788a)
            if sends:assert got['args'][0]==0x92a20524 and got['args'][2:]==[16,1]
            sync.append(dict(command_raw=hex(command),software_state=state,
                notification_request_selected=sends,synchronization_executed=False,
                allocation_or_send_executed=False))
    notifications=[]
    for command,start,expected in ((0x20,0xb17564,0x920232),(0x23,0xb175f8,0x920231)):
        put(STACK+0x8004,packet);u.mem_write(packet,b'\xa5'*16)
        got=n.run(start,(0xae401c,),[(UC_ARM_REG_R4,0x92a20524),
            (UC_ARM_REG_SP,STACK+0x8000)])
        assert got['args'][:2]==[0x92a20524,packet]
        assert bytes(u.mem_read(packet,16))==words(expected,0,0,0)
        notifications.append(dict(command_raw=hex(command),route='0x92a20524',
            event_word=hex(expected),remaining_words_zero=True,
            frame_handle_or_capture_generation_in_packet=False,send_executed=False))
    asynchronous=dict(original_synchronization_boundary_file='0xb176a4',
        dispatch_cases=sync,original_packet_cases=notifications,
        physical_asynchronous_completion_verified=False,
        missing=['Actual matched request/reply and queue-task execution for the same shot',
            'Terminal observation of backing/reference release with no late owner/ingress',
            'Original synchronization/accounting/notifier completion, not a supplied post-call slice'])
    waiter=[]
    for prior in (0,1):
        u.mem_write(0x1b200f5,bytes([prior]))
        got=n.run(0xb176a4,(0x498034,),[(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0x498034
        assert bytes(u.mem_read(0x1b200f5,1))==b'\1'
        if prior:
            # Explicit AFTER-unlock slice; native unlock did not execute.
            got=n.run(0xb176c2,(0x45cfac,))
            assert got['args'][0]==0x910041
            descriptor=bytes(u.mem_read(got['args'][1],40))
            assert struct.unpack('<10I',descriptor)==(40,0,0,0,0,0,10,0,0,0)
            # Explicit later flag input after omitted wait/lock; if still1,
            # native code goes back to another synchronization boundary.
            got=n.run(0xb176f8,(0x498034,))
            assert got['address']==BASE+0x498034
        waiter.append(dict(prior_busy=prior,native_state_still_busy=True,
            wait_descriptor_has_ten_raw_units=bool(prior),
            native_wait_lock_or_unlock_executed=False,
            elapsed_time_or_bounded_total_wait_proven=False))
    asynchronous['synchronization_wait_cases']=waiter
    asynchronous['one_wait_timeout_is_not_a_total_completion_deadline']=True

    # Clock0 getter stops BEFORE its actual hardware register read. That ROM
    # pointer is provenance only: no fabricated timer value, IRQ or ready bit.
    # Verify its original tail branch independently, and enter the pure target
    # prefix. Shared native-service guards stay unchanged in this fixture.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    branch=next(md.disasm(cp[0x69f488:0x69f48c],0x69f488))
    assert (branch.mnemonic,branch.op_str)==('b.w','#0x69f266')
    counter_sources=[]
    for index,base in enumerate((0xf4830000,0xf4840000,0xf4850000)):
        got=n.run(0x69f266,(0x69f272,),[(UC_ARM_REG_R0,index),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['args'][0]==base
        counter_sources.append(dict(index=index,counter_register=hex(base+0xe0),
            stopped_before_hardware_read=True))
    # Both original callback addresses are actually stored by this selector.
    selection=OWNER+0x3000
    for raw in (2,3):
        u.mem_write(selection,bytes(32))
        n.run(0x397afc,(0x397cae,),[(UC_ARM_REG_R4,selection),
            (UC_ARM_REG_R6,raw),(UC_ARM_REG_SP,STACK+0x8000)])
        assert get(selection+16)==BASE+0x3967f4+1
        assert get(selection+12)==(BASE+0x396878+1 if raw==2 else 0xb190bb)
    # Start callback samples the timer; end callback only posts an event.
    end_instructions=list(md.disasm(cp[0x396878:0x3968c8],0x396878))
    assert end_instructions[-1].address==0x3968c6
    calls=[i.op_str for i in end_instructions if i.mnemonic in ('bl','blx')]
    assert calls==['#0xa3b61c','#0x4e1a7c','#0xa3c57a','#0xa3b61c']
    got=n.run(0x3967f4,(0x69f488,),[(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['args'][0]==0
    samples=[]
    for sample in (0,0x12345678,0xffffffff):
        got=n.run(0x3967fe,(0xa3b61c,),[(UC_ARM_REG_R0,sample),
            (UC_ARM_REG_SP,STACK+0x8000)])
        assert get(0x1a508a0)==sample
        samples.append(dict(sample_raw=sample,latch_matches=True,real_timer_executed=False))
    events=[]
    for start,event in ((0x396816,1),(0x39688a,2)):
        got=n.run(start,(0x4e1a7c,),[(UC_ARM_REG_SP,STACK+0x8000)])
        assert got['args'][:2]==[0x34,event]
        events.append(dict(callback_slice_file=hex(start),event_flag_raw=0x34,
            event_bit=event,event_post_executed=False))
    timing=dict(start_callback_file='0x3967f4',end_callback_file='0x396878',
        clock0_counter_register='0xf48300e0',hardware_counter_read=False,
        samples=samples,event_posts=events,end_callback_does_not_store_end_timestamp=True,
        original_end_callback_direct_calls=calls,
        original_counter_sources=counter_sources,
        physical_exposure_timing_verified=False,
        missing=['Real exposure begin/end and real S2 edge from the same capture generation',
            'Calibrated clock rate/domain plus counter wrap/reset handling',
            'An independently observed pre-S2 exposure interval linked to actual retained pixels'])
    return dict(pool_provenance=pool,asynchronous_completion=asynchronous,
        exposure_timing=timing,all_three_physically_verified=False,
        camera_io=False,installable_observer_created=False)
