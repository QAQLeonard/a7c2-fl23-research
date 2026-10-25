"""Offline request/receipt encoding; deliberately no USB or camera session."""
import hashlib
import struct

DEVICE = struct.Struct('<8sIIQQQII16s')


def device_request(instance, operation, request_id, *, epoch=0, generation=0, media=None, nonce=0):
    if type(instance) is not bytes or len(instance) != 16 or not any(instance):
        raise ValueError('Invalid instance identity')
    if media is None: media = 0xffffffff if operation == 1 else 0
    for value in (operation, request_id, epoch, generation, media, nonce):
        if type(value) is not int or value < 0:
            raise ValueError('Invalid integer field')
    if operation not in (1, 2, 3, 4) or not 0 < request_id < 2**64 or epoch >= 2**64 or generation >= 2**64:
        raise ValueError('Invalid operation or request identity')
    if media >= 2**32 or nonce > 0xffffff:
        raise ValueError('Invalid media or nonce')
    if operation == 1:
        if not epoch or not generation: raise ValueError('ARM needs epoch and media generation')
    elif any((epoch, generation, media, nonce)):
        raise ValueError('Only ARM carries capture configuration')
    return DEVICE.pack(b'A7DEX001', operation, 0, request_id, epoch, generation, media, nonce, instance)


def receipt(data, request):
    """Reject incomplete/stale/corrupt receipts; never infer retry permission."""
    if len(data) < 112 or data[:8] != b'A7ENT001' or data[-8:] != b'A7DONE01':
        raise ValueError('Incomplete receipt; preserve without replay')
    abi, kind = struct.unpack_from('<II', data, 8)
    if abi != 1 or kind not in (0, 1, 2) or any(data[16:32]):
        raise ValueError('Unknown receipt schema')
    expected_kind = 1 if request[:8] == b'A7STG001' else 2 if request[:8] == b'A7DEX001' else 0
    if kind != expected_kind:
        raise ValueError('Receipt kind differs from request')
    if data[32:64] != hashlib.sha256(request).digest():
        raise ValueError('Receipt belongs to a different request')
    status, size = struct.unpack_from('<iI', data, 64)
    expected = 112 if kind == 1 else 2832
    if size != expected or len(data) != 64 + 8 + size + 32 + 8:
        raise ValueError('Invalid receipt extent')
    if hashlib.sha256(data[:-40]).digest() != data[-40:-8]:
        raise ValueError('Receipt digest differs')
    payload = data[72:72 + size]
    if status in (0, -16004) and struct.unpack_from('<I', payload)[0] != 1:
        raise ValueError('Unknown native payload ABI')
    result = {'kind': kind, 'status': status, 'command_completed': True, 'photo_complete': False}
    if kind == 1:
        result['phase'], result['completed_chunks'] = struct.unpack_from('<II', payload, 8)
    elif kind == 2 and len(payload) == 2832:
        intent, review = struct.unpack_from('<II', payload, 8)
        phase = struct.unpack_from('<I', payload, 80)[0]
        result.update(intent=intent, review=review, phase=phase,
                      request_id=struct.unpack_from('<Q', payload, 16)[0],
                      operation=struct.unpack_from('<I', payload, 4)[0],
                      active=struct.unpack_from('<I', payload, 44)[0])
        result['photo_complete'] = status == 0 and not intent and not review and phase == 7
    return result
