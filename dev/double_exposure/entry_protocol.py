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
    result = {'kind': kind, 'status': status, 'command_completed': True, 'photo_complete': False, 'arm_accepted': False}
    if kind == 1:
        result['phase'], result['completed_chunks'] = struct.unpack_from('<II', payload, 8)
    elif kind == 2 and len(payload) == 2832:
        intent, review = struct.unpack_from('<II', payload, 8)
        phase = struct.unpack_from('<I', payload, 80)[0]
        result.update(intent=intent, review=review, phase=phase,
                      request_id=struct.unpack_from('<Q', payload, 16)[0],
                      operation=struct.unpack_from('<I', payload, 4)[0],
                      active=struct.unpack_from('<I', payload, 44)[0])
        pipeline_abi, step, pipeline_intent, active, pipeline_review, queued, processing, attached = struct.unpack_from('<8I', payload, 32)
        generation, epoch = struct.unpack_from('<QQ', payload, 88)
        result.update(pipeline_abi=pipeline_abi, step=step, pipeline_intent=pipeline_intent,
                      pipeline_review=pipeline_review, queued=queued, processing=processing,
                      attached=attached, epoch=epoch, generation=generation,
                      media=struct.unpack_from('<I', payload, 84)[0],
                      device_status=struct.unpack_from('<i', payload, 24)[0],
                      pipeline_status=struct.unpack_from('<i', payload, 64)[0],
                      backend_error=struct.unpack_from('<i', payload, 68)[0])
        result['arm_accepted'] = (status == 0 and not intent and not review and
            pipeline_abi == 1 and not pipeline_intent and not pipeline_review and
            not processing and active == 1 and attached == 1 and phase == 1 and
            result['operation'] == 1 and result['device_status'] == 0 and
            result['pipeline_status'] == 0 and bool(epoch) and bool(generation))
        raw_path = payload[1688:2200]
        if b'\0' not in raw_path: raise ValueError('Unterminated result path')
        result['result_path'] = raw_path.split(b'\0', 1)[0].decode('ascii')
        result['catalog_uid'] = struct.unpack_from('<I', payload, 2760)[0]
        result['catalog_uid_valid'] = struct.unpack_from('<I', payload, 2764)[0]
        result['photo_complete'] = status == 0 and not intent and not review and phase == 7
        if result['photo_complete']:
            published = payload[2248:2760]
            if b'\0' not in published: raise ValueError('Unterminated published path')
            published = published.split(b'\0', 1)[0].decode('ascii')
            output_bytes, published_bytes = struct.unpack_from('<QQ', payload, 2224)
            if (pipeline_abi != 1 or pipeline_review or pipeline_intent or processing or
                result['device_status'] or result['pipeline_status'] or
                struct.unpack_from('<I', payload, 2212)[0] != 6 or
                result['catalog_uid_valid'] != 1 or not result['result_path'] or
                published != result['result_path'] or not output_bytes or output_bytes != published_bytes):
                raise ValueError('Incomplete native photo completion evidence')
    return result
