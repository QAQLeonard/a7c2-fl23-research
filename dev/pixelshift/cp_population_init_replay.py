"""Original imaging-context publication, default interface and libc lock init.

The previously bound native capture context supplies both complete record
publishers. The default virtual object comes from original ROM and its actual
initializer; lock type/ready/owner fields come from the original startup entry.
Backing, leaf parameters, CPU state and stage handoffs remain fixtures. No
capture, positioning, saved-setting write, physical boot or camera I/O.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_capture_gate_replay import replay as capture_replay, profile as capture_profile
from cp_image_parameter_replay import profile as image_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, image = image_profile(directory)
    _, _, gate = capture_profile(directory)
    thumb, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)
    target = image['populate'] != 0xb0c242

    def code(at, size, decoder=thumb):
        return list(decoder.disasm(data[at-0x108000:at-0x108000+size], at))

    def call(at, decoder=thumb):
        rows = code(at, 4, decoder)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w', 'b'):
            raise ValueError('Original population-init call differs: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, length, register, decoder=thumb):
        vals = [v for r, v in literals(code(at, length, decoder)) if r == register]
        if len(vals) != 1:
            raise ValueError('Population-init native binding is not unique')
        return vals[0]

    candidates, start = [], 0
    while True:
        offset = data.find(bytes.fromhex('80b56f460146'), start)
        if offset < 0:
            break
        start = offset+2
        rows = code(offset+0x108000, 22)
        if (len(rows) >= 8 and [i.mnemonic for i in rows[:8]] ==
                ['push', 'mov', 'mov', 'movw', 'movs', 'movt', 'blx', 'pop']
                and rows[4].op_str == 'r2, #0xc8'):
            candidates.append(offset+0x108000)
    if len(candidates) != 1:
        raise ValueError('Original 200-byte context publisher is not unique')
    first = candidates[0]
    second = first+0x16
    p = dict(getter=gate['context_getter'], context=gate['context'], first=first, second=second,
        primary=literal(first+6, 10, 'r0'), secondary=literal(second+6, 14, 'r4'),
        copy=call(first+0x10), derive=call(second+0x82))
    if call(second+0x14) != p['copy'] or p['secondary'] != p['primary']+200:
        raise ValueError('Original paired publishers do not share their source record contract')
    p['product'] = literal(p['derive']+8, 0x18, 'r3')

    metadata = call(image['populate']+0xbe)
    if code(metadata+10, 2)[0].op_str != 'r4, r1':
        raise ValueError('Original population metadata helper changed its context binding')
    p['virtual_getter'] = call(metadata+0xee)
    p['interface'] = literal(p['virtual_getter'], 8, 'r0')
    p['virtual_method'] = call(p['virtual_getter']+8)
    flag = p['interface']+8
    def move_immediate(value, opcode):
        # Thumb MOVW/MOVT R0 encoding, used only to locate source instructions.
        return struct.pack('<HH', opcode | ((value >> 12) & 15) | (((value >> 11) & 1) << 10),
                           (((value >> 8) & 7) << 12) | (value & 255))
    pattern = move_immediate(flag & 0xffff, 0xf240)+move_immediate(flag >> 16, 0xf2c0)
    locations, start = [], 0
    while True:
        offset = data.find(pattern, start)
        if offset < 0:
            break
        start = offset+2
        rows = code(offset+0x108000, 0x2a)
        if len(rows) > 5 and [i.mnemonic for i in rows[:5]] == ['movw', 'movt', 'ldrb', 'lsls', 'bne']:
            locations.append(offset+0x108000)
    if len(locations) != 1:
        raise ValueError('Native default-interface initializer is not unique')
    p['interface_init'] = locations[0]
    p['default_object'] = literal(p['interface_init']+0xe, 0x14, 'r3')

    def word(at):
        return struct.unpack_from('<I', data, at-0x108000)[0]

    vtable = word(p['default_object'])
    name_address = word(word(vtable-4)+4)
    p['default_type'] = data[name_address-0x108000:name_address-0x108000+200].split(b'\0', 1)[0].decode('ascii')
    if p['default_type'] != 'N6Camera2LC20CaptureSequence_NoneE':
        raise ValueError('Default object is not the original inspected None implementation')
    p['default_method'] = word(vtable+0x80) & ~1
    p['lock_init'] = 0x61ddd0-(0x218 if target else 0)
    p['lock'] = literal(p['lock_init']+0x14, 8, 'r0')
    p['lock_constructor'] = call(p['lock_init']+0x1c)
    p['lock_attrs'] = [call(p['lock_init']+offset) for offset in (6, 0xe)]
    p['lock_inner_init'] = call(p['lock_constructor']+0x30, arm)
    p['lock_acquire'] = call(p['lock_init']+0x38)
    p['lock_release'] = call(p['lock_init']+0x64)
    if p['lock_acquire'] != p['lock_constructor']+0x44:
        raise ValueError('Original lock startup and its actual client use different object protocols')

    # The derived-state publisher is leaf code with conditional return blocks.
    pending, seen = [p['derive']], {}
    while pending:
        at = pending.pop()
        if at in seen:
            continue
        if not p['derive'] <= at < p['derive']+0x300 or len(seen) > 250:
            raise ValueError('Derived configuration publisher leaves its inspected leaf body')
        rows = code(at, 4)
        if not rows:
            raise ValueError('Derived configuration publisher has undecoded code')
        row = rows[0]
        seen[at] = row
        if row.mnemonic in ('bl', 'blx'):
            raise ValueError('Derived configuration publisher gained an external call')
        if row.mnemonic == 'bx' or row.mnemonic == 'pop' and 'pc' in row.op_str:
            continue
        if row.mnemonic.startswith('b') and row.op_str.startswith('#'):
            pending.append(int(row.op_str[1:], 0))
            if row.mnemonic in ('b', 'b.w'):
                continue
        pending.append(at+row.size)
    derive_end = max(at+row.size for at, row in seen.items())
    constants = [v for _, v in literals(code(p['derive'], derive_end-p['derive']))]
    p['derived_spans'] = [(at, 4) for at in constants if 0x1100000 <= at < 0x2400000]
    p['regions'] = [(p['getter'], p['getter']+10), (first, first+22), (second, second+0x8a),
        (p['copy'], p['copy']+0x300), (p['derive'], derive_end),
        (p['interface_init'], p['interface_init']+0x2a),
        (p['virtual_getter'], p['virtual_getter']+12), (p['virtual_method'], p['virtual_method']+10),
        (p['default_method'], p['default_method']+6),
        (p['lock_init'], p['lock_init']+0x26), (p['lock_constructor'], p['lock_constructor']+0x44),
        (p['lock_acquire'], p['lock_release']+0x94),
        (p['lock_inner_init'], p['lock_inner_init']+0x1e8)]
    p['regions'] += [(at, at+size) for at, size in zip(p['lock_attrs'], (0x14, 0x38))]
    p['waits'] = [row.address for row in code(p['lock_inner_init'], 0x1e8, arm) if row.mnemonic == 'wfe']
    return data, p


def initialize(cpu, directory, *, component_a=0, component_b=0, dirty=0x6b, repeat=False):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    def map_range(at, size):
        for page in range(at & ~4095, (at+size+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)

    for at, n in [(p['primary']-4, 408), (p['interface']-4, 20), (p['lock']-4, 36)]+p['derived_spans']:
        map_range(at, n)
    cpu.mem_write(p['primary']-4, b'\xa5'*4+bytes([dirty])*400+b'\xa5'*4)
    cpu.mem_write(p['interface']-4, b'\xa5'*4+bytes(12)+b'\xa5'*4)
    cpu.mem_write(p['lock']-4, b'\xa5'*4+bytes([dirty])*28+b'\xa5'*4)
    leaf = struct.unpack('<I', cpu.mem_read(p['context']+12, 4))[0]
    cpu.mem_write(leaf+0x11c, struct.pack('<I', component_a))
    cpu.mem_write(leaf+0x124, struct.pack('<I', component_b))
    source = bytes(cpu.mem_read(p['context'], 200))
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0x00f00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    stack, finish = 0x3000f000, 0x30002000
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    saved = [cpu.reg_read(register) for register in protected]
    calls = []
    lock_pairs = 0

    def hook(uc, at, n, unused):
        if at in p['waits']:
            raise ValueError('Original uncontended initialized lock reached a wait')
        if not any(lo <= at and at+n <= hi for lo, hi in p['regions']):
            raise ValueError('Native population initialization reached an unresolved dependency: '+hex(at))
        if at in (p['first'], p['second'], p['interface_init'], p['lock_init'], p['lock_constructor']):
            calls.append(at)

    def write_hook(uc, access, at, n, value, unused):
        spans = [(p['primary'], 400), (p['interface'], 12), (p['lock'], 28),
                 (stack-4096, 4096)]+p['derived_spans']
        if not any(lo <= at and at+n <= lo+length for lo, length in spans):
            raise ValueError('Native population initialization changed unrelated state: '+hex(at))

    def run(entry, *, arm_code=False):
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry if arm_code else entry | 1, finish, count=10000)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or [cpu.reg_read(register) for register in protected] != saved):
            raise ValueError('Original initializer did not return with preserved caller state')

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        for _ in range(2 if repeat else 1):
            for publisher in (p['first'], p['second']):
                run(p['getter'])
                if cpu.reg_read(arm.UC_ARM_REG_R0) != p['context']:
                    raise ValueError('Original context getter returned another record')
                run(publisher)
            run(p['interface_init'])
            run(p['virtual_getter'])
            if cpu.reg_read(arm.UC_ARM_REG_R0) != 0xffff:
                raise ValueError('Original default virtual method did not return its native sentinel')
            run(p['lock_init'])
            if cpu.reg_read(arm.UC_ARM_REG_R0) != 0:
                raise ValueError('Original libc lock startup failed')
            expected_lock = struct.pack('<7I', 0x33330003, 1, 0xff, 0, 0, 0, 0)
            if bytes(cpu.mem_read(p['lock'], 28)) != expected_lock:
                raise ValueError('Original constructor did not initialize its complete lock record')
            irq_before = cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80
            cpu.reg_write(arm.UC_ARM_REG_R0, p['lock'])
            run(p['lock_acquire'], arm_code=True)
            if (cpu.reg_read(arm.UC_ARM_REG_R0) != 0
                    or struct.unpack('<2I', cpu.mem_read(p['lock']+8, 8)) != (0, 1)):
                raise ValueError('Original constructed lock did not acquire natively')
            cpu.reg_write(arm.UC_ARM_REG_R0, p['lock'])
            run(p['lock_release'], arm_code=True)
            if (cpu.reg_read(arm.UC_ARM_REG_R0) != 0
                    or struct.unpack('<2I', cpu.mem_read(p['lock']+8, 8)) != (0xff, 0)
                    or cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80 != irq_before):
                raise ValueError('Original constructed lock did not release and restore its IRQ state')
            lock_pairs += 1
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    product = struct.unpack('<I', cpu.mem_read(p['product'], 4))[0]
    expected_product = (component_a*component_b) & 0xffffffff or 1
    if (bytes(cpu.mem_read(p['primary'], 200)) != source
            or bytes(cpu.mem_read(p['secondary'], 200)) != source
            or bytes(cpu.mem_read(p['context'], 200)) != source
            or product != expected_product
            or struct.unpack('<3I', cpu.mem_read(p['interface'], 12)) != (p['default_object'], 0, 1)):
        raise ValueError('Native initialization copy/derived value/default object/lock differs')
    for at in (p['primary']-4, p['primary']+400, p['interface']-4, p['interface']+12, p['lock']-4, p['lock']+28):
        if bytes(cpu.mem_read(at, 4)) != b'\xa5'*4:
            raise ValueError('Native population initialization changed a neighboring canary')
    return dict(native_context_bytes=200, native_derived_product_or_one=product,
        native_default_type=p['default_type'], native_default_method_return=0xffff,
        native_initializer_entries=len(calls), native_lock_words=[0x33330003, 1, 0xff, 0, 0, 0, 0],
        native_libc_lock_acquire_release_pairs=lock_pairs, native_irq_state_restored=True,
        native_source_and_neighbors_preserved=True, native_caller_state_preserved=True,
        host_assigned_context_pointers_or_lock_magic=False, api_results_replaced=False,
        cpu_backing_leaf_inputs_and_stage_handoffs_are_fixtures=True,
        full_frame_population_executed=False, four_frame_scheduler_executed=False,
        positioning_or_exposure_executed=False, saved_off_setting_executed=False,
        camera_io=False, installable=False)


def replay(directory, *, component_a=0, component_b=0, dirty=0x6b, repeat=False):
    def continuation(cpu, snapshot, gate):
        return initialize(cpu, directory, component_a=component_a, component_b=component_b,
                          dirty=dirty, repeat=repeat)
    return capture_replay(directory, trinity=1, pipeline=1, capture_mode=2, native_context=True,
        guard_actions=('exit',), pipeline_source=dict(gpio_bit=1, capture_mode=2), continuation=continuation)


def compare(c2, reference):
    rows = []
    for a in (0, 100):
        for b in (0, 64):
            for dirty in (0, 0x6b):
                for repeat in (False, True):
                    values = dict(component_a=a, component_b=b, dirty=dirty, repeat=repeat)
                    x, y = replay(c2, **values), replay(reference, **values)
                    if x != y:
                        raise ValueError('C2/CR original population initialization contracts differ')
                    rows.append(dict(input=values, target=x, reference=y))
    return dict(schema='a7c2-native-population-initialization/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({key: result[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
