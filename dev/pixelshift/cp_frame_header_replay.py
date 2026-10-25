"""Native selected-mode -> manager mapping -> allocated frame-header prefix.

The existing native TRINITY dispatch, snapshot, eligibility and mode selection
supply the configuration in the same RAM. Original manager mapping executes
until its asynchronous notification, which is not dispatched. A separately
invoked original reset/capture-ID slice and the original image constructor then
reach and execute the actual frame-population prefix. Stop before the original
configuration-dependent image helper; no return value is fabricated.

Registered memory/OS state, initial counters and stage invocations are fixtures.
This is not a continuous capture callback, complete population, exposure,
positioning, cancellation/centering or boot-safety experiment. No camera I/O.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_capture_gate_replay import replay as capture_replay
from cp_image_parameter_replay import prepare_registered_pool, profile as image_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, image = image_profile(directory)
    delta = 0 if image['populate'] == 0xb0c242 else 0x1a2
    p = dict(image=image, mapper=0xb0d7d4+delta, reset=0xb0db16+delta)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, length):
        return list(md.disasm(data[at-0x108000:at-0x108000+length], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Native frame-header call changed: '+hex(at))
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, length, register):
        values = [v for r, v in literals(code(at, length)) if r == register]
        if len(values) != 1:
            raise ValueError('Native frame-header state binding is not unique')
        return values[0]

    p['header'] = call(image['populate']+12)
    p['getter'] = call(p['header']+0x18)
    p['manager_id'] = literal(p['header']+10, 10, 'sl')
    p['ordinal'] = literal(p['header']+0x24, 0x14, 'r3')
    p['count'] = literal(p['mapper']+0x2c, 0x10, 'r1')
    p['mode'] = literal(p['mapper']+0x2c, 0x10, 'r2')
    p['limit'] = literal(p['mapper']+0x1a, 12, 'r8')
    p['debug'] = literal(p['mapper']+0x92, 12, 'r0')
    p['count_getter'] = call(p['mapper']+0x28)
    p['notification'] = call(p['mapper']+0xbc)
    p['reset_aux'] = [call(p['reset']+0x28), call(p['reset']+0x74)]
    p['reset_state'] = literal(p['reset']+0x1a, 12, 'r0')
    p['activity_getter'] = call(p['header']+0x192)
    p['activity'] = literal(p['activity_getter'], 10, 'r0')
    p['prefix_end'] = p['header']+0x1be
    p['image_helper'] = call(p['prefix_end'])
    p['id_slice'] = p['header']-0x6b8
    if (call(p['id_slice']-4) != p['reset']
            or code(p['prefix_end']-6, 6)[0].mnemonic != 'add.w'):
        raise ValueError('Original reset/ID slice or population boundary differs')
    p['regions'] = image['regions']+[
        (p['mapper'], p['mapper']+0xc0), (p['count_getter'], p['count_getter']+0xb0),
        (p['reset'], p['reset']+0xa2), (p['getter'], p['getter']+0x36),
        (p['activity_getter'], p['activity_getter']+12),
        (image['populate'], image['populate']+16),
        (p['header'], p['prefix_end']), (p['id_slice'], p['id_slice']+12)]
    p['regions'] += [(at, at+14) for at in p['reset_aux']]
    return data, p


def replay(directory, *, initial_ordinal=0, dirty=0x6b, debug_count=0, source_count=4):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    image = p['image']

    def continue_frame(cpu, snapshot, capture):
        live = snapshot['root']+8
        selected = struct.unpack('<I', cpu.mem_read(live+0x158, 4))[0]
        if selected != 23 or struct.unpack('<I', cpu.mem_read(live+0x1a0, 4))[0] != 1:
            raise ValueError('Expected the prior original mode selection and TRINITY snapshot')
        cpu, _, initial = prepare_registered_pool(directory, cpu=cpu, dirty=dirty)
        kernel, base, stride = initial['kernel'], initial['base'], initial['stride']
        stack, finish = 0x3001f000, 0x3001e000

        def map_range(at, size):
            for page in range(at & ~4095, (at+size+4095) & ~4095, 4096):
                if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                    cpu.mem_map(page, 4096)

        map_range(p['manager_id']-4, 0x80)
        map_range(p['reset_state'], 16)
        map_range(p['activity'], 4)
        # Prior manager storage/diagnostic inputs. Selected mode and output
        # count are NOT assigned here or after the original mapper runs.
        cpu.mem_write(p['manager_id']-4, bytes(0x80))
        cpu.mem_write(p['manager_id']+12, struct.pack('<I', 0x22222222))
        cpu.mem_write(p['ordinal'], struct.pack('<I', 0x11111111))
        cpu.mem_write(p['reset_state'], b'\x6b'*16)
        cpu.mem_write(p['activity'], struct.pack('<I', 7))
        cpu.mem_write(p['debug']+0x6f, bytes([debug_count]))
        cpu.mem_write(p['debug']+0xb, b'\0')
        before_live = bytes(cpu.mem_read(snapshot['root'], 0xe00))
        phase, mapper_entries, header_entries, allocations = 'manager', 0, 0, 0
        resets = []
        protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
        saved = [0x77660000+n for n in range(8)]

        def hook(uc, at, n, unused):
            nonlocal mapper_entries, header_entries, allocations
            if at == p['notification']:
                raise ValueError('Asynchronous manager notification is outside this replay')
            if at == p['image_helper']:
                raise ValueError('Configuration-dependent image helper is outside this prefix')
            if at in image['mutex']['waits'] or at in image['locks']['waits']:
                raise ValueError('Native uncontended frame-header setup reached an OS wait')
            if not any(lo <= at and at+n <= hi for lo, hi in p['regions']):
                raise ValueError('Native frame header reached an unresolved dependency: '+hex(at))
            mapper_entries += int(at == p['mapper'])
            header_entries += int(at == p['header'])
            allocations += int(at == image['allocate'])
            if at in p['reset_aux']:
                resets.append(at)

        writes = []

        def write_hook(uc, access, at, n, value, unused):
            allowed = kernel['writes']+[(kernel['lock']['object'], 12), (kernel['core']+0x10, 4),
                (image['primary'], 24), (base, stride), (stack-4096, 4096),
                (p['manager_id'], 0x70), (p['reset_state'], 16)]
            if not any(lo <= at and at+n <= lo+size for lo, size in allowed):
                raise ValueError('Native manager/frame prefix changed unrelated state: '+hex(at))
            writes.append((phase, at, n, value))

        ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        try:
            cpu.reg_write(arm.UC_ARM_REG_R0, live+0x20)
            cpu.reg_write(arm.UC_ARM_REG_R1, 0)
            cpu.reg_write(arm.UC_ARM_REG_R2, 0)
            cpu.reg_write(arm.UC_ARM_REG_SP, stack)
            cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(p['mapper'] | 1, p['notification'], count=1000)
            expected_mode, expected_count, expected_limit = (1, debug_count >> 4, 0) if debug_count else (23, source_count, 1)
            mode, count, limit = (struct.unpack('<I', cpu.mem_read(p['mode'], 4))[0],
                struct.unpack('<I', cpu.mem_read(p['count'], 4))[0], cpu.mem_read(p['limit'], 1)[0])
            if (cpu.reg_read(arm.UC_ARM_REG_PC) != p['notification']
                    or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                    or (mode, count, limit) != (expected_mode, expected_count, expected_limit)):
                raise ValueError('Native mapper differs: mode/count/limit='+str((mode, count, limit))+
                    ', PC/SP='+str(tuple(hex(cpu.reg_read(r)) for r in (arm.UC_ARM_REG_PC, arm.UC_ARM_REG_SP))))
            phase = 'reset'
            cpu.reg_write(arm.UC_ARM_REG_SP, stack)
            cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(p['reset'] | 1, finish, count=1000)
            if cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack:
                raise ValueError('Original group counter reset did not return naturally')
            if (set(resets) != set(p['reset_aux'])
                    or bytes(cpu.mem_read(p['manager_id']+12, 4)) != bytes(4)
                    or bytes(cpu.mem_read(p['ordinal'], 4)) != bytes(4)):
                raise ValueError('Original reset did not clear both nonzero prior counters through its helpers')
            # The upstream completed-frame count is an explicit input. No host
            # writes frame+208/+210/count fields or changes an API return.
            cpu.hook_del(wh)
            cpu.mem_write(p['ordinal'], struct.pack('<I', initial_ordinal))
            wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
            phase = 'capture-id'
            capture_id = struct.unpack('<I', cpu.mem_read(snapshot['root'], 4))[0]
            cpu.reg_write(arm.UC_ARM_REG_R8, capture_id)
            cpu.emu_start(p['id_slice'] | 1, p['id_slice']+12, count=10)
            phase = 'construct-and-populate'
            request, record = 0x30008000, 0x30008100
            cpu.hook_del(wh)
            cpu.mem_write(request, struct.pack('<5I', image['invoker'] | 1, 0, image['populate'] | 1, 0, 0))
            cpu.mem_write(record, bytes(20))
            wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
            for register, value in zip(protected, saved):
                cpu.reg_write(register, value)
            for register, value in ((arm.UC_ARM_REG_R0, request), (arm.UC_ARM_REG_R1, record),
                                    (arm.UC_ARM_REG_R2, 0), (arm.UC_ARM_REG_SP, stack),
                                    (arm.UC_ARM_REG_LR, finish | 1)):
                cpu.reg_write(register, value)
            cpu.emu_start(image['construct'] | 1, p['prefix_end'], count=40000)
            if cpu.reg_read(arm.UC_ARM_REG_PC) != p['prefix_end']:
                raise ValueError('Native constructor/population missed the exact helper boundary')
        finally:
            cpu.hook_del(ch)
            cpu.hook_del(wh)
        actual = [struct.unpack('<I', cpu.mem_read(base+offset, 4))[0] for offset in (0x208, 0x20c, 0x210, 0x5c04, 0x5c08)]
        expected_secondary = 0
        if (actual != [initial_ordinal, expected_secondary, mode, capture_id, count]
                or mapper_entries != 1 or header_entries != 1 or allocations != 1
                or cpu.mem_read(base+0x5c0c, 1)[0] != limit
                or cpu.mem_read(base+0xbca, 1)[0] != 1
                or bytes(cpu.mem_read(snapshot['root'], 0xe00)) != before_live):
            raise ValueError('Native frame prefix lost upstream count/mode/ordinal/ID or changed its snapshot')
        native_ordinal = struct.unpack('<I', cpu.mem_read(p['ordinal'], 4))[0]
        if native_ordinal != initial_ordinal+int(initial_ordinal < count):
            raise ValueError('Original per-frame counter did not advance/saturate as expected')
        return dict(native_selected_mode=selected, native_mapped_mode=mode, native_group_count=count,
            native_frame_ordinal=actual[0], native_secondary_ordinal=actual[1], native_next_ordinal=native_ordinal,
            native_limit=limit, native_activity_flag=1, native_pool_allocations=allocations,
            native_frame_population_prefix_entries=header_entries, native_counter_reset_returned=True,
            capture_id_from_original_store=True, native_snapshot_preserved=True,
            selected_mode_and_count_assigned_by_host=False, frame_fields_assigned_by_host=False,
            api_returns_assigned_by_host=False, all_stages_share_one_ram=True,
            boundary='before_configuration_dependent_image_helper',
            asynchronous_manager_notification_executed=False, manager_mapper_returned=False,
            complete_population_executed=False, shared_group_creation_reached=False,
            continuous_capture_callback_executed=False, source_os_pool_and_prior_counters_are_fixtures=True,
            upstream_group_count_is_fixture=True,
            stage_handoffs_are_harness_driven=True, sensor_settling_or_exposure_executed=False,
            camera_io=False, installable=False)

    def initialize_count(cpu, snapshot, dispatch, source):
        # The independent upstream capture configuration count, before native
        # snapshot copy. This is not inferred from the selected TRINITY mode.
        cpu.mem_write(source+0x120, struct.pack('<I', source_count))

    result = capture_replay(directory, trinity=1, pipeline=1, capture_mode=2, native_context=True,
        guard_actions=('exit',),
        pipeline_source=dict(gpio_bit=1, capture_mode=2), continuation=continue_frame,
        source_initializer=initialize_count)
    return result


def compare(c2, reference):
    rows = []
    for ordinal in (0, 1, 3, 4):
        for dirty in (0, 0x6b):
            for debug in (0, 0x20):
                for count in (2, 4):
                    values = dict(initial_ordinal=ordinal, dirty=dirty, debug_count=debug, source_count=count)
                    a, b = replay(c2, **values), replay(reference, **values)
                    if a != b:
                        raise ValueError('Native C2/CR mode-manager-frame prefix differs')
                    rows.append(dict(input=values, target=a, reference=b))
    return dict(schema='a7c2-native-frame-header/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({key: result[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
