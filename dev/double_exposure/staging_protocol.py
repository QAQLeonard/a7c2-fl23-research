"""Construct bounded native staging requests offline; no transport or loading."""
import struct
from staging_model import Plan

CREATE, PUT, ASSEMBLE, QUERY = 1, 2, 3, 4
HEADER = struct.Struct('<8sII16sQII32s')


def request(plan, transaction, operation, index=0):
    if not isinstance(plan, Plan):
        raise ValueError('Supply a validated transfer plan')
    if type(transaction) is not bytes or len(transaction) != 16 or not any(transaction):
        raise ValueError('Supply a nonzero 16-byte transaction identity')
    if type(operation) is not int or operation not in (CREATE, PUT, ASSEMBLE, QUERY):
        raise ValueError('Unknown staging operation')
    if type(index) is not int or index < 0:
        raise ValueError('Invalid chunk index')
    if (operation != PUT and index != 0) or (operation == PUT and index >= len(plan.chunks)):
        raise ValueError('Invalid chunk index')
    wire = HEADER.pack(b'A7STG001', operation, index, transaction, plan.size,
                       len(plan.chunks), 0, bytes.fromhex(plan.sha256))
    if operation == CREATE:
        wire += b''.join(bytes.fromhex(value) for value in plan.chunks)
    return wire
