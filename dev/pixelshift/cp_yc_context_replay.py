"""Original AutoRecog/Yc reader construction and native image-bank publication.

Uses the previously bound capture registry and original ROM virtual methods.
Leaf data, cold BSS, heap-unavailable OS state and invocation order are fixtures.
The real destructor-registration failures are retained and reported. No complete
startup, frame population, four-frame scheduling, sensor or camera I/O.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_capture_gate_replay import replay as capture_replay, profile as capture_profile
from cp_population_init_replay import initialize as initialize_population, profile as population_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, _, gate = capture_profile(directory)
    _, population = population_profile(directory)
    # Independently inspected paired entries; constants/data are decoded below.
    delta = -0x218 if gate['context_getter'] == 0xb2ddb4 else 0
    p = dict(auto_getter=0x805982+delta, auto_ctor=0x805932+delta,
        reader=0x8d0e74+delta, backend=0x8d0866+delta,
        bank_getter=0x870436+delta, registry_getter=gate['context_getter'],
        register_destructor=0x61ddf8+delta, malloc=0x618d04+delta,
        lock=population['lock'], gate=gate)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at-0x108000:at-0x108000+size], at))

    def materialized(at, size, register, index=0):
        values = [value for reg, value in literals(code(at, size)) if reg == register]
        if len(values) <= index:
            raise ValueError('Original Yc context address is unavailable')
        return values[index]

    p['auto'] = materialized(p['auto_getter'], 10, 'r0')
    auto_vtable = materialized(p['auto_ctor']+6, 10, 'r0')+8
    def word(at):
        return struct.unpack_from('<I', data, at-0x108000)[0]
    name = word(word(auto_vtable-4)+4)
    p['auto_type'] = data[name-0x108000:name-0x108000+100].split(b'\0', 1)[0].decode('ascii')
    if p['auto_type'] != 'N6Camera2FC9AutoRecog20AutoRecogModeManagerE':
        raise ValueError('Original AutoRecog constructor/RTTI no longer match')
    p['auto_vtable'] = auto_vtable
    p['index'] = materialized(p['bank_getter'], 0x18, 'r0')
    p['banks'] = materialized(p['bank_getter'], 0x18, 'r1')
    rows = code(p['bank_getter'], 0x20)
    if (rows[2].op_str != 'r2, #0x818' or rows[-2].op_str != 'r0, r0, #0x750'):
        raise ValueError('Original Yc bank stride/member changed')

    # Complete inspected functions plus actual ROM virtual thunks/getters.
    spans = [(0x6137a8,0x78),(0x613898,0x78),(0x613bfc,0x90),(0x613d40,0x74),
        (0x618d04,0x50),(0x61ddf8,0x7e),(0x61ef18,0x138),
        (0x8053ca,10),(0x80544c,0x22),(0x805932,0x3e),(0x805982,10),
        (0x807aae,0x1c),(0x807b4e,10),(0x870436,0x20),
        (0x8ce640,0x1a),(0x8ce67e,0xc),(0x8ceac2,4),
        (0x8ceb42,0x3a),(0x8cebb8,6),(0x8cebc4,6),
        (0x8cf900,0x2a),(0x8cf98a,0x52),(0x8d03cc,0x6e),
        (0x8d0740,0x1e),(0x8d084a,0xc),(0x8d0866,0x52),(0x8d08be,6),(0x8d092a,6),
        (0x8d09e6,0x34),(0x8d0a1a,4),(0x8d0a7c,0x52),(0x8d0ad4,6),
        (0x8d0aec,0x2e),(0x8d0da0,0xe),(0x8d0dbc,0xe),(0x8d0de6,0xe),
        (0x8d0e68,0xc),(0x8d0e74,0x52),(0x8d0ef0,6),(0x8d0efc,6),
        (0x8d0f0e,6),(0x8d0f44,6)]
    p['regions'] = [(at+delta, at+delta+size) for at, size in spans]
    p['regions'].append((p['registry_getter'], p['registry_getter']+10))
    at = lambda value: value+delta
    # Writable owners decoded from the actual constructor/getter instructions.
    p['owners'] = [(p['auto'],0x54),(p['lock'],28),
                   (materialized(at(0x8ceb42),0x34,'r0',1),0x18)]
    for entry, length, register, size in [
            (0x8cf98a,0x26,'r4',8),
            (0x8d0866,0x26,'r4',8),(0x8d0a7c,0x26,'r4',12),
            (0x8d0e74,0x26,'r4',8)]:
        p['owners'].append((materialized(at(entry),length,register),size))
    for entry,length,register in [(0x8ceb42,14,'r4'),(0x8cf98a,14,'r5'),
            (0x8d0866,14,'r5'),(0x8d0a7c,14,'r5'),(0x8d0e74,14,'r5')]:
        p['owners'].append((materialized(at(entry),length,register),1))
    for entry in (0x8d03e8,0x8d03fc,0x8d0410,0x8d0424,
                  0x8d0b08,0x8cf91c,0x8d0a0c,0x8d0752):
        p['owners'].append((materialized(at(entry),8,'r1'),4))
    p['binding'] = materialized(at(0x8d0e68),8,'r0')
    p['published_bank'] = materialized(at(0x8d0752),8,'r1')
    p['owners'].append((p['binding'],4))
    # The original allocator's NULL heap is an explicit cold-start fixture.
    from capstone import CS_MODE_ARM
    arm = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    malloc_code = list(arm.disasm(data[p['malloc']-0x108000:p['malloc']-0x108000+0x18],p['malloc']))
    p['heap'] = next(value for reg,value in literals(malloc_code) if reg=='r6')
    p['destructor_head']=materialized(p['register_destructor']+0x20,8,'r3')
    p['memory'] = list(p['owners'])+[(p['index'],4),(p['banks'],2*0x818),(p['heap'],4),
                                  (p['destructor_head'],4)]
    # Additional readonly backing named by original constructors/getters.
    for lo,hi in p['regions']:
        p['memory'] += [(value,64) for _,value in literals(code(lo,hi-lo))
                        if 0x1100000 <= value < 0x2400000]
    return data,p


def initialize(cpu,directory,*,bank=0,repeat=False,heap_state=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _,p=profile(directory)
    if bank not in (0,1):
        raise ValueError('Only the two inspected bank-index fixtures are covered')
    for start,size in p['memory']:
        for page in range(start&~4095,(start+size+4095)&~4095,4096):
            if not any(lo<=page<=hi for lo,hi,_ in cpu.mem_regions()):
                cpu.mem_map(page,4096)
    # Cold data inputs, not published object pointers or successful API results.
    if heap_state is None:
        cpu.mem_write(p['heap'],bytes(4))
    elif struct.unpack('<I',cpu.mem_read(p['heap'],4))[0]!=heap_state['native_heap']:
        raise ValueError('The native heap was not published in this same CPU state')
    cpu.mem_write(p['index'],struct.pack('<I',bank))
    stack,finish=0x3000e000,0x3000d000
    before_context=bytes(cpu.mem_read(p['gate']['context'],200))
    calls,registrations,allocation_results,registration_inputs=[],[],[],[]
    expected_bank=p['banks']+bank*0x818+0x750
    saved_regs=[getattr(arm,'UC_ARM_REG_R'+str(n)) for n in range(4,12)]
    saved=[cpu.reg_read(reg) for reg in saved_regs]

    def code_hook(uc,at,n,_):
        if at==p['register_destructor']:
            registration_inputs.append([uc.reg_read(reg) for reg in
                (arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2)])
        if at==p['register_destructor']+0x1c:
            allocation_results.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at==p['register_destructor']+0x7c:
            registrations.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at==p['register_destructor']+0x40:
            registrations.append(uc.reg_read(arm.UC_ARM_REG_R0))
        regions=p['regions']+(heap_state['profile']['regions'] if heap_state else [])
        if not any(lo<=at and at+n<=hi for lo,hi in regions):
            raise ValueError('Native Yc initialization reached an unresolved dependency: '+hex(at))

    def write_hook(uc,access,at,n,value,_):
        spans=p['owners']+[(stack-4096,4096)]+(heap_state['writes'] if heap_state else [])
        if heap_state:
            spans.append((p['destructor_head'],4))
        if not any(lo<=at and at+n<=lo+size for lo,size in spans):
            raise ValueError('Native Yc initialization changed unrelated state: '+hex(at))

    def run(entry):
        cpu.reg_write(arm.UC_ARM_REG_SP,stack)
        cpu.reg_write(arm.UC_ARM_REG_LR,finish|1)
        cpu.emu_start(entry|1,finish,count=10000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC)!=finish or cpu.reg_read(arm.UC_ARM_REG_SP)!=stack
                or [cpu.reg_read(reg) for reg in saved_regs]!=saved):
            raise ValueError('Original Yc initializer did not return with preserved caller state')
        calls.append(entry)
        return cpu.reg_read(arm.UC_ARM_REG_R0)

    def virtual(obj,slot):
        vtable=struct.unpack('<I',cpu.mem_read(obj,4))[0]
        entry=struct.unpack('<I',cpu.mem_read(vtable+slot,4))[0]
        cpu.reg_write(arm.UC_ARM_REG_R0,obj)
        return run(entry)

    ch,wh=cpu.hook_add(UC_HOOK_CODE,code_hook),cpu.hook_add(UC_HOOK_MEM_WRITE,write_hook)
    try:
        run(p['auto_getter']);run(p['auto_ctor'])
        for _ in range(2 if repeat else 1):
            registry=run(p['registry_getter'])
            reader=run(p['reader'])
            cpu.reg_write(arm.UC_ARM_REG_R1,registry)
            virtual(reader,0x58)
            backend=run(p['backend'])
            virtual(backend,8)
            # Consume the original backend slot used by the frame publisher.
            published=virtual(backend,0x50)
            if (published!=expected_bank or struct.unpack('<I',cpu.mem_read(p['binding'],4))[0]!=registry
                    or struct.unpack('<I',cpu.mem_read(p['published_bank'],4))[0]!=expected_bank):
                raise ValueError('Native reader binding/bank publication differs from source layout')
    finally:
        cpu.hook_del(ch);cpu.hook_del(wh)
    expected_results=[0]*4 if heap_state else [0xffffffff]*4
    if (registrations!=expected_results
            or struct.unpack('<I',cpu.mem_read(p['auto'],4))[0]!=p['auto_vtable']
            or bytes(cpu.mem_read(p['gate']['context'],200))!=before_context):
        raise ValueError('Native construction/heap-unavailable registration/context contract differs')
    if heap_state:
        arena,size=heap_state['arena'],heap_state['size']
        if (len(allocation_results)!=4 or len(set(allocation_results))!=4
                or any(not arena<=node<arena+size-16 or node%8 for node in allocation_results)):
            raise ValueError('Native registration allocations are outside their original arena')
        node=struct.unpack('<I',cpu.mem_read(p['destructor_head'],4))[0]
        for expected_node,inputs in zip(reversed(allocation_results),reversed(registration_inputs)):
            if node!=expected_node:raise ValueError('Original destructor list order differs')
            words=struct.unpack('<4I',cpu.mem_read(node,16))
            if list(words[1:])!=inputs:raise ValueError('Native registration changed destructor/object/DSO')
            node=words[0]
        if node!=0:raise ValueError('Native destructor list has an unexpected tail')
        for at in (arena-4,arena+size):
            if bytes(cpu.mem_read(at,4))!=b'\xa5'*4:raise ValueError('Native allocation changed arena neighbor')
    elif allocation_results!=[0]*4:
        raise ValueError('Native unavailable-heap allocator did not preserve its failure')
    return dict(native_auto_type=p['auto_type'],native_bank_index=bank,native_bank_stride=0x818,
        native_bank_member_offset=0x750,native_reader_binding_and_backend_virtuals_executed=True,
        native_published_bank_matches_original_getter=True,native_initializer_calls=len(calls),
        native_malloc_results=['arena_node_'+str(n) for n in range(4)] if heap_state else allocation_results,
        native_destructor_registration_results=[0]*4 if heap_state else [-1]*4,
        destructor_registration_completed=heap_state is not None,heap_unavailable_fixture=heap_state is None,
        native_destructor_list_verified=heap_state is not None,
        native_context_and_caller_state_preserved=True,host_assigned_consumed_object_pointers=False,
        api_results_replaced=False,cold_data_and_stage_order_are_fixtures=True,
        full_startup_or_frame_population_executed=False,four_frame_scheduler_executed=False,
        positioning_or_exposure_executed=False,saved_off_setting_executed=False,camera_io=False,installable=False)


def replay(directory,*,bank=0,repeat=False,initialize_heap=False):
    def continuation(cpu,snapshot,capture):
        initialize_population(cpu,directory)
        heap_state=None
        if initialize_heap:
            from cp_native_heap_replay import initialize as initialize_arena
            heap_state=initialize_arena(cpu,directory)
        return initialize(cpu,directory,bank=bank,repeat=repeat,heap_state=heap_state)
    return capture_replay(directory,native_context=True,guard_actions=('exit',),
        pipeline_source=dict(gpio_bit=1,capture_mode=2),continuation=continuation)['native_continuation']


def compare(c2,reference):
    rows=[]
    for bank in (0,1):
        for repeat in (False,True):
            for initialize_heap in (False,True):
                values=dict(bank=bank,repeat=repeat,initialize_heap=initialize_heap)
                x,y=replay(c2,**values),replay(reference,**values)
                if x!=y:raise ValueError('Native C2/CR Yc initialization contracts differ')
                rows.append(dict(input=values,target=x,reference=y))
    return dict(schema='a7c2-native-yc-context/1',paired_cases=len(rows),cases=rows,
        camera_io=False,physical_shift_verified=False,installable=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=compare(args.c2,args.reference)
    with args.output.open('x',encoding='utf-8') as handle:json.dump(result,handle,indent=2)
    print(json.dumps({key:result[key] for key in ('paired_cases','camera_io','physical_shift_verified')}))


if __name__=='__main__':main()
