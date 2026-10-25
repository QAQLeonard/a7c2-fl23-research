"""New native RAW lease C code calling original CP functions, offline only.

CPU/task/lock/resource objects are explicit synthetic inputs. The original
get-task,try-lock,ownership-add,pin,unpin,ownership-drop and unlock instructions
execute with no successful service stubs. Final backing free/notifier stop.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import io

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn import arm_const as R
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP
from support.reference import CP_LOAD_BASE as BASE,SPECS
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB

LEASE,CONTEXT,LOCK,NODE=MEM+0x100,0x33000000,0x33001000,0x22b4f40
POOL,CPU_TABLE,LOCK_TABLE=0x22a4760,0x1b30708,0x1b29194
NAMES=('precapture_raw_hold','precapture_raw_drop')
STOPS=(0xb14ed6,0xb1746c,0x4fdd70,0x4e64fc,0x4e655c)
SPANS=((0x4e9f24,0x9c),(0x4e66f0,0xdc),(0x4e68a8,0xe0),
    (0xb16778,0x8a),(0xb16a52,0x184),(0xb16bd6,0x13a))


class Fixture:
    def __init__(self,elf,cp,*,memory_guard=True):
        self.u,self.symbols=image_loader(elf,'thumb',NAMES,cpu_model=R.UC_CPU_ARM_CORTEX_A9)
        u=self.u
        u.mem_map(BASE,(len(cp)+4095)&~4095);u.mem_write(BASE,cp)
        self.regions=((CONTEXT,0x5000),(POOL&~4095,0x12000),
            (CPU_TABLE&~4095,4096),(LOCK_TABLE&~4095,4096),(0x1a8c000,4096))
        for at,size in self.regions:u.mem_map(at,size)
        self.seen=[];self.calls=[];self.pixel_reads=[];self.code_spans=set()
        native_entries=(0x4e9f24,0x4e66f0,0x4e68a8,0xb16778,0xb16a52,0xb16b4c,0xb16bd6)
        def code(cpu,at,size,user):
            if at in {STOP,*(BASE+n for n in STOPS)}:
                self.seen.append(at);cpu.emu_stop();return
            if BASE<=at<BASE+len(cp):
                self.code_spans.add((at-BASE,size))
                if at-BASE in native_entries:self.calls.append(hex(at-BASE))
                if not any(BASE+a<=at<at+size<=BASE+a+n for a,n in SPANS):
                    raise AssertionError('Outside qualified original RAW routines: '+hex(at))
        def access(cpu,kind,at,size,value,user):
            if BASE<=at<at+size<=BASE+len(cp):
                assert kind!=UC_MEM_WRITE,'Original image write'
                self.code_spans.add((at-BASE,size))
            elif any(a<=at<at+size<=a+n for a,n in (*self.regions,(MEM,4096),(STACK,0x4000))):
                pass
            elif at==0x1b30d30 and size==4:
                assert kind!=UC_MEM_WRITE
            else:
                self.pixel_reads.append((at,size))
                raise AssertionError('Unexpected memory/pixel access: '+hex(at))
        u.hook_add(UC_HOOK_CODE,code)
        if memory_guard:u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access)
        self.reset()

    def put(self,at,value):self.u.mem_write(at,struct.pack('<I',value))
    def get(self,at):return struct.unpack('<I',self.u.mem_read(at,4))[0]
    def byte(self,at,value):self.u.mem_write(at,bytes([value]))
    def half(self,at,value):self.u.mem_write(at,struct.pack('<H',value))
    def reset(self,*,task=136,held=0,occupied=0,owners=1,pins=0,kind=0x50504,
              count=1,generation=1,sequence=77,high=5,offset=0x100000,size=0x1180000):
        u=self.u
        for at,n in self.regions:u.mem_write(at,bytes(n))
        u.mem_write(MEM,bytes(4096))
        self.put(CPU_TABLE,CONTEXT);self.put(0x1b30d30,CONTEXT+0x2000)
        self.put(CONTEXT,CONTEXT+0x2000+(task-1)*88)
        self.put(CONTEXT+0x10,held);self.put(LOCK_TABLE+107*4,LOCK)
        self.put(LOCK,occupied);self.put(LOCK+8,0x55 if occupied else 0)
        self.put(0x1a8c558,POOL)
        self.put(0x1a8c0ac,NODE)
        self.put(POOL,kind);self.put(POOL+4,sequence)
        self.byte(POOL+8,owners);self.byte(POOL+9,pins);self.byte(POOL+11,generation)
        self.half(POOL+12,2 if pins else 1);self.half(POOL+14,count)
        for i in range(min(count,12)):
            node=NODE+i*80;self.put(POOL+16+4*i,node)
            self.put(node+8,offset+i*size);self.put(node+12,high)
            self.put(node+16,0);self.put(node+20,size)
            self.put(node+0x28,POOL);self.put(node+0x2c,sequence)
        u.reg_write(R.UC_ARM_REG_CPSR,0x13)
        self.calls.clear();self.seen.clear();self.pixel_reads.clear()

    def call(self,name,*values,native=False,thumb=True):
        self.seen.clear();self.calls.clear()
        for i,v in enumerate(values):self.u.reg_write(getattr(R,f'UC_ARM_REG_R{i}'),v)
        self.u.reg_write(R.UC_ARM_REG_SP,STACK+0x3000)
        self.u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        at=(BASE+name)|int(thumb) if native else self.symbols[name]
        self.u.emu_start(at,0xffffffff,count=50000)
        assert len(self.seen)==1,'Exhausted execution is not completion'
        result=self.u.reg_read(R.UC_ARM_REG_R0)&0xffffffff
        return result if result<0x80000000 else result-0x100000000,self.seen[0]

    def state(self):
        return dict(phase=self.get(LEASE),owners=bytes(self.u.mem_read(POOL+8,1))[0],
            pins=bytes(self.u.mem_read(POOL+9,1))[0],
            lock=self.get(LOCK),IRQ=bool(self.u.reg_read(R.UC_ARM_REG_CPSR)&0x80))


def exercise(elf,cp,*,memory_guard=True):
    f=Fixture(elf,cp,memory_guard=memory_guard);cases=[]
    status,boundary=f.call(NAMES[0],LEASE,9,1,0x8400)
    assert (status,boundary)==(0,STOP)
    assert f.state()==dict(phase=1,owners=2,pins=1,lock=0,IRQ=False)
    assert struct.unpack('<4I',f.u.mem_read(LEASE+32,16))==(0x100000,5,0x1180000,0)
    assert '0xb16778' in f.calls and '0xb16a52' in f.calls
    cases.append(dict(case='actual_native_extra_owner_and_pin',state=f.state(),calls=f.calls.copy()))
    status,boundary=f.call(NAMES[1],LEASE,9,1)
    assert (status,boundary)==(0,STOP)
    assert f.state()==dict(phase=2,owners=1,pins=0,lock=0,IRQ=False)
    cases.append(dict(case='drop_only_adapter_reference',state=f.state(),calls=f.calls.copy()))
    before=f.state();status,boundary=f.call(NAMES[1],LEASE,9,1)
    assert status==-22 and boundary==STOP and f.state()==before and not f.calls
    cases.append(dict(case='duplicate_drop_refused',state=f.state()))
    for label,options in [('preexisting_pin',dict(pins=1)),
                         ('last_owner_reference_capacity',dict(owners=254)),
                         ('last_pin_capacity',dict(pins=254)),
                         ('all_twelve_metadata_descriptors',dict(count=12))]:
        f.reset(**options);owners=f.state()['owners'];pins=f.state()['pins']
        assert f.call(NAMES[0],LEASE,9,6,0x8400)==(0,STOP)
        assert f.state()['owners']==owners+1 and f.state()['pins']==pins+1
        assert f.call(NAMES[0],LEASE,9,6,0x8400)==(-22,STOP) and not f.calls
        assert f.call(NAMES[1],LEASE,9,6)==(0,STOP)
        assert f.state()==dict(phase=2,owners=owners,pins=pins,lock=0,IRQ=False)
        cases.append(dict(case=label,state=f.state()))
    f.reset();assert f.call(NAMES[0],LEASE,9,2,0x8400)==(0,STOP)
    assert f.call(0x4e66f0,0x6c,native=True,thumb=False)==(0,STOP)
    status,boundary=f.call(0xb16bd6,0x8400,native=True)
    assert (status,boundary)==(0,STOP) and f.state()['owners']==1 and f.state()['pins']==1
    assert f.call(0x4e68a8,0x6c,native=True,thumb=False)==(0,STOP)
    cases.append(dict(case='ordinary_owner_drop_preserves_adapter_pin',state=f.state()))
    status,boundary=f.call(NAMES[1],LEASE,9,2)
    assert boundary==BASE+0xb14ed6 and f.state()['phase']==3
    calls=f.calls.copy();before=f.state()
    assert f.call(NAMES[1],LEASE,9,2)==(-22,STOP) and f.state()==before and not f.calls
    cases.append(dict(case='final_backing_free_boundary_retains_UNKNOWN',state=before,calls=calls,
        backing_free_executed=False,notification_executed=False))
    for label,options in [('wrong_task',dict(task=137)),('busy_lock',dict(occupied=1)),
                         ('stale_generation',dict(generation=2)),('owner_saturated',dict(owners=255)),
                         ('pin_saturated',dict(pins=255)),('wrong_type',dict(kind=0x505)),
                         ('empty_descriptor',dict(count=0)),('too_many_descriptors',dict(count=13))]:
        f.reset(**options);owners=f.state()['owners'];pins=f.state()['pins']
        status,boundary=f.call(NAMES[0],LEASE,9,3,0x8400)
        assert status!=0 and boundary==STOP and f.state()['owners']==owners and f.state()['pins']==pins
        assert '0xb16778' not in f.calls and '0xb16a52' not in f.calls
        cases.append(dict(case=label,state=f.state(),calls=f.calls.copy()))
    for label,address,value in [('unqualified_node_address',POOL+16,0x35000000),
                                ('node_owned_by_other_record',NODE+0x28,POOL+64),
                                ('stale_node_sequence',NODE+0x2c,78)]:
        f.reset();f.put(address,value);status,boundary=f.call(NAMES[0],LEASE,9,3,0x8400)
        assert status==-116 and boundary==STOP and f.state()==dict(phase=0,owners=1,pins=0,lock=0,IRQ=False), (label,status,hex(boundary),f.state())
        assert '0xb16778' not in f.calls and '0xb16a52' not in f.calls
        cases.append(dict(case=label,state=f.state(),calls=f.calls.copy()))
    for label,options in [('wrong_address_domain',dict(high=8)),('outside_root_extent',dict(offset=0x3ffff000,size=8192))]:
        f.reset(**options);status,boundary=f.call(NAMES[0],LEASE,9,4,0x8400)
        assert status==-5 and boundary==STOP and f.state()==dict(phase=3,owners=2,pins=1,lock=0,IRQ=False)
        before=f.state();assert f.call(NAMES[0],LEASE,9,4,0x8400)==(-22,STOP) and f.state()==before
        assert not f.calls
        cases.append(dict(case=label+'_retains_UNKNOWN',state=f.state()))
    f.reset();assert f.call(NAMES[0],LEASE,9,5,0x8400)==(0,STOP)
    before=f.state();assert f.call(NAMES[1],LEASE,10,5)==(-22,STOP) and f.state()==before and not f.calls
    cases.append(dict(case='foreign_epoch_refused',state=f.state()))
    f.put(POOL+4,78);status,boundary=f.call(NAMES[1],LEASE,9,5)
    assert status==-116 and boundary==STOP and f.state()['phase']==3
    assert '0xb16b4c' not in f.calls and '0xb16bd6' not in f.calls
    cases.append(dict(case='changed_native_sequence_retains_UNKNOWN',state=f.state()))
    assert not f.pixel_reads
    return cases,f.code_spans


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True);p.add_argument('--current-cp',type=Path,required=True)
    p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();cp=a.cp.read_bytes();current=a.current_cp.read_bytes()
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:raise ValueError('Exact original CP required')
    a.output.mkdir(exist_ok=False);elf=a.output/'native-raw-lease.elf'
    source=Path(__file__).with_name('cp_raw_lease.c')
    compile_shared(a.zig,'thumb',elf,[source],extra_flags=('-mrestrict-it',))
    compiled=ELFFile(io.BytesIO(elf.read_bytes()));text=compiled.get_section_by_name('.text')
    instructions=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(text.data(),text['sh_addr']))
    assert not any(i.mnemonic.startswith('it') and i.mnemonic!='it' for i in instructions), 'Multi-instruction IT block in new adapter'
    cases,spans=exercise(elf,cp)
    unobserved,_=exercise(elf,cp,memory_guard=False)
    assert cases==unobserved,'Memory observer changed native execution'
    if len(current)!=len(cp) or any(current[at:at+size]!=cp[at:at+size] for at,size in spans):
        raise ValueError('Current CP native lease routine differs')
    report=dict(schema='OFFLINE_COMPILED_NATIVE_RAW_LEASE/1',camera_io=False,
        original_firmware_services_stubbed=False,original_reference_functions_executed=True,
        physical_pixels_read=False,installed=False,physical_RAW_lifetime_verified=False,
        memory_observer_controls_identical=True,new_component_multi_instruction_IT_blocks=False,
        additional_compiler_flags=['-mrestrict-it'],
        cases=cases,selected_original_FILE_spans=[dict(offset=hex(at),bytes=size) for at,size in sorted(spans)],
        original_CP_sha256=hashlib.sha256(cp).hexdigest(),current_CP_sha256=hashlib.sha256(current).hexdigest(),
        compiled_ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        limits=['CPU/task/lock/metadata/descriptor nodes are explicit synthetic state',
            'No live ingress hook,placement,storage,loaded source or current policy admission exists',
            'Root-domain bounds do not establish physical image ownership or timestamps',
            'Final backing free/notification stop before execution;UNKNOWN retains references'])
    report['source_sha256']={str(x.name):hashlib.sha256(x.read_bytes()).hexdigest() for x in
        [Path(__file__),source,source.with_suffix('.h')]}
    (a.output/'report.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(len(cases),'compiled adapter/original CP cases passed; no camera operation or physical lease claim')


if __name__=='__main__':main()
