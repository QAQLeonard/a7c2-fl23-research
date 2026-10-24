"""Existing-extent CP metadata prototype, offline original/new instruction tests.

No complete firmware, manifest, native writer or host trigger is emitted. Source
equivalence cannot qualify loaded code, physical cache/MMU or a camera boot.
"""
import argparse,hashlib,itertools,json,random,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_MEM_WRITE
from unicorn import arm_const as R
from support.cp_metadata_probe import (BASE,BRANCH,ALIGN,CALL,PROBE,DEFAULT,REPLY,ENTRY,POINTERS,STATUS,SPANS,apply_for_emulator)
from support.reference import SPECS

MESSAGE,STACK,STOP=0x30000100,0x40000000,0x50000000
REGS=tuple(getattr(R,f'UC_ARM_REG_R{i}') for i in range(13))+(R.UC_ARM_REG_SP,R.UC_ARM_REG_LR,R.UC_ARM_REG_CPSR)


class Fixture:
    def __init__(self,raw):
        self.u=u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        u.mem_map(BASE,(len(raw)+4095)&~4095);u.mem_write(BASE,raw)
        for at,size in ((MESSAGE&~4095,8192),(STACK,65536),(STOP,4096),(POINTERS&~4095,4096),(0x1a7e000,4096)):
            u.mem_map(at,size)
        self.target={STOP};self.seen=[];self.accesses=[]
        def code(cpu,address,size,user):
            if address in self.target:self.seen.append(address);cpu.emu_stop()
            elif not BASE+ENTRY<=address<BASE+0x45e7c8:
                raise AssertionError('Unexpected native service or code boundary '+hex(address))
        def access(cpu,kind,address,size,value,user):
            self.accesses.append((kind,address,size))
            if STACK<=address<address+size<=STACK+65536:return
            if MESSAGE<=address<address+size<=MESSAGE+24:return
            if kind!=UC_MEM_WRITE and POINTERS<=address<address+size<=POINTERS+16:return
            if kind!=UC_MEM_WRITE and address==0x1a7e988 and size==4:return
            if kind!=UC_MEM_WRITE and address==0x30001038 and size==4:return
            # TBB's four original in-text dispatch bytes are data reads.
            if kind!=UC_MEM_WRITE and BASE+0x45e704<=address<address+size<=BASE+0x45e708:return
            raise AssertionError('Unexpected memory or pointer follow '+hex(address))
        u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access)
    def run(self,start,targets,values=()):
        self.target={STOP,*[BASE+at for at in targets]};self.seen.clear();self.accesses.clear()
        for reg,value in values:self.u.reg_write(reg,value&0xffffffff)
        self.u.emu_start((BASE+start)|1,0xffffffff,count=500)
        assert len(self.seen)==1 and self.u.reg_read(R.UC_ARM_REG_PC)==self.seen[0],'Instruction budget or wrong boundary'
        return tuple(self.u.reg_read(r) for r in REGS)
    def initialize(self,flags=0,mode=0):
        u=self.u;u.mem_write(STACK,b'\xa5'*65536);u.mem_write(MESSAGE&~4095,b'\x6b'*4096)
        packet=bytearray(b'\x5a'*24);packet[0]=mode;struct.pack_into('<I',packet,20,0x138bc713)
        u.mem_write(MESSAGE,bytes(packet));u.reg_write(R.UC_ARM_REG_CPSR,0x1f3|flags)
        for index,reg in enumerate(REGS[:13]):u.reg_write(reg,0xc1000000+index)
        u.reg_write(R.UC_ARM_REG_R0,MESSAGE);u.reg_write(R.UC_ARM_REG_SP,STACK+0x8000);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        return bytes(packet)


def audit(original,current,folder):
    if hashlib.sha256(original).hexdigest()!=SPECS['a7c2-2.01']['sha256']:raise ValueError('Exact original CP required')
    target,changes=apply_for_emulator(original,current)
    old,new=Fixture(current),Fixture(target)
    # Independent arithmetic partitions: all low6 address/length bits plus
    # zero/high/near-overflow aligned lengths and nonzero address high words.
    math_cases=0
    for low,tail,whole in itertools.product(range(64),range(64),(0,0x1000,0xffffffc0)):
        addr=(0x12340000|low);length=(whole|tail)
        values=((R.UC_ARM_REG_R1,addr),(R.UC_ARM_REG_R2,0xfedcba98),(R.UC_ARM_REG_R3,length))
        outputs=[]
        for fixture in (old,new):
            fixture.initialize(flags=0xa80f0000)
            outputs.append(fixture.run(ALIGN,(CALL,),values))
        assert outputs[0]==outputs[1],(hex(addr),hex(length),outputs)
        assert outputs[0][0]==addr&~63 and outputs[0][1]==((length+(addr&63)+63)&0xffffffff)&~63
        math_cases+=1
    rng=random.Random(138);random_cases=0
    for _ in range(512):
        values=tuple(zip((R.UC_ARM_REG_R1,R.UC_ARM_REG_R2,R.UC_ARM_REG_R3),[rng.getrandbits(32) for _ in range(3)]))
        outputs=[];flags=(rng.getrandbits(4)<<28)|0x080f0000
        for fixture in (old,new):
            fixture.initialize(flags=flags)
            outputs.append(fixture.run(ALIGN,(CALL,),values))
        assert outputs[0]==outputs[1];random_cases+=1
    # Whole callback/defaults and all supported dispatch prefixes: do not
    # fabricate a native config/cache/logger return for either source.
    mode_cases=[]
    pointers=(0x22a4760,0x22b4720,0x22b4728,0x22b4730)
    for mode in range(256):
        outputs=[];packets=[]
        for fixture in (old,new):
            fixture.initialize(flags=0x980f0000,mode=mode)
            fixture.u.mem_write(POINTERS,struct.pack('<4I',*pointers))
            state=fixture.run(ENTRY,(0x45e708,0x45e728,0x45e730,0x45e736))
            outputs.append((fixture.seen[0],state));packets.append(bytes(fixture.u.mem_read(MESSAGE,24)))
        if 0xe2<=mode<=0xe5:
            expected=bytearray(packets[0]);expected[1]=STATUS;expected[8:20]=struct.pack('<3I',pointers[mode-0xe2],0,0)
            assert packets[1]==bytes(expected)
            reads=[(at,n) for kind,at,n in new.accesses if kind!=UC_MEM_WRITE and POINTERS<=at<POINTERS+16]
            assert reads==[(POINTERS+4*(mode-0xe2),4)]
            assert new.seen==[STOP] and new.u.reg_read(R.UC_ARM_REG_SP)==STACK+0x8000
            assert outputs[1][1][4:12]==outputs[0][1][4:12]
        else:
            assert outputs[0]==outputs[1] and packets[0]==packets[1],mode
        mode_cases.append(dict(mode=mode,new_fixed_pointer=0xe2<=mode<=0xe5,
            original_supported_body_stopped=1<=mode<=4,native_services_executed=False))
    # Each returned value is raw data, including unmapped/MMIO-like values:
    # the prototype must not dereference them or infer allocation from zeros.
    raw_cases=0
    for value in (0,1,0xffffffff,0xf48300e0):
        for mode in range(0xe2,0xe6):
            new.initialize(mode=mode);new.u.mem_write(POINTERS,struct.pack('<4I',*([value]*4)))
            new.run(ENTRY,());packet=bytes(new.u.mem_read(MESSAGE,24))
            assert struct.unpack_from('<I',packet,8)[0]==value;raw_cases+=1
    whole_prefix_cases=0
    # Entire original mode1 prefix reaches the unchanged cache call through
    # actual dispatch/global/size reads, not a fabricated service return.
    for size in (0,1,63,64,65,0xfffffff0):
        outputs=[]
        for fixture in (old,new):
            fixture.initialize(mode=1)
            fixture.u.mem_write(0x1a7e988,struct.pack('<I',0x30001000))
            fixture.u.mem_write(0x30001038,struct.pack('<I',size))
            outputs.append(fixture.run(ENTRY,(CALL,)))
        assert outputs[0]==outputs[1]
        whole_prefix_cases+=1
    if target[:0x20154]!=current[:0x20154]:raise AssertionError('Bootstrap/header changed')
    allowed={at+i for at,raw in changes for i in range(len(raw))}
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(current,target)))
    # Selected source drift refuses before assembly or construction.
    bad=bytearray(current);bad[0x45e6d8]^=1
    try:apply_for_emulator(original,bytes(bad))
    except ValueError:pass
    else:raise AssertionError('Changed callback admitted')
    report=dict(schema='OFFLINE_EXISTING_EXTENT_CP_METADATA_PROBE/1',camera_IO=False,installed=False,
        source_sha256=hashlib.sha256(current).hexdigest(),prototype_sha256=hashlib.sha256(target).hexdigest(),
        changed_bytes=sum(a!=b for a,b in zip(current,target)),window_bytes=sum(len(raw) for _,raw in changes),
        windows=[dict(file_offset=hex(at),bytes=len(raw),original_sha256=hashlib.sha256(current[at:at+len(raw)]).hexdigest(),
            target_sha256=hashlib.sha256(raw).hexdigest()) for at,raw in changes],
        arithmetic_partition_cases=math_cases,random_full_word_cases=random_cases,all_registers_and_APSR_equal_at_original_cache_call=True,
        modes=mode_cases,unfollowed_raw_pointer_cases=raw_cases,exact_inverse=True,
        whole_original_mode1_prefix_cases=whole_prefix_cases,private_response_status=STATUS,
        original_cache_call_unchanged=True,no_new_code_page_or_state=True,physical_safety_proven=False,
        limitations=['Original/new arithmetic executes only on synthetic memory',
            'Supported services stop before execution; original call address/arguments/stack remain unchanged',
            'Four fixed BSS reads are not a coherent pool snapshot or pixel ownership proof',
            'Current loaded code/boot identity, explicit patch review and exact camera inverse remain required'])
    (folder/'report.private.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cp',type=Path,required=True)
    p.add_argument('--current-cp',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(exist_ok=False)
    report=audit(a.cp.read_bytes(),a.current_cp.read_bytes(),a.output)
    print(report['arithmetic_partition_cases']+report['random_full_word_cases'],'native arithmetic comparisons;',len(report['modes']),
        'mode cases;',report['unfollowed_raw_pointer_cases'],'raw-value controls; no camera I/O')
if __name__=='__main__':main()
