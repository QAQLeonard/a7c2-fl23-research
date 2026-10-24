"""Original CAP_MGR construction, cancellation mask and request13 admission.

All owners/requests/modes are synthetic. Run pure original constructors and
field operations. Separate post-log slices take explicit input registers;
no logging, timer, allocation, IPC or hardware call is made successful.
This is not an installer or a camera recording/retention test.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_R8, UC_ARM_REG_R10, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from support.cp_mapping import PINNED

from support.capture_native import NativeCapture, BASE, OWNER, WIRE, STACK, STOP, DEBUG, words
from support.capture_completion import audit as audit_completion, SPANS as COMPLETION_SPANS
from support.capture_resources import audit as audit_resources, SPANS as RESOURCE_SPANS
from support.resource_service import audit as audit_resource_service, SPANS as SERVICE_SPANS
from support.backing_memory import audit as audit_backing, SPANS as BACKING_SPANS


READOUT_SPANS = ((0xa186ba,0x66),(0xa1872c,0xae),(0xa19fbc,0x10),
    (0xa16f76,0x1ca),(0xa18392,4),(0xa1a02c,14),
    (0xa16f40,0x1a),(0x7d569e,0x10),(0xa17412,0xcc),
    (0xa17140,0x34),(0xc8f468,320*16),(0x7d5114,0xcf8),
    (0xdd2204,0x300),(0x25e95c,0x28),(0xc8e410,246*16),
    (0xa17354,0x7a),(0xdd13ea,26))


def readout_admission(cp):
    """Original entry and explicit AFTER-prepare slice, no successful services.

    The native mode/selector words are synthetic raw inputs. This only locates
    the first outstanding native boundary; it never bypasses that boundary.
    """
    n=NativeCapture(cp);u=n.u
    u.mem_map(0x1a52000,4096)
    u.mem_map(0x1725000,4096)
    u.mem_map(0x1b1d000,4096)
    u.mem_map(0x1870000,0x2000)
    context,flags=OWNER+0x1000,OWNER+0x2000
    controller,event=OWNER+0x3000,OWNER+0x4000
    entry=[]
    for busy in (0,1,2):
        u.mem_write(OWNER,bytes(0x6000))
        u.mem_write(OWNER+0xc,words(context))
        u.mem_write(OWNER+0x14,words(flags))
        u.mem_write(context+0xc,words(busy))
        got=n.run(0xa186ba,(0xa1ac7e,0xa19c70),[
            (UC_ARM_REG_R0,OWNER),(UC_ARM_REG_R1,event),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        assert got['address']==BASE+(0xa19c70 if busy else 0xa1ac7e)
        assert got['args'][0]==(context if busy else flags)
        assert u.mem_read(context+0xc,4)==words(busy or 1)
        entry.append(dict(busy_raw=busy,boundary_file=hex(got['address']-BASE),
            external_executed=False,prepare_executed=False))
    cases=[]
    for state,subtype,selector in itertools.product(range(0x88),(1,4,13),(0,1,2)):
        u.mem_write(OWNER,bytes(0x6000))
        u.mem_write(OWNER+0xc,words(context))
        u.mem_write(OWNER+0x1c,words(controller))
        u.mem_write(controller+0x28,words(selector))
        u.mem_write(event+0xc,words(subtype))
        u.mem_write(0x1a52ad4,words(state))
        before=bytes(u.mem_read(OWNER,0x6000))
        got=n.run(0xa1872c,(0x3ad874,0xa19c70),[
            (UC_ARM_REG_R4,OWNER),(UC_ARM_REG_R5,event),
            (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
        # 3001 is recognized in raw states9/55; 3000 in8/4e/69, with
        # subtype4 additionally selecting the direct status-update branch.
        direct=state in (9,0x55) or (state in (8,0x4e,0x69) and subtype==4) or selector==2
        assert got['address']==BASE+(0x3ad874 if direct else 0xa19c70), (state,subtype,selector,hex(got['address']-BASE))
        assert bytes(u.mem_read(OWNER,0x6000))==before
        assert bytes(u.mem_read(0x1a52ad4,4))==words(state)
        cases.append(dict(state_raw=state,subtype=subtype,selector_raw=selector,
            boundary_file=hex(got['address']-BASE),
            external_executed=False,postprepare_slice=True))
    # Original getter + constructor binds the actual 320-entry ROM table.
    # Stop before the following subsystem initializer; never fake its return.
    got=n.run(0xa16f40,(0x25e8f4,),[
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0x25e8f4
    assert u.mem_read(0x1725858,8)==words(0xd97468,320)
    records=[struct.unpack_from('<4I',cp,0xc8f468+i*16) for i in range(320)]
    table_checks=[]
    for command in (0x3015,0x3013,0x3014,0x3032):
        recognized=[]
        for state in range(0x88):
            u.mem_write(0x1a52ad4,words(state))
            u.mem_write(0x1b1df9a,b'\0\0')
            got=n.call(0xa17140,[command])
            expected=int(any(row[0]==state and row[1]==command for row in records))
            assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==expected
            if expected:recognized.append(state)
        # Native busy flag forbids table acceptance regardless of pair.
        u.mem_write(0x1b1df9a,b'\1\0')
        got=n.call(0xa17140,[command])
        assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==0
        table_checks.append(dict(command_raw=hex(command),states_raw=recognized,
            native_queries=0x88,transition_callback_executed=False))
    # Execute each matched original descriptor callback on explicit synthetic
    # configuration. It returns a software state sequence, NOT a sensor ACK.
    sequences=[]
    configuration,shot,other=OWNER+0x5000,OWNER+0x5100,OWNER+0x5500
    u.mem_write(configuration,bytes(0x100));u.mem_write(shot,bytes(0x400))
    u.mem_write(other,bytes(0x200))
    u.mem_write(configuration+0x10,words(shot))
    u.mem_write(configuration+0x34,words(other))
    for state,command,callback,following in records:
        if command not in (0x3015,0x3013,0x3014,0x3032):continue
        u.mem_write(0x1725860,bytes(12))
        got=n.call(0xa1745c,[0x1725858,state,command,configuration])
        assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==1
        sequence,index,next_command=struct.unpack('<3I',u.mem_read(0x1725860,12))
        assert index==1 and next_command==following
        count=struct.unpack('<H',u.mem_read(sequence,2))[0]
        assert 0<count<=16
        native_states=[]
        for expected_index in range(1,count+1):
            got=n.call(0xa174a8,[0x1725858])
            assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==int(expected_index>=count)
            got=n.call(0xa174b8,[0x1725858])
            assert got['address']==STOP
            native_states.append(u.reg_read(UC_ARM_REG_R0))
            got=n.call(0xa174c2,[0x1725858]);assert got['address']==STOP
        assert native_states==list(struct.unpack('<'+'H'*count,u.mem_read(sequence+2,count*2)))
        sequences.append(dict(state_raw=state,command_raw=hex(command),
            original_callback_file=hex((callback&~1)-BASE),
            state_sequence_raw=native_states,next_command_raw=hex(next_command),
            configuration_all_zero_except_two_pointers=True,
            hardware_transition_executed=False))
    # The next table is runtime-built: do NOT read its BSS VA as a ROM FILE
    # offset or invent the62 dynamically generated rows. Execute the original
    # fixed246-row copy AFTER its omitted property reads, stopping before the
    # first dynamic callback. Only this explicitly incomplete prefix is used.
    got=n.run(0x25e95c,(0x25e984,),[
        (UC_ARM_REG_SP,STACK+0x8000),(UC_ARM_REG_LR,STOP|1)])
    assert got['address']==BASE+0x25e984
    assert u.mem_read(0x1870468,246*16)==cp[0xc8e410:0xc8e410+246*16]
    prefix=OWNER+0x6000
    got=n.call(0xa17354,[prefix,0x1870468,246]);assert got['address']==STOP
    got=n.call(0xa1735a,[prefix,0x11,0x3b])
    assert got['address']==STOP and u.reg_read(UC_ARM_REG_R0)==1
    actions=struct.unpack('<'+'H'*14,u.mem_read(prefix+0x16,28))
    expected=list(struct.unpack_from('<13H',cp,0xdd13ea))
    assert expected[-1]&0x8000 and not any(v&0x8000 for v in expected[:-1])
    # Original interpreter stores each nonterminal word by its encoded index;
    # the high-bit terminal word remains at its original input pointer/index.
    assert all(actions[v>>8]==v for v in expected[:-1])
    descriptor=struct.unpack('<6I',u.mem_read(prefix,24))
    assert descriptor[3:]==(0xed93ea,13,12)
    return dict(entry=entry,postprepare_cases=cases,
        original_transition_table_entries=320,transition_table=table_checks,
        original_sequence_callbacks=sequences,
        fixed_state_pair_prefix_rows=246,dynamic_state_pair_rows_unbound=62,
        original_state11_to_3b_actions=[hex(v) for v in expected],
        action_words_are_not_hardware_completion=True,
        full_native_prepare_or_hardware_state_request_executed=False,
        parameter_or_RAW_ownership_acquired=False,
        limits=['Postprepare entry is an explicit independent slice, not a successful prepare callback',
            'Raw state IDs and selector values have no established camera UI interpretation',
            'Native status update or configuration services stop before execution',
            'No sensor/readout request, frame IRQ, retained RAW or terminal fence is supplied'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--current-cp', type=Path,
        help='Compare selected original readout spans only; no loaded-source admission')
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    # Pin native queue's command dispatch, rather than assigning the handler.
    assert 0x3511a0 + 2 * cp[0x3511a0 + 0x403d - 0x4036] == 0x3511fa
    n = NativeCapture(cp)
    u = n.u
    fixture = n.fixture()
    cancelled = []
    for mask, action in itertools.product((0, 4, 0x8000, 0x20000, 0x4000000, 0x220402, 0xffffffff), (0, 1)):
        u.mem_write(OWNER, fixture)
        u.mem_write(OWNER + 0x2a0, words(mask))
        wire = bytes([5, 0, 0x3d, 0x40]) + words(0, 4) + bytes([action, 0, 0, 0])
        u.mem_write(WIRE, wire)
        before = bytearray(u.mem_read(OWNER, 0x1000))
        got = n.run(0x9d9686, (0x9d972e,), [(UC_ARM_REG_R4, OWNER),
            (UC_ARM_REG_R5, WIRE), (UC_ARM_REG_R6, WIRE + 12),
            (UC_ARM_REG_R10, 0x90030001), (UC_ARM_REG_SP, STACK + 0x8000)])
        expected = mask | 4 if action else mask & ~4
        struct.pack_into('<I', before, 0x2a0, expected)
        assert bytes(u.mem_read(OWNER, 0x1000)) == bytes(before)
        assert bytes(u.mem_read(WIRE, 16)) == wire
        assert got['args'][0] == OWNER + 0x278
        cancelled.append(dict(mask_before=hex(mask), cancel=bool(action), mask_after=hex(expected),
            stopped_before_native_arbitration=True))
    # Release of a controller with its native +0x1a set may send an additional
    # service notification. Stop there; do not make it return successfully.
    u.mem_write(OWNER, fixture)
    u.mem_write(OWNER + 0x292, b'\x01')
    u.mem_write(OWNER + 0x2a0, words(4))
    u.mem_write(WIRE, bytes([5, 0, 0x3d, 0x40]) + words(0, 4) + bytes(4))
    got = n.run(0x9d9686, (0x9dc38e,), [(UC_ARM_REG_R4, OWNER),
        (UC_ARM_REG_R5, WIRE), (UC_ARM_REG_R6, WIRE + 12),
        (UC_ARM_REG_R10, 0x90030001), (UC_ARM_REG_SP, STACK + 0x8000)])
    assert got['args'][:2] == [0x40000000, 0]
    assert struct.unpack('<I', u.mem_read(OWNER + 0x2a0, 4))[0] == 0
    release_service = dict(address=hex(got['address']), args=got['args'], executed=False)

    admission = []
    for mode, mask, suppress in itertools.product((0, 1, 10, 22),
            (0, 4, 0x8000, 0x20000, 0x40000, 0x100000, 2, 0x4000000), (0, 4)):
        u.mem_write(OWNER, fixture)
        # Native admission reads flags-context+4, not CAP owner+4 (callback).
        n.call(0x9d9470, [OWNER + 0x298, mode])
        u.mem_write(OWNER + 0x2a0, words(mask, suppress))
        # Explicit native request slot13, not an acquired frame/RAW ID.
        u.mem_write(OWNER + 0x158 + 13 * 16 + 0x14, b'\x01')
        u.mem_write(OWNER + 0x158 + 13 * 16 + 0x18, words(0x12345678, 0x90030001))
        # Native pure priority/selector execute together on the constructed owner.
        n.call(0x9d917c, [OWNER + 0x158])
        assert u.reg_read(UC_ARM_REG_R0) == 13
        # Separate original post-diagnostic arbitration slice, with explicit
        # selected request/context. The preceding timer/config logging is not
        # executed or made to return. No successful dispatch is fabricated.
        got = n.run(0x9da36e, (0xa3b61c, 0x9dc38e, 0x9da430), [
            (UC_ARM_REG_R5, OWNER + 0x278), (UC_ARM_REG_R4, 13),
            (UC_ARM_REG_R10, 0x12345678), (UC_ARM_REG_SP, STACK + 0x8000)])
        boundary = got['address'] - BASE
        expected_admission = mask & ~suppress == 0 and mode in (1, 22)
        assert (boundary == 0xa3b61c) == expected_admission, (mode, hex(mask), hex(suppress), hex(boundary))
        if boundary == 0xa3b61c:
            assert got['args'] == [4, 0x2000, 0, 0]
            # Explicit post-diagnostic slice, not a manufactured log return.
            got = n.run(0x9da394, (0x69f488,), [(UC_ARM_REG_R5, OWNER + 0x278),
                (UC_ARM_REG_R4, 13), (UC_ARM_REG_R10, 0x12345678),
                (UC_ARM_REG_SP, STACK + 0x8000)])
            assert u.mem_read(OWNER + 0x290, 2) == b'\x01\x01'
            result = 'admitted-before-diagnostic-and-separate-slice-reaches-timer'
        elif boundary == 0x9dc38e:
            assert mask & ~suppress
            result = 'native-cancellation-service-boundary'
        else:
            result = 'native-nonadmission-continuation'
        admission.append(dict(mode_raw=mode, reason_mask=hex(mask), suppression=hex(suppress),
            result=result, boundary_file=hex(boundary),
            separate_postdiagnostic_boundary_file=hex(got['address'] - BASE)
                if expected_admission else None, external_executed=False))
    report = dict(schema='OFFLINE_ORIGINAL_CAPTURE_TRANSITION/1', cp_sha256=digest,
        camera_io=False, firmware_candidate_written=False, original_constructor_executed=True,
        original_pointer_binding_slice_executed=True,
        timer_descriptor_is_synthetic=True,
        positive_request13_admission_cases=sum(x['result'].startswith('admitted-') for x in admission),
        timer_backup_binding_executed=False, cancel_masks=cancelled,
        release_extra_service=release_service, request13_admission=admission,
        limits=['Owners, configuration masks, request slots and modes are synthetic',
            'No lock, timer, IPC, allocation, sensor, image save or release service executes',
            'Selected request13 is not evidence of pre-trigger exposure or saved pixels',
            'Passing cancellation send is not evidence that CAP_MGR processed it',
            'No cached parameter refresh event or cross-task synchronization is supplied'])
    report['readout_admission']=readout_admission(cp)
    report['software_state_completion']=audit_completion(cp)
    report['resource_preparation']=audit_resources(cp)
    report['resource_service']=audit_resource_service(cp)
    report['backing_memory']=audit_backing(cp)
    if a.current_cp:
        current=a.current_cp.read_bytes()
        selected_spans=(*READOUT_SPANS,*COMPLETION_SPANS,*RESOURCE_SPANS,*SERVICE_SPANS,*BACKING_SPANS)
        if any(current[at:at+size]!=cp[at:at+size] for at,size in selected_spans):
            raise ValueError('Current CP differs in selected readout-admission FILE spans')
        report['current_readout_spans']=dict(sha256=hashlib.sha256(current).hexdigest(),
            spans=[dict(file_offset=hex(at),bytes=size) for at,size in selected_spans],
            loaded_source_proven=False)
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Original checks preserved; native cached-block allocation, worker/client reply and resource return verified on synthetic RAM. No camera I/O.')


if __name__ == '__main__':
    main()
