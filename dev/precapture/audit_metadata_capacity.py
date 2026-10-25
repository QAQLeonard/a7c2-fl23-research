"""Execute the original metadata-ring initializer/pop/return, offline only.

The ring contains resource-management indices, not image buffers. All arena
contents below are synthetic. No CP query, lock, native configuration read,
pixel address, device operation or deployment artifact is produced.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
import zipfile

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn import arm_const as R
from support.capture_native import NativeCapture, BASE, OWNER, STACK, STOP, words
from support.reference import SPECS

ARENA = 0x22a4760
HEAD, TAIL, COUNT, RING = 0x22b4720, 0x22b4728, 0x22b4730, 0x22b4738
SHARED = 0x32000000
SPANS = ((0xb16314, 0x146), (0xb16686, 0x58), (0xb1671a, 0x5e),
         (0xb15b34, 12), (0x516d00, 0x100), (0xb15d32, 0x18c),
         (0x4f6b50, 4))


def audit(cp):
    native = NativeCapture(cp)
    cpu = native.u
    cpu.mem_map(0x1a8b000, 8192)
    cpu.mem_map(ARENA & ~4095, 0x12000)
    cpu.mem_map(SHARED, 0x40000)
    get = lambda at: struct.unpack('<I', cpu.mem_read(at, 4))[0]
    put = lambda at, value: cpu.mem_write(at, words(value))
    accesses = []

    def code(_, at, size, user):
        if at in (STOP, BASE + 0xb14220, BASE + 0x45d204):
            return  # NativeCapture stops BEFORE these external boundaries.
        if not any(BASE + a <= at < at + size <= BASE + a + n for a, n in SPANS):
            raise AssertionError('Unqualified original instruction span: ' + hex(at))

    def access(_, kind, at, size, value, user):
        # A firmware constant may be read, but never modified. Every mutable
        # location must be our explicitly mapped metadata/stack/global fixture.
        mutable = ((ARENA, 0x10800), (0x1a8b000, 8192), (SHARED, 0x40000),
                   (OWNER, 0x10000), (STACK, 0x10000))
        if any(a <= at < at + size <= a + n for a, n in mutable):
            accesses.append((kind, at, size))
        elif kind != UC_MEM_WRITE and BASE <= at < at + size <= BASE + len(cp):
            return
        else:
            raise AssertionError('Outside metadata-only fixture: ' + hex(at))

    cpu.hook_add(UC_HOOK_CODE, code)
    cpu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, access)
    cpu.mem_write(ARENA, b'\xa5' * 0x10800)
    # Execute the real source's arena arithmetic, stop BEFORE the native
    # backing/configuration initializer. No successful return is supplied.
    got = native.run(0xb16314, (0xb14220,), [
        (R.UC_ARM_REG_R0, 0), (R.UC_ARM_REG_R1, ARENA),
        (R.UC_ARM_REG_SP, STACK + 0x8000), (R.UC_ARM_REG_LR, STOP | 1)])
    assert got['address'] == BASE + 0xb14220
    assert [get(at) for at in (0x1a8c558, 0x1a8c55c, 0x1a8c560,
                              0x1a8c564, 0x1a8c568)] == [ARENA, HEAD, TAIL, COUNT, RING]
    # Independent post-configuration slice. Explicit zero pre-reserved-record
    # fixture; the omitted configuration reader was not executed or mocked.
    put(0x1a8c30c, 0)
    native.stops = {BASE + 0xb16398}
    native.observed.clear()
    cpu.emu_start(BASE + 0xb163ae | 1, 0xffffffff, count=250000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == BASE + 0xb16398
    assert len(native.observed) == 1 and cpu.reg_read(R.UC_ARM_REG_R0) == 0
    assert (get(HEAD), get(TAIL), get(COUNT)) == (0, 1023, 1023)
    assert struct.unpack('<1023H', cpu.mem_read(RING, 2046)) == tuple(range(1023))
    for slot in range(1023):
        assert bytes(cpu.mem_read(ARENA + slot * 64, 64)) == words(0xffffffff, 0xffffffff) + bytes(56)
    # Index1023 is the controls themselves, not a 1024th record. Do not
    # classify its nonzero initialized words as an extra available slot.
    assert ARENA + 1023 * 64 == HEAD
    out = OWNER + 0x100
    # Consume every real free-index entry, including refusal at empty. No
    # backing allocator or image memory is involved in the entire sequence.
    for slot in range(1023):
        cpu.mem_write(out, b'\xa5' * 4)
        native.call(0xb16686, [out])
        assert cpu.reg_read(R.UC_ARM_REG_R0) == 0
        assert bytes(cpu.mem_read(out, 2)) == struct.pack('<H', slot)
        assert get(COUNT) == 1022 - slot
    before = bytes(cpu.mem_read(ARENA, 0x10800))
    cpu.mem_write(out, b'\xa5' * 4)
    native.call(0xb16686, [out])
    assert cpu.reg_read(R.UC_ARM_REG_R0) == 0xffffceff
    assert bytes(cpu.mem_read(out, 4)) == b'\xa5' * 4
    assert bytes(cpu.mem_read(ARENA, 0x10800)) == before
    # Return the same indices through original instructions, including the
    # tail wrap1023->0; a 1024th entry must be refused without mutation.
    for slot in range(1023):
        native.call(0xb1671a, [slot])
        assert cpu.reg_read(R.UC_ARM_REG_R0) == 0 and get(COUNT) == slot + 1
    before = bytes(cpu.mem_read(ARENA, 0x10800))
    native.call(0xb1671a, [0])
    assert cpu.reg_read(R.UC_ARM_REG_R0) == 0xffffffff
    assert bytes(cpu.mem_read(ARENA, 0x10800)) == before
    # Cover all1024 possible starting indices and model the observed count907
    # as synthetic metadata state. This is not a replay of physical RAM.
    for head in range(1024):
        tail = (head + 907) & 1023
        put(HEAD, head); put(TAIL, tail); put(COUNT, 907)
        cpu.mem_write(RING + head * 2, struct.pack('<H', 17))
        native.call(0xb16686, [out])
        assert (get(HEAD), get(TAIL), get(COUNT)) == ((head + 1) & 1023, tail, 906)
        native.call(0xb1671a, [17])
        assert (get(HEAD), get(TAIL), get(COUNT)) == ((head + 1) & 1023, (tail + 1) & 1023, 907)
    # AP command0b/subcommand61 supplies a block used for shared bookkeeping.
    # First stop at the real message allocation, then independently enter the
    # post-reply slice with an explicitly synthetic block, not a service return.
    got = native.run(0xb15d32, (0x45d204,), [
        (R.UC_ARM_REG_SP, STACK + 0x8000), (R.UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][0] == 0x8f013a and got['args'][2:] == [16, 1]
    cpu.mem_write(SHARED, b'\xa5' * 0x40000)
    accesses.clear()
    native.stops = {STOP}; native.observed.clear()
    cpu.reg_write(R.UC_ARM_REG_R6, SHARED)
    cpu.emu_start(BASE + 0xb15d82 | 1, 0xffffffff, count=500000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == STOP and len(native.observed) == 1
    pointers = ((0x1a8bf70, 0x28), (0x1a8bf9c, 0x199c),
                (0x1a8c0ec, 0x1ec0), (0x1a8c314, 0xfac4),
                (0x1a8c330, 0x1bac8), (0x1a8c334, 0x3ca48))
    for pointer, offset in pointers:
        assert get(pointer) == SHARED + offset
    for offset, marker in ((0x24, 0x51434f4c), (0x1998, 0x51564452),
                           (0x1ebc, 0x4c545845), (0xfac0, 0x474f4c50),
                           (0x1bac4, 0x53434341), (0x3ca44, 0x56415350),
                           (0x3ca8c, 0x4c444e45)):
        assert get(SHARED + offset) == marker
    for offset, size in ((0x1ec0, 0xdc00), (0xfac4, 0xc000), (0x3ca48, 0x44)):
        assert bytes(cpu.mem_read(SHARED + offset, size)) == bytes(size)
    for index in range(1023):
        at = SHARED + 0x1bac8 + index * 0x84
        assert bytes(cpu.mem_read(at, 2)) == bytes(2)
        assert bytes(cpu.mem_read(at + 2, 0x82)) == b'\xa5' * 0x82
    assert get(SHARED) == 0xa5a5a5a5 and get(SHARED + 0x3ca90) == 0xa5a5a5a5
    # The original address helper is literally BX LR; it validates no range.
    assert cp[0x4f6b50:0x4f6b54] == bytes.fromhex('1eff2fe1')
    return dict(camera_IO=False,original_initializer_executed_after_omitted_configuration=True,
        initial_free_metadata_indices=1023,metadata_record_bytes=64,ring_positions=1024,
        original_pop_cases=2048,original_return_cases=2048,
        source_arena=hex(ARENA),source_head_tail_count=[hex(v) for v in (HEAD, TAIL, COUNT)],
        original_empty_full_refusals_preserve_metadata=True,
        original_post_reply_shared_bookkeeping_layout_executed=True,
        shared_bookkeeping_offsets=[hex(offset) for _, offset in pointers],
        shared_bookkeeping_max_write_end='0x3ca90',
        shared_address_helper_is_identity_only=True,
        pixels_read_or_allocated=False,native_configuration_or_lock_executed=False,
        physical_pool_provenance_verified=False,physical_RAW_capacity=None,
        conclusions=['count describes free management records, not free RAW frames',
            'A count907 observation cannot determine bytes, RAW formats or retained-photo capacity',
            'Repeated head/tail values can wrap; this ring is not a capture-generation fence',
            'AP shared-block binding and actual backing-node ownership remain separate prerequisites'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--current-snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = args.cp.read_bytes()
    if hashlib.sha256(original).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Exact original CP2.01 required')
    with zipfile.ZipFile(args.current_snapshot) as archive:
        if archive.namelist().count('cpapp-b.bin') != 1:
            raise ValueError('Ambiguous CP source')
        current = archive.read('cpapp-b.bin')
    if len(current) != len(original) or any(current[a:a+n] != original[a:a+n] for a,n in SPANS):
        raise ValueError('Current metadata code differs')
    report = audit(original)
    report.update(original_CP_sha256=hashlib.sha256(original).hexdigest(),
                  current_CP_sha256=hashlib.sha256(current).hexdigest(),
                  selected_current_FILE_spans_match=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2); stream.write('\n')
    print('Original1023-record initialization,2048 pops/returns and shared bookkeeping layout passed; no pixels or camera operation')


if __name__ == '__main__':
    main()
