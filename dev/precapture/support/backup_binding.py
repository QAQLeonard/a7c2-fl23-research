"""Original primary BK4 binder and scalar getter on explicit test RAM.

The primary segment is a caller-selected model input. Native semaphore take/
release remain separate unexecuted boundaries; post-call slices do not supply
successful service returns. This does not identify the body's loaded table.
"""
import hashlib
import struct

from unicorn import arm_const as R
from .backup import scalar_segment
from .capture_native import BASE, STOP

BACKUP = 0x04000000
GLOBALS = 0x1a7e85c


def validate(raw):
    segment = scalar_segment(raw, 0, [0xfa0182])
    if segment['size'] != len(raw):
        raise ValueError('One complete BK4 segment required')
    if len(segment['records'][0xfa0182]['data']) != 8:
        raise ValueError('Exact 8-byte policy address required')
    return segment


def bind(native, raw):
    segment = validate(raw)
    native.u.mem_write(BACKUP, raw)
    got = native.call(0x455f9c, [BACKUP])
    assert got['address'] == STOP and native.u.reg_read(R.UC_ARM_REG_R0) == 0
    pointers = struct.unpack('<3I', native.u.mem_read(GLOBALS, 12))
    assert pointers == (BACKUP, BACKUP+0x100, BACKUP+segment['property_table'])
    assert bytes(native.u.mem_read(BACKUP, len(raw))) == raw
    return dict(segment_sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
        primary_pointers=[hex(v) for v in pointers], original_binder_executed=True,
        selected_primary_segment_is_fixture=True, loaded_body_binding_verified=False)


def query_body(native, *, return_file):
    """Enter the actual getter at its pending call; preserve caller registers."""
    boundary = BASE+0xae133a
    was_external = boundary in native.external
    native.external.discard(boundary)
    try:
        got = native.run(0xae133a, (0x4ed03c,))
        assert got['address'] == BASE+0x4ed03c
        # The post-take path overwrites R0 from the original callee-saved key.
        # No semaphore result or successful lock status is inserted.
        got = native.run(0xae1358, (0x4ed384,))
        assert got['address'] == BASE+0x4ed384
        # Original loads already hold the scalar in R4/R5. The post-release
        # tail copies those actual loaded words back to the original caller.
        got = native.run(0xae1384, (return_file,))
        assert got['address'] == BASE+return_file
        return native.u.reg_read(R.UC_ARM_REG_R0) | (native.u.reg_read(R.UC_ARM_REG_R1) << 32)
    finally:
        if was_external:
            native.external.add(boundary)
