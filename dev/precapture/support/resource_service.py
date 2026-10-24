"""Original RAW resource-service dispatch/handle checks; strictly offline.

Separates dynamic reply-queue allocation from target service61003c. The two
original worker/direct dispatch tables have different semantics. No queue,
lock, backing memory, native allocation or hardware reply is supplied.
"""
import itertools
import struct

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
    UC_ARM_REG_SP, UC_ARM_REG_LR)
from .capture_native import NativeCapture, BASE, OWNER, STACK, STOP, words
from .reference import SPECS

SPANS=((0x495da4,0x24),(0xb17ed8,4),(0xb139f0,0x40),
    (0xb1614a,0x28),(0xb13cbc,0x3c),(0xb13eba,0x16),
    (0xd9e404,0x170),(0xb13890,0x1c),(0xb12d0c,0x2c),
    (0xb1510c,0x88),(0xb15402,0x26),(0xb15bac,0x16),(0x495620,0xc0),
    (0xb1645a,0x11a),(0xb16686,0x58),(0xb17460,12),(0xb16a52,0xee),
    (0xb16b4c,0x8a),(0xb16bd6,0x10a),
    (0x5301e8,0x18),(0x45dd24,0xda),(0x45e000,0x10),
    (0x530176,0x44),(0x40ab24,0x16))


def audit(cp):
    n=NativeCapture(cp);u=n.u
    for at,size in ((0x1a8b000,8192),(0x1b20000,4096),(0x23a5000,4096)):
        u.mem_map(at,size)
    get=lambda at:struct.unpack('<I',u.mem_read(at,4))[0]
    put=lambda at,v:u.mem_write(at,words(v))
    half=lambda at:struct.unpack('<H',u.mem_read(at,2))[0]
    puth=lambda at,v:u.mem_write(at,struct.pack('<H',v))
    request,reply=OWNER,OWNER+0x1000
    # Execute original reply-ID allocation entry up to the native mutex.
    # A distinct final-store slice demonstrates this call writes a new ID,
    # rather than resolving61003c or discovering a resource-service endpoint.
    out=OWNER+0x5000;u.mem_write(out,b'\xa5'*16)
    got=n.run(0x45dd24,(0xae37dc,),[(UC_ARM_REG_R0,0x2a),
        (UC_ARM_REG_R1,5),(UC_ARM_REG_R2,out),(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['args'][0]==0x10d9580
    assert u.reg_read(UC_ARM_REG_R10)==5 and bytes(u.mem_read(out,16))==b'\xa5'*16
    pool=0x10d9580
    # Synthetic queue-pool header, not a camera mutation or a successful lock.
    put(pool+0xc,32)
    got=n.run(0x45ddca,(0x45ddfe,),[(UC_ARM_REG_R8,pool),
        (UC_ARM_REG_R9,0),(UC_ARM_REG_R6,0x2a),(UC_ARM_REG_R10,5),
        (UC_ARM_REG_SP,STACK+0x8000)])
    assert got['address']==BASE+0x45ddfe
    assert get(STACK+0x8018)==0x50000
    put(STACK+0x8020,out)
    got=n.run(0x45e000,(0x45e00c,),[(UC_ARM_REG_R4,3),(UC_ARM_REG_R6,0x2a),
        (UC_ARM_REG_SP,STACK+0x8000)])
    assert get(out)==0x50003 and bytes(u.mem_read(out+4,12))==b'\xa5'*12
    # Destructor uses a different flag combination and never calls resource
    # target61003c. It still stops before invoking the original allocator/free.
    obj=OWNER+0x6000;u.mem_write(obj,words(0x50003,1))
    got=n.run(0x5301e8,(0x45dd24,),[(UC_ARM_REG_R0,obj),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['args'][:2]==[0x5004b,0]
    # Original service registration provides exact target/callback identity.
    got=n.run(0x495da4,(0x45c8f8,),[(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['args']==[0x61003c,0x1a8c554,BASE+0xb1620a+1,0]
    # Original task descriptor and entry establish the asynchronous receiver.
    spec=SPECS['a7c2-2.01'];names,count=spec['task_names'],spec['task_count']
    table=names-count*4-4-count*40
    assert struct.unpack_from('<I',cp,names-count*4-4)[0]==count
    row=struct.unpack_from('<10I',cp,table+255*40)
    name_at=struct.unpack_from('<I',cp,names+255*4)[0]-BASE
    assert cp[name_at:cp.index(0,name_at)]==b'MEMMGR_CP'
    assert row[2]==BASE+0xb17ed8+1
    got=n.run(0xb17ed8,(0x45d3a8,),[(UC_ARM_REG_SP,STACK+0x8000),
        (UC_ARM_REG_LR,STOP|1)])
    assert got['args'][0]==0x61003c and got['args'][2]==0xffffffff

    dispatch=[]
    for command in (0x14,0x20,0x23):
        u.mem_write(request,bytes(0x48));puth(request+12,command)
        for direct in (False,True):
            at=(struct.unpack_from('<I',cp,(0xea64bc if direct else 0xea6404)-BASE+command*4)[0]&~1)-BASE
            if direct:
                got=n.run(0xb13eba,(at,),[(UC_ARM_REG_R0,command),
                    (UC_ARM_REG_R9,reply),(UC_ARM_REG_SP,STACK+0x8000)])
                assert got['args']==[STACK+0x80e8,reply,reply+24,at+BASE+1]
            else:
                got=n.run(0xb13cbc,(at,),[(UC_ARM_REG_R0,request),
                    (UC_ARM_REG_R1,reply),(UC_ARM_REG_SP,STACK+0x8000),
                    (UC_ARM_REG_LR,STOP|1)])
                assert got['args'][:3]==[request,reply,reply+24]
            dispatch.append(dict(command=hex(command),direct=direct,
                handler_file=hex(at),handler_executed=False))
    assert [r['handler_file'] for r in dispatch if r['command']=='0x14']==['0xb12d0c','0xb13890']
    # Direct command14 is deliberately unsupported. It cannot stand in for
    # the worker's category-selection/query path or prove a missing feature.
    u.mem_write(reply,b'\xa5'*64);puth(request+12,0x14);puth(request+32,0x55)
    n.call(0xb13890,[request,reply])
    assert half(reply)==0x8014 and half(reply+2)==0xfff9 and half(reply+6)==0x55

    # Worker14 changes a bounded category-selector stack, then returns a
    # configured category value. No selection is a pixel allocation/count.
    selector,selected=OWNER+0x2000,OWNER+0x2100
    put(0x1a8c0d4,selector);put(0x1a8c0d8,selected)
    categories=[]
    for depth,mode,category in itertools.product((0,1,7),(0,0x100,0x101,2),(0,5,63,64)):
        u.mem_write(selector,bytes(16));puth(selector,depth)
        u.mem_write(selected,b'\xa5'*32);before=bytearray(u.mem_read(selected,32))
        got=n.run(0xb1510c,(0xb1746c,),[(UC_ARM_REG_R0,category),
            (UC_ARM_REG_R1,mode),(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0xb1746c and got['args'][0]==0x14
        expected_depth=depth
        if mode==0 and category<64:struct.pack_into('<H',before,depth*2,category)
        if mode==0x100 and category<64 and depth<7:
            expected_depth+=1;struct.pack_into('<H',before,expected_depth*2,category)
        if mode==0x101 and depth>0:expected_depth-=1
        assert half(selector)==expected_depth
        assert bytes(u.mem_read(selected,32))==bytes(before)
        categories.append(dict(depth=depth,mode_raw=hex(mode),category=category,
            next_depth=expected_depth,notification_executed=False))
    for category in (0,5,63,64):
        puth(selector,0);puth(selected,category)
        u.mem_write(0x23a50f0,bytes(range(64)))
        got=n.call(0xb15402,[])
        assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==(category if category<64 else 0)
    worker_query=[]
    for category,value in ((0,3),(5,9),(63,255)):
        puth(selector,0);u.mem_write(selected,bytes(32))
        u.mem_write(0x23a50f0,bytes(64));u.mem_write(0x23a50f0+category,bytes([value]))
        u.mem_write(request,bytes(0x48));puth(request+12,0x14)
        u.mem_write(request+14,bytes([category]));puth(request+32,0x55)
        u.mem_write(reply,b'\xa5'*64)
        got=n.run(0xb12d0c,(0xb1746c,),[(UC_ARM_REG_R0,request),
            (UC_ARM_REG_R1,reply),(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0xb1746c and half(selected)==category
        # Explicit AFTER-notification slice, no fake successful notifier.
        # The original status is still held in its callee-saved R4.
        got=n.run(0xb15190,())
        assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==2
        assert half(reply)==0x8014 and half(reply+2)==0 and half(reply+6)==0x55
        assert half(reply+12)==value
        worker_query.append(dict(category=category,configured_value=value,
            original_worker_reply_checked=True,notification_executed=False))

    # The original native handle validates a10-bit slot and5-bit generation.
    # It is not sufficient as the controller's never-reused capture generation.
    pool=OWNER+0x10000
    u.mem_map(pool,0x10000)
    put(0x1a8c558,pool)
    handles=[]
    for stored_generation,handle_generation,state,pins,marked in itertools.product(
            (0,1,31),(0,1,31),(0,1,2,3,4,7),(0,1,2),(0,1)):
        slot=3;record=pool+slot*64
        data=bytearray(64);data[11]=stored_generation;data[9]=pins
        struct.pack_into('<H',data,12,state)
        u.mem_write(record,bytes(data));handle=slot|(handle_generation<<10)|(marked<<15)
        got=n.call(0xb16b4c,[handle]);assert got['address']==STOP
        expected=bytearray(data)
        if stored_generation!=handle_generation:want=0xfffffdfb
        elif state in (1,7) and (state==1 or pins==0):want=1
        elif state in (2,3,7) and pins:
            expected[9]-=1
            if expected[9]==0:struct.pack_into('<H',expected,12,1)
            want=0
        else:want=0xffffffff
        assert u.reg_read(UC_ARM_REG_R0)==want
        assert bytes(u.mem_read(record,64))==bytes(expected)
        handles.append(dict(stored_generation=stored_generation,handle_generation=handle_generation,
            state_raw=state,pins=pins,high_marker_bit=marked,result_raw=hex(want),
            native_only_five_generation_bits=True,backing_pixels_unqualified=True))
    got=n.call(0xb16b4c,[0x83ff]);assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0xfffffefb

    # Producer allocation resolves a resource-type list before a backing-memory
    # allocator. Missing/NULL original policy leaves the supplied output invalid.
    policies=OWNER+0x4000;out=OWNER+0x5000;put(0x1a8c570,policies)
    missing=[]
    for configured in (0x505,0x506):
        u.mem_write(policies,words(configured,0,0xffffffff));u.mem_write(out,b'\xa5'*16)
        got=n.call(0xb1645a,[0x505,0x11,out])
        assert got['address']==STOP and get(out)==0xffffffff
        assert u.reg_read(UC_ARM_REG_R0)==0xfffffffd
        assert bytes(u.mem_read(out+4,12))==b'\xa5'*12
        missing.append(dict(configured_type=hex(configured),native_output_invalid=True))
    # Exact original free-index ring and metadata record construction, with
    # synthetic type policy. Stop BEFORE allocating any backing pixel memory.
    controls=OWNER+0x6000;ring=OWNER+0x6100;template=OWNER+0x6200
    for address,offset in ((0x1a8c55c,0),(0x1a8c560,4),
            (0x1a8c564,8),(0x1a8c568,12),(0x1a8c56c,16)):
        put(address,ring if offset==12 else controls+offset)
    metadata=[]
    for slot,old_generation in itertools.product((0,3,1022),(0,1,30,31)):
        u.mem_write(controls,words(0,1,1,0,0))
        puth(ring,slot);record=pool+slot*64
        u.mem_write(record,bytes(64));u.mem_write(record+11,bytes([old_generation]))
        u.mem_write(policies,words(0x505,template,0xffffffff))
        u.mem_write(template,words(0x500,0xffffffff));u.mem_write(out,b'\xa5'*16)
        got=n.run(0xb1645a,(0xb144d6,),[(UC_ARM_REG_R0,0x505),
            (UC_ARM_REG_R1,0x11),(UC_ARM_REG_R2,out),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0xb144d6
        generation=old_generation+1 if old_generation<=30 else 1
        encoded=0x8000|(generation<<10)|slot
        assert get(controls)==1 and get(controls+8)==0
        assert get(record)==0x505 and get(record+4)==1
        assert half(record+8)==1 and bytes(u.mem_read(record+11,1))==bytes([generation])
        assert half(record+12)==1 and u.reg_read(UC_ARM_REG_R6)==encoded
        assert bytes(u.mem_read(out,16))==b'\xa5'*16
        metadata.append(dict(slot=slot,old_generation=old_generation,
            new_generation=generation,encoded_handle=hex(encoded),
            free_metadata_slot_consumed=True,caller_handle_not_published=True,
            backing_allocator_executed=False))
    u.mem_write(controls,words(0,0,0,0,0));u.mem_write(out,b'\xa5'*16)
    got=n.call(0xb1645a,[0x505,0x11,out])
    assert got['address']==STOP and get(out)==0xffffffff
    assert u.reg_read(UC_ARM_REG_R0)==0xffffceff
    references=[]
    record=pool+3*64;node=OWNER+0x7000;descriptors=OWNER+0x8000;count_out=OWNER+0x8100
    handle=0x8403
    for state,mode,pins,count in itertools.product((1,2,3),(0,1,0x1001),(0,254,255),(0,1,2)):
        u.mem_write(record,bytes(64));u.mem_write(record+11,b'\1');u.mem_write(record+9,bytes([pins]))
        puth(record+12,state);puth(record+14,count)
        for index in range(2):
            pointer=node+index*64;put(record+16+index*4,pointer)
            u.mem_write(pointer,bytes(64));put(pointer+8,0xfffffff0+index)
            put(pointer+12,1);put(pointer+16,32);put(pointer+20,4096)
        u.mem_write(descriptors,b'\xa5'*48);u.mem_write(count_out,b'\xa5'*4)
        before=bytearray(u.mem_read(record,64))
        got=n.call(0xb16a52,[handle,mode,descriptors,count_out])
        assert got['address']==STOP
        accepted=mode==0x1001 or (state in (1,2) and pins<255)
        if accepted:
            assert u.reg_read(UC_ARM_REG_R0)==0 and half(count_out)==count
            for index in range(count):
                assert bytes(u.mem_read(descriptors+index*16,12))==words(0x10+index,2,4096)
            if mode!=0x1001:
                before[9]+=1;struct.pack_into('<H',before,12,2)
        else:
            assert u.reg_read(UC_ARM_REG_R0)==(0xffffccff if state==3 else 0xffffffff)
            assert half(count_out)==0 and bytes(u.mem_read(descriptors,48))==b'\xa5'*48
        assert bytes(u.mem_read(record,64))==bytes(before)
        references.append(dict(state_raw=state,mode_raw=hex(mode),pins_before=pins,
            descriptor_count=count,accepted=accepted,pin_incremented=accepted and mode!=0x1001,
            addresses_are_synthetic=True,physical_image_reference_proven=False))
    # Original pin/unpin then final-owner release: stop BEFORE backing free.
    u.mem_write(record,bytes(64));u.mem_write(record+8,b'\1\0\0\1')
    puth(record+12,1);puth(record+14,1);put(record+16,node)
    n.call(0xb16a52,[handle,1,descriptors,count_out])
    assert bytes(u.mem_read(record+9,1))==b'\1' and half(record+12)==2
    n.call(0xb16b4c,[handle])
    assert bytes(u.mem_read(record+9,1))==b'\0' and half(record+12)==1
    got=n.run(0xb16bd6,(0xb14ed6,),[(UC_ARM_REG_R0,handle),
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0xb14ed6 and got['args'][0]==node
    assert half(record+12)==0
    return dict(camera_io=False,service_route='0x61003c',service_callback_file='0xb1620a',
        dynamic_reply_ID=dict(allocation_flags='0x2a',type_raw=5,
            explicit_selected_slot=3,original_ID_store='0x50003',mutex_executed=False,
            destruction_flags_are_distinct=True),
        task=dict(id=256,name='MEMMGR_CP',entry_file='0xb139f0'),
        dispatch=dispatch,direct_query14_unsupported=True,category_selection_cases=categories,
        worker_query_reply_cases=worker_query,
        worker_query14_changes_selector_state=True,
        category_values_are_configured_bytes=True,handle_cases=handles,
        missing_policy_cases=missing,metadata_allocation_cases=metadata,
        exhausted_metadata_ring_refused=True,
        descriptor_reference_cases=references,original_pin_unpin_to_backing_free_boundary=True,
        local_record_zero_precedes_backing_free=True,
        limits=['Descriptor pools, categories, generation bytes and packets are synthetic',
            'Worker14 changes the category selector and notifies state; it is not a read-only capacity query',
            'Worker and direct tables are distinct; direct14 rejection is not worker14 capability evidence',
            'The original5-bit handle generation wraps; no capture-lifetime proof follows',
            'No queue registration, receive, lock, allocator or backing pixel memory is executed',
            'Camera pre-capture and service ownership/lifetime integration remain incomplete'])
