"""Offline CP sound-selector differential against the A1 II path.

Executes original selector instructions and original state-query/getter chain
with synthetic input. Stops BEFORE dispatch or at function return. The local
two-byte trial is never written to the source file or connected to USB.
The AP/CP input fragments are verified separately by verify_selector_inputs.py.
This trace alone is not an installable patch or physical sound evidence.
"""
import argparse
import json
from pathlib import Path
import struct


TRIAL_OFFSET = 0x3935ca
BEFORE = bytes.fromhex('0021')
AFTER = bytes.fromhex('0321')
CONTEXT = 0x30000000


def execute(cp, selector, descriptor_word, *, trial=False, skip_policy=False,
            skip_pending=False, defer_dispatch=False, counter_limit=0, capture_count=0,
            patched_cp=None, capture_request=None, mechanical_tail_only=False):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_R0
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages = set()

    def mapped(address, length):
        for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
            if page not in pages:
                cpu.mem_map(page, 4096)
                pages.add(page)

    if cp[TRIAL_OFFSET:TRIAL_OFFSET + 2] != BEFORE:
        raise ValueError('Original selector instruction differs')
    segments = [(0x49b538, 0xda), (0x876e34, 16), (0x8c6c4e, 4),
                (0x8b8054, 24), (0xa765c2, 24), (0x8cb9e4, 12),
                (0x877b02, 10), (0x8b8004, 18)]
    image=cp if patched_cp is None else patched_cp
    for va, size in segments:
        mapped(va, size)
        cpu.mem_write(va, image[va - 0x108000:va - 0x108000 + size])
    if trial:
        cpu.mem_write(TRIAL_OFFSET + 0x108000, AFTER)
    mapped(CONTEXT, 0x7000)
    mapped(0x10000000, 4096)
    mapped(0x20000000, 0x4000)
    mapped(0x19f9250, 4)
    mapped(0x1ac5644, 0x100)
    mapped(0xb19e5c, 4)
    mapped(0x201a000, 0x3000)
    stop = 0x50000000
    mapped(stop, 4096)
    # Object passed by the original constructor, copied by its actual LDM/STM.
    cpu.mem_write(0x19f9250, struct.pack('<I', 0x10000100))
    cpu.mem_write(0x10000100, struct.pack('<4I', 0, 0, 0, descriptor_word))
    cpu.mem_write(0x10000000, struct.pack('<I', CONTEXT))
    cpu.mem_write(CONTEXT + 0x1698, struct.pack('<I', selector))
    cpu.mem_write(CONTEXT + 0x5c1c, struct.pack('<I', 0x12345678))
    cpu.mem_write(0x1ac5644 + 0x81, struct.pack('>H', counter_limit))
    cpu.mem_write(CONTEXT + 0x11e0, struct.pack('<H', capture_count))
    cpu.mem_write(CONTEXT + 0x9d7,bytes([bool(mechanical_tail_only)]))
    if skip_policy:
        cpu.mem_write(CONTEXT + 0x5c10, struct.pack('<I', 1))
    if skip_pending:
        cpu.mem_write(CONTEXT + 0x66e8, struct.pack('<I', 2))
        cpu.mem_write(CONTEXT + 0x66ec, struct.pack('<I', 0xffffffff))
    if defer_dispatch:
        cpu.mem_write(CONTEXT + 0x886, struct.pack('<H', 1))
    if capture_request is not None:
        # Execute the real producer of the per-capture flag, not a UI setting or
        # a mocked getter. Async propagation into this function is not emulated.
        from unicorn.arm_const import UC_ARM_REG_R5
        cpu.mem_write(0x10000400+0x4c8, struct.pack('<I', capture_request))
        cpu.mem_write(0x20003010, struct.pack('<I', 0x201afd0))
        cpu.reg_write(UC_ARM_REG_R0,0x10000400)
        cpu.reg_write(UC_ARM_REG_SP,0x20003000)
        def producer_end(uc,va,size,user):
            if va==0x8b8016:uc.emu_stop()
        hook=cpu.hook_add(UC_HOOK_CODE,producer_end)
        cpu.emu_start(0x8b8005,0x8b8018,count=16)
        cpu.hook_del(hook)
        if cpu.mem_read(0x201bfe9,1)[0]!=int(capture_request==1):
            raise ValueError('Per-capture electronic flag producer differs')
    cpu.reg_write(UC_ARM_REG_R0, 0x10000000)
    cpu.reg_write(UC_ARM_REG_SP, 0x20003000)
    cpu.reg_write(UC_ARM_REG_LR, stop | 1)
    dispatched = []
    returned = []

    def boundary(uc, va, size, user):
        if va == 0xb19e5c:
            dispatched.append(va)
            uc.emu_stop()
        elif va == stop:
            returned.append(va)
            uc.emu_stop()

    cpu.hook_add(UC_HOOK_CODE, boundary)
    cpu.emu_start(0x49b538 | 1, stop + 2, count=256)
    if len(dispatched) + len(returned) != 1:
        raise ValueError('Original selector did not reach a known boundary')
    selected_mode = struct.unpack('<I', cpu.mem_read(CONTEXT + 0x5c1c, 4))[0]
    return {'mode': selected_mode, 'at_dispatch': bool(dispatched),
            'returned': bool(returned)}


def verify(cp):
    rows = []
    for selector in range(5):
        for descriptor_word in range(5):
            for guard in ('none', 'policy', 'pending', 'defer'):
                for limit, count in ((0, 0), (3, 0), (3, 3)):
                    options = dict(skip_policy=guard == 'policy', skip_pending=guard == 'pending',
                                   defer_dispatch=guard == 'defer', counter_limit=limit, capture_count=count)
                    before = execute(cp, selector, descriptor_word, **options)
                    after = execute(cp, selector, descriptor_word, trial=True, **options)
                    expected_change = selector == 1 and descriptor_word != 3 and guard in ('none', 'defer')
                    if expected_change:
                        wanted = 1 if limit and count < limit else 3
                        if before['mode'] != 0 or after['mode'] != wanted:
                            raise ValueError('Trial changed the native counter-policy result')
                        if before['at_dispatch'] != after['at_dispatch']:
                            raise ValueError('Trial changed dispatch eligibility')
                    elif before != after:
                        raise ValueError('Trial changed an unselected branch/guard')
                    rows.append(dict(selector=selector, descriptor_word=descriptor_word,
                                     guard=guard, counter_limit=limit, capture_count=count,
                                     before=before, after=after))
    return {'native_cases': len(rows), 'executions': 2 * len(rows),
            'original_state_query_chain_executed': True,
            'only_local_instruction_trial': True, 'candidate_bytes': AFTER.hex(),
            'original_bytes': BEFORE.hex(), 'file_offset': hex(TRIAL_OFFSET),
            'unselected_test_cases_unchanged': True,
            'input_mapping_verifier': 'verify_selector_inputs.py',
            'actual_ui_to_selector_binding_tested': False,
            'silent_mode_semantics_proven': False,
            'camera_io': False, 'installable': False, 'cases': rows}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cp', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args(argv)
    result = verify(a.cp.read_bytes())
    text = json.dumps(result, indent=2)
    if a.output:
        with a.output.open('x', encoding='utf-8') as f:
            f.write(text + '\n')
    else:
        print(text)


if __name__ == '__main__':
    main()
