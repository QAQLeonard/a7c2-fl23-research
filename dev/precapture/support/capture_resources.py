"""Original resource preparation/request slices, on synthetic memory only.

External logging, locks, waits, allocation and IPC stop before execution.
Independent post-service slices do not manufacture successful native returns.
No device I/O, resource acquisition, exposure or installable firmware exists.
"""
import itertools
import struct

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_SP, UC_ARM_REG_LR)
from .capture_native import NativeCapture, BASE, OWNER, STACK, STOP, DEBUG, words

CAP, RESOURCE, SETTINGS = 0x1a3aae0, 0x1a3f380, 0x1720298
SPANS=((0xa05976,0xc0),(0x36ee18,0xa4),(0xa09aee,0x3a),
    (0xa06e5e,0x40),(0xa06e9e,0x1de),(0xa079d4,0x36),
    (0x370f3c,0x128),(0xa12b90,0x30),(0xa010f8,12),
    (0xbe0380,0x88),(0xa06b80,0x3e),(0xa06bbe,0x62),
    (0xa13b3a,0x30),(0x40a63c,0x13a),
    (0xa07400,0xb4),(0x370402,0x86),(0xa075c6,0x30),
    (0xa074f0,0x5a),(0x3708e8,0x10a),(0xa07df6,0x22),
    (0x408870,0x22),(0x4089b4,0xb2),(0x370af0,0x70),
    (0x37078c,0x122),(0x37019c,0x16c),(0xa074b4,0x3c),
    (0xa04f28,0x11a),(0xa13a60,0x38),(0x408fdc,0x20),
    (0x409030,0x24),(0x4090ec,0x62))


def audit(cp):
    n=NativeCapture(cp);u=n.u
    for at,size in ((0x1a3a000,4096),(0x1a3f000,4096),(0x1720000,4096),
            (0x1b1d000,4096),(0x1ac5000,4096),(0x1a44000,8192)):
        u.mem_map(at,size)
    put=lambda at,v:u.mem_write(at,words(v))
    get=lambda at:struct.unpack('<I',u.mem_read(at,4))[0]
    u.mem_write(0x1a45ca4,words(CAP))
    configuration=[]
    # Original producer reaches the actual retention-config callback enqueue.
    # Mode22 is a negative synthetic profile, not a UI drive/shutter name.
    for mode,count in itertools.product((0,1,2,6,22,23,26,33),(0,1,2)):
        u.mem_write(OWNER,bytes(0x1000));put(OWNER+0x138,mode);put(OWNER+0x120,count)
        u.mem_write(DEBUG,bytes(256));u.mem_write(0x1a3ab04,bytes(0x60))
        before=bytes(u.mem_read(OWNER,0x1000))
        got=n.run(0xa05976,(0x407f1c,0xa3c57a),[
            (UC_ARM_REG_R0,OWNER),(UC_ARM_REG_R1,0),(UC_ARM_REG_R2,0),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert bytes(u.mem_read(OWNER,0x1000))==before
        assert (got['address']==BASE+0xa3c57a)==(mode==22)
        if mode!=22:
            assert got['args'][0]==CAP and got['args'][2:]==[0,0]
            assert bytes(u.mem_read(got['args'][1],20))==words(0x74ca7b,0,BASE+0xa09b28+1,0,0)
        configuration.append(dict(mode_raw=mode,count_raw=count,
            boundary_file=hex(got['address']-BASE),
            native_policy=get(0x1a3ab08),derived_count=get(0x1a3ab14),
            actual_OS_enqueue_executed=False))

    # Function entry logs, then takes a native critical section. The known
    # entry and AFTER-logger slice stop separately before those services.
    admission=[]
    for mode,count in itertools.product((0,1,2,6,22,26,33),(0,1,2)):
        u.mem_write(RESOURCE,bytes(0x40));u.mem_write(SETTINGS,bytes(24))
        before=bytes(u.mem_read(RESOURCE,0x40))
        got=n.run(0xa06e5e,(0xa3b61c,),[
            (UC_ARM_REG_R0,mode),(UC_ARM_REG_R1,count),(UC_ARM_REG_R2,0),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['args']==[4,0x6003,mode,count]
        assert bytes(u.mem_read(RESOURCE,0x40))==before
        got=n.run(0xa06e7c,(0x4ded8c,))
        assert got['args'][0]==14 and bytes(u.mem_read(RESOURCE,0x40))==before
        # Independent input at the AFTER-critical-section boundary. Only
        # callee-saved native context is retained; no return value is supplied.
        got=n.run(0xa06e9e,(0xa06b80,0x9da5e2,0xa3c57a,0xa0697e,0x4e1cc4,0xa13b3a))
        early=mode in (6,22) and count==0
        assert got['address']==BASE+(0xa0697e if early else 0xa06b80)
        assert get(RESOURCE+0x2c)==1
        if early:assert get(RESOURCE)==1
        else:
            assert get(RESOURCE)==1 and get(RESOURCE+4)==0
            assert bytes(u.mem_read(RESOURCE+8,24))==bytes(24)
        admission.append(dict(mode_raw=mode,count_raw=count,
            first_postcritical_boundary_file=hex(got['address']-BASE),
            critical_section_executed=False,pixel_resource_acquired=False))

    # Existing raw states select stop or a separate transition check before
    # query/start. Their descriptor is not replaced with blank storage here.
    held=[]
    for state in (1,2,3):
        u.mem_write(RESOURCE,words(1,state,0x12345678,5,0x99,7,8)+bytes(36))
        before=bytes(u.mem_read(RESOURCE,0x40))
        got=n.run(0xa06e9e,(0xa06b80,0xa13b3a,0xa0697e,0xa3c57a,0x9da5e2,0x371708),[
            (UC_ARM_REG_R4,2),(UC_ARM_REG_R5,0),(UC_ARM_REG_R6,1),
            (UC_ARM_REG_R10,RESOURCE),(UC_ARM_REG_SP,STACK+0x8000)])
        # Only raw state1 selects this immediate stop; other states need
        # later original checks, never a fake successful stop or resource free.
        assert got['address']==BASE+(0xa06b80 if state==1 else 0x371708)
        assert bytes(u.mem_read(RESOURCE+4,0x28))==before[4:0x2c]
        held.append(dict(state_raw=state,boundary_file=hex(got['address']-BASE),
            old_resource_descriptor_preserved=True,stop_or_transition_executed=False))

    waits=[]
    for routine,first,after,target in ((0xa06b80,0x4e1cc4,0xa06b8e,0x37051c),
            (0xa06bbe,0x9da5e2,0xa06bd6,0x4e1cc4)):
        got=n.run(routine,(first,),[(UC_ARM_REG_R0,5),(UC_ARM_REG_R1,2),
            (UC_ARM_REG_R2,1),(UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+first
        got=n.run(after,(target,))
        assert got['address']==BASE+target
        waits.append(dict(entry_file=hex(routine),first_boundary_file=hex(first),
            explicit_after_service_boundary_file=hex(target),service_success_supplied=False))

    # Capacity query wrapper and real client, up to the first native endpoint
    # lookup. Output pointer is pre-existing synthetic caller storage.
    query=[]
    for kind in (0,1,2,5,255):
        out=OWNER+0x4000;u.mem_write(out,b'\xa5'*16)
        got=n.run(0xa13b3a,(0xa3b61c,),[(UC_ARM_REG_R0,kind),
            (UC_ARM_REG_R1,out),(UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['args']==[4,0x26,kind,0]
        got=n.run(0xa13b4e,(0x45dd24,))
        assert got['args'][0]==0x2a and bytes(u.mem_read(out,16))==b'\xa5'*16
        assert got['args'][1]==5 and get(got['args'][2]-4)==2
        query.append(dict(kind_raw=kind,lookup_boundary_file='0x45dd24',
            caller_output_unchanged=True,resource_query_executed=False))

    # Explicit AFTER-allocation packet builder. No allocator, send/receive,
    # endpoint discovery or response ownership is made successful.
    packet=OWNER+0x5000;reply=OWNER+0x6000
    for kind in (0,1,5,255):
        u.mem_write(packet,b'\xa5'*0x40)
        frame=STACK+0x8000
        put(frame+0x14,packet);put(frame+0xc,0x61003c)
        got=n.run(0x40a690,(0x45cb38,),[(UC_ARM_REG_R4,kind),(UC_ARM_REG_SP,frame)])
        expected=bytearray(b'\xa5'*0x40)
        struct.pack_into('<H',expected,0,0x14);expected[2]=kind
        struct.pack_into('<2H',expected,0x14,0x55,0)
        assert bytes(u.mem_read(packet,0x40))==expected
        assert got['args'][0]==0x61003c
    replies=[]
    for header,status,operation,value in itertools.product((0x8014,0x8013),(0,-1),(0x55,0x54),(0,7,65535)):
        raw=bytearray(32);struct.pack_into('<Hh',raw,0,header,status)
        struct.pack_into('<H',raw,6,operation);struct.pack_into('<H',raw,12,value)
        u.mem_write(reply,bytes(raw));out=OWNER+0x4000;u.mem_write(out,b'\xa5'*16)
        frame=STACK+0x8000;put(frame+8,reply)
        got=n.run(0x40a722,(0xa3c57a,0x5301ba),[(UC_ARM_REG_SP,frame),
            (UC_ARM_REG_R9,out),(UC_ARM_REG_R10,packet)])
        accepted=header==0x8014 and status==0 and operation==0x55
        assert got['address']==BASE+(0x5301ba if accepted else 0xa3c57a)
        assert bytes(u.mem_read(out,16))==(struct.pack('<H',value)+b'\xa5'*14 if accepted else b'\xa5'*16)
        replies.append(dict(header=hex(header),status=status,operation=operation,
            output_value=value,accepted=accepted,reply_is_synthetic=True,
            reply_or_message_release_executed=False))
    # Connect staged slot configuration -> original active-pool copy -> real
    # prefetch callback -> actual RAW service lookup. No service succeeds here.
    staged,current=0x17205d0,0x17202b0
    startup=[]
    for identifiers in ((0x505,),(0x505,0x500,0x170000),(0x50504,)):
        n.run(0xa07400,(0xa3b5dc,),[(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        n.call(0xa075c6,[])  # Original task constructor, no task creation.
        assert bytes(u.mem_read(0x1a3f3b0+0x14,8))==words(0x87,0x37)
        for i,identifier in enumerate(identifiers):
            n.call(0xa07492,[i,identifier])
        assert bytes(u.mem_read(staged+0x308,1))==bytes([len(identifiers)])
        staged_before=bytes(u.mem_read(staged,0x320))
        # Explicit post-a12866 entry, not a manufactured service success.
        got=n.run(0x370402,(0x407f1c,),[(UC_ARM_REG_R4,0),(UC_ARM_REG_R5,0),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['args'][0]==0x1a3f3b0
        assert bytes(u.mem_read(got['args'][1],20))==words(0x74ca7b,0,BASE+0xa074f0+1,0,0)
        active=bytes(u.mem_read(current,0x320))
        expected=bytearray(staged_before);struct.pack_into('<I',expected,0x318,0x4784e5)
        assert active==expected
        # Whole original callback prefix marks local active and starts at the
        # original cursor; its log is still a real boundary.
        got=n.run(0xa074f0,(0xa3b61c,),[(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert get(0x1a3f3d0)==1 and bytes(u.mem_read(current,1))==b'\1'
        got=n.run(0xa07542,(0xa3b61c,))
        assert got['args']==[4,0x13,identifiers[0],1]
        # Explicit post-log slice uses the real first identifier, then
        # reaches the actual service client and its endpoint lookup.
        got=n.run(0x37097e,(0x45dd24,))
        assert got['args'][0:2]==[0x2a,5]
        # Original client retains arguments in callee-saved registers.
        assert u.reg_read(UC_ARM_REG_R4)==identifiers[0]
        flag=0x31 if identifiers[0] in (0x50504,0x50505,0x5056e) else 0x11
        assert u.reg_read(UC_ARM_REG_R5)==flag
        assert get(current+0x10)==0xffffffff  # No RAW descriptor acquired.
        startup.append(dict(identifiers_raw=[hex(v) for v in identifiers],
            staged_to_active_copy_exact=True,prefetch_task_id_raw=0x87,
            prefetch_queue_raw=0x37,request_flags_raw=hex(flag),
            boundary_file='0x45dd24',OS_or_RAW_service_executed=False,
            descriptor_still_invalid=True))
    raw_replies=[]
    # Original RAW reply checks and actual d8-byte memcpy. Descriptor bytes
    # are caller-supplied test inputs, NOT acquired memory or a native reply.
    for header,status,operation,identifier,flags,count,address in itertools.product(
            (0x8020,0x8014),(0,6,65535),(0x55,0x54),(7,0xffffffff),
            (1,0x11,0x31),(0,1),(0,0x31000000)):
        raw=bytearray(range(0xd8))
        struct.pack_into('<2H',raw,0,header,status);struct.pack_into('<H',raw,6,operation)
        struct.pack_into('<H',raw,8,count);struct.pack_into('<I',raw,12,identifier)
        struct.pack_into('<I',raw,0x20,address)
        u.mem_write(reply,bytes(raw));out=OWNER+0x4000;u.mem_write(out,b'\xa5'*0x100)
        got=n.run(0x4089b4,(0xa3c57a,0x5301ba),[
            (UC_ARM_REG_R9,reply),(UC_ARM_REG_R8,out),(UC_ARM_REG_R5,flags),
            (UC_ARM_REG_R4,0x505),(UC_ARM_REG_R6,0),(UC_ARM_REG_SP,STACK+0x8000)])
        accepted=status==0 and header==0x8020 and operation==0x55 and identifier!=0xffffffff and (
            flags!=1 or (count!=0 and address!=0))
        if accepted:
            assert got['address']==BASE+0x5301ba and u.reg_read(UC_ARM_REG_R4)==0
            assert bytes(u.mem_read(out,0x100))==bytes(raw)+b'\xa5'*0x28
        else:
            assert bytes(u.mem_read(out,0x100))==b'\xa5'*0x100
            assert got['address']==BASE+(0x5301ba if status==6 else 0xa3c57a)
            if status==6:assert u.reg_read(UC_ARM_REG_R4)==0xfffffffc
        raw_replies.append(dict(header=hex(header),status=status,operation=operation,
            identifier_raw=hex(identifier),flags_raw=hex(flags),count=count,
            first_address_nonzero=bool(address),accepted_descriptor_copy=accepted,
            descriptor_is_synthetic=True,reply_release_executed=False))
    copies=[]
    for count in (0,1,2,3,65535):
        descriptor=OWNER+0x7000;data=bytearray(0xd8)
        struct.pack_into('<H',data,8,count);struct.pack_into('<I',data,12,7)
        for i in range(2):struct.pack_into('<3I',data,0x18+i*16,
            0x31000000+i*0x1000,0x32000000+i*0x1000,0x1000)
        u.mem_write(descriptor,bytes(data));u.mem_write(current,bytes(0x320))
        put(STACK+0x8000+0x24,7);u.mem_write(STACK+0x8000+0x20,struct.pack('<H',count))
        got=n.run(0x370af0,(0x370b60,),[(UC_ARM_REG_R6,current),
            (UC_ARM_REG_R8,current+8),(UC_ARM_REG_R10,descriptor),
            (UC_ARM_REG_SP,STACK+0x8000)])
        assert got['address']==BASE+0x370b60
        assert get(current+0x10)==7 and struct.unpack('<H',u.mem_read(current+0x14,2))[0]==count
        assert bytes(u.mem_read(current+0x18,min(count,2)*16))==bytes(data[0x18:0x18+min(count,2)*16])
        assert bytes(u.mem_read(current+8,1))==b'\1'
        copies.append(dict(reply_count_raw=count,native_copies_at_most_two_records=True,
            original_count_is_preserved=True,real_pixel_ownership_proven=False))
    takes=[]
    for slot,active,state,ready,matching in itertools.product(range(16),(0,1),
            (0,1,2,3),(0,1),(False,True)):
        u.mem_write(current,bytes(0x320));u.mem_write(current,bytes([active]))
        u.mem_write(current+0x308,bytes([16]));put(0x1a3f3d0,state)
        at=current+48*slot;identifier=0x505;put(at+0xc,identifier)
        u.mem_write(at+8,bytes([ready]));put(at+0x10,7)
        u.mem_write(at+0x14,struct.pack('<H',1))
        for i in range(2):u.mem_write(at+0x18+i*16,words(0x31000000+i*0x1000,0x32000000+i*0x1000,4096))
        before=bytes(u.mem_read(current,0x320));out=OWNER+0x4000;u.mem_write(out,b'\xa5'*64)
        got=n.run(0x37078c,(0xa3c57a,0x4ec144),[(UC_ARM_REG_R0,out),
            (UC_ARM_REG_R1,identifier if matching else identifier+1),(UC_ARM_REG_R2,slot),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        success=bool(active and state==2 and ready and matching)
        if success:
            assert got['address']==STOP
            assert bytes(u.mem_read(out,64))==before[slot*48+0x10:slot*48+0x38]+b'\xa5'*24
            expected=bytearray(before);expected[slot*48+8]=0
            struct.pack_into('<IIH',expected,slot*48+0xc,0,0xffffffff,0)
            assert bytes(u.mem_read(current,0x320))==bytes(expected)
            # Same identifier cannot be consumed again from the cleared slot.
            u.mem_write(out,b'\xa5'*64)
            again=n.run(0x37078c,(0xa3c57a,0x4ec144),[(UC_ARM_REG_R0,out),
                (UC_ARM_REG_R1,identifier),(UC_ARM_REG_R2,slot),
                (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
            assert again['address']==STOP and get(out)==0xffffffff
            assert bytes(u.mem_read(current,0x320))==bytes(expected)
        else:
            assert bytes(u.mem_read(current,0x320))==before
            assert bytes(u.mem_read(out+4,60))==b'\xa5'*60
            if got['address']==STOP:assert get(out)==0xffffffff
        takes.append(dict(slot=slot,active=active,native_state_raw=state,
            ready=ready,identifier_matches=matching,original_descriptor_transferred=success,
            boundary_file=hex(got['address']-BASE),
            acquired_physical_pixels=False))
    allocations=[]
    for active,ready,state,kind in itertools.product((0,1),(0,1),(0,1,2,3),(0x505,0x50504)):
        u.mem_write(current,bytes(0x320));u.mem_write(current,bytes([active]))
        u.mem_write(current+8,bytes([ready]));put(current+0xc,kind)
        put(current+0x10,7);u.mem_write(current+0x14,struct.pack('<H',1))
        u.mem_write(current+0x308,b'\1');put(0x1a3f3d0,state)
        u.mem_write(current+0x18,words(0x31000000,0x32000000,4096))
        before=bytes(u.mem_read(current,0x320));out=OWNER+0x4000;u.mem_write(out,b'\xa5'*64)
        # Whole native entry stops at its first actual logger.
        got=n.run(0x37019c,(0xa3b61c,),[(UC_ARM_REG_R0,out),(UC_ARM_REG_R1,kind),
            (UC_ARM_REG_R2,0),(UC_ARM_REG_R3,0),(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert got['args'][0:2]==[4,0x6009]
        # Explicit post-log slice can really consume the existing synthetic
        # descriptor; every wait, follow-up service and allocation is a stop.
        got=n.run(0x3701ba,(0xa0708e,0xa3c57a,0x4ec144,0x40aa00,0x4ded8c,0x3a1940))
        transferred=bool(active and ready and state==2)
        if transferred:
            assert get(out)==7
            assert get(current+0x10)==0xffffffff and get(current+0xc)==0
            assert got['address']==BASE+(0x40aa00 if kind==0x50504 else 0x4ded8c)
        else:
            assert bytes(u.mem_read(current,0x320))==before
            if got['address']==BASE+0xa0708e:assert get(out)==0xffffffff
        allocations.append(dict(active=active,ready=ready,state_raw=state,
            kind_raw=hex(kind),existing_descriptor_transferred=transferred,
            next_native_boundary_file=hex(got['address']-BASE),
            completed_allocation_or_pixel_ownership=False))
    frame=OWNER+0x8000;frame_cases=[]
    u.mem_write(frame,b'\xa5'*0x6800);put(frame+0x5ad8,7)
    before=bytes(u.mem_read(frame,0x6800))
    got=n.call(0xa04f28,[frame])
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==7
    assert bytes(u.mem_read(frame,0x6800))==before
    frame_cases.append(dict(kind='existing-frame-ID-skips-allocation',unchanged=True))
    for ignored in (0xffffffff,0xfffffffb,0xdeadbeef):
        u.mem_write(frame,before)
        got=n.run(0xa04fe6,(0xa13a60,),[(UC_ARM_REG_R0,frame),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['args'][0:2]==[7,2] and bytes(u.mem_read(frame,0x6800))==before
        # Independent post-release slice. Its input R0 is immediately
        # overwritten by original MOV -1: no release success is supplied.
        got=n.run(0xa04ffe,(0x36fdf8,),[(UC_ARM_REG_R0,ignored)])
        expected=bytearray(before);struct.pack_into('<I',expected,0x5ad8,0xffffffff)
        expected[0x5ea8:0x5ebc]=bytes(20)
        assert bytes(u.mem_read(frame,0x6800))==bytes(expected)
        assert got['args'][0:2]==[2,0]
        frame_cases.append(dict(kind='original-post-release-clears-without-testing-return',
            ignored_input_raw=hex(ignored),native_release_executed=False,
            local_ID_invalidated=True,pixel_release_proven=False))
    put(frame+0x5ad8,0xffffffff);before=bytes(u.mem_read(frame,0x6800))
    got=n.run(0xa04fe6,(0x36fdf8,),[(UC_ARM_REG_R0,frame),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['args'][0]==2 and bytes(u.mem_read(frame,0x6800))==before
    frame_cases.append(dict(kind='invalid-ID-does-not-call-release',unchanged=True))
    release=[]
    for header,status,operation,transport in itertools.product((0x8023,0x8020),
            (0,1,-1),(0x55,0x54),(0,0xffffffff)):
        raw=bytearray(32);struct.pack_into('<Hh',raw,0,header,status)
        struct.pack_into('<H',raw,6,operation);u.mem_write(reply,bytes(raw))
        got=n.run(0x4090ec,(0xa3c57a,0x5301ba),[(UC_ARM_REG_R6,reply),
            (UC_ARM_REG_R9,transport),(UC_ARM_REG_R4,7),(UC_ARM_REG_R5,2),
            (UC_ARM_REG_SP,STACK+0x8000)])
        accepted=transport==0 and header==0x8023 and status==0 and operation==0x55
        assert got['address']==BASE+(0x5301ba if accepted else 0xa3c57a)
        if accepted:assert u.reg_read(UC_ARM_REG_R4)==0
        assert bytes(u.mem_read(reply,32))==bytes(raw)
        release.append(dict(reply_header=hex(header),status=status,operation=operation,
            transport_raw=hex(transport),native_release_reply_accepted=accepted,
            response_is_synthetic=True,hardware_release_executed=False))
    release_entry=n.run(0xa13a60,(0xa3b61c,),[(UC_ARM_REG_R0,7),
        (UC_ARM_REG_R1,2),(UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert release_entry['args']==[4,13,7,2]
    got=n.run(0xa13a78,(0x45dd24,))
    assert got['args'][0:2]==[0x2a,5]
    return dict(camera_io=False,retention_configuration=configuration,
        resource_admission=admission,existing_resource=held,wait_boundaries=waits,
        query_entry=query,query_packet_cases=4,query_reply_cases=replies,
        staged_to_actual_RAW_client=startup,
        actual_RAW_reply_admission=raw_replies,original_slot_descriptor_copies=copies,
        original_slot_take_cases=takes,
        original_frame_allocator_continuation=allocations,
        original_frame_handle_lifecycle=frame_cases,
        original_release_reply_cases=release,release_endpoint_lookup_executed=False,
        limits=['Every native mode, descriptor, endpoint and reply is an explicit synthetic fixture',
            'Separate post-service slices are not native lock/wait/allocation success',
            'The queried16-bit value is not an acquired RAW handle or available retained photos',
            'Prefetch flags11/31 can copy zero-count/zero-address reply metadata; copying is not ownership',
            'The original frame release caller clears metadata without checking release status; invalid ID is not a terminal pixel fence',
            'No hardware readout, pixel allocation, preview, RAW save or physical cancellation ran'])
