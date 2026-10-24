"""Generated packet-export code on synthetic lanes, strictly offline.

No CP callback is installed, no native service is stubbed or executed, and no
memory placement, transport lifetime, DMA or physical safety is qualified.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from unicorn import UC_HOOK_MEM_WRITE
from unicorn import arm_const as A,arm64_const as B
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM,STACK,STOP
from support.trace import BYTES,BINDING
from support.trace_export import request,reconstruct,PACKET

LANE=0x31001000;BIND=MEM+0x100;EVENT=MEM+0x200;MESSAGE=MEM+0x300
EXPECTED=dict(zip(BINDING,(0x58389855,0x12345678,0xabcdef01,256,64,1,0x137e20ab)))
NAMES=('precapture_trace_initialize','precapture_trace_append','precapture_trace_freeze','precapture_trace_read_packet')


def exercise(elf,arch,folder):
    u,symbols=image_loader(elf,arch,NAMES);u.mem_map(0x31000000,0x3000)
    regs=A if arch=='thumb' else B
    args=tuple(getattr(regs,('UC_ARM_REG_R' if arch=='thumb' else 'UC_ARM64_REG_X')+str(i)) for i in range(4))
    sp,lr,pc=(A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_PC) if arch=='thumb' else (B.UC_ARM64_REG_SP,B.UC_ARM64_REG_LR,B.UC_ARM64_REG_PC)
    exporting=False;writes=[]
    def onwrite(cpu,kind,at,size,value,user):
        if exporting:
            assert MESSAGE<=at<at+size<=MESSAGE+24,'Exporter changed lane/global/stack'
            writes.append((at,size))
    # Generated exporter uses its own stack on Thumb; permit that stack only.
    def writecheck(cpu,kind,at,size,value,user):
        if exporting and not STACK<=at<at+size<=STACK+0x3000:onwrite(cpu,kind,at,size,value,user)
    u.hook_add(UC_HOOK_MEM_WRITE,writecheck)
    def call(which,*values):
        for reg,value in zip(args,values):u.reg_write(reg,value)
        u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP|int(arch=='thumb'))
        u.emu_start(symbols[NAMES[which]],STOP,count=50000)
        assert u.reg_read(pc)==STOP,'Instruction budget exhausted'
        value=u.reg_read(args[0])&0xffffffff
        return value if value<0x80000000 else value-0x100000000
    u.mem_write(LANE,bytes(BYTES));u.mem_write(BIND,struct.pack('<8I',*EXPECTED.values(),0))
    assert call(0,LANE,BIND)==1
    for index in range(4):
        u.mem_write(EVENT,struct.pack('<10I',5+index%3,0,0,0,index*37,19,1,2,3,4))
        assert call(1,LANE,256,EVENT)==1
    exporting=True
    u.mem_write(MESSAGE,request(0,EXPECTED['nonce']))
    assert call(3,LANE,MESSAGE)==1 and PACKET.unpack(bytes(u.mem_read(MESSAGE,24)))[1]==0x83
    exporting=False;assert call(2,LANE,256)==1;exporting=True
    frozen=bytes(u.mem_read(LANE,BYTES));packets=[]
    for offset in range(0,BYTES,12):
        u.mem_write(MESSAGE,request(offset,EXPECTED['nonce']));assert call(3,LANE,MESSAGE)==1
        packets.append(bytes(u.mem_read(MESSAGE,24)))
    raw,result=reconstruct(packets,EXPECTED)
    assert raw==frozen and result['complete_recording'] and not result['physical_capture_proven']
    assert bytes(u.mem_read(LANE,BYTES))==frozen
    (folder/(arch+'-lane.bin')).write_bytes(raw)
    (folder/(arch+'-packets.bin')).write_bytes(b''.join(packets))
    refused=[]
    for name,offset,value in [('busy',52,1),('unfrozen',44,0),('bad-magic',0,0),('bad-size',8,0),
            ('bad-owner',24,0),('bad-count',40,65),('bad-capacity',28,65),('bad-reserved',56,1),('bad-nonce',36,0)]:
        broken=bytearray(frozen);struct.pack_into('<I',broken,offset,value);u.mem_write(LANE,bytes(broken))
        u.mem_write(MESSAGE,request(0,EXPECTED['nonce']));assert call(3,LANE,MESSAGE)==1
        answer=PACKET.unpack(bytes(u.mem_read(MESSAGE,24)))
        assert answer[1:3]==(0x83,0) and not any(answer[4]) and bytes(u.mem_read(LANE,BYTES))==bytes(broken)
        refused.append(name)
    u.mem_write(LANE,frozen)
    for name,at,value in [('status',1,1),('count',2,1),('data',8,1),('nonce',20,0),('past-end',4,BYTES),('offset-wrap',4,0xffffffff)]:
        broken=bytearray(request(0,EXPECTED['nonce']));struct.pack_into('<I',broken,at,value)
        u.mem_write(MESSAGE,bytes(broken));assert call(3,LANE,MESSAGE)==1
        answer=PACKET.unpack(bytes(u.mem_read(MESSAGE,24)))
        assert answer[1:3]==(0x83,0) and not any(answer[4]);refused.append(name)
    for mode in (0,1,4,0xe1,255):
        packet=bytearray(request(0,EXPECTED['nonce']));packet[0]=mode
        u.mem_write(MESSAGE,bytes(packet));assert call(3,LANE,MESSAGE)==0
        assert bytes(u.mem_read(MESSAGE,24))==bytes(packet)
    # Pointer validity/aliasing is checked before any output write.
    before=bytes(u.mem_read(LANE,BYTES));writes.clear()
    for lane,message in ((0,MESSAGE),(LANE,0),(LANE+1,MESSAGE),(LANE,MESSAGE+1),(LANE,LANE),(LANE,LANE+BYTES-4)):
        assert call(3,lane,message)==-22 and not writes
    assert bytes(u.mem_read(LANE,BYTES))==before
    # Overflow exports remain forensic/incomplete; export never clears it.
    overflow=bytearray(frozen);struct.pack_into('<I',overflow,48,1);u.mem_write(LANE,bytes(overflow));overflow_packets=[]
    for offset in range(0,BYTES,12):
        u.mem_write(MESSAGE,request(offset,EXPECTED['nonce']));assert call(3,LANE,MESSAGE)==1
        overflow_packets.append(bytes(u.mem_read(MESSAGE,24)))
    assert reconstruct(overflow_packets,EXPECTED)[1]['overflow']
    assert not reconstruct(overflow_packets,EXPECTED)[1]['complete_recording']
    corrupt=[]
    controls={'missing':packets[:-1],'duplicate':packets[:1]+packets[:-1],
        'reordered':[packets[1],packets[0],*packets[2:]],'short':[packets[0][:-1],*packets[1:]]}
    for name,offset in [('packet-nonce',20),('packet-mode',0),('packet-status',1),('packet-count',2),('record-guard',8)]:
        bad=list(packets);b=bytearray(bad[9 if name=='record-guard' else 0]);b[offset]^=1
        bad[9 if name=='record-guard' else 0]=bytes(b);controls[name]=bad
    # Final chunk is4 bytes; all unused response bytes must be zero.
    bad=list(packets);b=bytearray(bad[-1]);b[12]=1;bad[-1]=bytes(b);controls['last-padding']=bad
    for name,bad in controls.items():
        try:reconstruct(bad,EXPECTED)
        except ValueError:corrupt.append(name)
        else:raise AssertionError(name)
    return dict(arch=arch,packet_count=len(packets),lane_bytes=BYTES,refusals=refused,
        untouched_modes=5,invalid_pointer_cases=6,host_corruptions=corrupt,overflow_preserved=True,
        original_services_executed=False,camera_IO=False,native_placement_or_export_lifetime_proven=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(exist_ok=False)
    folder=Path(__file__).resolve().parent;results=[]
    sources=[folder/'cp_trace.c',folder/'cp_trace_export.c']
    for arch in ('thumb','aarch64'):
        elf=args.output/(arch+'.so');compile_shared(args.zig,arch,elf,sources)
        results.append(exercise(elf,arch,args.output))
    assert (args.output/'thumb-lane.bin').read_bytes()==(args.output/'aarch64-lane.bin').read_bytes()
    assert (args.output/'thumb-packets.bin').read_bytes()==(args.output/'aarch64-packets.bin').read_bytes()
    report=dict(schema='OFFLINE_CP_TRACE_EXPORT/1',cases=results,camera_IO=False,installed=False,
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources+[folder/'cp_trace_export.h',folder/'support/trace_export.py',Path(__file__)]})
    (args.output/'report.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Both ISAs:262 exact packets reconstruct3136 bytes; refusal/alias/overflow/corruption controls pass; uninstalled')
if __name__=='__main__':main()
