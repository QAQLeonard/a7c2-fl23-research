"""Use native context binding and CapturingLv writes before capture selection.

The full original context binder supplies the consumed pipeline pointer; its
native getter independently identifies the same pipeline object. Enter/exit
CapturingLv functions write the capture guard rather than a host assignment.
The lifecycle order, root auxiliary pointers, pipeline data, debug setting,
capture mode and override are fixtures. No full startup, scheduler, saved
setting, positioning, settling or exposure runs. CapturingLv is an original
function label, not evidence of a sensor/stabilizer mode.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_context_source_replay import profile as context_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, source, context = context_profile(directory)
    delta = source['select']-0xb3bff2
    p = dict(bind=context['bind'], core=context['core_bind'],
             pipeline_getter=0xb2dc52+delta,
             enter=0x46e0cc+(0 if delta == 0 else -0x218),
             exit=0x46e10c+(0 if delta == 0 else -0x218))
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at-0x108000:at-0x108000+size], at))

    getter = code(p['pipeline_getter'], 0x10)
    p['root'] = next(value for reg, value in literals(getter) if reg == 'r1')
    if (getter[1].op_str != 'r0, #0x2950' or getter[-2].op_str != 'r0, r1'
            or getter[-1].op_str != 'lr'):
        raise ValueError('Original pipeline getter no longer identifies root+2950')
    guard_globals, debug = set(), set()
    for name, value in (('enter', 1), ('exit', 0)):
        instructions = code(p[name], 0x20)
        addresses = [at for reg, at in literals(instructions) if reg == 'r0']
        if (len(addresses) != 2 or instructions[1].op_str != f'r1, #{value}'
                or instructions[3].mnemonic != 'strb' or instructions[3].op_str != 'r1, [r0]'
                or not any(i.mnemonic == 'ldrsb.w' and i.op_str == 'r0, [r0, #0xa7]'
                           for i in instructions)):
            raise ValueError('Native CapturingLv guard writer changed')
        guard_globals.add(addresses[0])
        debug.add(addresses[1]+0xa7)
    if len(guard_globals) != 1 or len(debug) != 1:
        raise ValueError('Native enter/exit functions use different state objects')
    p['guard'], p['debug'] = guard_globals.pop(), debug.pop()
    return data, p


def initialize(cpu, directory, capture, pipeline, actions):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    actions = tuple(actions)
    if not actions or any(action not in ('enter', 'exit') for action in actions):
        raise ValueError('Expected an explicit native CapturingLv enter/exit sequence')
    if p['guard'] != capture['state']:
        raise ValueError('Native writer does not own the capture selector guard')
    root, context = p['root'], capture['context']
    stack, finish = 0x3000e000, 0x3000d000
    for begin, end in ((root, root+0x4e64), (context-4, context+0xcc),
                       (p['debug'], p['debug']+1), (p['guard']-4, p['guard']+5)):
        for page in range(begin & ~4095, (end+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    # The binder reads these auxiliary pointers, but this experiment does not
    # invoke or simulate the corresponding peripherals or their constructors.
    cpu.mem_write(root, b'\x6b'*0x4e64)
    cpu.mem_write(root+0x4e38, struct.pack('<9I', *(0x30007000+0x100*n for n in range(9))))
    cpu.mem_write(context-4, b'\xa5'*0xd0)
    cpu.mem_write(p['guard']-4, b'\xa5'*9)
    cpu.mem_write(p['debug'], b'\0')  # Native no-log path, not a supplied API result.
    root_before = bytes(cpu.mem_read(root, 0x4e64))
    phase, pointer_writes, guard_writes = 'bind', [], []
    regions = [(p['bind'], p['bind']+0x86), (p['core'], p['core']+0x118),
               (p['pipeline_getter'], p['pipeline_getter']+0x10),
               (p['enter'], p['enter']+0x28), (p['exit'], p['exit']+0x28)]

    def code_hook(uc, at, size, unused):
        if not any(lo <= at and at+size <= hi for lo, hi in regions):
            raise ValueError('Native context/guard publication entered an unresolved dependency: '+hex(at))

    def write_hook(uc, access, at, size, value, unused):
        if stack-4096 <= at and at+size <= stack:
            return
        if phase == 'bind' and context <= at and at+size <= context+0xc8:
            if at == context+0x10:
                pointer_writes.append((size, value))
            return
        if phase in ('enter', 'exit') and at == p['guard'] and size == 1:
            guard_writes.append(value)
            return
        raise ValueError('Native context/guard publication changed unrelated state: '+hex(at))

    def execute(entry, r0=0, r1=0):
        protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
        saved = [0x66550000+n for n in range(8)]
        for register, value in zip(protected, saved):
            cpu.reg_write(register, value)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.reg_write(arm.UC_ARM_REG_R0, r0)
        cpu.reg_write(arm.UC_ARM_REG_R1, r1)
        cpu.emu_start(entry | 1, finish, count=1000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(register) for register in protected] != saved):
            raise ValueError('Original context/guard helper did not return naturally')

    ch = cpu.hook_add(UC_HOOK_CODE, code_hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        execute(p['bind'], root, context)
        phase = 'getter'
        execute(p['pipeline_getter'])
        native_pipeline = cpu.reg_read(arm.UC_ARM_REG_R0)
        if (native_pipeline != root+0x2950 or pointer_writes != [(4, native_pipeline)]
                or struct.unpack('<I', cpu.mem_read(context+0x10, 4))[0] != native_pipeline):
            raise ValueError('Original binder and pipeline getter do not identify the same object')
        bound_context = bytes(cpu.mem_read(context-4, 0xd0))
        if bound_context[:4] != b'\xa5'*4 or bound_context[-4:] != b'\xa5'*4:
            raise ValueError('Native binder overwrote adjacent context data')
        for phase in actions:
            execute(p[phase])
        expected = [int(action == 'enter') for action in actions]
        guard = cpu.mem_read(p['guard'], 1)[0]
        if guard_writes != expected or guard != expected[-1]:
            raise ValueError('Original CapturingLv transitions differ from their native writes')
        if (bytes(cpu.mem_read(root, 0x4e64)) != root_before
                or bytes(cpu.mem_read(context-4, 0xd0)) != bound_context
                or bytes(cpu.mem_read(p['guard']-4, 4)) != b'\xa5'*4
                or bytes(cpu.mem_read(p['guard']+1, 4)) != b'\xa5'*4):
            raise ValueError('Native publication changed its source or adjacent fields')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    # Data remain fixtures: only their destination object's identity is native.
    cpu.mem_write(native_pipeline+0x102, bytes([pipeline]))
    cpu.mem_write(native_pipeline+0x13c, bytes(4))
    return dict(native_guard=guard, native_guard_transitions=guard_writes,
                native_pipeline_pointer_stores=len(pointer_writes),
                native_context_binder_executed=True, native_pipeline_getter_executed=True,
                binder_and_getter_share_object=True, native_helpers_returned=True,
                host_assigned_consumed_pointer_or_guard=False,
                pipeline_parameters_are_fixtures=True, lifecycle_order_is_fixture=True,
                startup_and_scheduler_executed=False, camera_io=False)


def compare(c2, reference):
    from cp_capture_gate_replay import replay
    rows = []
    for actions in (('enter',), ('exit',), ('enter', 'exit'), ('exit', 'enter')):
        for mode in (2, 6, 7, 33):
            for override in (0, 1):
                for pipeline in (0, 1, 2):
                    for trinity in (0, 1):
                        args = dict(trinity=trinity, capture_mode=mode, override=override,
                                    pipeline=pipeline, native_state=int(actions[-1] == 'enter'),
                                    native_context=True, guard_actions=actions)
                        a, b = replay(c2, **args), replay(reference, **args)
                        if a != b:
                            raise ValueError('Native C2/CR context-to-capture lifecycle differs')
                        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-capture-context/1', paired_cases=len(rows), cases=rows,
                camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
