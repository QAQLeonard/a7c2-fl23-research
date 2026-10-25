"""Original existing-free-block backing allocator, on synthetic RAM only.

Executes the unmodified allocator and unlink/reference helpers, not a newly
invented pool implementation. Free nodes and addresses are explicit fixtures.
Growing a pool, native notification and hardware services remain boundaries.
No camera, acquired physical pixels or installable patch is produced.
"""
import hashlib
import itertools
import struct

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR)
from .capture_native import NativeCapture, BASE, OWNER, STACK, STOP, words

HEAD, RECORDS = OWNER+0x10000, OWNER+0x20000
NODE, NODE2, OUT = OWNER+0x4000, OWNER+0x4100, OWNER+0x4200
CONTROL, RING, POLICY, TEMPLATE, SELECTOR, CATEGORIES = [OWNER+n for n in
    (0x6000,0x6100,0x6200,0x6300,0x6400,0x6410)]
SPANS=((0xb144d6,0x56),(0xb14554,0x704),
    (0xb15adc,0x24),(0xb15b1c,0x18),(0xb1529a,0x66),
    (0xb14ed6,0x236),(0xb16bd6,0x138),(0xb1671a,0x5e),
    (0xb14c58,0x27e),(0xb15ad0,12),(0xb15b02,0x1a))
SPANS += ((0x4088c8,0x80),(0xb12dba,0x1da),(0x495620,0xc0),
    (0x4089b4,0xb2),(0xb13236,0x5c),(0x409104,0x48),
    (0xb1645a,0x22a))
SPANS += ((0xb143fe,0xa0),(0xb15526,0xce),(0x516cf0,0x110))


class Fixture:
    def __init__(self,cp):
        self.n=NativeCapture(cp);self.u=u=self.n.u
        for at,size in ((0x1a8b000,8192),(0x174e000,8192),(HEAD,0x30000),
                (0x257b000,4096)):
            u.mem_map(at,size)
        u.mem_map(0x1b1e000,4096);u.mem_map(0x1b20000,4096)
        u.mem_map(0x31000000,0x3000)
        self.pixels=bytes((i*17+3)&255 for i in range(0x3000))
        u.mem_write(0x31000000,self.pixels)
        self.reset()

    def put(self,at,value):self.u.mem_write(at,words(value))
    def get(self,at):return struct.unpack('<I',self.u.mem_read(at,4))[0]
    def half(self,at,value):self.u.mem_write(at,struct.pack('<H',value))
    def call(self,at,values=(),stops=(0xb1474c,0xb155f4,0xb1746c)):
        return self.n.run(at,stops,[*zip((UC_ARM_REG_R0,UC_ARM_REG_R1,
            UC_ARM_REG_R2,UC_ARM_REG_R3),values),(UC_ARM_REG_SP,STACK+0x8000),
            (UC_ARM_REG_LR,STOP|1)])

    def node(self,at,*,kind=0x500,flags=2,size=4096,owner=0,odd=0,parent=0):
        self.u.mem_write(at,bytes(80));self.u.mem_write(at+2,bytes([odd]))
        self.put(at+4,flags);self.put(at+8,0x31000000);self.put(at+12,0)
        self.put(at+0x14,size);self.put(at+0x24,kind);self.put(at+0x28,owner)
        self.put(at+0x20,parent)

    def reset(self):
        u=self.u
        u.mem_write(OWNER,bytes(0x10000));u.mem_write(HEAD,bytes(0x30000))
        u.mem_write(0x1a8b000,bytes(8192));u.mem_write(0x174e000,bytes(8192))
        self.put(0x1a8c0cc,HEAD);self.put(0x1a8c0d0,CONTROL+0x50)
        self.put(CONTROL+0x50,7)
        self.put(HEAD+0x500*8,NODE);self.put(HEAD+0x500*8+4,NODE)
        self.node(NODE)
        self.put(0x1a8c558,RECORDS)
        for address,offset in ((0x1a8c55c,0),(0x1a8c560,4),(0x1a8c564,8),
                (0x1a8c568,12),(0x1a8c56c,16)):
            self.put(address,RING if offset==12 else CONTROL+offset)
        u.mem_write(CONTROL,words(0,1,1,0,0));self.half(RING,3)
        self.put(0x1a8c570,POLICY);u.mem_write(POLICY,words(0x505,TEMPLATE,0xffffffff))
        u.mem_write(TEMPLATE,words(0x500,0xffffffff))
        self.put(0x1a8c0d4,SELECTOR);self.put(0x1a8c0d8,CATEGORIES)
        u.mem_write(OUT,b'\xa5'*64)


def configured_nodes(f):
    """Original config-row -> free-node construction; synthetic rows only.

    Runs the real node allocator and insertion, never supplies their successful
    returns. Entry is explicitly AFTER omitted configuration parsing; neither
    that parser nor a real physical memory owner is claimed.
    """
    u=f.u;rows=[]
    descriptor,table,available,indices=OWNER+0x9600,OWNER+0x9700,OWNER+0xa000,OWNER+0xb800
    for domain,offset,size in ((0,0,0),(4,0x100000,0x800000),
            (5,0x200000,0x100000),(0xffff,0xfffffff0,0xffffffff)):
        f.reset();u.mem_write(NODE,b'\xa5'*80);f.half(NODE,1)
        u.mem_write(descriptor,bytes(40));f.put(table,descriptor)
        f.put(descriptor,offset);f.half(descriptor+6,domain)
        f.put(descriptor+8,0x500);f.put(descriptor+12,size)
        f.put(descriptor+16,2);f.put(descriptor+28,0xffffffff)
        # One owned synthetic node in the original allocator's free-node table.
        for address,value in ((0x1a8c0b8,CONTROL+0x80),(0x1a8c0b0,CONTROL+0x84),
                (0x1a8c0bc,available),(0x1a8c0c0,indices),
                (0x1a8c0c4,CONTROL+0x88),(0x1a8c0c8,CONTROL+0x8c)):
            f.put(address,value)
        f.put(CONTROL+0x80,1);f.put(CONTROL+0x84,0)
        f.put(CONTROL+0x88,0);f.put(CONTROL+0x8c,0)
        f.put(available,NODE);f.put(indices,0x11223344)
        f.put(HEAD+0x500*8,0);f.put(HEAD+0x500*8+4,0)
        got=f.n.run(0xb143fe,(0xb1449e,),[(UC_ARM_REG_R0,table),
            (UC_ARM_REG_R5,0x1a8c0d0),(UC_ARM_REG_R11,0xffff),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+0xb1449e
        assert f.get(available)==0 and f.get(indices)==0xffffffff
        assert f.get(CONTROL+0x80)==0 and f.get(CONTROL+0x84)==1
        assert f.get(HEAD+0x500*8)==f.get(HEAD+0x500*8+4)==NODE
        assert f.get(CONTROL+0x88)==f.get(CONTROL+0x8c)==NODE
        assert [f.get(NODE+n) for n in (8,12,16,20,36)]==[0,domain,offset,size,0x500]
        assert f.get(NODE+0x28)==0 and f.get(NODE+0x2c)==0xffffffff
        assert f.get(NODE+0x3c)==8
        produced=None
        if size:
            # Compose the original constructor's node with the actual original
            # allocator and pin-to-descriptor path. Returned addresses remain
            # untrusted synthetic values and are deliberately not dereferenced.
            got=f.call(0xb1645a,[0x505,0x31,OUT])
            assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
            handle=f.get(OUT);assert handle==0x8403
            output,count=OWNER+0x9c00,OWNER+0x9d00
            got=f.call(0xb16a52,[handle,1,output,count])
            assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
            produced=list(struct.unpack('<3I',u.mem_read(output,12)))
            assert produced==[offset,domain,size]
        rows.append(dict(configured_address_high_word=domain,configured_offset=offset,
            configured_size=size,original_node_allocation_and_free_list_insertion=True,
            original_allocator_and_pin_descriptor=produced,
            memory_address_or_extent_validated=False,pixel_memory_accessed=False,
            configuration_and_node_storage_are_synthetic=True))
    return rows


def audit(cp):
    f=Fixture(cp);u=f.u;checks=[]
    for matching,flags,size,owner,odd in itertools.product((False,True),(0,2),
            (0,4096),(0,OWNER+0x8000),(0,1)):
        f.reset();f.node(NODE,kind=0x500 if matching else 0x501,
            flags=flags,size=size,owner=owner,odd=odd)
        before=bytes(u.mem_read(NODE,80));f.put(OUT,0)
        got=f.call(0xb14554,[0x500,2,0,OUT])
        accepted=matching and flags!=0 and size!=0 and owner==0 and odd==0
        if accepted:
            assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
            assert f.get(OUT)==NODE and f.get(CONTROL+0x50)==8
            expected=bytearray(before);struct.pack_into('<I',expected,0x3c,8)
            assert bytes(u.mem_read(NODE,80))==bytes(expected)
            assert f.get(HEAD+0x500*8)==NODE  # Selection precedes actual unlink.
        else:
            assert got['address']==BASE+0xb1474c
            assert bytes(u.mem_read(NODE,80))==before and f.get(CONTROL+0x50)==7
        checks.append(dict(type_matches=matching,flags=flags,size=size,
            owner_nonzero=bool(owner),odd_flag=odd,selected_existing_free_node=accepted,
            growing_allocator_executed=False))
    # Whole native allocation can associate an already-free backing node with
    # a new handle WITHOUT calling an invented allocator or success stub.
    f.reset();record=RECORDS+3*64
    got=f.call(0xb1645a,[0x505,0x31,OUT])
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
    handle=f.get(OUT);assert handle==0x8403
    assert f.get(NODE+0x28)==record and f.get(NODE+0x2c)==f.get(record+4)==1
    assert f.get(record+16)==NODE
    assert f.get(HEAD+0x500*8)==0 and f.get(HEAD+0x500*8+4)==0
    assert bytes(u.mem_read(record+14,2))==b'\1\0'
    descriptor,number=OWNER+0x7000,OWNER+0x7100
    got=f.call(0xb16a52,[handle,1,descriptor,number])
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
    assert bytes(u.mem_read(descriptor,12))==words(0x31000000,0,4096)
    assert bytes(u.mem_read(number,2))==b'\1\0'
    assert bytes(u.mem_read(record+9,1))==b'\1'
    got=f.call(0xb16b4c,[handle]);assert got['address']==STOP
    assert bytes(u.mem_read(record+9,1))==b'\0'
    # Final release executes actual owner clear/free-list relink. The original
    # state notifier is a boundary; success is not supplied for it.
    got=f.call(0xb16bd6,[handle],stops=(0xb1746c,0xb155f4))
    assert got['address']==BASE+0xb1746c and got['args'][0]==0x23
    assert f.get(NODE+0x28)==0
    assert f.get(HEAD+0x500*8)==NODE and f.get(HEAD+0x500*8+4)==NODE
    assert f.get(CONTROL)==1 and f.get(CONTROL+4)==2 and f.get(CONTROL+8)==1
    assert bytes(u.mem_read(RING+2,2))==b'\3\0'
    # Native slot reuse after that local relink is independently entered; no
    # successful notification or physical terminal fence is implied. The old
    # handle must fail against the new generation even for the same node.
    u.mem_write(OUT,b'\xa5'*64)
    got=f.call(0xb1645a,[0x505,0x31,OUT])
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
    newer=f.get(OUT);assert newer==0x8803
    got=f.call(0xb16a52,[handle,1,descriptor,number])
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0xfffffdfb
    got=f.call(0xb16a52,[newer,1,descriptor,number])
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
    got=f.call(0xb16b4c,[newer]);assert got['address']==STOP
    # Test all positions of a real three-node original doubly linked free
    # list. Matching selects/unlinks only one; its neighbors stay connected.
    list_cases=[]
    for chosen in range(3):
        f.reset();nodes=(NODE,NODE2,NODE2+0x100)
        f.put(HEAD+0x500*8,nodes[0]);f.put(HEAD+0x500*8+4,nodes[-1])
        for i,at in enumerate(nodes):
            f.node(at,flags=2 if i==chosen else 0)
            f.put(at+0x40,nodes[i-1] if i else 0)
            f.put(at+0x44,nodes[i+1] if i<2 else 0)
        got=f.call(0xb144d6,[0x500,2,0,OUT])
        assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
        assert f.get(OUT)==nodes[chosen]
        remaining=[v for i,v in enumerate(nodes) if i!=chosen]
        assert f.get(HEAD+0x500*8)==remaining[0] and f.get(HEAD+0x500*8+4)==remaining[-1]
        assert f.get(nodes[chosen]+0x40)==f.get(nodes[chosen]+0x44)==0
        for i,at in enumerate(remaining):
            assert f.get(at+0x40)==(remaining[i-1] if i else 0)
            assert f.get(at+0x44)==(remaining[i+1] if i<len(remaining)-1 else 0)
        list_cases.append(dict(chosen_position=chosen,original_unlink=True,
            remaining_neighbors_preserved=True,synthetic_nodes_only=True))
    address_cases=[]
    for low,high,offset,size in ((0,0,0,4096),(0x31000000,0,0,4096),
            (0xf1380000,0,0,4096),(0xfffffff0,0xffffffff,64,4096),
            (0x31000000,0,0,0xffffffff)):
        f.reset();f.put(NODE+8,low);f.put(NODE+12,high)
        f.put(NODE+16,offset);f.put(NODE+20,size)
        f.put(OUT,0)
        got=f.call(0xb14554,[0x500,2,0,OUT])
        assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0 and f.get(OUT)==NODE
        address_cases.append(dict(base_low=hex(low),base_high=hex(high),offset=offset,
            size=size,selected_from_trusted_pool_assumption=True,
            advertised_address_not_dereferenced=True,physical_bounds_proven=False))
    binds=[]
    for record_sequence,node_sequence in itertools.product((1,2,0xffffffff),repeat=2):
        f.reset();record=RECORDS+3*64;f.put(record+4,record_sequence)
        f.put(NODE+0x2c,node_sequence)
        before=bytes(u.mem_read(NODE,80))
        got=f.call(0xb14cda,[record,NODE])
        assert got['address']==STOP
        accepted=record_sequence==node_sequence and record_sequence!=0xffffffff
        assert u.reg_read(UC_ARM_REG_R0)==(0 if accepted else 0xffffffff)
        if accepted:
            assert f.get(NODE+0x28)==record and f.get(HEAD+0x500*8)==0
        else:
            assert bytes(u.mem_read(NODE,80))==before and f.get(HEAD+0x500*8)==NODE
        binds.append(dict(record_sequence_raw=hex(record_sequence),
            node_sequence_raw=hex(node_sequence),bound_by_original=accepted,
            actual_lifetime_proven=False))
    shared=[]
    parent,provider,limits=OWNER+0x8000,OWNER+0x8100,OWNER+0x8200
    for category,grant,in_use in itertools.product((0,3,63,64),(0,4,5),(0,4,6)):
        f.reset();f.node(NODE,parent=parent);f.half(parent+0x30,0)
        f.put(0x1a8c308,provider);f.put(0x1a8c0dc,limits)
        f.half(0x257b180,0);u.mem_write(provider+16+category,bytes([grant]));f.half(limits,in_use)
        before=bytes(u.mem_read(NODE,80))
        got=f.call(0xb14554,[0x500,2,category,OUT])
        accepted=category<=63 and grant>0 and grant>=in_use
        assert (got['address']==STOP)==accepted
        if accepted:
            assert u.reg_read(UC_ARM_REG_R0)==0 and f.get(OUT)==NODE
        else:
            assert got['address']==BASE+(0xb155f4 if category>63 else 0xb1474c)
            assert bytes(u.mem_read(NODE,80))==before
        shared.append(dict(category=category,configured_grant=grant,in_use=in_use,
            original_parent_backed_cached_node_admitted=accepted,
            provider_data_is_synthetic=True,growing_or_freeing_parent_executed=False))
    # Actual client packet stores -> original worker20 -> allocator/pin ->
    # original client reply acceptance. Queue delivery and accounting are
    # explicitly separate boundaries, never successful native stubs.
    f.reset();packet,request,reply,client_out=OWNER+0x9000,OWNER+0x9100,OWNER+0x9200,OWNER+0x9400
    stack=STACK+0x8000
    f.put(stack+0x20,packet);f.put(stack+0x10,packet)
    f.put(stack+0x18,0x61003c)
    u.mem_write(packet,bytes(0xd8))
    got=f.n.run(0x4088c8,(0xae401c,),[(UC_ARM_REG_R0,0),
        (UC_ARM_REG_R4,0x505),(UC_ARM_REG_R5,0x31),(UC_ARM_REG_R6,0),
        (UC_ARM_REG_SP,stack)])
    assert got['args'][:2]==[0x61003c,packet]
    raw=bytes(u.mem_read(packet,0xd8))
    u.mem_write(request,bytes(0x48));u.mem_write(request+12,raw[:40])
    u.mem_write(reply,bytes(0xd8))
    got=f.call(0xb12dba,[request,reply,reply+24],stops=(0xb15bc2,0xb1746c))
    assert got['address']==BASE+0xb15bc2
    handle=f.get(reply+12);assert handle==0x8403
    assert f.get(NODE+0x28)==RECORDS+3*64
    assert bytes(u.mem_read(RECORDS+3*64+9,1))==b'\1'
    # AFTER-resource-accounting input: R0 is overwritten; no accounting
    # success is fabricated. Exact native status remains callee-saved in R6.
    got=f.n.run(0xb12f6a,())
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==2
    assert bytes(u.mem_read(reply,2))==b'\x20\x80'
    assert bytes(u.mem_read(reply+2,2))==bytes(2)
    assert bytes(u.mem_read(reply+6,2))==b'\x55\0'
    assert bytes(u.mem_read(reply+8,2))==b'\1\0'
    assert bytes(u.mem_read(reply+24,12))==words(0x31000000,0,4096)
    u.mem_write(client_out,b'\xa5'*0x100)
    got=f.n.run(0x4089b4,(0x5301ba,),[(UC_ARM_REG_R9,reply),
        (UC_ARM_REG_R8,client_out),(UC_ARM_REG_R5,0x31),(UC_ARM_REG_R4,0x505),
        (UC_ARM_REG_R6,0),(UC_ARM_REG_SP,stack)])
    assert got['address']==BASE+0x5301ba and u.reg_read(UC_ARM_REG_R4)==0
    assert bytes(u.mem_read(client_out,0xd8))==bytes(u.mem_read(reply,0xd8))
    # Matching provider23 uses the actual handle from provider20, unpins,
    # releases and restores the synthetic free list. Stop before notifier.
    u.mem_write(request,bytes(0x48));f.half(request+12,0x23)
    f.put(request+20,handle);f.half(request+32,0x55);f.half(request+34,2)
    u.mem_write(reply,bytes(0xd8))
    got=f.call(0xb13236,[request,reply,reply+24],stops=(0xb1746c,0xb15bc2))
    assert got['address']==BASE+0xb1746c and got['args'][0]==0x23
    assert f.get(NODE+0x28)==0 and f.get(HEAD+0x500*8)==NODE
    assert bytes(u.mem_read(RECORDS+3*64+12,2))==bytes(2)
    # AFTER-notifier slice retains its original R5/R8 bookkeeping results.
    # It does not provide a successful notifier return in R0.
    got=f.n.run(0xb16d08,(0xb15bc2,))
    assert got['address']==BASE+0xb15bc2
    got=f.n.run(0xb13280,())
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==2
    assert bytes(u.mem_read(reply,2))==b'\x23\x80'
    assert bytes(u.mem_read(reply+2,2))==bytes(2)
    assert bytes(u.mem_read(reply+6,2))==b'\x55\0' and f.get(reply+12)==handle
    got=f.n.run(0x409104,(0x5301ba,),[(UC_ARM_REG_R6,reply),
        (UC_ARM_REG_R4,handle),(UC_ARM_REG_SP,stack)])
    assert got['address']==BASE+0x5301ba and u.reg_read(UC_ARM_REG_R4)==0
    # Caller output must not be published merely from a metadata reservation.
    f.reset();f.node(NODE,owner=OWNER+0x8000)
    got=f.call(0xb1645a,[0x505,0x31,OUT])
    assert got['address']==BASE+0xb1474c
    assert bytes(u.mem_read(OUT,64))==b'\xa5'*64
    assert f.get(CONTROL)==1 and f.get(CONTROL+8)==0
    assert bytes(u.mem_read(RECORDS+3*64+12,2))==b'\1\0'
    assert bytes(u.mem_read(0x31000000,0x3000))==f.pixels
    return dict(camera_io=False,existing_free_node_cases=checks,
        original_whole_metadata_and_backing_allocation_executed=True,
        original_unlink_bind_pin_unpin_relink_executed=True,
        terminal_notifier_executed=False,unresolved_backing_path_keeps_unpublished_handle=True,
        metadata_reservation_already_consumed_on_unresolved_backing_path=True,
        original_reallocation_rejects_stale_handle=True,linked_free_list_cases=list_cases,
        original_free_pool_trust_cases=address_cases,
        original_owner_sequence_binding_cases=binds,
        parent_backed_cached_selection_cases=shared,
        original_configuration_to_backing_node_cases=configured_nodes(f),
        original_client_worker_allocator_reply_path=True,
        original_provider23_release_and_client_reply_path=True,
        queue_delivery_and_resource_accounting_executed=False,
        synthetic_pixel_region_preserved_sha256=hashlib.sha256(f.pixels).hexdigest(),
        limits=['The initial free list and address31000000 are synthetic, not camera resources',
            'Only existing-free-node allocation is covered; growing and final parent-backed release remain boundaries',
            'No original lock/task admission, image exposure or camera pixel contents are supplied',
            'The allocator trusts free-pool node addresses/sizes; synthetic acceptance is not physical address admission',
            'Free-list relink before notification is not a physical terminal lease fence'])
