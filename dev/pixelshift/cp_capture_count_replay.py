"""Native cached Pixel Shift mode -> capture-count prefix -> CP storage.

Original getter/snapshot fragments and the 0x4014 builder prefix generate the
count, independently of TRINITY packet byte9. Stop before native memset;
remaining format/features/send do not execute. Unchanged prefix bytes cross
an explicit fixture into the CP storage stage after its earlier side effects.
No complete dispatcher, four-frame scheduling, exposure or persistence runs.
"""
from functools import lru_cache
import argparse
import json
from pathlib import Path
import struct

from native_replay import source
from ap_group_setup_replay import profile as group_profile
from cp_dispatch_replay import profile as dispatch_profile


@lru_cache(maxsize=2)
def profile(directory):
    image,info=source(directory)
    _,group=group_profile(directory)
    data,dispatch=dispatch_profile(directory)
    target=info['model']=='ILCE-7CM2'
    delta=0 if target else 0x4e8
    p=dict(builder=0x35463d8+delta,stop=0x3546cb0+delta,
        interval=0x3519048+delta,copy=None,getters=[group['getters'][0],group['getters'][3]],
        cp_begin=0x35566e if target else 0x3557ce,cp_end=0x355762 if target else 0x3558c2,
        cp_source=dispatch['parameter']-0x180)
    p['snapshots']=[]
    for getter,offset in zip(p['getters'],(0x5f8,0x604)):
        store=0xb9000000|((offset//4)<<10)|(19<<5)
        pattern=struct.pack('<II',0xb9400000,store)
        matches=[];start=0
        while True:
            pos=image.data.find(pattern,start)
            if pos<0:break
            start=pos+4
            try:at=image.address(pos)-4;rows=image.instructions(at,12)
            except ValueError:continue
            if rows[0].mnemonic=='bl' and int(rows[0].op_str.lstrip('#'),0)==getter:matches.append(at)
        if len(matches)!=1:raise ValueError('Original capture cached-setting snapshot is not unique')
        p['snapshots'].append(matches[0])
    # Original model caller copies these cached values to input+30/+34.
    pattern=struct.pack('<IIII',0xb945fa60,0xb900eba0,0xb9460660,0xb900efa0)
    matches=[];start=0
    while True:
        pos=image.data.find(pattern,start)
        if pos<0:break
        start=pos+4
        try:matches.append(image.address(pos))
        except ValueError:pass
    if len(matches)!=2:raise ValueError('Original paired capture-argument copy sites changed')
    p['copy']=min(matches)
    code=image.instructions(p['builder'],0x48)
    if not any(row.op_str=='w1, #0x4014' for row in code):
        raise ValueError('Original capture configuration command changed')
    p['regions']=[(p['builder'],p['builder']+0xe6c),(p['interval'],p['interval']+0x44),
        (p['copy'],p['copy']+16)]+[(at,at+12) for at in p['snapshots']]
    p['regions'] += [(at,at+20) for at in p['getters']]
    return image,data,p


def produce(directory,*,mode=1,companion=0):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_UNMAPPED,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
    import unicorn.arm64_const as arm
    image,data,p=profile(directory)
    cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM);mapped=set()
    def load(uc,access,at,n,value,_):
        page=at&~4095
        if page in mapped:return True
        if not any(s['p_vaddr']<=page and page+4096<=s['p_vaddr']+s['p_memsz'] for s in image.segments):
            raise ValueError('Native capture formatter left its module: '+hex(at))
        uc.mem_map(page,4096);mapped.add(page)
        try:offset=image.offset(page,4096)
        except ValueError:pass
        else:uc.mem_write(page,image.data[offset:offset+4096])
        return True
    cpu.hook_add(UC_HOOK_MEM_UNMAPPED,load)
    cpu.mem_map(0x10000000,0x20000)
    cache,fp,stack,finish=0x10004000,0x10008f00,0x1001f000,0x10003000
    record=fp+0xb8
    cpu.mem_write(record-4,b'\xa5'*4+bytes(0x50)+b'\xa5'*4)
    cpu.mem_write(record,struct.pack('<I',0x12345678))
    cpu.mem_write(record+0x1c,struct.pack('<I',1))  # Independent format input.
    def execute(entry,end=finish):
        cpu.reg_write(arm.UC_ARM64_REG_SP,stack)
        cpu.reg_write(arm.UC_ARM64_REG_LR,finish)
        cpu.emu_start(entry,end,count=5000)
    for getter,value in zip(p['getters'],(mode,companion)):
        execute(getter)
        slot=cpu.reg_read(arm.UC_ARM64_REG_X0);load(cpu,0,slot,4,0,None)
        cpu.mem_write(slot,struct.pack('<I',value))
    boundary=None
    def hook(uc,at,n,_):
        nonlocal boundary
        if at==p['stop']:
            boundary='before_native_format_buffer_initialization';uc.emu_stop();return
        if not any(lo<=at and at+n<=hi for lo,hi in p['regions']):
            raise ValueError('Native count prefix reached an unresolved dependency: '+hex(at))
    def write(uc,access,at,n,value,_):
        spans=[(cache+0x5f8,4),(cache+0x604,4),(record+0x30,8),(stack-0x1000,0x1000)]
        if not any(lo<=at and at+n<=lo+size for lo,size in spans):
            raise ValueError('Native count prefix changed unrelated state: '+hex(at))
    ch,wh=cpu.hook_add(UC_HOOK_CODE,hook),cpu.hook_add(UC_HOOK_MEM_WRITE,write)
    try:
        cpu.reg_write(arm.UC_ARM64_REG_X19,cache)
        for at in p['snapshots']:execute(at,at+12)
        cpu.reg_write(arm.UC_ARM64_REG_X29,fp)
        execute(p['copy'],p['copy']+16)
        before=bytes(cpu.mem_read(record-4,0x58))
        cpu.reg_write(arm.UC_ARM64_REG_X0,record)
        cpu.reg_write(arm.UC_ARM64_REG_X1,0x10002000)
        execute(p['builder'])
        sp=cpu.reg_read(arm.UC_ARM64_REG_SP)
        prefix=bytes(cpu.mem_read(sp+0x68,24))
        if boundary is None or bytes(cpu.mem_read(record-4,0x58))!=before:
            raise ValueError('Native count prefix did not stop with preserved input')
    finally:cpu.hook_del(ch);cpu.hook_del(wh)
    expected_count=1 if companion else 4 if mode==1 else 16 if mode==2 else 1
    expected_mode=23 if companion or mode else 0
    if (struct.unpack_from('<H',prefix,2)[0]!=0x4014 or prefix[8]!=expected_mode
            or struct.unpack_from('<I',prefix,12)[0]!=expected_count):
        raise ValueError('Native AP capture count differs from independent mode classification')
    return prefix


def publish(cpu,directory,prefix):
    # Prefix bytes are unchanged. Earlier CP side effects and later handlers
    # are explicit unexecuted boundaries; this is not the complete CP command.
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
    import unicorn.arm_const as cp
    _,data,p=profile(directory)
    cc=cpu;packet=0x30008000;src=p['cp_source']
    cc.mem_write(packet,prefix)
    for page in range(src&~4095,(src+0x400+4095)&~4095,4096):
        if not any(lo<=page<=hi for lo,hi,_ in cc.mem_regions()):cc.mem_map(page,4096)
    decoded=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(data[p['cp_begin']-0x108000:p['cp_begin']-0x108000+8],p['cp_begin']))
    from cp_serial_replay import literals
    debug=next(v for r,v in literals(decoded) if r=='sb')
    if not any(lo<=debug<=hi for lo,hi,_ in cc.mem_regions()):cc.mem_map(debug&~4095,4096)
    cc.mem_write(debug+0x32,b'\0');cc.mem_write(debug+0xb8,b'\0')
    before=bytes(cc.mem_read(src,0x400))
    cc.reg_write(cp.UC_ARM_REG_R4,packet);cc.reg_write(cp.UC_ARM_REG_R8,src)
    def ccode(uc,at,n,_):
        if not (p['cp_begin']<=at and at+n<=p['cp_end']):
            raise ValueError('Native capture storage left its inspected stage')
    def cwrite(uc,access,at,n,value,_):
        spans=[(src+o,size) for o,size in [(0x138,4),(0x128,4),(0x13c,4),(0x120,4),
            (0x100,4),(0x110,4),(0x12c,4)]]
        if not any(lo<=at and at+n<=lo+size for lo,size in spans):
            raise ValueError('Native capture storage changed unrelated state: '+hex(at))
    ch,wh=cc.hook_add(UC_HOOK_CODE,ccode),cc.hook_add(UC_HOOK_MEM_WRITE,cwrite)
    try:cc.emu_start(p['cp_begin']|1,p['cp_end'],count=200)
    finally:cc.hook_del(ch);cc.hook_del(wh)
    count=struct.unpack('<I',cc.mem_read(src+0x120,4))[0]
    expected_count=struct.unpack_from('<I',prefix,12)[0]
    expected=bytearray(before)
    for destination,value in ((0x138,prefix[8]),(0x128,prefix[9]),(0x13c,prefix[10]),
                              (0x120,expected_count),(0x100,prefix[16]),(0x110,prefix[17])):
        struct.pack_into('<I',expected,destination,value)
    expected[0x12c:0x130]=prefix[18:22]
    if (cc.reg_read(cp.UC_ARM_REG_PC)!=p['cp_end'] or count!=expected_count
            or bytes(cc.mem_read(src,0x400))!=bytes(expected)
            or bytes(cc.mem_read(packet,24))!=prefix):
        raise ValueError('Original capture storage did not publish the AP-generated count')
    return dict(native_capture_mode=prefix[8],native_capture_count=count,
        native_cached_snapshot_and_argument_copy_executed=True,native_ap_prefix_bytes_preserved=True,
        native_cp_total_count_storage_executed=True,host_assigned_capture_count=False,
        api_results_replaced=False,transport_and_stage_handoffs_are_fixtures=True,
        complete_ap_formatter_or_cp_handler_executed=False,four_frame_scheduler_executed=False,
        saved_off_setting_executed=False,positioning_or_exposure_executed=False,camera_io=False,installable=False)


def replay(directory,*,mode=1,companion=0):
    from cp_sequence_replay import machine
    _,data,_=profile(directory)
    return publish(machine(data,[]),directory,produce(directory,mode=mode,companion=companion))


def compare(c2,reference):
    cases=[]
    for mode in (0,1,2):
        for companion in (0,1):
            values=dict(mode=mode,companion=companion)
            x,y=replay(c2,**values),replay(reference,**values)
            if x!=y:raise ValueError('Native C2/CR capture-count production differs')
            cases.append(dict(input=values,target=x,reference=y))
    return dict(paired_cases=len(cases),cases=cases,camera_io=False,physical_shift_verified=False)


def compare_headers(c2,reference):
    from cp_frame_header_replay import replay as header
    cases=[]
    for mode in (1,2):
        for companion in (0,1):
            for clear in (False,True):
                values=dict(mode=mode,companion=companion)
                args=dict(continue_header=True,clear_after_header=clear,native_count_inputs=values)
                x,y=header(c2,**args),header(reference,**args)
                if x!=y:raise ValueError('Native count/snapshot/first-frame/group-end propagation differs')
                cases.append(dict(input=dict(**values,queued_clear=clear),target=x,reference=y))
    return dict(paired_cases=len(cases),cases=cases,camera_io=False,physical_shift_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2',type=Path,required=True);parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frame-header',action='store_true',help='Continue native count through snapshot/header and optional queued group end')
    args=parser.parse_args()
    result=(compare_headers if args.frame_header else compare)(args.c2,args.reference)
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ('paired_cases','camera_io','physical_shift_verified')}))


if __name__=='__main__':main()
