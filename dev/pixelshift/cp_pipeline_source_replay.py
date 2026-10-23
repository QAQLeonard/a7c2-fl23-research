"""Generate the shared capture condition before native snapshot/selection.

A complete original state producer and GPIO reader run on independent fixture
inputs. Original configuration slices publish its source byte and adjacent
policy field into the native-bound pipeline object. No calculated source
condition, pipeline flag, API result or hardware acknowledgement is supplied;
prior flag/policy words are explicit retained-state fixtures.
Only producer branch 3 is covered. GPIO address/pin selection, register words,
configuration bytes, prior state and stage/register bindings remain fixtures.
This is neither an actual GPIO mapping nor physical positioning evidence.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    delta = -0x218 if model == 'ILCE-7CM2' else 0
    p = dict(producer=0x8aecc6+delta, producer_end=0x8af45a+delta,
             caller=0x8c7904+delta, wrapper=0x8c7266+delta,
             argument_slice=0x8c797e+delta, argument_end=0x8c7998+delta,
             copy=0x8a1f82+delta, copy_end=0x8a1fac+delta,
             policy=0x8a24ba+delta, policy_end=0x8a2542+delta)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at-0x108000:at-0x108000+size], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'b.w'):
            raise ValueError('Original pipeline-source call changed: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Native pipeline-source object is not unique')
        return values[0]

    p['source_getter'] = call(p['caller']+0x3e)
    p['source'] = literal(p['source_getter'], 10, 'r0')
    p['liro_getter'] = call(p['caller']+0x38)
    p['liro'] = literal(p['liro_getter'], 10, 'r0')
    p['mirror_getter'] = call(p['producer']+0x770)
    p['mirror'] = literal(p['mirror_getter'], 10, 'r0')
    # The original wrapper passes its R1 unchanged to the caller. The caller's
    # real stack stores pass that pointer as argument 12 and the actual source
    # getter's value as argument 8; this is not an equal-offset inference.
    generator = call(p['caller']+0x174)
    source_store = code(p['caller']+0x162, 4)
    target_store = code(p['caller']+0x16c, 4)
    if (call(p['wrapper']+0x18) != p['caller']
            or source_store[0].op_str != 'r2, r8, [sp, #8]'
            or target_store[0].op_str != 'r4, sb, [sp, #0x18]'
            or not any(i.op_str == 'sb, [r7, #0x24]' for i in code(generator, 0x2c))
            or code(p['copy'], 2)[0].op_str != 'r1, [r5]'
            or not any(i.op_str == 'r1, [sb, #0x102]' for i in code(p['copy'], 0x2a))):
        raise ValueError('Original caller no longer binds the inspected source/pipeline arguments')
    p['leaf'] = call(p['producer']+0x9a)
    p['port_getter'] = call(p['leaf']+0x16)
    p['pin_getter'] = call(p['leaf']+0x1c)
    p['port'] = literal(p['port_getter'], 12, 'r0')
    p['pin'] = literal(p['pin_getter'], 12, 'r0')
    p['gpio_read'] = call(p['leaf']+0x24)
    p['control_read'] = call(p['gpio_read']+0x10)
    p['output_read'] = call(p['gpio_read']+0x1e)
    p['input_read'] = call(p['gpio_read']+0x2e)
    p['gpio_base'] = literal(p['control_read'], 14, 'r2')
    p['mode'] = literal(p['producer']+0x40, 12, 'r0')+5
    p['flags'] = literal(p['producer']+10, 0x14, 'sb')
    p['polarity'] = literal(p['leaf'], 0x10, 'r0')+12
    p['policy_mirror_getter'] = call(generator+0x18)
    p['policy_mirror'] = literal(p['policy_mirror_getter'], 10, 'r0')
    p['guard_getter'] = call(p['argument_slice'])
    # Confirm that the real outer caller uses this model's original root and
    # context, then passes root+2950 through the wrapper to the generator.
    from cp_capture_context_replay import profile as context_profile
    _, context = context_profile(directory)
    target = model == 'ILCE-7CM2'
    root_at, add_at, outer = ((0x4dcd20, 0x4dd09e, 0x4dd0c8) if target else
                              (0x4dcf3c, 0x4dd2ba, 0x4dd2e4))
    if (literal(root_at, 12, 'fp') != context['root']
            or [i.op_str for i in code(add_at, 8)] != ['r0, #0x2950', 'r4, fp, r0']
            or code(outer+4, 2)[0].op_str != 'r1, r4'
            or call(call(outer+10)) != p['wrapper']):
        raise ValueError('Actual outer caller no longer publishes to the native-bound pipeline object')
    p['outer_context'] = literal(outer, 10, 'r0')
    p['regions'] = [(p['producer'], p['producer_end']), (p['leaf'], p['leaf']+0x2c),
                    (p['gpio_read'], p['gpio_read']+0x32),
                    (p['control_read'], p['control_read']+0x14),
                    (p['input_read'], p['input_read']+0x1a),
                    (p['output_read'], p['output_read']+0x1a),
                    (p['argument_slice'], p['argument_end']),
                    (p['copy'], p['copy_end']), (p['policy'], p['policy_end'])]
    p['regions'] += [(p[key], p[key]+12) for key in
        ('source_getter', 'liro_getter', 'port_getter', 'pin_getter', 'mirror_getter',
         'policy_mirror_getter', 'guard_getter')]
    return data, p


def publish(cpu, directory, capture, pipeline, *, gpio_bit=1, gpio_output=False,
            polarity=1, enabled=1, retained=0, inhibit_input=0, special=False,
            policy_enable=1, policy_input=1, policy_prior=0, capture_mode=2):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
    import unicorn.arm_const as arm
    _, p = profile(directory)
    if p['outer_context'] != capture['context']:
        raise ValueError('Actual pipeline producer and capture gate use different contexts')
    stack, finish, port, pin = 0x3000e000, 0x3000d000, 1, 2
    gpio = p['gpio_base']+0x1000*port
    ranges = [(p['source']-4, p['source']+0x184), (p['liro'], p['liro']+0xd64),
              (p['mirror']+0x7b9, p['mirror']+0x7c4), (p['policy_mirror']+0x717, p['policy_mirror']+0x720),
              (p['port'], p['port']+1), (p['pin'], p['pin']+1),
              (p['flags'], p['flags']+0x1d), (p['mode'], p['mode']+1),
              (p['polarity'], p['polarity']+1), (gpio, gpio+0x44)]
    for begin, end in ranges:
        for page in range(begin & ~4095, (end+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    cpu.mem_write(p['source']-4, b'\xa5'*0x188)
    initial = bytearray(b'\x6b'*0x180)
    for offset, value in {0: 0, 1: 0x13, 2: retained, 3: 0x19, 0xc1: 0,
            0xd2: 1, 0xd5: enabled, 0xe8: 0x27, 0xeb: 1, 0xec: 2 if special else policy_enable,
            0xf8: 0, 0xfb: 255, 0x100: 1, 0x102: policy_input, 0x103: 0}.items():
        initial[offset] = value
    cpu.mem_write(p['source'], bytes(initial))
    cpu.mem_write(p['liro']+0xd60, bytes([inhibit_input]))
    cpu.mem_write(p['flags'], b'\0')
    cpu.mem_write(p['flags']+0x1c, bytes([int(special)]))
    cpu.mem_write(p['mode'], b'\3')  # Only this original producer branch is covered.
    cpu.mem_write(p['polarity'], bytes([polarity]))
    cpu.mem_write(p['port'], bytes([port]))
    cpu.mem_write(p['pin'], bytes([pin]))
    cpu.mem_write(gpio, struct.pack('<I', int(gpio_output) << pin))
    cpu.mem_write(gpio+0x10, struct.pack('<I', (1-gpio_bit if gpio_output else gpio_bit) << pin))
    cpu.mem_write(gpio+0x40, struct.pack('<I', (gpio_bit if gpio_output else 1-gpio_bit) << pin))
    cpu.mem_write(p['mirror']+0x7b9, b'\xa5'*11)
    cpu.mem_write(p['policy_mirror']+0x717, b'\xa5'*9)
    # A prior policy word is an explicit fixture. The native disabled branch
    # retains it; the harness must not normalize that behavior to zero.
    cpu.mem_write(pipeline+0x13c, struct.pack('<I', policy_prior))
    source_before = bytes(cpu.mem_read(p['source']-4, 0x188))
    phase, writes, gpio_reads, producer_returns = 'getter', [], [], 0
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    saved = [0x77550000+n for n in range(8)]

    def code_hook(uc, at, size, unused):
        nonlocal producer_returns
        if not any(lo <= at and at+size <= hi for lo, hi in p['regions']):
            raise ValueError('Native condition publication entered an unresolved dependency: '+hex(at))
        if at == p['producer_end']-2:
            producer_returns += 1

    def write_hook(uc, access, at, size, value, unused):
        if stack-4096 <= at and at+size <= stack+4:
            return
        if phase == 'argument' and at == stack+0x38 and size == 4:
            return  # Original caller saves its output pointer at this exact stack slot.
        allowed = []
        if phase == 'producer':
            allowed = [(p['source']+n, 1) for n in (0, 2, 0xc1, 0xc2, 0xd0, 0xd1, 0xd2, 0xd3, 0xd4)]
            allowed += [(p['mirror']+0x7bd, 3)]
        elif phase == 'copy':
            allowed = [(pipeline+0x100, 4), (pipeline+0xd4, 1), (pipeline+0x106, 1)]
        elif phase == 'policy':
            allowed = [(pipeline+0x137, 3), (pipeline+0x13c, 4), (p['policy_mirror']+0x71b, 1)]
        if not any(lo <= at and at+size <= lo+n for lo, n in allowed):
            raise ValueError('Native condition publication changed unrelated state: '+hex(at))
        writes.append((phase, at, size, value))

    def read_hook(uc, access, at, size, value, unused):
        if gpio <= at < gpio+0x1000:
            gpio_reads.append((at-gpio, size))

    def run(entry, end=finish, **registers):
        for register, value in registers.items():
            cpu.reg_write(getattr(arm, 'UC_ARM_REG_'+register.upper()), value)
        cpu.emu_start(entry | 1, end, count=10000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != end:
            raise ValueError('Native source stage did not reach its inspected boundary')

    ch = cpu.hook_add(UC_HOOK_CODE, code_hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    rh = cpu.hook_add(UC_HOOK_MEM_READ, read_hook)
    try:
        run(p['source_getter'], sp=stack, lr=finish | 1)
        if cpu.reg_read(arm.UC_ARM_REG_R0) != p['source']:
            raise ValueError('Native source getter differs from the verified caller binding')
        run(p['liro_getter'], lr=finish | 1)
        native_liro = cpu.reg_read(arm.UC_ARM_REG_R0)
        phase = 'argument'
        run(p['argument_slice'], p['argument_end'], r4=native_liro, sb=pipeline)
        inhibit = cpu.reg_read(arm.UC_ARM_REG_R3)
        for register, value in zip(protected, saved):
            cpu.reg_write(register, value)
        cpu.mem_write(stack, struct.pack('<I', p['source']))  # Native-identified fifth argument.
        phase = 'producer'
        run(p['producer'], r0=0x303, r1=0, r2=capture_mode, r3=inhibit, sp=stack, lr=finish | 1)
        if (cpu.reg_read(arm.UC_ARM_REG_SP) != stack or producer_returns != 1
                or [cpu.reg_read(register) for register in protected] != saved):
            raise ValueError('Complete original condition producer failed its return contract')
        native_flag = cpu.mem_read(p['source']+2, 1)[0]
        gpio_value = gpio_bit ^ int(polarity == 0)
        guard = cpu.mem_read(capture['state'], 1)[0]
        expected_inhibit = int(bool(guard and inhibit_input))
        expected_flag = int(bool(gpio_value and enabled))
        retained_branch = special or bool(expected_inhibit and expected_flag)
        if retained_branch:
            expected_flag = retained
        flag_writes = [w for w in writes if w[0] == 'producer' and w[1] == p['source']+2]
        if (inhibit != expected_inhibit or native_flag != expected_flag
                or len(flag_writes) != int(not retained_branch)
                or gpio_reads != [(0, 4), (0x40 if gpio_output else 0x10, 4)]):
            raise ValueError('Native GPIO/condition producer differs from independent fixture arithmetic')
        source_after = bytes(cpu.mem_read(p['source']-4, 0x188))
        for index, (before, after) in enumerate(zip(source_before, source_after)):
            if before != after and index-4 not in (0, 2, 0xc1, 0xc2, 0xd0, 0xd1, 0xd2, 0xd3, 0xd4):
                raise ValueError('Native producer changed an unrelated source byte')
        pipeline_before = bytes(cpu.mem_read(pipeline, 0x160))
        phase = 'copy'
        run(p['copy'], p['copy_end'], r5=p['source'], sb=pipeline)
        phase = 'getter'
        run(p['policy_mirror_getter'], lr=finish | 1)
        phase = 'policy'
        run(p['policy'], p['policy_end'], r5=p['source'], sb=pipeline,
            sl=cpu.reg_read(arm.UC_ARM_REG_R0))
        expected_policy = policy_prior if not policy_enable and not special else (
            1 if policy_input == 1 else 2 if policy_input == 0 else 0)
        actual = bytes(cpu.mem_read(pipeline, 0x160))
        if (actual[0x100:0x104] != bytes(cpu.mem_read(p['source'], 3))+b'\x27'
                or actual[0xd4] != 0x19 or actual[0x106] != 0
                or struct.unpack_from('<I', actual, 0x13c)[0] != expected_policy):
            raise ValueError('Original configuration publication differs from its source/policy')
        for n, (before, after) in enumerate(zip(pipeline_before, actual)):
            if before != after and n not in (0xd4, 0x100, 0x101, 0x102, 0x103, 0x106,
                                            0x137, 0x138, 0x139, 0x13c, 0x13d, 0x13e, 0x13f):
                raise ValueError('Original publication changed unrelated pipeline fields')
        if bytes(cpu.mem_read(p['source']-4, 0x188)) != source_after:
            raise ValueError('Configuration publication overwrote its source')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        cpu.hook_del(rh)
    return dict(native_pipeline_flag=native_flag, native_source_flag=native_flag,
                source_flag_written=bool(flag_writes), native_inhibit_argument=inhibit,
                native_policy_field=expected_policy, native_gpio_read_offsets=[x[0] for x in gpio_reads],
                source_producer_returned=True, source_and_target_binding_verified=True,
                host_assigned_computed_flag_or_api_return=False,
                gpio_inputs_and_mapping_are_fixtures=True, notification_history_is_fixture=True,
                producer_branch=3, complete_configuration_function_executed=False,
                stages_and_register_bindings_are_harness_supplied=True,
                hardware_acknowledgement_supplied=False, camera_io=False)


def compare(c2, reference):
    from cp_capture_gate_replay import replay
    rows = []
    fixtures = []
    for mode in (2, 6, 33):
        for bit in (0, 1):
            for output in (False, True):
                for polarity in (0, 1):
                    for enabled in (0, 1):
                        for guard in (0, 1):
                            fixtures.append((mode, guard, dict(gpio_bit=bit, gpio_output=output,
                                polarity=polarity, enabled=enabled, capture_mode=mode)))
    for guard in (0, 1):
        for retained in (0, 1):
            for policy_input in (0, 1, 2):
                fixtures.append((2, guard, dict(gpio_bit=1, polarity=1, enabled=1,
                    retained=retained, inhibit_input=1, policy_input=policy_input)))
                fixtures.append((2, guard, dict(gpio_bit=0, polarity=1, enabled=0,
                    retained=retained, special=True, policy_input=policy_input)))
    for policy_prior in (0, 1, 0x12345678):
        fixtures.append((2, 0, dict(policy_enable=0, policy_prior=policy_prior)))
    for mode, guard, source in fixtures:
        raw = source.get('gpio_bit', 1) ^ int(source.get('polarity', 1) == 0)
        flag = int(bool(raw and source.get('enabled', 1)))
        if source.get('special') or (guard and source.get('inhibit_input') and flag):
            flag = source.get('retained', 0)
        for override in (0, 1):
            for trinity in (0, 1):
                args = dict(trinity=trinity, capture_mode=mode, override=override,
                    pipeline=flag, native_state=guard, native_context=True,
                    guard_actions=('enter',) if guard else ('exit',), pipeline_source=source)
                a, b = replay(c2, **args), replay(reference, **args)
                if a != b:
                    raise ValueError('Native C2/CR GPIO-to-capture configuration differs')
                rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-pipeline-source/1', paired_cases=len(rows), cases=rows,
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
