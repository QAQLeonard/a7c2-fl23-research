"""Original/new instruction and fixed pool packet tests, strictly offline.

Does not install a candidate, follow CP pixels, execute native services or prove
a serial/atomic pool snapshot. The completed private single-query experiment
does not grant these offline commands permission to operate on a camera.
"""
import argparse,hashlib,itertools,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_MEM_WRITE
from unicorn import arm_const as R
from support import cp_pool_probe as p
from support.reference import SPECS

MESSAGE,STACK,STOP=0x30000100,0x40000000,0x50000000
REGS=tuple(getattr(R,f'UC_ARM_REG_R{i}') for i in range(13))+(R.UC_ARM_REG_SP,R.UC_ARM_REG_LR,R.UC_ARM_REG_CPSR)


class Fixture:
    def __init__(self,image):
        self.u=u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(p.BASE,(len(image)+4095)&~4095);u.mem_write(p.BASE,image)
        for at,n in ((MESSAGE&~4095,4096),(STACK,65536),(STOP,4096),(p.HEAD&~4095,4096)):u.mem_map(at,n)
        self.stops={STOP};self.accesses=[];self.terminal=[]
        def code(cpu,at,size,user):
            if at in self.stops:self.terminal.append(at);cpu.emu_stop()
            elif not p.BASE+p.ENTRY<=at<p.BASE+0x45e7c8:raise AssertionError('Unexpected native service/code')
        def access(cpu,kind,at,size,value,user):
            self.accesses.append((kind,at,size))
            if STACK<=at<at+size<=STACK+65536 or MESSAGE<=at<at+size<=MESSAGE+24:return
            if kind!=UC_MEM_WRITE and ((at,size) in ((p.HEAD,4),(p.TAIL,4),(p.COUNT,4)) or
                    p.BASE+0x45e704<=at<at+size<=p.BASE+0x45e708):return
            raise AssertionError('Access outside fixed words/message/stack')
        u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access)
    def reset(self,mode=0,values=(0,3,3),flags=0xa80f0000):
        self.u.mem_write(STACK,b'\xa5'*65536);self.u.mem_write(MESSAGE,b'\x5a'*24)
        raw=bytearray(b'\x5a'*24);raw[0]=mode
        if mode==0xe2:raw[2:8]=bytes(6)
        struct.pack_into('<I',raw,20,0x155ac713);self.u.mem_write(MESSAGE,bytes(raw))
        for at,value in zip((p.HEAD,p.TAIL,p.COUNT),values):self.u.mem_write(at,struct.pack('<I',value))
        self.u.reg_write(R.UC_ARM_REG_CPSR,0x1f3|flags)
        for i,reg in enumerate(REGS[:13]):self.u.reg_write(reg,0xc1000000+i)
        self.u.reg_write(R.UC_ARM_REG_R0,MESSAGE);self.u.reg_write(R.UC_ARM_REG_SP,STACK+0x8000);self.u.reg_write(R.UC_ARM_REG_LR,STOP|1)
    def run(self,entry,stops,inputs=()):
        self.stops={STOP,*[p.BASE+x for x in stops]};self.accesses.clear();self.terminal.clear()
        for reg,v in inputs:self.u.reg_write(reg,v)
        self.u.emu_start(p.BASE+entry|1,0xffffffff,count=500)
        assert len(self.terminal)==1,'Instruction budget is not completion'
        return self.terminal[0],tuple(self.u.reg_read(r) for r in REGS),bytes(self.u.mem_read(MESSAGE,24))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--current-cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(exist_ok=False)
    original=args.cp.read_bytes();current=args.current_cp.read_bytes()
    assert hashlib.sha256(original).hexdigest()==SPECS['a7c2-2.01']['sha256']
    target,changes=p.apply_for_emulator(original,current);old,new=Fixture(current),Fixture(target);math_cases=0
    for low,tail,whole in itertools.product(range(64),range(64),(0,0x1000,0xffffffc0)):
        values=((R.UC_ARM_REG_R1,0x12340000|low),(R.UC_ARM_REG_R2,0xfedcba98),(R.UC_ARM_REG_R3,whole|tail));out=[]
        for fixture in (old,new):fixture.reset();out.append(fixture.run(p.ALIGN,(p.CALL,),values))
        assert out[0]==out[1];math_cases+=1
    modes=[]
    for mode in range(256):
        results=[]
        for fixture in (old,new):fixture.reset(mode);results.append(fixture.run(p.ENTRY,(0x45e708,0x45e728,0x45e730,0x45e736)))
        if mode==0xe2:
            packet=results[1][2];result=p.decode_sample(packet,0x155ac713)
            assert (result['head'],result['tail'],result['free_metadata_records'])==(0,3,3)
            reads=[(at,n) for kind,at,n in new.accesses if kind!=UC_MEM_WRITE and p.HEAD<=at<=p.COUNT]
            assert reads==[(p.TAIL,4),(p.COUNT,4),(p.HEAD,4)]
        else:assert results[0]==results[1],mode
        modes.append(dict(mode=mode,sample=mode==0xe2,native_service_executed=False))
    cases=[]
    for values,accepted in [((0,0,0),True),((1022,1,3),True),((1,0,1023),True),((0,3,4),False),
            ((1024,3,3),False),((0,1024,3),False),((0,3,1024),False),((0xffffffff,0,1),False)]:
        new.reset(0xe2,values);result=new.run(p.ENTRY,())[2]
        try:decoded=p.decode_sample(result,0x155ac713)
        except ValueError:assert not accepted
        else:assert accepted and not decoded['atomic_or_owner_serialized_snapshot']
        cases.append(dict(values=values,host_accepted=accepted))
    packet=bytearray(struct.pack('<BB6s4I',0xe2,p.STATUS,bytes(6),0,3,3,0x155ac713));corrupt=[]
    for offset in (0,1,2,7,20):
        bad=bytearray(packet);bad[offset]^=1
        try:p.decode_sample(bytes(bad),0x155ac713)
        except ValueError:corrupt.append(offset)
        else:raise AssertionError(offset)
    report=dict(schema='OFFLINE_EXISTING_EXTENT_POOL_SAMPLE/1',camera_IO=False,installed=False,owner_authorization=False,
        arithmetic_cases=math_cases,modes=modes,pool_cases=cases,corruption_refusals=corrupt,
        window_bytes=sum(len(raw) for _,raw in changes),no_new_code_pages_or_state=True,
        exact_inverse=True,physical_pool_sample_verified=False,atomic_snapshot_proven=False,
        source_sha256=hashlib.sha256(current).hexdigest(),target_sha256=hashlib.sha256(target).hexdigest())
    (args.output/'report.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(math_cases,'original cache comparisons;256 mode cases;8 pool/range cases;5 corruption refusals; NO physical admission')
if __name__=='__main__':main()
