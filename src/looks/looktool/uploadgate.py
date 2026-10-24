"""Exact native LUT-upload gate checks and in-memory compatibility helpers.

The restored entry keeps Sony's existing repeat-upload condition. It does not
disable every upload or establish video correctness. No camera, filesystem or
assembler dependency is needed here.
"""

OFFSET = 0x13553a
NATIVE = bytes.fromhex('42f6b010')
FORCED = bytes.fromhex('f1f1e89f')

# VA 0x23d53e: movt/byte load/bit-6 branch, followed by the native no-repeat
# path. Check complete instructions, including both branch destinations.
_FOLLOWING = bytes.fromhex('c0f27910007d400611d4d8f8080024e0')

# Historical retry_windows assembler output, at CP VA = file offset+0x108000.
# These exact authored instructions are required only while FORCED can reach
# them. Restoring the native entry leaves their former storage unchanged.
_FORCED_STUBS = (
    (0xb2750e, bytes.fromhex('d4bbb5f8880140f20121884234d100f02cb8')),
    (0xb27578, bytes.fromhex('d8f80c00d0f8b00608b10df6f39f42f6b0100df6d89f')),
)


def _source(cp):
    if type(cp) not in (bytes, bytearray):
        raise TypeError('CP program must be bytes or bytearray')
    return bytes(cp)


def validate(cp):
    """Reject unknown entries, changed native context or reachable retry code.

    This is an edited-byte check, not recognition of a complete CP layout.
    Callers retain their independent layout, extent and source checks.
    """
    source = _source(cp)
    from . import uploadpending
    if uploadpending.active(source):
        uploadpending.normalize(source)
        return
    end = OFFSET + len(NATIVE)
    gate = source[OFFSET:end]
    if gate not in (NATIVE, FORCED):
        raise ValueError('Unknown LUT upload gate instruction')
    if source[end:end + len(_FOLLOWING)] != _FOLLOWING:
        raise ValueError('Native LUT upload gate context differs')
    if gate == FORCED:
        for at, expected in _FORCED_STUBS:
            if source[at:at + len(expected)] != expected:
                raise ValueError('Historical LUT upload retry trampoline differs')


def restore(cp):
    """Return native-gate bytes; change only the exact historical four bytes."""
    source = _source(cp)
    validate(source)
    if source[OFFSET:OFFSET + len(NATIVE)] == NATIVE:
        return source
    return source[:OFFSET] + NATIVE + source[OFFSET + len(NATIVE):]


def restore_legacy_for_test(cp):
    """Exact inverse for the isolated A/B test, never a normal install target.

    Native admission alone does not validate the dormant trampoline bytes.
    Check both complete historical stubs before making them reachable again.
    """
    source = _source(cp)
    validate(source)
    for at, expected in _FORCED_STUBS:
        if source[at:at + len(expected)] != expected:
            raise ValueError('Historical LUT upload retry trampoline differs')
    if source[OFFSET:OFFSET + len(FORCED)] == FORCED:
        return source
    return source[:OFFSET] + FORCED + source[OFFSET + len(FORCED):]


def legacy_hash_source(cp):
    """Normalize reviewed upload layouts solely for an existing strict hash.

    The returned bytes are a hash input, never a write candidate. Complete
    acknowledgment layouts are validated and reduced to their exact underlay;
    all other bytes still satisfy the caller's original canonical SHA check.
    """
    source = _source(cp)
    from . import uploadpending
    if uploadpending.active(source):
        source = uploadpending.normalize(source)
    validate(source)
    if source[OFFSET:OFFSET + len(FORCED)] == FORCED:
        return source
    return source[:OFFSET] + FORCED + source[OFFSET + len(FORCED):]
