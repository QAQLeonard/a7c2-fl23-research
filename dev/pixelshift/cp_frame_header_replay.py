"""Native selected-mode -> manager notification -> allocated frame header.

The existing native TRINITY dispatch, snapshot, eligibility and mode selection
supply the configuration in the same RAM. Original manager mapping executes
until its asynchronous notification, which is not dispatched. A separately
invoked original reset/capture-ID slice and the original image constructor then
reach and execute the actual frame-population prefix. Stop before the original
configuration-dependent image helper; no return value is fabricated. Optional
--continue-header executes the complete original helper/header and notification.
--queued-clear adds actual queued group-end and AP-built runtime-mode clearing.
Registered actor bindings/configuration banks remain fixtures in both variants;
neither the rest of frame population nor saved-OFF writes execute.

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


def replay(directory, *, initial_ordinal=0, dirty=0x6b, debug_count=0, source_count=4,
           continue_header=False, queue_start=0, bank_gate=0, aux_flag=0, clear_after_header=False,
           disable_runtime_mode=False, initialize_population=False, native_count_inputs=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    image = p['image']
    native_count_prefix=None
    count_evidence=None
    capture_mode=2
    if native_count_inputs is not None:
        from cp_capture_count_replay import produce
        native_count_prefix=produce(directory,**native_count_inputs)
        source_count=struct.unpack_from('<I',native_count_prefix,12)[0]
        capture_mode=native_count_prefix[8]
        if capture_mode!=23:
            raise ValueError('This group-header experiment requires an original Pixel Shift mode prefix')

    def continue_frame(cpu, snapshot, capture):
        live = snapshot['root']+8
        selected = struct.unpack('<I', cpu.mem_read(live+0x158, 4))[0]
        if selected != 23 or struct.unpack('<I', cpu.mem_read(live+0x1a0, 4))[0] != 1:
            raise ValueError('Expected the prior original mode selection and TRINITY snapshot')
        cpu, _, initial = prepare_registered_pool(directory, cpu=cpu, dirty=dirty,
            free_count=3 if continue_header else 2, reserved_count=int(continue_header))
        kernel, base, stride = initial['kernel'], initial['base'], initial['stride']
        stack, finish = 0x3001f000, 0x3001e000
        extension = None
        population_initialization = None
        regions = list(p['regions'])
        if continue_header:
            from cp_frame_extensions import prepare
            from cp_shared_group_lifecycle_replay import profile as shared_profile
            extension = prepare(cpu, directory, kernel, queue_start=queue_start, bank_gate=bank_gate, aux_flag=aux_flag)
            shared = shared_profile(directory)[1]
            regions += extension['profile']['regions']+shared['regions']
            for index in range(initial['total']):
                cpu.mem_write(base+index*stride+0x52d8, b'\0')
            if initialize_population:
                from cp_population_init_replay import initialize
                population_initialization = initialize(cpu, directory, dirty=dirty)

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
        sent, received, callback_count, receiver = [], [], 0, None
        header_entry = None
        end_entries, clear_verified = 0, False

        def hook(uc, at, n, unused):
            nonlocal mapper_entries, header_entries, allocations, callback_count, receiver, header_entry, end_entries
            if at == p['notification'] and not continue_header:
                raise ValueError('Asynchronous manager notification is outside this replay')
            if at == p['image_helper'] and not continue_header:
                raise ValueError('Configuration-dependent image helper is outside this prefix')
            if at in image['mutex']['waits'] or at in image['locks']['waits']:
                raise ValueError('Native uncontended frame-header setup reached an OS wait')
            if extension:
                ep = extension['profile']
                c, q = ep['actor']['completion'], ep['actor']['queue']
                if at == q['send']:
                    length = uc.reg_read(arm.UC_ARM_REG_R2)
                    if uc.reg_read(arm.UC_ARM_REG_R0) != q['ident'] or length != 28:
                        raise ValueError('Manager notification used a different queue or record size')
                    sent.append(bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), length)))
                if at == q['receive']:
                    receiver = uc.reg_read(arm.UC_ARM_REG_R1)
                if at == c['worker']+0x32:
                    length = uc.reg_read(arm.UC_ARM_REG_R0)
                    if length != 28 or receiver is None:
                        raise ValueError('Notification worker did not receive its complete original message')
                    received.append(bytes(uc.mem_read(receiver, length)))
                if at == ep['callback']:
                    callback_count += 1
                if at == ep['clear']['group']['end']:
                    end_entries += 1
                    if phase != 'clear-worker' or uc.reg_read(arm.UC_ARM_REG_LR) & ~1 != c['worker']+0x76:
                        raise ValueError('Native group end did not come from the queued worker')
                if phase in ('notification-worker', 'clear-worker') and at == c['worker']+0x76:
                    uc.emu_stop()
                    return
            if not any(lo <= at and at+n <= hi for lo, hi in regions):
                raise ValueError('Native frame header reached an unresolved dependency: '+hex(at))
            mapper_entries += int(at == p['mapper'])
            header_entries += int(at == p['header'])
            if at == p['header']:
                header_entry = (uc.reg_read(arm.UC_ARM_REG_SP), [uc.reg_read(r) for r in protected])
            allocations += int(at == image['allocate'])
            if at in p['reset_aux']:
                resets.append(at)

        writes = []

        def write_hook(uc, access, at, n, value, unused):
            allowed = kernel['writes']+[(kernel['lock']['object'], 12), (kernel['core']+0x10, 4),
                (image['primary'], 24), (base, stride*initial['total']), (stack-4096, 4096),
                (p['manager_id'], 0x70), (p['reset_state'], 16)]
            if extension:
                allowed += extension['writes']+[(0x3100e000, 0x1000), (0x3001c000, 0x1000)]
            if not any(lo <= at and at+n <= lo+size for lo, size in allowed):
                raise ValueError('Native manager/frame prefix changed unrelated state: '+hex(at))
            writes.append((phase, at, n, value))

        ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        try:
            if extension:
                c = extension['profile']['actor']['completion']
                phase = 'notification-actor-init'
                cpu.reg_write(arm.UC_ARM_REG_SP, stack)
                cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
                cpu.emu_start(c['initialize'] | 1, finish, count=1000)
                if cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack:
                    raise ValueError('Native notification actor initializer did not return')
            phase = 'manager'
            cpu.reg_write(arm.UC_ARM_REG_R0, live+0x20)
            cpu.reg_write(arm.UC_ARM_REG_R1, 0)
            cpu.reg_write(arm.UC_ARM_REG_R2, 0)
            cpu.reg_write(arm.UC_ARM_REG_SP, stack)
            cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(p['mapper'] | 1, finish if continue_header else p['notification'], count=30000)
            expected_mode, expected_count, expected_limit = (1, debug_count >> 4, 0) if debug_count else (23, source_count, 1)
            mode, count, limit = (struct.unpack('<I', cpu.mem_read(p['mode'], 4))[0],
                struct.unpack('<I', cpu.mem_read(p['count'], 4))[0], cpu.mem_read(p['limit'], 1)[0])
            if (cpu.reg_read(arm.UC_ARM_REG_PC) != (finish if continue_header else p['notification'])
                    or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                    or (mode, count, limit) != (expected_mode, expected_count, expected_limit)):
                raise ValueError('Native mapper differs: mode/count/limit='+str((mode, count, limit))+
                    ', PC/SP='+str(tuple(hex(cpu.reg_read(r)) for r in (arm.UC_ARM_REG_PC, arm.UC_ARM_REG_SP))))
            if extension:
                ep = extension['profile']
                c = ep['actor']['completion']
                phase = 'notification-worker'
                cpu.reg_write(arm.UC_ARM_REG_R0, c['manager'])
                cpu.reg_write(arm.UC_ARM_REG_SP, 0x3100f000)
                cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
                cpu.emu_start(c['worker'] | 1, finish, count=30000)
                queue_words = struct.unpack('<10I', cpu.mem_read(extension['queue']['root'], 40))
                expected_message = struct.pack('<7I', ep['notification_invoker'] | 1, 0,
                    ep['callback'] | 1, 0, 0, 0, 0)
                if (cpu.reg_read(arm.UC_ARM_REG_PC) != c['worker']+0x76
                        or sent != received or sent != [expected_message] or callback_count != 1
                        or queue_words[6:] != (128, (queue_start+32)%128, (queue_start+32)%128, 0)
                        or struct.unpack('<2I', cpu.mem_read(ep['target']+0x14, 8)) != (1, 0)):
                    raise ValueError('Native notification did not initialize its target and empty its queue')
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
            if not continue_header or initial_ordinal:
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
            stop = image['populate']+16 if continue_header else p['prefix_end']
            cpu.emu_start(image['construct'] | 1, stop, count=80000)
            if cpu.reg_read(arm.UC_ARM_REG_PC) != stop:
                raise ValueError('Native constructor/population missed the exact helper boundary')
            if continue_header and header_entry != (cpu.reg_read(arm.UC_ARM_REG_SP), [cpu.reg_read(r) for r in protected]):
                raise ValueError('Complete native frame header did not restore its caller stack/registers')
            if clear_after_header:
                if extension is None:
                    raise ValueError('Queued group clear requires the complete native frame header')
                ep, g = extension['profile'], shared['group']
                c = ep['actor']['completion']
                group = struct.unpack('<I', cpu.mem_read(base+0x5aa0, 4))[0]
                group_before = bytes(cpu.mem_read(group, stride))
                if struct.unpack_from('<I', group_before, 4)[0] != 2:
                    raise ValueError('Expected both native frame and retained references before queued end')
                phase = 'clear-handler'
                cpu.reg_write(arm.UC_ARM_REG_SP, 0x3001d000)
                cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
                cpu.emu_start(ep['clear']['handler'] | 1, finish, count=30000)
                if cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_R0) != 1:
                    raise ValueError('Original clear handler did not return after native enqueue')
                phase = 'clear-worker'
                cpu.reg_write(arm.UC_ARM_REG_R0, c['manager'])
                cpu.reg_write(arm.UC_ARM_REG_SP, 0x3100f000)
                cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
                cpu.emu_start(c['worker'] | 1, finish, count=30000)
                expected_group = bytearray(group_before)
                struct.pack_into('<I', expected_group, 4, 1)
                expected_clear = struct.pack('<7I', ep['clear']['invoker'] | 1, 0, g['end'] | 1, 0, 0, 0, 0)
                words = struct.unpack('<10I', cpu.mem_read(extension['queue']['root'], 40))
                if (cpu.reg_read(arm.UC_ARM_REG_PC) != c['worker']+0x76 or end_entries != 1
                        or sent != received or sent[1:] != [expected_clear]
                        or bytes(cpu.mem_read(group, stride)) != bytes(expected_group)
                        or struct.unpack('<I', cpu.mem_read(g['group'], 4))[0] != 0
                        or cpu.mem_read(g['ended'], 1)[0] != 1
                        or cpu.mem_read(g['ordinal'], 1)[0] != 0
                        or struct.unpack('<I', cpu.mem_read(g['mode'], 4))[0] != 1
                        or words[6:] != (128, (queue_start+64)%128, (queue_start+64)%128, 0)):
                    raise ValueError('Queued end freed an active frame reference or changed its mode/data/queue')
                clear_verified = True
            if disable_runtime_mode:
                if not clear_verified:
                    raise ValueError('This runtime-disable experiment follows a verified queued group end')
                from trinity_replay import configure
                packet = bytes.fromhex(configure(directory, mode=0)['packet'])
                if len(packet) != 12 or struct.unpack_from('<H', packet, 2)[0] != 0x40ee:
                    raise ValueError('Original AP builder did not produce the expected mode command')
                # Explicit transport fixture, unchanged AP-generated bytes.
                # This is not a real AP/CP connection or a saved-setting write.
                address = 0x31005000
                cpu.hook_del(wh)
                cpu.mem_write(address, packet)
                wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
                phase = 'runtime-mode-clear'
                cpu.reg_write(arm.UC_ARM_REG_R0, address)
                cpu.reg_write(arm.UC_ARM_REG_R1, 0x80020002)
                cpu.reg_write(arm.UC_ARM_REG_SP, 0x3001d000)
                cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
                cpu.emu_start(extension['profile']['dispatch']['dispatcher'] | 1, finish, count=30000)
                if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish
                        or bytes(cpu.mem_read(shared['group']['mode'], 4)) != bytes(4)):
                    raise ValueError('Original AP-built clear did not disable the native CP source mode')
        finally:
            cpu.hook_del(ch)
            cpu.hook_del(wh)
        actual = [struct.unpack('<I', cpu.mem_read(base+offset, 4))[0] for offset in (0x208, 0x20c, 0x210, 0x5c04, 0x5c08)]
        expected_secondary = 0
        if (actual != [initial_ordinal, expected_secondary, mode, capture_id, count]
                or mapper_entries != 1 or header_entries != 1 or allocations != (2 if continue_header else 1)
                or cpu.mem_read(base+0x5c0c, 1)[0] != limit
                or cpu.mem_read(base+0xbca, 1)[0] != 1
                or bytes(cpu.mem_read(snapshot['root'], 0xe00)) != before_live):
            raise ValueError('Native frame prefix lost upstream count/mode/ordinal/ID or changed its snapshot')
        native_ordinal = struct.unpack('<I', cpu.mem_read(p['ordinal'], 4))[0]
        if native_ordinal != initial_ordinal+int(initial_ordinal < count):
            raise ValueError('Original per-frame counter did not advance/saturate as expected')
        group_count, helper_result = None, None
        if continue_header:
            group = struct.unpack('<I', cpu.mem_read(base+0x5aa0, 4))[0]
            group_count = struct.unpack('<I', cpu.mem_read(group+4, 4))[0]
            helper_result = cpu.mem_read(base+0x9b0, 1)[0]
            if (group != base+stride or group_count != (1 if clear_verified else 2)
                    or struct.unpack('<I', cpu.mem_read(image['primary']+8, 4))[0] != 1
                    or helper_result != (aux_flag if bank_gate else int(initial_ordinal == 0))):
                raise ValueError('Native group/helper differs: '+str((hex(group), group_count, helper_result,
                    dirty, bank_gate, aux_flag, source_count)))
        return dict(native_selected_mode=selected, native_mapped_mode=mode, native_group_count=count,
            native_frame_ordinal=actual[0], native_secondary_ordinal=actual[1], native_next_ordinal=native_ordinal,
            native_limit=limit, native_activity_flag=1, native_pool_allocations=allocations,
            native_frame_population_prefix_entries=header_entries, native_counter_reset_returned=True,
            capture_id_from_original_store=True, native_snapshot_preserved=True,
            selected_mode_and_count_assigned_by_host=False, frame_fields_assigned_by_host=False,
            api_returns_assigned_by_host=False, all_stages_share_one_ram=True,
            boundary='after_original_frame_header' if continue_header else 'before_configuration_dependent_image_helper',
            asynchronous_manager_notification_executed=continue_header, manager_mapper_returned=continue_header,
            complete_population_executed=False, shared_group_creation_reached=continue_header,
            complete_frame_header_returned=continue_header,
            notification_actor_binding_and_configuration_banks_are_fixtures=continue_header,
            native_notification_callbacks=callback_count,
            native_population_initialization=population_initialization,
            first_ordinal_produced_by_native_reset=continue_header and initial_ordinal == 0,
            native_shared_group_reference_count=group_count, native_image_helper_result=helper_result,
            queued_group_end_executed=clear_verified, native_group_end_invocations=end_entries,
            active_frame_reference_preserved_after_group_end=clear_verified,
            group_end_disables_persistent_experiment=False,
            native_runtime_mode_clear_executed=disable_runtime_mode,
            saved_off_setting_executed=False, ap_cp_hardware_transport_executed=False,
            continuous_capture_callback_executed=False, source_os_pool_and_prior_counters_are_fixtures=True,
            upstream_group_count_is_fixture=True,
            stage_handoffs_are_harness_driven=True, sensor_settling_or_exposure_executed=False,
            camera_io=False, installable=False)

    def initialize_count(cpu, snapshot, dispatch, source):
        nonlocal count_evidence
        # The independent upstream capture configuration count, before native
        # snapshot copy. This is not inferred from the selected TRINITY mode.
        if native_count_prefix is None:
            cpu.mem_write(source+0x120, struct.pack('<I', source_count))
        else:
            from cp_capture_count_replay import publish,profile as count_profile
            if count_profile(directory)[2]['cp_source']!=source:
                raise ValueError('Native capture-count storage and snapshot use different source objects')
            count_evidence=publish(cpu,directory,native_count_prefix)

    result = capture_replay(directory, trinity=1, pipeline=1, capture_mode=capture_mode, native_context=True,
        guard_actions=('exit',),
        pipeline_source=dict(gpio_bit=1, capture_mode=2), continuation=continue_frame,
        source_initializer=initialize_count)
    if count_evidence is not None:
        result['native_capture_count_production']=count_evidence
        result['native_continuation']['upstream_group_count_is_fixture']=False
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


def compare_continued(c2, reference):
    rows = []
    for dirty in (0, 0x6b):
        for queue_start in (0, 112):
            for bank_gate in (0, 1):
                for aux_flag in (0, 1):
                    for count in (2, 4):
                        values = dict(continue_header=True, dirty=dirty, queue_start=queue_start,
                            bank_gate=bank_gate, aux_flag=aux_flag, source_count=count)
                        a, b = replay(c2, **values), replay(reference, **values)
                        if a != b:
                            raise ValueError('Native C2/CR notification and complete frame-header propagation differ')
                        rows.append(dict(input=values, target=a, reference=b))
    return dict(schema='a7c2-native-complete-frame-header/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def compare_queued_clear(c2, reference):
    rows = []
    for dirty in (0, 0x6b):
        for queue_start in (0, 112):
            for aux_flag in (0, 1):
                for disable in (False, True):
                    values = dict(continue_header=True, clear_after_header=True, dirty=dirty,
                        queue_start=queue_start, bank_gate=1, aux_flag=aux_flag, disable_runtime_mode=disable)
                    a, b = replay(c2, **values), replay(reference, **values)
                    if a != b:
                        raise ValueError('Native C2/CR frame-header/queued-end/runtime-mode-clear differs')
                    rows.append(dict(input=values, target=a, reference=b))
    return dict(schema='a7c2-native-frame-header-queued-clear/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def compare_initialized(c2, reference):
    rows = []
    for dirty in (0, 0x6b):
        for queue_start in (0, 112):
            for clear in (False, True):
                values = dict(continue_header=True, initialize_population=True, dirty=dirty,
                    queue_start=queue_start, clear_after_header=clear, disable_runtime_mode=clear)
                x, y = replay(c2, **values), replay(reference, **values)
                if x != y:
                    raise ValueError('C2/CR initialized population/header/clear chain differs')
                rows.append(dict(input=values, target=x, reference=y))
    return dict(schema='a7c2-native-initialized-frame-header/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--continue-header', action='store_true',
        help='Execute original notification and complete header on explicit actor/configuration fixtures')
    parser.add_argument('--queued-clear', action='store_true',
        help='Follow complete header with native queued group-end and optional runtime-mode clear')
    parser.add_argument('--initialize-population', action='store_true',
        help='Execute original context/default-interface/libc-lock initialization before complete header')
    args = parser.parse_args()
    runner = (compare_initialized if args.initialize_population else compare_queued_clear if args.queued_clear
              else compare_continued if args.continue_header else compare)
    result = runner(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({key: result[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
