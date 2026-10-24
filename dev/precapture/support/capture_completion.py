"""Original software-state feedback fixture; no camera or peripheral model.

Requested/current words and configuration objects are explicit synthetic inputs.
Only original stores, table interpretation and masked completion execute. No
native property return, hardware completion, sensor or RAW lease is supplied.
"""
import struct

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4,
    UC_ARM_REG_R2, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R11,
    UC_ARM_REG_SP, UC_ARM_REG_LR)
from .capture_native import NativeCapture, BASE, OWNER, STACK, STOP, words

ROOT, TABLE, FLAGS, STATE = 0x1a52a88, 0x1725858, 0x1b1df9a, 0x1a52ad4
CONFIG, DEBUG = 0x173efe8, 0x1a533a4
SPANS = ((0x3aab54,0x48),(0xa171a0,0xfa),(0xa17354,0x176),
    (0x3d2b22,0x126),(0x3d2cb8,0x3c),(0xa25db4,10),
    (0xc8e410,246*16),(0xdd13ea,26),(0x25e95c,0x28),
    (0x3d2b12,0x10),(0x3d2cf8,0x2e),(0xa27066,0x1c),
    (0xa1729c,0x14),(0xa179fe,0x26),(0x3ae37c,0x20a),
    (0xa17e10,10),(0xa26f74,0x24),(0x3ad8ea,0x80),
    (0x3ada5e,0x10),(0xa1a312,4),(0xa19ab4,0x38),
    (0xa0585a,10),(0xa061a4,0x36),
    (0x36d0e8,0x1fa),(0xa0085c,0x18),(0xa06268,0x46),
    (0xa07e18,0x22),(0x36eed8,0x258))


def audit(cp):
    n=NativeCapture(cp);u=n.u
    for at,size in ((ROOT&~4095,4096),(TABLE&~4095,4096),
            (FLAGS&~4095,4096),(CONFIG&~4095,8192),(0x1870000,8192),
            (0x1a6a000,4096),(0x171f000,8192),(0x1a3a000,4096),
            (0x1a3f000,4096)):
        u.mem_map(at,size)
    getw=lambda at:struct.unpack('<I',u.mem_read(at,4))[0]
    half=lambda at:struct.unpack('<H',u.mem_read(at,2))[0]
    putw=lambda at,v:u.mem_write(at,words(v))
    puth=lambda at,v:u.mem_write(at,struct.pack('<H',v))
    # Original fixed-prefix initialization, independently entered AFTER the
    # omitted property reads; stop before the62 dynamic row constructors.
    n.run(0x25e95c,(0x25e984,),[(UC_ARM_REG_SP,STACK+0x8000)])
    assert bytes(u.mem_read(0x1870468,246*16))==cp[0xc8e410:0xc8e410+246*16]
    pair=next(struct.unpack_from('<4I',cp,0xc8e410+i*16) for i in range(246)
        if struct.unpack_from('<2I',cp,0xc8e410+i*16)==(0x11,0x3b))
    expected=list(struct.unpack_from('<13H',cp,pair[2]-BASE))
    terminal=expected[-1]
    assert terminal==0x8027
    watched=[i for i in range(13) if terminal&(1<<i)]
    assert watched==[0,1,2,5]

    def fresh():
        u.mem_write(ROOT,bytes(0x60));u.mem_write(TABLE,bytes(0x20))
        u.mem_write(FLAGS,bytes(4))
        assert n.call(0xa17354,[ROOT,0x1870468,246])['address']==STOP
        assert n.call(0xa1735a,[ROOT,0x11,0x3b])['address']==STOP
        assert getw(ROOT+0x14)==12
        assert getw(ROOT+0x10)==13
        assert bytes(u.mem_read(ROOT+0x18,26))==struct.pack('<13H',
            *[next((v for v in expected[:-1] if v>>8==i+1),0) for i in range(13)])
        for i in range(13):puth(ROOT+0x32+i*2,half(ROOT+0x18+i*2))

    # Independently mutate every current word. Unwatched differences cannot
    # be silently promoted into a proof that all groups or hardware completed.
    masks=[]
    for active in (0,1):
        for changed in (None,*range(13)):
            fresh();u.mem_write(ROOT+8,bytes([active]))
            if changed is not None:puth(ROOT+0x32+changed*2,half(ROOT+0x32+changed*2)^1)
            before=bytes(u.mem_read(ROOT,0x60))
            got=n.call(0x3aab54,[ROOT])
            result=u.reg_read(UC_ARM_REG_R0)
            assert got['address']==STOP and result==int(active==1 and changed not in watched)
            assert bytes(u.mem_read(ROOT,0x60))==before
            masks.append(dict(active=active,current_word_changed=changed,
                native_software_complete=bool(result),owner_unchanged=True))
    fresh();putw(ROOT+0x14,11)
    got=n.run(0x3aab54,(0xa3c57a,),[(UC_ARM_REG_R0,ROOT),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0xa3c57a
    private,handle=0x171f4d8,0x12345678
    # Explicit raw mode1 and two independent pre-existing capture-reference
    # inputs; no synthetic acquisition or reference is presented as physical.
    callback_frontier=[]
    for active in (0,1):
        u.mem_write(private,bytes(0x1000));putw(private,handle)
        putw(private+0x160,1)
        u.mem_write(0x1a3f3e0,bytes([active,0,active,0]))
        u.mem_write(0x1a3ab04,bytes(0x60));u.mem_write(OWNER,bytes(0x1000))
        u.mem_write(CONFIG,bytes(0x100));putw(CONFIG+0xc,OWNER)
        u.mem_write(0x1b1dea4,b'\1\1')
        got=n.run(0x36d0e8,(0xa05976,0xa06e5e,0x69f488,0xa3c57a),[
            (UC_ARM_REG_R0,handle),(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+(0xa06e5e if active else 0xa05976)
        callback_frontier.append(dict(existing_capture_reference=active,
            boundary_file=hex(got['address']-BASE),
            parameter_mode_raw=1,configuration_flags_are_synthetic=True,
            actual_reference_count=half(0x1a3f3e2),RAW_or_sensor_service_executed=False))

    # Execute the actual feedback stores at the end of the configuration job.
    # Distinct values prove provenance, including the debug selector mask.
    native,params,alternate,extra=OWNER,OWNER+0x1000,OWNER+0x3000,OWNER+0x8000
    source_offsets={0:(0xc,0xba4),2:(0x10,0),1:(0x44,0x14),
        3:(0x48,0),4:(0x38,0),6:(0x50,0),8:(0x20,0),9:(0x58,0)}
    selectors=[0x800,0x1fff,0xaaa|0x800,0x555|0x800]
    selectors+=list({0x800|(1<<i) for i in (0,1,2,3,4,6,8,9,10,12)})
    feedback=[]
    for selector in sorted(set(selectors)):
        fresh();u.mem_write(CONFIG,bytes(0x100));u.mem_write(OWNER,bytes(0xc000))
        putw(CONFIG,native)
        for field,_ in source_offsets.values():
            putw(CONFIG+field,params if field==0xc else alternate+field*8)
        for index,(field,offset) in source_offsets.items():
            at=getw(CONFIG+field)+offset;puth(at,0x200+index)
        puth(extra+0x3d52,0x20a);puth(extra+0x3d54,0x20c)
        native_offsets={0:4,1:8,2:6,3:10,4:12,5:14,6:16,
            8:18,9:20,10:22,11:24,12:26}
        for i,offset in native_offsets.items():puth(native+offset,0x100+i)
        puth(DEBUG+0x8e,selector)
        source=bytes(u.mem_read(OWNER,0xc000));config_before=bytes(u.mem_read(CONFIG,0x100))
        got=n.run(0x3d2b22,(0xa171cc,),[(UC_ARM_REG_R9,CONFIG),
            (UC_ARM_REG_R8,extra),(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0xa171cc
        selected=[]
        for i in range(13):
            if i==7:want=half(ROOT+0x18+14)  # No index7 store in this path.
            elif i in (5,11) or selector&(1<<i):want=0x100+i
            else:want=0x200+i
            assert half(ROOT+0x32+i*2)==want,(selector,i,half(ROOT+0x32+i*2),want)
            selected.append(want)
        assert bytes(u.mem_read(OWNER,0xc000))==source
        assert bytes(u.mem_read(CONFIG,0x100))==config_before
        feedback.append(dict(selector_raw=hex(selector),current_words=selected,
            stopped_before_completion=True,hardware_services_executed=False))
    # With selector11 clear the real native getter is a boundary. No invented
    # successful getter result is used to reach the later completion call.
    puth(DEBUG+0x8e,0)
    got=n.run(0x3d2b22,(0x94147c,),[(UC_ARM_REG_R9,CONFIG),
        (UC_ARM_REG_R8,extra),(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0x94147c
    # The actual parent path has its own upstream admission byte. Starting
    # at the later feedback slice alone must never claim this was satisfied.
    ready_cases=[]
    for ready in (0,1,2,255):
        putw(CONFIG+0x2c,alternate)
        u.mem_write(alternate+8,bytes([ready]))
        got=n.run(0x3d2b12,(0x3d2b22,0x3d2d26),[
            (UC_ARM_REG_R9,CONFIG),(UC_ARM_REG_R6,0),(UC_ARM_REG_R11,0)])
        assert got['address']==BASE+(0x3d2b22 if ready else 0x3d2d26)
        ready_cases.append(dict(upstream_byte=ready,feedback_selected=bool(ready)))

    # A completed software fence advances native bookkeeping only after the
    # selected current words match. A missing acknowledgement leaves it intact.
    completed=[]
    for acknowledged in (False,True):
        for notify in (0,1):
            fresh()
            # Original one-state descriptor for command3015 at state11.
            sequence=0xeda22e
            assert bytes(u.mem_read(sequence,4))==struct.pack('<2H',1,0x3b)
            u.mem_write(TABLE+8,words(sequence,1,0x3015))
            for at,value in ((STATE,0x11),(STATE+8,0x11111111),(STATE+12,0x11),
                    (STATE+16,0x3b),(STATE+20,0x3b),(STATE+24,0x22222222)):
                putw(at,value)
            u.mem_write(FLAGS,bytes([1,0,notify,1]))
            if not acknowledged:puth(ROOT+0x32,half(ROOT+0x18)^1)
            before=bytes(u.mem_read(STATE,28))+bytes(u.mem_read(FLAGS,4))
            got=n.call(0xa171cc,[]);assert got['address']==STOP
            if acknowledged:
                assert getw(STATE)==0x3b and getw(STATE+12)==0x3b
                assert getw(STATE+24)==(0x11111111 if notify else 0x3015)
                assert bytes(u.mem_read(FLAGS,4))==bytes(4)
                assert getw(STATE+8)==0  # Clear stored command only here.
            else:
                assert bytes(u.mem_read(STATE,28))+bytes(u.mem_read(FLAGS,4))==before
            completed.append(dict(acknowledged=acknowledged,notify=notify,
                native_bookkeeping_advanced=acknowledged,physical_completion_proven=False))
    # Independent constructor slice binds the actual deferred task; no task
    # startup or callback execution is fabricated from this metadata.
    task=0x1a6a728
    n.run(0xa27066,(0xa27082,),[(UC_ARM_REG_R0,0x74ca63),
        (UC_ARM_REG_R1,0x510021),(UC_ARM_REG_R4,0)])
    assert bytes(u.mem_read(task,29))==words(0x74ca63,0,0x510021,0,task,0x9d,0x42)+b'\0'
    # Actual post-completion producer: stop before OS enqueue.
    got=n.run(0x3d2cf8,(0x407f1c,),[(UC_ARM_REG_SP,STACK+0x8000)])
    assert got['args']==[task,STACK+0x8028,0,0]
    functor=bytes(u.mem_read(got['args'][1],20))
    assert functor==words(0x74ca7b,0,BASE+0xa26f74+1,0,0)
    # Skip no service as a successful call: this callback's first real logging
    # dependency is recorded separately; its following slice is explicit.
    got=n.run(0xa26f74,(0x4fb1b4,),[(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0x4fb1b4
    notifications=[]
    expected_events={0x3013:0x309,0x3014:0x308,0x3015:0x30b,0x3032:0x308}
    for command in (0x3013,0x3014,0x3015,0x3032):
        putw(STATE+24,command)
        got=n.run(0xa179fe,(0x3adfe4,),[(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0x3adfe4
        assert got['args'][0:2]==[0x1a52b34,0x900302d9]
        assert got['args'][3]==32 and getw(STATE+24)==0
        packet=struct.unpack('<8I',u.mem_read(got['args'][2],32))
        assert packet[:2]==(1,expected_events[command]) and packet[2:]==(0,)*6
        notifications.append(dict(completed_command_raw=hex(command),
            internal_event_raw=hex(packet[1]),post_executed=False,
            pending_slot_consumed_by_original_code=True))
    putw(STATE+24,0)
    got=n.run(0xa179fe,(0x7d31b8,),[(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0x7d31b8 and getw(STATE+24)==0
    # Independent receive slice AFTER real queue delivery/entry observers.
    # The collision above survives into the SAME original callback path.
    receiver=[]
    for command,event in expected_events.items():
        packet=OWNER+0x9000
        putw(packet,event)
        handler=0x3ad900+2*struct.unpack_from('<H',cp,0x3ad900+(event-0x300)*2)[0]
        got=n.run(0x3ad8ea,(handler,),[(UC_ARM_REG_R2,event),
            (UC_ARM_REG_R4,OWNER),(UC_ARM_REG_R5,packet)])
        assert got['address']==BASE+handler
        receiver.append(dict(command_raw=hex(command),internal_event_raw=hex(event),
            receive_handler_file=hex(handler),OS_delivery_executed=False))
    u.mem_write(OWNER,bytes(0x100));context=OWNER+0x1000;handle=0x12345678
    putw(OWNER+4,context);putw(context+4,handle)
    got=n.run(0x3ada5e,(0x407f1c,),[(UC_ARM_REG_R4,OWNER),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['args'][0]==0x1a3aae0 and got['args'][2:]==[handle,0]
    assert bytes(u.mem_read(got['args'][1],20))==words(0x870879,0,BASE+0x36d0e8+1,0,0)
    # Actual CAP callback validates its parameter handle before its first
    # configuration accessor. No RAW acquired by this prefix.
    private=0x171f4d8
    u.mem_write(DEBUG+0xa7,b'\0');u.mem_write(private,bytes(0x1000));putw(private,handle)
    got=n.run(0x36d0e8,(0xa00868,),[(UC_ARM_REG_R0,handle),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0xa00868
    assert u.reg_read(UC_ARM_REG_R6)==private+8
    got=n.run(0x36d0e8,(0xa3c57a,),[(UC_ARM_REG_R0,handle+1),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0xa3c57a
    return dict(terminal_raw=hex(terminal),watched_current_indices=watched,
        mask_cases=masks,nonterminal_input_stops_at_diagnostic=True,
        original_feedback_cases=feedback,unselected_native_getter_executed=False,
        original_completion_cases=completed,camera_io=False,
        upstream_feedback_admission_cases=ready_cases,
        deferred_task=dict(task_id_raw=0x9d,queue_id_raw=0x42,OS_enqueue_executed=False),
        original_completion_notifications=notifications,
        notification_packet_has_no_command_or_generation_token=True,
        empty_notification_slot_does_not_post=True,
        receive_dispatch=receiver,callback_handle_validated=True,
        first_CAP_callback_configuration_accessor_file='0xa00868',
        original_CAP_callback_frontier=callback_frontier,
        limits=['All configuration/current feedback is synthetic, never captured sensor state',
            'Current word updates are software observations, not a terminal sensor or RAW lifetime fence',
            '3014 and3032 share event308; that event alone cannot identify which request completed',
            'The original pending slot clears before post; ambiguous delivery never permits replay',
            'Only the fixed246-row state-pair prefix is used;62 dynamic rows remain unbound',
            'No exposure, pixel acquisition, image writer, cancellation or menu is installed'])


