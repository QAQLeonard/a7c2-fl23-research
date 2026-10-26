"""Native libc arena construction/publication on a registered-region fixture.

Stops outside region lookup/admission. Original arena, global publication and
lock initialization run; allocation/free clients may reuse the same CPU state.
No API result, allocator return or registration node is supplied by the host.
"""
from functools import lru_cache
import struct

from cp_population_init_replay import profile as population_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    data, population = population_profile(directory)
    delta = population['lock_init']-0x61ddd0
    p = dict(start=0x619178+delta, end=0x6191a0+delta,
        constructor=0x616770+delta, malloc=0x618d04+delta,
        free=0x618da4+delta)
    decoder=Cs(CS_ARCH_ARM,CS_MODE_ARM)
    def code(at,n):return list(decoder.disasm(data[at-0x108000:at-0x108000+n],at))
    def materialized(at,n,reg):
        values=[v for r,v in literals(code(at,n)) if r==reg]
        if len(values)!=1:raise ValueError('Native heap binding is not unique')
        return values[0]
    init=code(p['start'],p['end']-p['start'])
    calls=[int(row.op_str.lstrip('#'),0) for row in init if row.mnemonic=='bl']
    if len(calls)!=2 or calls[0]!=p['constructor']:
        raise ValueError('Original arena publication slice changed')
    p['lock_init']=calls[1]
    p['heap']=materialized(p['start']+16,8,'r1')
    p['lock']=materialized(p['start']+28,8,'r0')
    p['config']=materialized(p['constructor']+8,16,'r8')
    p['regions']=[(p['start'],p['end'])]+[(at+delta,at+delta+n) for at,n in [
        (0x616770,0x174),(0x616904,0xbe4),(0x6174e8,0x7a0),
        (0x618d04,0x50),(0x618da4,0x38),(0x613740,0x10),
        (0x613bd0,0xbc),(0x613d40,0x74),(0x61ef18,0x138)]]
    return data,p


def initialize(cpu,directory,*,arena=0x37000008,size=0x10000):
    import unicorn.arm_const as arm
    from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
    _,p=profile(directory)
    stack=0x3000e000
    for at,n in [(arena-4,size+8),(p['config']-4,32),(p['heap']-4,12),(p['lock']-4,20)]:
        for page in range(at&~4095,(at+n+4095)&~4095,4096):
            if not any(lo<=page<=hi for lo,hi,_ in cpu.mem_regions()):cpu.mem_map(page,4096)
    cpu.mem_write(arena-4,b'\xa5'*4+bytes(size)+b'\xa5'*4)
    cpu.mem_write(p['config']-4,b'\xa5'*4+bytes(24)+b'\xa5'*4)
    cpu.mem_write(p['heap']-4,b'\xa5'*4+bytes(4)+b'\xa5'*4)
    cpu.mem_write(p['lock']-4,b'\xa5'*4+bytes(12)+b'\xa5'*4)
    # Inputs normally produced by the original registered-region lookup.
    cpu.mem_write(stack,struct.pack('<II',size,arena))
    writable=[(arena,size),(p['config'],24),(p['heap'],4),(p['lock'],12),(stack-4096,4104)]
    def hook(uc,at,n,_):
        if not any(lo<=at and at+n<=hi for lo,hi in p['regions']):
            raise ValueError('Native arena startup reached an unresolved dependency: '+hex(at))
    def write(uc,access,at,n,value,_):
        if not any(lo<=at and at+n<=lo+length for lo,length in writable):
            raise ValueError('Native arena startup changed unrelated state: '+hex(at))
    protected=[getattr(arm,'UC_ARM_REG_R'+str(n)) for n in range(4,12)]
    before=[cpu.reg_read(reg) for reg in protected]
    ch,wh=cpu.hook_add(UC_HOOK_CODE,hook),cpu.hook_add(UC_HOOK_MEM_WRITE,write)
    cpu.reg_write(arm.UC_ARM_REG_SP,stack)
    try:cpu.emu_start(p['start'],p['end'],count=10000)
    finally:cpu.hook_del(ch);cpu.hook_del(wh)
    native_heap=struct.unpack('<I',cpu.mem_read(p['heap'],4))[0]
    if (cpu.reg_read(arm.UC_ARM_REG_PC)!=p['end'] or cpu.reg_read(arm.UC_ARM_REG_SP)!=stack
            or [cpu.reg_read(reg) for reg in protected]!=before or native_heap!=arena+8
            or struct.unpack('<2I',cpu.mem_read(p['lock'],8))!=(0xff,0)):
        raise ValueError('Original arena publication/lock/caller contract differs')
    for at in (arena-4,arena+size,p['config']-4,p['config']+24,p['heap']-4,p['heap']+4,p['lock']-4,p['lock']+12):
        if bytes(cpu.mem_read(at,4))!=b'\xa5'*4:raise ValueError('Native arena startup changed a neighbor')
    return dict(profile=p,arena=arena,size=size,native_heap=native_heap,writes=writable[:-1],
        region_lookup_and_admission_executed=False,native_arena_and_publication_executed=True,
        host_assigned_allocator_output=False,camera_io=False)


def replay(directory,*,size=0x10000,requests=(16,24,512,4096)):
    from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    from cp_sequence_replay import machine
    data,p=profile(directory)
    cpu=machine(data,[])
    state=initialize(cpu,directory,size=size)
    stack,finish=0x3000e000,0x3000d000
    def code(uc,at,n,_):
        if not any(lo<=at and at+n<=hi for lo,hi in p['regions']):
            raise ValueError('Original heap client reached an unresolved dependency: '+hex(at))
    def write(uc,access,at,n,value,_):
        if not any(lo<=at and at+n<=lo+length for lo,length in state['writes']+[(stack-4096,4096)]):
            raise ValueError('Original heap client changed unrelated state: '+hex(at))
    def run(entry,value):
        cpu.reg_write(arm.UC_ARM_REG_R0,value)
        cpu.reg_write(arm.UC_ARM_REG_SP,stack)
        cpu.reg_write(arm.UC_ARM_REG_LR,finish|1)
        protected=[getattr(arm,'UC_ARM_REG_R'+str(n)) for n in range(4,12)]
        saved=[cpu.reg_read(r) for r in protected]
        irq=cpu.reg_read(arm.UC_ARM_REG_CPSR)&0x80
        cpu.emu_start(entry,finish,count=20000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC)!=finish or cpu.reg_read(arm.UC_ARM_REG_SP)!=stack
                or [cpu.reg_read(r) for r in protected]!=saved or cpu.reg_read(arm.UC_ARM_REG_CPSR)&0x80!=irq):
            raise ValueError('Original heap client failed to preserve caller/IRQ state')
        return cpu.reg_read(arm.UC_ARM_REG_R0)
    ch,wh=cpu.hook_add(UC_HOOK_CODE,code),cpu.hook_add(UC_HOOK_MEM_WRITE,write)
    nodes=[]
    try:
        large=run(p['malloc'],size-0x1000)
        if not large:raise ValueError('Native arena cannot allocate its bounded baseline request')
        run(p['free'],large)
        for n,length in enumerate(requests):
            node=run(p['malloc'],length)
            if (not state['arena']<=node<=state['arena']+size-length or node%8
                    or any(node<prior+prior_size and prior<node+length for prior,prior_size in nodes)):
                raise ValueError('Native allocations overlap or leave their source arena')
            cpu.mem_write(node,bytes([0x31+n])*length)  # Client payload input, not an API result.
            nodes.append((node,length))
        for n,(node,length) in enumerate(nodes):
            if bytes(cpu.mem_read(node,length))!=bytes([0x31+n])*length:
                raise ValueError('Native allocation damaged another outstanding client payload')
        for node,_ in reversed(nodes):run(p['free'],node)
        after=run(p['malloc'],size-0x1000)
        if after!=large:raise ValueError('Native free/coalescing did not restore the large allocation')
        run(p['free'],after)
    finally:cpu.hook_del(ch);cpu.hook_del(wh)
    if struct.unpack('<2I',cpu.mem_read(p['lock'],8))!=(0xff,0):
        raise ValueError('Native allocation/free left the heap locked')
    for at in (state['arena']-4,state['arena']+size):
        if bytes(cpu.mem_read(at,4))!=b'\xa5'*4:raise ValueError('Native heap client crossed arena boundary')
    return dict(native_allocation_count=len(nodes)+2,native_free_count=len(nodes)+2,
        client_payloads_preserved=True,large_allocation_restored_after_coalescing=True,
        native_lock_released=True,api_results_replaced=False,region_admission_is_fixture=True,
        full_os_startup_executed=False,camera_io=False,installable=False)


def compare(c2,reference):
    rows=[]
    for size in (0x10000,0x20000):
        for requests in ((16,),(16,24,512,4096)):
            values=dict(size=size,requests=requests)
            x,y=replay(c2,**values),replay(reference,**values)
            if x!=y:raise ValueError('Native C2/CR arena allocation/recycling differs')
            rows.append(dict(input=values,target=x,reference=y))
    return dict(paired_cases=len(rows),cases=rows,camera_io=False,physical_shift_verified=False)
