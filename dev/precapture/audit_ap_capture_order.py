"""Original AP start/data dispatch and pending-record admission, offline only.

Executes original instructions on synthetic bookkeeping. No service return,
capture request, RAW allocation, CP send or photo save is fabricated. The
start slice begins AFTER earlier native preparation; reaching it is unproven.
"""
import argparse
import hashlib
import io
import itertools
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R
from support.boundaries import BoundaryRunner

MEM, STACK, STOP = 0x30000000, 0x40000000, 0x50000000
SPECS = {
    'target': dict(sha='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
        dispatch=0x34ae244, table=0x4c5f418, base=0x34ae264,
        start_route=0x34ae264, data_route=0x34ae2a4,
        start=0x34a76d4, data=0x34a98f8, producer=0x34a7b0c,
        producer_end=0x34a7b48, push=0x34a144c, growth=0x34a1480,
        consumer=0x34a99b8, guard=0x34a60d8, accepted=0x34a6198,
        diagnostic=0x36e9310, alternative=0x34a9b78,
        mode=0x51c, alternate=0xcd0, flag=0xd24),
    'donor': dict(sha='d04cc70b41382a147ef5c67d7e86ba706d66526aee17619767b07cbb416b77ca',
        dispatch=0x3161324, table=0x480e3d0, base=0x3161344,
        start_route=0x3161344, data_route=0x3161384,
        start=0x315a6f8, data=0x315cab8, producer=0x315aba8,
        producer_end=0x315abe4, push=0x3154328, growth=0x315435c,
        consumer=0x315cb68, guard=0x3159148, accepted=0x3159208,
        diagnostic=0x338c490, alternative=0x315cd28,
        mode=0x4ec, alternate=0xc98, flag=0xcec),
}


def spans(spec):
    return [(spec['dispatch'], 32), (spec['table'], 82),
        (spec['start_route'], 12), (spec['data_route'], 12),
        (spec['producer'], spec['producer_end']-spec['producer']),
        (spec['push'], spec['growth']-spec['push']),
        (spec['consumer'], 40),
        (spec['guard'], spec['accepted']+20-spec['guard'])]


def qualify_current(original, current, spec):
    for offset, size in spans(spec):
        if current[offset:offset+size] != original[offset:offset+size]:
            raise ValueError('Current AP differs in an admitted FILE span: '+hex(offset))
    return [dict(file_offset=hex(at), bytes=size,
        sha256=hashlib.sha256(original[at:at+size]).hexdigest()) for at,size in spans(spec)]


def audit(raw, spec):
    if hashlib.sha256(raw).hexdigest() != spec['sha']:
        raise ValueError('Unsupported complete original AP')
    elf=ELFFile(io.BytesIO(raw))
    # These exact AP fixtures use identical FILE/ELF VA coordinates here.
    for at,size in spans(spec):
        matches=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD'
            and s['p_offset']<=at and at+size<=s['p_offset']+s['p_filesz']]
        if len(matches)!=1 or matches[0]['p_vaddr']!=matches[0]['p_offset']:
            raise ValueError('Unqualified FILE/VA coordinate')
    u=Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages={page for at,size in spans(spec) for page in
        range(at&~4095,(at+size+4095)&~4095,4096)}
    pages.update(spec[key]&~4095 for key in
        ('diagnostic','accepted','alternative','start','data','producer_end','growth'))
    for page in pages:
        u.mem_map(page,4096);u.mem_write(page,raw[page:page+4096])
    for at,size in ((MEM,0x10000),(STACK,0x10000),(STOP,4096)):
        u.mem_map(at,size)
    runner=BoundaryRunner(u,(),stop=STOP,stack=STACK,count=400)
    putq=lambda at,v:u.mem_write(at,struct.pack('<Q',v))
    putw=lambda at,v:u.mem_write(at,struct.pack('<I',v))
    getq=lambda at:struct.unpack('<Q',u.mem_read(at,8))[0]
    routes=[]
    table=struct.unpack_from('<41h',raw,spec['table'])
    for event,key in ((6,'start'),(7,'data')):
        assert spec['base']+4*table[event]==spec[key+'_route']
        got=runner.run(spec['dispatch'],(spec['start'],spec['data']),[
            (R.UC_ARM64_REG_X23,event),(R.UC_ARM64_REG_X19,MEM),
            (R.UC_ARM64_REG_X20,MEM+0x2000)])
        assert got['at']==spec[key] and got['args'][:2]==[MEM,MEM+0x2000]
        routes.append(dict(event=event,callee_file=hex(got['at']),callee_executed=False))
    # Event7 reaching normal processing without a real start-created record
    # selects the same empty-pending diagnostic in BOTH original models.
    u.mem_write(MEM,bytes(0x1000));putq(MEM+0x330,MEM+0x4000);putq(MEM+0x350,MEM+0x4000)
    got=runner.call(spec['guard'],(MEM,MEM+0x2000,0),
        (spec['accepted'],spec['diagnostic']))
    assert got['at']==spec['diagnostic']
    cases=[]
    for mode,alternate,flag in itertools.product((0,1,2,22),(0,1,2),(0,1)):
        for slot in (0,19):
            owner=bytearray(0x1000)
            struct.pack_into('<I',owner,spec['mode'],mode)
            struct.pack_into('<I',owner,spec['alternate'],alternate)
            owner[spec['flag']]=flag
            begin=MEM+0x4000+24*slot
            for offset in (0x330,0x350):struct.pack_into('<Q',owner,offset,begin)
            for offset in (0x340,0x360):struct.pack_into('<Q',owner,offset,MEM+0x4000+504)
            u.mem_write(MEM,bytes(owner));u.mem_write(MEM+0x3ff0,b'\xa5'*536)
            u.mem_write(MEM+0x2000,bytes(64));putw(MEM+0x2004,0x12345678)
            frame=STACK+0x8000
            u.mem_write(frame,bytes(0x100))
            # A separately entered original post-preparation slice. Native
            # producer prepares its OWN 24-byte record before its actual push.
            got=runner.run(spec['producer'],(spec['producer_end'],spec['growth']),[
                (R.UC_ARM64_REG_X19,MEM),(R.UC_ARM64_REG_X20,frame+0x80),
                (R.UC_ARM64_REG_X24,MEM+0x2000),(R.UC_ARM64_REG_X29,frame),
                (R.UC_ARM64_REG_SP,frame)])
            assert got['at']==spec['producer_end']
            appended=mode!=1 and alternate==0 and flag==0
            assert getq(MEM+0x350)==begin+(24 if appended else 0)
            expected=bytearray(b'\xa5'*536)
            if appended:expected[16+slot*24:40+slot*24]=struct.pack('<IIQQ',0x12345678,0,0,2**64-1)
            assert bytes(u.mem_read(MEM+0x3ff0,536))==bytes(expected)
            before=bytes(u.mem_read(MEM,0x1000))
            got=runner.call(spec['guard'],(MEM,MEM+0x2000,0),
                (spec['accepted'],spec['diagnostic']))
            assert got['at']==spec['accepted' if appended else 'diagnostic']
            assert bytes(u.mem_read(MEM,0x1000))==before
            if appended:
                got=runner.run(spec['accepted'],(spec['accepted']+20,))
                assert got['at']==spec['accepted']+20 and getq(begin+8)==1
                expected[24+slot*24:32+slot*24]=struct.pack('<Q',1)
                assert bytes(u.mem_read(MEM+0x3ff0,536))==bytes(expected)
            # Original normal-data selection, not a fabricated successful
            # processing call. Alternative modes stop before their own path.
            selected=runner.run(spec['consumer'],(spec['guard'],spec['alternative'],spec['alternative']+24),[
                (R.UC_ARM64_REG_X19,MEM),(R.UC_ARM64_REG_X21,MEM+0x2000),
                (R.UC_ARM64_REG_X22,0)])
            assert (selected['at']==spec['guard'])==(mode==0 and alternate==0 and flag==0)
            cases.append(dict(mode_raw=mode,alternate_raw=alternate,flag_raw=flag,
                slot=slot,record_appended=appended,normal_guard_accepts=appended,
                data_selection_boundary_file=hex(selected['at']),external_services_executed=False))
    # No input can manufacture capacity at the last slot: stop at real growth.
    putq(MEM+0x350,MEM+0x4000+480)
    got=runner.call(spec['push'],(MEM+0x320,MEM+0x2000),(spec['growth'],))
    assert got['at']==spec['growth']
    return dict(source_sha256=spec['sha'],dispatch=routes,cases=cases,
        data_before_start_selects_empty_pending_diagnostic=True,
        original_record_counter_increment_checked=True,
        actual_original_postpreparation_record_push_executed=True,
        growth_stopped_before_allocation=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap',type=Path,required=True)
    p.add_argument('--donor-ap',type=Path,required=True)
    p.add_argument('--current-ap',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.ap.read_bytes();donor=a.donor_ap.read_bytes()
    report=dict(schema='OFFLINE_AP_CAPTURE_ORDER/1',camera_io=False,
        target=audit(raw,SPECS['target']),donor=audit(donor,SPECS['donor']),
        limits=['The entered producer slice follows earlier native preparation that was not executed',
            'Event6 before event7 is not proven physical scheduling or CP retention admission',
            'Raw mode fields are not user-visible drive/shutter settings',
            'No artificial AP pending record may be injected to bypass the real capture-start path',
            'No sensor, pre-trigger RAW, save, cancellation fence or menu is implemented by this audit'])
    if a.current_ap:
        current=a.current_ap.read_bytes()
        report['current_selected_spans']=qualify_current(raw,current,SPECS['target'])
        report['current_ap_sha256']=hashlib.sha256(current).hexdigest()
        rejected=0
        for at,size in spans(SPECS['target']):
            bad=bytearray(current);bad[at+size-1]^=1
            try:qualify_current(raw,bad,SPECS['target'])
            except ValueError:rejected+=1
            else:raise AssertionError('Changed source span admitted')
        assert rejected==len(spans(SPECS['target']))
        report['source_drift_controls_rejected']=rejected
    with a.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    print('Original target/donor event6/7 and 96 pending-record admission cases passed; no camera I/O.')


if __name__=='__main__':main()
