"""Original DMM stream parsing and root-node construction on synthetic RAM.

The real property query/lock is an omitted boundary on every read. Explicit
post-query inputs exercise the original reader; no service return is stubbed.
Configured roots describe resources, not acquired physical image buffers.
"""
import hashlib
import struct

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn import arm_const as R

from .capture_native import NativeCapture, BASE, OWNER, STACK, STOP, words
from .dmm_config import config_tables, CP_CONFIG_SHA256
from . import pool_notification
from . import backup_binding
from . import raw_lease

ARENA, STREAM, PAGE_ROOT = 0x22a4760, 0x09a08e00, 0x32000000
REGIONS = ((0x1a8b000, 8192), (0x1a93000, 4096), (0x174e000, 4096),
    (0x1b20000, 4096), (0x22a4000, 0x318000),
    (STREAM & ~4095, 0xc000), (PAGE_ROOT, 0x4000))
BOUNDARIES = (0x496044, 0xb1563e, 0xb15688)


def merged_spans(spans):
    result = []
    for at, size in sorted(spans):
        if result and at <= result[-1][0]+result[-1][1]:
            start, length = result[-1]
            result[-1] = (start, max(start+length, at+size)-start)
        else:
            result.append((at, size))
    return result


def audit(cp, raw, *, notification=None, primary_backup=None, lease_adapter=None):
    if hashlib.sha256(raw).hexdigest() != CP_CONFIG_SHA256:
        raise ValueError('Exact retained original CP DMM configuration required')
    expected = config_tables(raw)
    if primary_backup is not None:
        backup_binding.validate(primary_backup)
    if notification is not None:
        if notification not in pool_notification.SCENARIOS:
            raise ValueError('Unsupported synthetic notification scenario')
    n = NativeCapture(cp, cpu_model=R.UC_CPU_ARM_CORTEX_A9 if notification or lease_adapter else None)
    u = n.u
    backup_regions = ((backup_binding.BACKUP, (len(primary_backup)+4095) & ~4095),
        (backup_binding.GLOBALS & ~4095, 4096)) if primary_backup is not None else ()
    regions = (*REGIONS, *backup_regions,
        *(pool_notification.REGIONS if notification is not None else ()),
        *(raw_lease.REGIONS if lease_adapter is not None else ()))
    for at, size in regions:
        if not any(a<=at and at+size-1<=b for a,b,_ in u.mem_regions()):u.mem_map(at, size)
    put = lambda at, value: u.mem_write(at, words(value))
    get = lambda at: struct.unpack('<I', u.mem_read(at, 4))[0]
    u.mem_write(STREAM, raw)
    put(0x1a93d44, PAGE_ROOT)
    put(PAGE_ROOT+(STREAM >> 20)*4, 2)
    source_spans = set()
    diagnostic_writes = []
    notification_state_writes = []
    source_end = BASE+len(cp)
    mutable = (*regions, (OWNER, 0x10000), (STACK, 0x10000))
    component_regions=()

    def code(cpu, at, size, user):
        if any(flags&1 and start<=at<at+size<=start+length for start,length,flags in component_regions):
            return
        if at in {STOP, *(BASE+b for b in (*BOUNDARIES, 0xb1474c))}:
            return
        if at == BASE+0xae133a and primary_backup is None:
            return
        if not BASE <= at < at+size <= source_end:
            raise AssertionError('Outside original instruction source')
        source_spans.add((at-BASE, size))

    def access(cpu, kind, at, size, value, user):
        if BASE <= at < at+size <= source_end:
            if kind == UC_MEM_WRITE:
                # Exact original allocation-diagnostic halfword in initialized
                # data. This is a guest RAM copy, never an instruction patch.
                pc = cpu.reg_read(R.UC_ARM_REG_PC)
                event = dict(address=hex(at), bytes=size, writer_file_offset=hex(pc-BASE), value=value)
                if notification is not None and at == 0x11f7330 and size == 4 and pc == BASE+0xb17488:
                    notification_state_writes.append(event)
                else:
                    assert at == 0x120614c and size == 2 and pc in (
                            BASE+0xb145a0, BASE+0xb147a0, BASE+0xb14c16), (
                        'Outside allocation diagnostic cell', hex(at), hex(pc))
                    diagnostic_writes.append(event)
            source_spans.add((at-BASE, size))
        elif any(start <= at < at+size <= start+length for start,length in mutable):
            assert kind != UC_MEM_WRITE or not STREAM <= at < STREAM+len(raw), 'Config modified'
            if primary_backup is not None and backup_binding.BACKUP <= at < backup_binding.BACKUP+len(primary_backup):
                assert kind != UC_MEM_WRITE, 'Bound BK4 bytes modified'
        elif any(start<=at<at+size<=start+length for start,length,_ in component_regions):
            assert kind!=UC_MEM_WRITE,'Generated component writes outside its explicit state'
        else:
            raise AssertionError('Outside explicit synthetic storage: '+hex(at))

    u.hook_add(UC_HOOK_CODE, code)
    u.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, access)
    binding = backup_binding.bind(n, primary_backup) if primary_backup is not None else None
    if lease_adapter is not None:
        lease_symbols,component_regions=raw_lease.load(n,lease_adapter)
    got = n.run(0xb16314, BOUNDARIES, [(R.UC_ARM_REG_R0, 0),
        (R.UC_ARM_REG_R1, ARENA), (R.UC_ARM_REG_SP, STACK+0x8000),
        (R.UC_ARM_REG_LR, STOP | 1)], instruction_budget=500000)
    reads = []
    while got['address'] == BASE+0x496044:
        destination, size = got['args'][:2]
        offset = get(0x1a8c578)
        if len(reads) >= 4096 or offset+size > len(raw):
            raise AssertionError('Original parser exceeded retained stream')
        reads.append(dict(offset=offset, bytes=size, destination=hex(destination)))
        got = n.run(0x496044, (0xae133a,))
        assert got['args'][0] == 0xfa0182
        # Use an explicit value fixture or execute the bound snapshot getter
        # body. Neither path supplies native semaphore completion.
        if binding is None:
            inputs = [(R.UC_ARM_REG_R0, STREAM), (R.UC_ARM_REG_R1, 8)]
        else:
            value = backup_binding.query_body(n, return_file=0x49605c)
            if value != 0x800000000+STREAM:
                raise ValueError('Bound policy address differs from explicit stream fixture')
            inputs = ()
        got = n.run(0x49605c, BOUNDARIES, inputs, instruction_budget=500000)
    assert got['address'] == STOP and u.reg_read(R.UC_ARM_REG_R0) == 0
    assert get(0x1a8c578) == len(raw) and sum(r['bytes'] for r in reads) == len(raw)
    assert bytes(u.mem_read(STREAM, len(raw))) == raw

    # Independent host-format decoder versus actual original parser outputs.
    for table, groups in ((0x23a50e0, expected['roots']), (0x23a5180, expected['groups'])):
        for index, group in enumerate(groups):
            at = table+index*80
            assert bytes(u.mem_read(at+4, 76)) == raw[group['offset']+4:group['offset']+80]
            child = get(at)
            for c in group['children']:
                assert bytes(u.mem_read(child, 20)) == raw[c['offset']:c['offset']+20]
                child += 20
            assert get(child+8) == 0xffffffff
        assert get(table+len(groups)*80) == 0
    for index, unit in enumerate(expected['units']):
        at = 0x25b7ee8+index*8
        assert get(at) == unit['type']
        values = struct.unpack('<'+'I'*(len(unit['extent_ids'])+1),
            u.mem_read(get(at+4), 4*(len(unit['extent_ids'])+1)))
        assert values == (*unit['extent_ids'], 0xffffffff)
    end = 0x25b7ee8+len(expected['units'])*8
    assert get(end) == 0xffffffff and get(end+4) == 0
    assert bytes(u.mem_read(0x1b200c7, 44)) == raw[-44:]
    assert [get(at) for at in (0x22b4720, 0x22b4728, 0x22b4730)] == [0, 1023, 1023]
    for slot in range(1023):
        assert bytes(u.mem_read(ARENA+slot*64, 64)) == words(0xffffffff, 0xffffffff)+bytes(56)

    roots = []
    head = get(0x1a8c0cc)
    for group in expected['roots']:
        for child in group['children']:
            offset, encoded, kind, size, flags = child['words']
            node = get(head+kind*8)
            assert node and get(head+kind*8+4) == node
            assert [get(node+n) for n in (8, 12, 16, 20, 36)] == [0, encoded >> 16, offset, size, kind]
            assert get(node+4) == flags and get(node+0x28) == 0
            roots.append(dict(kind_raw=hex(kind), address_words=[offset, encoded >> 16],
                configured_bytes=size, flags_raw=hex(flags), pixel_accessed=False))

    # Contrast the prior arbitrary fixture type with a type actually present
    # in the original stream. Stop before the unresolved parent allocation.
    attempts = []
    out = OWNER+0x100
    actual = next(unit for unit in expected['units'] if unit['type'] == 0x50504)
    assert actual['extent_ids'] == [0xeb]
    for kind in (0x505, actual['type']):
        before = get(0x22b4730)
        got = n.run(0xb1645a, (0xb1474c,), [(R.UC_ARM_REG_R0, kind),
            (R.UC_ARM_REG_R1, 0x31), (R.UC_ARM_REG_R2, out),
            (R.UC_ARM_REG_SP, STACK+0x8000), (R.UC_ARM_REG_LR, STOP | 1)])
        parent_boundary = got['address'] == BASE+0xb1474c
        assert parent_boundary == (kind == actual['type'])
        assert get(out) == 0xffffffff
        assert get(0x22b4730) == before-int(parent_boundary)
        if not parent_boundary:
            assert got['address'] == STOP and u.reg_read(R.UC_ARM_REG_R0) == 0xfffffffd
        else:
            assert get(ARENA) == kind and bytes(u.mem_read(ARENA+12, 2)) == b'\x01\x00'
        attempts.append(dict(requested_type_raw=hex(kind), parent_boundary=parent_boundary,
            metadata_before=before, metadata_after=get(0x22b4730), handle_published=False,
            complete_allocation=False))
    parent = n.run(0xb1474c, (0xb155f4, 0xb1746c), instruction_budget=500000)
    assert parent['address'] == STOP and u.reg_read(R.UC_ARM_REG_R0) == 0
    handle = get(out)
    assert handle == 0x8400 and get(0x22b4730) == 1022
    parent_result = dict(boundary=hex(parent['address']), args=parent['args'],
        handle_raw=hex(get(out)), metadata_remaining=get(0x22b4730))
    lease_roundtrip = raw_lease.roundtrip(n,lease_adapter,lease_symbols,handle) if lease_adapter is not None else None
    descriptor, number = OWNER+0x400, OWNER+0x500
    n.call(0xb16a52, [handle, 1, descriptor, number])
    assert u.reg_read(R.UC_ARM_REG_R0) == 0
    assert bytes(u.mem_read(number, 2)) == b'\x01\x00'
    address_low, address_high, byte_size = struct.unpack('<3I', u.mem_read(descriptor, 12))
    assert address_high == 5 and byte_size == 0x1180000
    assert address_low+byte_size <= 0x40000000
    assert bytes(u.mem_read(ARENA+9, 1)) == b'\x01'
    n.call(0xb16b4c, [handle])
    assert u.reg_read(R.UC_ARM_REG_R0) == 0
    assert bytes(u.mem_read(ARENA+9, 1)) == b'\x00'
    if notification is not None:
        pool_notification.prepare(n, notification)
    released = n.run(0xb16bd6, (0xb1746c, 0xb155f4),
        [(R.UC_ARM_REG_R0, handle), (R.UC_ARM_REG_SP, STACK+0x8000),
            (R.UC_ARM_REG_LR, STOP | 1)], instruction_budget=500000)
    assert released['address'] == BASE+0xb1746c and released['args'][0] == 0x23
    assert get(0x22b4730) == 1023
    local_release = dict(descriptor_words=[address_low, address_high, byte_size],
        descriptor_pinned_and_unpinned=True, metadata_records_after_release=1023,
        stopped_before_notification=True, notification_executed=False,
        physical_pixel_lease_or_terminal_completion_verified=False)
    report = dict(schema='OFFLINE_ORIGINAL_DMM_BACKING_STREAM/1', camera_io=False,
        configuration_sha256=CP_CONFIG_SHA256, configuration_bytes=len(raw),
        original_read_slices=reads, omitted_property_queries=len(reads),
        property_query_and_lock_executed=False, property_address_is_synthetic=True,
        roots=len(expected['roots']), groups=len(expected['groups']), units=len(expected['units']),
        independent_decoded_tables_match=True, original_root_nodes=roots,
        metadata_records_initialized=1023, allocation_boundary_cases=attempts,
        parent_continuation=parent_result,
        local_release=local_release,
        synthetic_allocation_diagnostic_writes=diagnostic_writes,
        source_spans=[dict(offset=at, bytes=size) for at,size in merged_spans(source_spans)],
        physical_backing_ownership_verified=False, physical_precapture_complete=False,
        limits=['Retained DmmCfg bytes are accepted by original CP parsing on synthetic RAM',
            'The selected current fa0182 value, stream bytes and boot ownership remain unobserved',
            'Root extents are configuration data, not acquired RAW pixel buffers',
            'Parent-backed allocation and local release execute only on fixture metadata',
            'Notification, native task locks, physical pixels and terminal release remain unverified'])
    if notification is not None:
        report['native_notification'] = pool_notification.finish(n, notification)
        report['native_notification']['initialized_guest_state_writes'] = notification_state_writes
        report['native_notification']['continued_from_same_local_release'] = True
        report['native_notification']['available_metadata_records'] = get(0x22b4730)
        assert get(0x22b4730) == 1023
        report['limits'][-1] = 'Physical CPU/task/IRQ ownership, clocks, messages and terminal release remain unverified'
        report['source_spans'] = [dict(offset=at, bytes=size)
            for at,size in merged_spans(source_spans)]
    if binding is not None:
        assert bytes(u.mem_read(backup_binding.BACKUP, len(primary_backup))) == primary_backup
        report['primary_backup_binding'] = binding
        report['omitted_property_queries'] = 0
        report['property_query_body_executed'] = True
        report['property_address_is_synthetic'] = False
        report['property_address_from_bound_snapshot'] = True
        report['stream_storage_is_synthetic'] = True
        report['omitted_property_semaphore_calls'] = 2*len(reads)
        report['limits'][1] = 'Primary-bank selection and policy-stream storage are explicit model inputs; current loaded binding remains unobserved'
    if lease_roundtrip is not None:
        report['compiled_native_lease']=lease_roundtrip
        report['source_spans']=[dict(offset=at,bytes=size) for at,size in merged_spans(source_spans)]
    return report
