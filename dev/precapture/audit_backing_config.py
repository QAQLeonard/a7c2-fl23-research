"""Original RAW policy-stream address reader, strictly offline.

Runs original address selection/page checks/copies on synthetic RAM. Optional
factory scalars are historical inputs, not the current body's configuration.
The native configuration query/lock and error logger remain boundaries.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_SP, UC_ARM_REG_LR)

from support.backup import factory_segments
from support.capture_native import NativeCapture, BASE, OWNER, STACK, STOP, words
from support.reference import SPECS
from support.backing_config import audit as audit_stream
from support.pool_notification import SCENARIOS as NOTIFICATION_SCENARIOS

TABLE = 0xcee830
PAGE_ROOT = OWNER + 0x8000
DATA = 0x09a08e00
SPANS = ((0x496044, 0xbc), (TABLE-BASE, 128), (0x4f6b54, 0x40),
    (0x509ddc, 0x24), (0x5130c8, 0x154), (0x51660c, 0x160),
    (0xb12cd8, 14), (0xb173e0, 0x80))


def audit(cp, factory=None):
    n = NativeCapture(cp)
    u = n.u
    visited = set()
    u.hook_add(UC_HOOK_CODE, lambda cpu, at, size, user: visited.add(at))
    for at, size in ((0x1a8c000, 4096), (0x1a93000, 4096),
                     (DATA & ~4095, 4096)):
        u.mem_map(at, size)
    table = [struct.unpack_from('<4Q', cp, TABLE-BASE+i*32) for i in range(4)]
    assert table == [(0x500000000, 0x80000000, 0x80000000, 0x7e000000),
        (0x800000000, 0, 0, 0x80000000),
        (0xfe000000, 0xfe000000, 0xfe000000, 0x500000),
        (0xfe800000, 0xfe800000, 0xfe800000, 0x500000)]

    def put(at, value):
        u.mem_write(at, words(value))

    def get(at):
        return struct.unpack('<I', u.mem_read(at, 4))[0]

    def begin(destination=OWNER, size=8):
        # Execute the original entry, but stop BEFORE the real configuration
        # getter. Its locking, runtime pointer and value are never stubbed.
        got = n.run(0x496044, (0xae133a,), [
            (UC_ARM_REG_R0, destination), (UC_ARM_REG_R1, size),
            (UC_ARM_REG_SP, STACK+0x8000), (UC_ARM_REG_LR, STOP | 1)])
        assert got['args'][0] == 0xfa0182

    def select(value):
        begin()
        # Explicit separate post-query slice. This is not a successful
        # configuration-service return or a boot continuation.
        return n.run(0x49605c, (0x4960be, 0x4b440), [
            (UC_ARM_REG_R0, value & 0xffffffff),
            (UC_ARM_REG_R1, value >> 32)])

    values = {0, 0xffffffffffffffff, 0x4110c4000, 0x809a08e00}
    for start, _, _, size in table:
        values.update((start-1, start, start+1, start+size-1, start+size))
    selections = []
    for value in sorted(values):
        expected = next(((i, target+value-start) for i, (start, target, _, size)
            in enumerate(table) if start <= value < start+size), None)
        got = select(value)
        if expected is None:
            assert got['address'] == BASE+0x4b440
        else:
            assert got['address'] == BASE+0x4960be
            assert got['args'][:2] == [expected[1], 0]
        selections.append(dict(input_u64=hex(value),
            matched_row=expected[0] if expected else None,
            translated_u32=hex(expected[1]) if expected else None,
            stopped_before='page_check' if expected else 'error_logger'))

    # Synthetic first-level translation entries qualify only these fixture
    # accesses. Run the original ARM page-attribute helper, not a success stub.
    put(0x1a93d44, PAGE_ROOT)
    reads, writes = [], []
    def observe_read(cpu, access, address, size, value, user):
        if (DATA & ~4095) <= address < (DATA & ~4095)+4096:
            reads.append((address, size))
    def observe_write(cpu, access, address, size, value, user):
        if OWNER <= address < OWNER+0x100:
            writes.append((address, size))
    u.hook_add(UC_HOOK_MEM_READ, observe_read)
    u.hook_add(UC_HOOK_MEM_WRITE, observe_write)
    payload = bytes((i*29+7) & 255 for i in range(128))
    u.mem_write(DATA, payload)
    streams = []
    for descriptor, admitted in ((0, False), (2, True), (0x1002, True),
                                  (0xa, False)):
        put(PAGE_ROOT+(DATA >> 20)*4, descriptor)
        put(0x1a8c578, 0)
        u.mem_write(OWNER, b'\xa5'*128)
        reads.clear(); writes.clear()
        begin()
        n.run(0x49605c, (), [(UC_ARM_REG_R0, DATA), (UC_ARM_REG_R1, 8)])
        assert u.reg_read(UC_ARM_REG_R0) == (0 if admitted else 0xffffffff), (
            hex(descriptor), hex(u.reg_read(UC_ARM_REG_R0)))
        assert get(0x1a8c574) == (DATA if admitted else 0)
        assert get(0x1a8c578) == (8 if admitted else 0)
        assert bytes(u.mem_read(OWNER, 128)) == (
            payload[:8]+b'\xa5'*120 if admitted else b'\xa5'*128)
        assert bool(reads) == admitted and bool(writes) == admitted
        first = dict(page_descriptor_raw=hex(descriptor), accepted=admitted,
            source_reads=[list(x) for x in reads], destination_writes=[list(x) for x in writes])
        if admitted:
            # A subsequent original read advances its persistent stream offset.
            # Its requested extent is explicit fixture input, not native bounds.
            reads.clear(); writes.clear()
            begin(OWNER+8, 20)
            n.run(0x49605c, (), [(UC_ARM_REG_R0, DATA), (UC_ARM_REG_R1, 8)])
            assert u.reg_read(UC_ARM_REG_R0) == 0 and get(0x1a8c578) == 28
            assert bytes(u.mem_read(OWNER, 128)) == payload[:28]+b'\xa5'*100
            first['second_original_copy_bytes'] = 20
            first['stream_offset_after_two_reads'] = 28
        streams.append(first)

    # A start address inside row2 can still copy across that row's end.
    # Both pages below are explicit synthetic storage. The original reader
    # does not check start+length against its address-classification extent.
    crossing = 0xfe4ffffc
    u.mem_map(crossing & ~4095, 8192)
    put(PAGE_ROOT+(crossing >> 20)*4, 2)
    u.mem_write(crossing, b'boundary')
    put(0x1a8c578, 0)
    u.mem_write(OWNER, b'\xa5'*16)
    begin()
    n.run(0x49605c, (), [(UC_ARM_REG_R0, crossing), (UC_ARM_REG_R1, 0)])
    assert u.reg_read(UC_ARM_REG_R0) == 0 and get(0x1a8c578) == 8
    assert bytes(u.mem_read(OWNER, 16)) == b'boundary'+b'\xa5'*8
    assert crossing < table[2][0]+table[2][3] < crossing+8

    historical = None
    if factory is not None:
        name, segments = factory_segments(factory, [0xfa0182])
        historical = dict(source_name=name, source_sha256=hashlib.sha256(factory).hexdigest(),
            current_body_or_selected_segment_proven=False, segments=[])
        for segment in segments:
            value = int.from_bytes(segment['records'][0xfa0182]['data'], 'little')
            got = select(value)
            historical['segments'].append(dict(offset=hex(segment['offset']),
                scalar_u64=hex(value), reaches_original_page_check=got['address']==BASE+0x4960be,
                translated_u32=hex(got['args'][0]) if got['address']==BASE+0x4960be else None))
    # Include every original instruction reached by this audit in the optional
    # retained-file comparison. External stops are observed, never executed.
    executed = {at-BASE for at in visited if BASE <= at < BASE+len(cp)
        and at not in (BASE+0xae133a, BASE+0x4b440)}
    uncovered = sorted(at for at in executed
        if not any(start <= at < start+size for start,size in SPANS))
    assert not uncovered, [hex(at) for at in uncovered]
    return dict(schema='OFFLINE_ORIGINAL_BACKING_CONFIG_READER/1', camera_io=False,
        original_instruction_addresses_covered=len(executed),
        CP_query_executed=False, native_configuration_lock_executed=False,
        runtime_configuration_supplied=False, firmware_candidate_written=False,
        source_table=[dict(input_start=hex(a), output_start=hex(b),
            third_word_raw=hex(c), byte_extent=hex(d)) for a,b,c,d in table],
        range_cases=selections, synthetic_original_page_and_copy_cases=streams,
        synthetic_extent_crossing=dict(start=hex(crossing), copy_bytes=8,
            classification_end=hex(table[2][0]+table[2][3]),
            original_copy_crossed_classification_end=True,
            physical_memory_accessed=False),
        historical_factory_scalar=historical,
        physical_backing_ownership_verified=False, physical_precapture_complete=False,
        limits=['Post-query inputs are explicit synthetic or historical values, never native service success',
            'Page tables and bytes copied are synthetic, not current CP RAM or RAW pixels',
            'Only the start address is classified here; neither the stream length nor a terminal pixel lease is established',
            'No equivalence between DmmCfg.bin extent definitions and the fa0182 policy stream is proven',
            'A historical factory segment is not the selected or current runtime property'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--factory', type=Path)
    parser.add_argument('--current-cp', type=Path)
    parser.add_argument('--config', type=Path,
        help='Retained original CP DmmCfg; execute its native parser on synthetic RAM')
    parser.add_argument('--notification', choices=NOTIFICATION_SCENARIOS,
        help='With --config: execute original notification/lock paths on a synthetic CPU')
    parser.add_argument('--backup-segment', type=Path,
        help='With --config: bind one retained BK4 segment and execute the original scalar getter body')
    parser.add_argument('--lease-adapter',type=Path,
        help='With --config: execute a compiled native RAW lease against the original allocator output')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.notification and not args.config:
        parser.error('--notification requires --config')
    if args.backup_segment and not args.config:
        parser.error('--backup-segment requires --config')
    if args.lease_adapter and not args.config:
        parser.error('--lease-adapter requires --config')
    cp = args.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Exact original target CP required')
    report = audit(cp, args.factory.read_bytes() if args.factory else None)
    selected_spans = list(SPANS)
    if args.config:
        report['retained_configuration_stream'] = stream_audit = audit_stream(
            cp, args.config.read_bytes(), notification=args.notification,
            primary_backup=args.backup_segment.read_bytes() if args.backup_segment else None,
            lease_adapter=args.lease_adapter)
        selected_spans.extend((s['offset'], s['bytes']) for s in stream_audit['source_spans'])
    report['original_CP_sha256'] = hashlib.sha256(cp).hexdigest()
    report['selected_FILE_spans'] = [dict(offset=hex(at), bytes=size) for at,size in selected_spans]
    if args.current_cp:
        current = args.current_cp.read_bytes()
        if len(current) != len(cp) or any(current[at:at+size] != cp[at:at+size] for at,size in selected_spans):
            raise ValueError('Current CP differs in selected configuration-reader FILE spans')
        report['current_FILE_spans_match'] = True
        report['current_CP_sha256'] = hashlib.sha256(current).hexdigest()
        report['loaded_CP_RAM_verified'] = False
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(status='OFFLINE_ORIGINAL_CONFIG_READER_PASSED',
        range_cases=len(report['range_cases']), page_cases=len(report['synthetic_original_page_and_copy_cases']),
        config_stream_reads=len(stream_audit['original_read_slices']) if args.config else 0,
        camera_io=False, physical_backing_ownership_verified=False)))


if __name__ == '__main__':
    main()
