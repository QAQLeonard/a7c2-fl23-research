"""Match original steady-timer callback and capture wait event, offline only.

Native callback, ARM interrupt-context detector and waiter prefix execute on
synthetic frame/OS data, stopping BEFORE RTOS event APIs. Callback and waiter
are invoked separately: no timer fires, event is delivered, wait completes,
motor settles, or exposure/centering executes. This identifies time-based
synchronization, not a position-feedback acknowledgement.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_sequence_replay import machine
from cp_serial_replay import literals
from cp_timing_replay import profile as timing_profile, request


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, timing = timing_profile(directory)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    callback = timing['callback']
    calls = [int(i.op_str.lstrip('#'), 0) for i in code(callback, 0x4a) if i.mnemonic == 'blx']
    if len(calls) != 3:
        raise ValueError('Steady callback context/event calls changed')
    context, irq_set, task_set = calls
    arm = list(Cs(CS_ARCH_ARM, CS_MODE_ARM).disasm(
        data[context - 0x108000:context - 0x108000 + 0x34], context))
    if (not any(i.mnemonic == 'mrc' and 'c0, c0, #5' in i.op_str for i in arm)
            or (arm[-1].mnemonic, arm[-1].op_str) != ('bx', 'lr')):
        raise ValueError('Original interrupt-context detector changed')
    table = [v for r, v in literals(arm) if r == 'r2']
    if len(table) != 1:
        raise ValueError('Native per-core context table not identified')
    waiter = 0xb18b0a if timing['model'] == 'ILCE-7CM2' else 0xb18968
    predicate = waiter + 0x42
    roots = [v for r, v in literals(code(predicate, 16)) if r == 'r1']
    if len(roots) != 1:
        raise ValueError('Native steady-path eligibility flag not identified')
    wait_calls = [int(i.op_str.lstrip('#'), 0) for i in code(waiter, 0x42) if i.mnemonic == 'bl']
    if len(wait_calls) != 2:
        raise ValueError('Original steady waiter layout changed')
    wait_helper, cancel_timer = wait_calls
    helper_calls = [int(i.op_str.lstrip('#'), 0) for i in code(wait_helper, 0x48) if i.mnemonic == 'blx']
    if len(helper_calls) != 3:
        raise ValueError('Original event wait helper changed')
    timed_wait = helper_calls[0]
    traces = {int(i.op_str.lstrip('#'), 0) for i in code(callback, 0x4a) + code(wait_helper, 0x48)
              if i.mnemonic == 'bl'} - {context}
    p = dict(callback=callback, context=context, context_table=table[0], irq_set=irq_set,
             task_set=task_set, waiter=waiter, wait_helper=wait_helper, timed_wait=timed_wait,
             cancel_timer=cancel_timer, traces=traces, predicate=predicate, debug=roots[0] + 0x11)
    p['regions'] = [(callback, callback + 0x4a), (context, context + 0x34),
                    (waiter, waiter + 0x42), (wait_helper, wait_helper + 0x48),
                    (predicate, predicate + 0x58)]
    return data, p


def correlate(directory, *, ordinal, interrupt_context):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
    data, p = profile(directory)
    cpu = machine(data, [p['context_table'] & ~4095, p['debug'] & ~4095])
    frame, tcb, stack, finish = 0x30000000, 0x30010000, 0x3001f000, 0x3001e000
    for core in range(4):
        cpu.mem_write(p['context_table'] + core * 4, struct.pack('<I', tcb))
    cpu.mem_write(tcb + 0x40, struct.pack('<I', interrupt_context))
    for offset, value in ((0x208, ordinal), (0x5c04, 0x12)):
        cpu.mem_write(frame + offset, struct.pack('<I', value))
    cpu.mem_write(frame + 0x5c3a, b'\x34')
    cpu.mem_write(frame + 0x9d7, b'\1')
    cpu.mem_write(frame + 0x1698, struct.pack('<I', 1))
    before = bytes(cpu.mem_read(frame, 0x7000))
    phase, boundary, context_seen, traces = 'predicate', None, False, []

    def hook(uc, address, size, unused):
        nonlocal boundary, context_seen
        if address == p['context']:
            context_seen = True
        if address in (p['irq_set'], p['task_set'], p['timed_wait']):
            boundary = address
            uc.emu_stop()
            return
        if address in p['traces']:
            traces.append(phase)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
            return
        if not any(lo <= address and address + size <= hi for lo, hi in p['regions']):
            raise ValueError('Steady event replay reached omitted code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        if not (stack - 512 <= address and address + size <= stack):
            raise ValueError('Steady event replay changed non-stack state: ' + hex(address))

    def run(at):
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, finish, count=300)

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    for field, blocked in ((p['debug'], 8), (frame + 0x9d7, 0), (frame + 0x5c28, 1)):
        original = bytes(cpu.mem_read(field, 1))
        cpu.mem_write(field, bytes([blocked]))
        cpu.reg_write(UC_ARM_REG_R0, frame)
        run(p['predicate'])
        if cpu.reg_read(UC_ARM_REG_PC) != finish or cpu.reg_read(UC_ARM_REG_R0) != 0:
            raise ValueError('Native steady-path inhibition did not reject its synthetic input')
        cpu.mem_write(field, original)
    cpu.reg_write(UC_ARM_REG_R0, frame)
    run(p['predicate'])
    if cpu.reg_read(UC_ARM_REG_PC) != finish or cpu.reg_read(UC_ARM_REG_R0) != 1:
        raise ValueError('Native steady-path predicate did not admit its synthetic input')
    phase = 'callback'
    run(p['callback'])
    callback_event = (cpu.reg_read(UC_ARM_REG_R0), cpu.reg_read(UC_ARM_REG_R1))
    if (not context_seen or boundary != p['irq_set' if interrupt_context else 'task_set']
            or callback_event != (0x2e, 0x80000000)):
        raise ValueError('Native timer callback selected a different context/event')
    phase, boundary = 'waiter', None
    cpu.reg_write(UC_ARM_REG_R0, frame)
    run(p['waiter'])
    wait_event = (cpu.reg_read(UC_ARM_REG_R0), cpu.reg_read(UC_ARM_REG_R1))
    timeout = struct.unpack('<I', cpu.mem_read(cpu.reg_read(UC_ARM_REG_SP), 4))[0]
    if (boundary != p['timed_wait'] or wait_event != callback_event or timeout != 10000
            or cpu.reg_read(UC_ARM_REG_R2) != 2
            or cpu.reg_read(UC_ARM_REG_R3) != cpu.reg_read(UC_ARM_REG_SP) + 4
            or bytes(cpu.mem_read(frame, 0x7000)) != before or traces != ['callback', 'waiter']):
        raise ValueError('Native steady callback/wait arguments do not match')
    # The original early-return flag must avoid both the wait and timer cancellation.
    cpu.mem_write(frame + 0x9ed, b'\1')
    phase, boundary = 'skip', None
    cpu.reg_write(UC_ARM_REG_R0, frame)
    run(p['waiter'])
    if boundary is not None or cpu.reg_read(UC_ARM_REG_PC) != finish or cpu.reg_read(UC_ARM_REG_SP) != stack:
        raise ValueError('Original steady-wait bypass did not return directly')
    return dict(ordinal=ordinal, synthetic_interrupt_context=interrupt_context,
                original_arm_context_detector_executed=True, event_id=callback_event[0],
                event_mask=callback_event[1], wait_mode=2, timeout_argument=timeout,
                native_bypass_verified=True, diagnostic_calls_omitted=len(traces),
                native_predicate_and_inhibitions_verified=True,
                rtos_event_api_executed=False, event_delivered=False, wait_completed=False,
                motor_settling_verified=False, exposure_or_centering_executed=False)


def compare(c2, reference):
    timer_a, timer_b = request(c2, 100000), request(reference, 100000)
    if timer_a != timer_b:
        raise ValueError('Native steady timer requests differ')
    cases = []
    for ordinal in range(4):
        for context in (0, 1):
            a = correlate(c2, ordinal=ordinal, interrupt_context=context)
            b = correlate(reference, ordinal=ordinal, interrupt_context=context)
            if a != b:
                raise ValueError('C2/A7CR native steady event synchronization differs')
            cases.append(dict(target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-steady-event/1', paired_cases=len(cases),
                timer_request=timer_a, cases=cases, camera_io=False, installable=False,
                separate_callback_and_waiter_invocations=True, physical_shift_verified=False)


def deliver(directory, *, ordinal=0, initial_bits=0, signal=True):
    """Execute callback -> real event set -> native timed wait/clear.

    Task/frame/event backing and callback invocation are fixtures. A pre-set
    software event does not establish elapsed time or actuator settling.
    Stop before the outer waiter's timer-cancel operation, which needs its own
    timer registration lifecycle. Preserve the existing void-log omissions.
    """
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    from cp_completion_replay import profile as completion_profile
    from cp_native_mutex_replay import setup as setup_kernel
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, p = profile(directory)
    _, event_profile = completion_profile(directory)
    cpu = machine(data, [])
    kernel = setup_kernel(cpu, directory)
    frame, event, attrs, stack, finish = 0x34000000, 0x30015000, 0x30003400, 0x3001f000, 0x3001e000
    cpu.mem_map(frame, 0x8000)
    slot = event_profile['table']+4*(0x2e-1)
    for address in (slot, p['debug']):
        page = address & ~4095
        if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    cpu.mem_write(slot, struct.pack('<I', event))
    cpu.mem_write(event-4, b'\xa5'*4+struct.pack('<4I', event, event, attrs, initial_bits)+b'\xa5'*4)
    cpu.mem_write(attrs, bytes(8))
    cpu.mem_write(p['debug'], b'\0')
    cpu.mem_write(frame, bytes(0x7000))
    cpu.mem_write(frame+0x208, struct.pack('<I', ordinal))
    cpu.mem_write(frame+0x5c04, struct.pack('<I', 0x12345678))
    cpu.mem_write(frame+0x9d7, b'\1')
    source = bytes(cpu.mem_read(frame, 0x7000))
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    at = p['wait_helper']+0x3e
    call = list(decoder.disasm(data[at-0x108000:at-0x108000+4], at))
    if len(call) != 1 or call[0].mnemonic != 'blx':
        raise ValueError('Original steady wait helper no longer clears the event after waiting')
    clear = int(call[0].op_str.lstrip('#'), 0)
    regions = p['regions']+[(p['task_set'], p['task_set']+0x248),
        (p['timed_wait'], p['timed_wait']+0x34c), (clear, clear+0x248)]
    phase, diagnostics, wait_statuses, clear_statuses, returned_flags = 'callback', [], [], [], []
    boundary, wait_arguments = None, None

    def hook(uc, address, size, unused):
        nonlocal boundary, wait_arguments
        if address == p['timed_wait']+0x214:
            boundary = 'before_native_waiter_state_change'
            uc.emu_stop()
            return
        if address in p['traces']:
            diagnostics.append(phase)
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if address == p['cancel_timer']:
            boundary = 'before_original_timer_cancel'
            uc.emu_stop()
            return
        if address == p['timed_wait']:
            wait_arguments = [uc.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)]
            wait_arguments.append(struct.unpack('<I', uc.mem_read(uc.reg_read(arm.UC_ARM_REG_SP), 4))[0])
        if address == p['wait_helper']+0x38:
            wait_statuses.append(uc.reg_read(arm.UC_ARM_REG_R0))
            returned_flags.append(struct.unpack('<I', uc.mem_read(uc.reg_read(arm.UC_ARM_REG_SP)+4, 4))[0])
        if address == p['wait_helper']+0x42:
            clear_statuses.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if not any(lo <= address and address+size <= hi for lo, hi in regions):
            raise ValueError('Native steady event delivery reached an unresolved dependency: '+hex(address))

    def write_hook(uc, access, address, size, value, unused):
        spans = [(event+12, 4), (event_profile['guard'], 4), (stack-4096, 4096)]+kernel['writes']
        if not any(lo <= address and address+size <= lo+n for lo, n in spans):
            raise ValueError('Native steady event delivery changed unrelated state: '+hex(address))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        if signal:
            cpu.reg_write(arm.UC_ARM_REG_R0, frame)
            cpu.reg_write(arm.UC_ARM_REG_SP, stack)
            cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(p['callback'] | 1, finish, count=10000)
        after_callback = struct.unpack('<I', cpu.mem_read(event+12, 4))[0]
        if ((signal and cpu.reg_read(arm.UC_ARM_REG_PC) != finish)
                or after_callback != initial_bits | (0x80000000 if signal else 0)):
            raise ValueError('Original callback/event API did not produce its ready bit')
        phase = 'waiter'
        cpu.reg_write(arm.UC_ARM_REG_R0, frame)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(p['waiter'] | 1, finish, count=20000)
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    after_wait = struct.unpack('<I', cpu.mem_read(event+12, 4))[0]
    if (boundary != ('before_original_timer_cancel' if signal else 'before_native_waiter_state_change')
            or wait_statuses != ([0] if signal else []) or clear_statuses != ([0] if signal else [])
            or returned_flags != ([initial_bits | 0x80000000] if signal else []) or after_wait != initial_bits
            or wait_arguments != [0x2e, 0x80000000, 2, 10000]
            or bytes(cpu.mem_read(frame, 0x7000)) != source
            or bytes(cpu.mem_read(event-4, 4)) != b'\xa5'*4 or bytes(cpu.mem_read(event+16, 4)) != b'\xa5'*4
            or diagnostics != (['callback', 'waiter'] if signal else ['waiter'])):
        raise ValueError('Native steady event wait/clear did not preserve its software contract')
    return dict(ordinal=ordinal, initial_event_bits=initial_bits, after_callback=after_callback, after_wait=after_wait,
        native_timed_wait_status=wait_statuses[0] if signal else None,
        native_clear_status=clear_statuses[0] if signal else None,
        native_wait_arguments=wait_arguments, software_event_delivered=signal, timed_wait_completed=signal,
        frame_and_neighbors_preserved=True, diagnostic_calls_omitted=len(diagnostics),
        boundary=boundary, host_assigned_event_bits_after_callback=False, api_results_replaced=False,
        callback_invocation_frame_event_and_os_are_fixtures=True, timer_expiry_or_registration_executed=False,
        outer_waiter_returned=False, timer_cancel_executed=False, physical_position_acknowledgement_verified=False,
        exposure_or_centering_executed=False, saved_off_setting_executed=False, camera_io=False, installable=False)


def compare_delivery(c2, reference):
    rows = []
    for ordinal in range(4):
        for bits in (0, 0x204):
            for signal in (False, True):
                values = dict(ordinal=ordinal, initial_bits=bits, signal=signal)
                x, y = deliver(c2, **values), deliver(reference, **values)
                if x != y:
                    raise ValueError('C2/CR native steady event delivery differs')
                rows.append(dict(input=values, target=x, reference=y))
    return dict(schema='a7c2-native-steady-event-delivery/1', paired_cases=len(rows), cases=rows,
        camera_io=False, physical_shift_verified=False, installable=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--deliver-event', action='store_true', help='Execute actual task-context event set/wait/clear')
    args = parser.parse_args(argv)
    report = (compare_delivery if args.deliver_event else compare)(args.c2, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
