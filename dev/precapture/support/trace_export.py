"""Fixed trace packets and reconstruction from local bytes; no transport/I/O."""
import struct
from .trace import BYTES,decode

MODE=0xe2
PACKET=struct.Struct('<BBHI12sI')


def request(offset,nonce):
    if type(offset) is not int or not 0<=offset<BYTES or offset%12:
        raise ValueError('Canonical lane offset required')
    if type(nonce) is not int or not 0<nonce<=0xffffffff:
        raise ValueError('Nonzero 32-bit lane nonce required')
    return PACKET.pack(MODE,0,0,offset,bytes(12),nonce)


def reconstruct(packets,expected):
    """No partial success, sorting, deduplication or automatic retries.

    Frozen-lane lifetime and actual message ownership remain caller duties.
    Valid transport bytes are not evidence of physical CP execution.
    """
    parts=[]
    if len(packets)!=(BYTES+11)//12:raise ValueError('Exact packet count required')
    for index,raw in enumerate(packets):
        if not isinstance(raw,bytes) or len(raw)!=PACKET.size:raise ValueError('Exact packet extent required')
        mode,status,count,offset,data,nonce=PACKET.unpack(raw)
        wanted=index*12;n=min(12,BYTES-wanted)
        if (mode,status,count,offset,nonce)!=(MODE,1,n,wanted,expected['nonce']) or any(data[n:]):
            raise ValueError('Refused, changed, duplicated, reordered or truncated packet')
        parts.append(data[:n])
    raw=b''.join(parts)
    result=decode(raw,expected)
    result['export_packets']=len(packets)
    result['native_export_lifetime_proven']=False
    return raw,result
