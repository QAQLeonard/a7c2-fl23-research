"""Follow the native capture flag from its caller into snapshot and mode choice.

The actual eligibility helper/caller suffix supplies the snapshot argument;
the original snapshot writes +D88 and the real capture getter supplies the mode
selector's pointer in the same RAM as the AP-built TRINITY command. Optional
native context/state/input producers replace selected intermediate fixtures;
source mode, underlying inputs and capture invocation remain synthetic. Complete
scheduling, capture preparation, MMIO, motion and exposure do not run. No host
writes +D88/+D8E, assigns an API result, or substitutes the 0x9416 data-block path.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_capture_replay import profile as capture_profile
from cp_config_replay import _snapshot, profile as snapshot_profile
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, s = snapshot_profile(directory)
    _, c = capture_profile(directory)
    delta = 0x1a2 if s['entry'] == 0xb0e074 else 0
    p = dict(caller=0xb21a74+delta, caller_end=0xb21a9e+delta,
             selector=c['begin']-8, selector_end=c['end'], state=c['state_address'],
             state_getter=c['getter'], consistency=c['consistency'],
             consistency_end=c['finish'], trace=c['trace'])
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, length):
        return list(md.disasm(data[at-0x108000:at-0x108000+length], at))

    def call(at):
        row = code(at, 4)
        if len(row) != 1 or row[0].mnemonic != 'bl':
            raise ValueError('Original capture-caller call changed')
        return int(row[0].op_str.lstrip('#'), 0)

    p['source_getter'] = call(p['caller'])
    p['gate'] = call(p['caller']+6)
    p['context_getter'] = call(p['caller']+12)
    p['context'] = next(value for reg, value in literals(code(p['context_getter'], 10)) if reg == 'r0')
    p['data_getter'] = call(p['gate']+4)
    p['classify'] = call(p['gate']+12)
    p['source'] = next(value for reg, value in literals(code(p['source_getter'], 10)) if reg == 'r0')
    if p['source'] != next(value for reg, value in literals(code(p['data_getter'], 10)) if reg == 'r0'):
        raise ValueError('Capture eligibility and snapshot do not share the actual source')
    p['override'] = next(value+4 for reg, value in literals(code(p['gate']+0x14, 12)) if reg == 'r0')
    p['live_getter'] = call(p['selector']+2)
    live = code(p['live_getter'], 0x36)
    live_root = next(value for reg, value in literals(live) if reg == 'r4')
    if (live_root != s['root'] or call(p['caller_end']-4) != s['entry']
            or not any(row.mnemonic == 'strb.w' and row.op_str == 'sb, [r4, #0xd90]'
                       for row in code(s['entry'], 0xc4))):
        raise ValueError('Original snapshot/live getter no longer bind the +D88 capture field')
    p['regions'] = [(p['caller'], p['caller_end']), (p['gate'], p['gate']+0x3a),
                    (p['source_getter'], p['source_getter']+10),
                    (p['data_getter'], p['data_getter']+10),
                    (p['context_getter'], p['context_getter']+10),
                    (p['classify'], p['classify']+0x6a),
                    (s['entry'], s['entry']+0xc4), (s['copy'], s['copy']+0x300),
                    (s['predicates'][0], s['predicates'][0]+0x22),
                    (s['predicates'][1], s['predicates'][1]+0x30),
                    (p['live_getter'], p['live_getter']+0x36),
                    (p['selector'], p['selector_end']),
                    (p['consistency'], p['consistency_end']),
                    (p['state_getter'], p['state_getter']+12)]
    return data, s, p


def replay(directory, *, trinity=1, capture_mode=2, override=0, pipeline=1, native_state=0,
           native_context=False, guard_actions=(), pipeline_source=None, native_request=False,
           queue_start=0):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, s, p = profile(directory)
    gate_value, written_flag, write_phase, snapshot_calls = None, None, None, 0
    input_evidence = None
    manager_evidence = None
    if native_request and not native_context:
        raise ValueError('Native request replay requires native context binding')

    def initialize(cpu, snapshot, dispatch, source):
        nonlocal input_evidence
        if source != p['source']:
            raise ValueError('Capture gate consumes a different LiRo source object')
        for at in (p['context'], p['override'], p['state']):
            page = at & ~4095
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
        cpu.mem_write(source+0x138, struct.pack('<II', capture_mode, 0))
        cpu.mem_write(p['override'], bytes([override]))
        if native_context:
            from cp_capture_context_replay import initialize as publish_context
            input_evidence = publish_context(cpu, directory, p, pipeline, guard_actions,
                                             pipeline_source=pipeline_source)
            if input_evidence['native_guard'] != native_state:
                raise ValueError('Native guard lifecycle differs from the requested comparison state')
        else:
            if guard_actions or pipeline_source is not None:
                raise ValueError('Guard actions/pipeline production require native context publication')
            cpu.mem_map(0x30012000, 4096)
            cpu.mem_write(p['state'], bytes([native_state]))
            cpu.mem_write(p['context']+0x10, struct.pack('<I', 0x30012000))
            cpu.mem_write(0x30012102, bytes([pipeline]))
            cpu.mem_write(0x3001213c, bytes(4))

    def run_snapshot(cpu, snapshot, dispatch, source, capture_id, stack):
        nonlocal gate_value, written_flag, write_phase, snapshot_calls, manager_evidence
        if native_request:
            from cp_capture_request_replay import snapshot_caller
            manager_evidence = snapshot_caller(cpu, directory, p, snapshot, source, capture_id, stack)
            gate_value = manager_evidence['native_gate']
            written_flag = manager_evidence['native_snapshot_flag']
            snapshot_calls = manager_evidence['native_snapshot_calls']
            return manager_evidence['stop_pc']
        write_phase = 'snapshot'

        def code_hook(uc, at, size, unused):
            nonlocal gate_value, snapshot_calls
            if not any(lo <= at and at+size <= hi for lo, hi in p['regions']):
                raise ValueError('Native capture-gate chain entered an unresolved dependency: '+hex(at))
            if at == p['caller']+10:
                gate_value = uc.reg_read(arm.UC_ARM_REG_R0)
            if at == snapshot['entry']:
                snapshot_calls += 1
                if uc.reg_read(arm.UC_ARM_REG_R2) != gate_value:
                    raise ValueError('Original caller did not pass the native eligibility result')

        def write_hook(uc, access, at, size, value, unused):
            nonlocal written_flag
            if stack-4096 <= at and at+size <= stack+8:
                return
            allowed = [(snapshot['root']+0x28, 0xd64), (snapshot['root']+0xd90, 13)]
            if not any(lo <= at and at+size <= lo+n for lo, n in allowed):
                raise ValueError('Native capture-gate chain changed unrelated state: '+hex(at))
            if at == snapshot['root']+0xd90:
                if write_phase != 'snapshot' or size != 1:
                    raise ValueError('Capture field +D88 was overwritten outside the original snapshot')
                written_flag = value

        ch, wh = cpu.hook_add(UC_HOOK_CODE, code_hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        cpu.reg_write(arm.UC_ARM_REG_R5, capture_id)
        cpu.reg_write(arm.UC_ARM_REG_SB, 4)
        cpu.reg_write(arm.UC_ARM_REG_R8, 0x87654321)
        cpu.emu_start(p['caller'] | 1, p['caller_end'], count=10000)
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        if cpu.reg_read(arm.UC_ARM_REG_SP) != stack:
            raise ValueError('Original caller suffix did not regain its stack after the snapshot returned')
        return p['caller_end']

    def validate_manager(cpu, snapshot):
        from cp_capture_request_replay import validate_header
        validate_header(cpu, directory, snapshot, manager_evidence)

    cpu, snapshot, _, prior = _snapshot(directory, mode=trinity,
        source_initializer=initialize, snapshot_runner=run_snapshot,
        manager_validator=validate_manager if native_request else None)
    flag = cpu.mem_read(snapshot['root']+0xd90, 1)[0]
    eligible = (capture_mode-6 not in range(0x16) or bool((0x1fbffa >> (capture_mode-6)) & 1))
    expected_flag = int(eligible and bool(override or pipeline))
    if gate_value != expected_flag or flag != expected_flag or written_flag != expected_flag or snapshot_calls != 1:
        raise ValueError('Native capture eligibility/snapshot differs from independent classification')
    frame = snapshot['root']+8
    policy_flag = 0
    if pipeline_source is not None:
        policy_flag = int(input_evidence['pipeline_source']['native_policy_field'] == 1)
    if cpu.mem_read(frame+0xd8e, 1)[0] != policy_flag:
        raise ValueError('Native snapshot did not propagate the independently checked pipeline policy')
    before = bytes(cpu.mem_read(frame, 0xda0))
    stack = 0x3000f000

    def code_hook(uc, at, size, unused):
        if not any(lo <= at and at+size <= hi for lo, hi in p['regions']):
            raise ValueError('Live capture getter/selection entered an unresolved dependency: '+hex(at))

    def write_hook(uc, access, at, size, value, unused):
        if stack-4096 <= at and at+size <= stack:
            return
        if not frame+0x158 <= at or at+size > frame+0x160:
            raise ValueError('Native capture selection changed unrelated snapshot fields')

    request_evidence = None
    if native_request:
        from cp_capture_request_replay import select_via_queue
        request_evidence = select_via_queue(cpu, directory, p, snapshot, start=queue_start)
    else:
        ch, wh = cpu.hook_add(UC_HOOK_CODE, code_hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        cpu.reg_write(arm.UC_ARM_REG_R8, 0x12345678)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.emu_start(p['selector'] | 1, p['selector_end'], count=1000)
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    selected, adjacent = struct.unpack('<II', cpu.mem_read(frame+0x158, 8))
    expected_mode = capture_mode
    expected_adjacent = 0
    if not native_state:
        if capture_mode == 2 and expected_flag:
            expected_mode, expected_adjacent = 0x17, 1
        elif capture_mode == 0x21 and (expected_flag or policy_flag):
            expected_mode = 1
    after = bytes(cpu.mem_read(frame, 0xda0))
    if (cpu.reg_read(arm.UC_ARM_REG_PC) != p['selector_end']
            or (selected, adjacent) != (expected_mode, expected_adjacent)
            or before[:0x158] != after[:0x158] or before[0x160:] != after[0x160:]):
        raise ValueError('Live getter/native capture selection differs from the generated flag')
    consistency_before = bytes(cpu.mem_read(frame, 0xda0))
    diagnostics = 0

    def consistency_hook(uc, at, size, unused):
        nonlocal diagnostics
        if at == p['trace']:
            # This diagnostic-only call's result is overwritten by native
            # MOVS R0,#0 before the policy store. No API success is supplied.
            diagnostics += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if not (p['consistency'] <= at and at+size <= p['consistency_end']):
            raise ValueError('Native TRINITY consistency entered an unresolved dependency')

    def consistency_write(uc, access, at, size, value, unused):
        if not frame+0x1a0 <= at or at+size > frame+0x1a4:
            raise ValueError('Native TRINITY consistency changed unrelated state')

    ch = cpu.hook_add(UC_HOOK_CODE, consistency_hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, consistency_write)
    cpu.reg_write(arm.UC_ARM_REG_R5, frame)
    cpu.reg_write(arm.UC_ARM_REG_R8, selected)
    cpu.emu_start(p['consistency'] | 1, p['consistency_end'], count=100)
    cpu.hook_del(ch)
    cpu.hook_del(wh)
    final_trinity = struct.unpack('<I', cpu.mem_read(frame+0x1a0, 4))[0]
    expected_trinity = 0 if trinity == 1 and selected != 0x17 else trinity
    consistency_after = bytes(cpu.mem_read(frame, 0xda0))
    if (cpu.reg_read(arm.UC_ARM_REG_PC) != p['consistency_end']
            or final_trinity != expected_trinity or diagnostics != int(trinity != expected_trinity)
            or consistency_before[:0x1a0] != consistency_after[:0x1a0]
            or consistency_before[0x1a4:] != consistency_after[0x1a4:]):
        raise ValueError('Original consistency policy did not retain/clear the same propagated TRINITY value')
    result = dict(native_gate=gate_value, native_snapshot_flag_d88=flag, selected_mode=selected,
                adjacent=adjacent, propagated_trinity=prior['capture_configuration_trinity'],
                final_trinity=final_trinity, diagnostic_calls_omitted=diagnostics,
                native_snapshot_copy_bytes=prior['copied_bytes'], native_snapshot_returned_to_caller=True,
                live_getter_pointer_matches_snapshot=True, source_parameters_are_fixtures=True,
                host_assigned_capture_flag_or_api_returns=False, full_outer_caller_executed=False,
                automatically_scheduled=False, data_block_9416_used_as_live_source=False,
                positioning_or_exposure_executed=False, same_ram=True, camera_io=False, installable=False)
    if input_evidence is not None:
        result['native_context_publication'] = input_evidence
    if pipeline_source is not None:
        result['native_snapshot_flag_d8e'] = policy_flag
    if native_request:
        result['native_manager_initialization'] = {key: value for key, value in manager_evidence.items()
            if key not in ('stop_pc', 'expected_header', 'capture_id')}
        result['native_capture_request'] = request_evidence
    return result


def compare(c2, reference):
    rows = []
    for capture_mode in (2, 6, 7, 0x21):
        for override in (0, 1):
            for pipeline in (0, 1, 2):
                for native_state in (0, 1):
                    for trinity in (0, 1):
                        args = dict(capture_mode=capture_mode, override=override, pipeline=pipeline,
                                    native_state=native_state, trinity=trinity)
                        a, b = replay(c2, **args), replay(reference, **args)
                        if a != b:
                            raise ValueError('Native C2/CR capture-gate-to-mode chain differs')
                        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-capture-gate/1', paired_cases=len(rows), cases=rows,
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
