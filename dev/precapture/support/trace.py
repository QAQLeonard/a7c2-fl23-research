"""Decode immutable owner-lane bytes only; no USB, memory access or live proof."""
import struct

MAGIC,ABI,CAPACITY,HEADER,RECORD=0x31544350,1,64,64,48
BYTES=HEADER+CAPACITY*RECORD
KINDS={1:'pool',2:'request',3:'reply',4:'release',5:'exposure_begin',
       6:'exposure_end',7:'s2',8:'diagnostic'}
BINDING=('source_tag','epoch_lo','epoch_hi','owner','capacity','clock_domain','nonce')


def decode(raw,expected):
    if len(raw)!=BYTES:raise ValueError('Exact lane extent required')
    words=struct.unpack_from('<16I',raw)
    if words[:3]!=(MAGIC,ABI,BYTES):raise ValueError('Unknown trace header')
    bound=dict(zip(BINDING,words[3:10]))
    if set(expected)!=set(BINDING) or bound!=expected:raise ValueError('Trace binding differs')
    if not all(bound[k] for k in ('source_tag','owner','capacity','clock_domain','nonce')):
        raise ValueError('Missing lane binding')
    if not(bound['epoch_lo'] or bound['epoch_hi']) or not 1<=bound['capacity']<=CAPACITY:
        raise ValueError('Invalid epoch/capacity')
    count,frozen,overflow,busy,res0,res1=words[10:]
    if count>bound['capacity'] or frozen!=1 or overflow not in (0,1) or busy or res0 or res1:
        raise ValueError('Trace is not a finalized owner-lane snapshot')
    records=[]
    for i in range(count):
        values=struct.unpack_from('<12I',raw,HEADER+i*RECORD)
        if values[0]!=i+1 or values[1] not in KINDS:raise ValueError('Broken record sequence/kind')
        guard=2166136261
        for value in values[:-1]:guard=((guard^value)*16777619)&0xffffffff
        if values[-1]!=guard:raise ValueError('Torn or corrupted record')
        records.append(dict(sequence=values[0],kind=KINDS[values[1]],generation=values[2],
            ticket=values[3],handle=values[4],clock_raw=values[5],context_raw=values[6],
            detail=list(values[7:11])))
    # No writes into an uncommitted slot may be hidden by a shortened header.
    if any(raw[HEADER+count*RECORD:]):raise ValueError('Uncommitted/trailing slot is not empty')
    return dict(binding=bound,records=records,overflow=bool(overflow),
        owner_recording_frozen=True,complete_recording=not overflow,
        native_owner_or_storage_binding_proven=False,physical_capture_proven=False,
        clock_is_raw_32bit=True,sensor_or_resource_quiescence_proven=False)
