"""Full7 six-look data and preview adapters. Offline, exact-source only."""
import struct
from .native import decode
from .firmware import sha,transition,apply
from . import uploadgate

AP_SHA='690b5f17f21cba5c7cd937e6feb0f6967ea2793c0b4ca6fc1fffdcaa1ed0d761'
CP_SWITCH_SHA='100e286f3d4c308dc4619d8d9630fba3dd7432d73bdbf7eb169c13aa2d30fc58'
CP_SHA='90d1ed6d47df21c881936816647973b1562764458122eb72869e60b1a624900b'
TABLE_FILE=0x8000
PREFIX_VA=0x110000
TABLE_VA=PREFIX_VA+32
TABLE_BYTES=1215
MAGIC=0x364c3741
VERSION=0x10006
ORDER=['Classic Neg.','Classic Chrome','Nostalgic Neg.','Eterna','GR Positive Film','GR Negative Film']

def fnv(raw):
    value=2166136261
    for byte in raw:value=((value^byte)*16777619)&0xffffffff
    return value

def prefix(tables):
    if len(tables)!=6:raise ValueError('Six full-precision tables required')
    for raw in tables:decode(raw)
    return struct.pack('<8I',MAGIC,VERSION,*[fnv(raw) for raw in tables])+b''.join(tables)

def read_tables(cp):
    if len(cp)<TABLE_FILE+32+6*TABLE_BYTES:raise ValueError('Truncated full7 table storage')
    header=struct.unpack_from('<8I',cp,TABLE_FILE)
    if header[:2]!=(MAGIC,VERSION):raise ValueError('Unknown six-table header')
    tables=[cp[TABLE_FILE+32+i*TABLE_BYTES:TABLE_FILE+32+(i+1)*TABLE_BYTES] for i in range(6)]
    for i,raw in enumerate(tables):
        decode(raw)
        if fnv(raw)!=header[i+2]:raise ValueError('Six-table checksum mismatch')
    return tables

def replace_tables(ap,cp,replacements):
    if not replacements or any(type(slot) is not int or slot not in range(1,7) for slot in replacements):
        raise ValueError('Select distinct custom slots 1..6')
    if sha(ap)!=AP_SHA or sha(uploadgate.legacy_hash_source(cp))!=CP_SHA:
        raise ValueError('Six-table adapter requires the exact documented full7-v4 AP/CP pair')
    read_tables(cp);target=bytearray(cp);spans=[]
    for slot,raw in replacements.items():
        decode(raw);index=slot-1
        at=TABLE_FILE+32+index*TABLE_BYTES;check=TABLE_FILE+8+index*4
        target[at:at+TABLE_BYTES]=raw;struct.pack_into('<I',target,check,fnv(raw))
        spans.extend([(at,TABLE_BYTES),(check,4)])
    read_tables(bytes(target))
    before={'appFw.so':ap,'cpapp-b.bin':cp};after={'appFw.so':ap,'cpapp-b.bin':bytes(target)}
    target=uploadgate.restore(bytes(target))
    if target[uploadgate.OFFSET:uploadgate.OFFSET+4]!=cp[uploadgate.OFFSET:uploadgate.OFFSET+4]:
        spans.append((uploadgate.OFFSET,4))
    after['cpapp-b.bin']=target
    regions={'appFw.so':[],'cpapp-b.bin':spans}
    forward,reverse=transition(before,after,regions),transition(after,before,regions)
    if apply(apply(before,forward),reverse)!=before:raise ValueError('Six-table inverse differs')
    return forward,reverse,after

def retry_windows(asm):
    # Retain the historical dormant storage for exact layout compatibility,
    # but keep Sony's original entry and native upload conditions active.
    entry,second,legacy=0xc2f50e,0xc2f578,0xc2f586
    first=asm('\n'.join([f'cbnz r4,0x{legacy:x}','ldrh.w r0,[r5,#0x188]',
        'movw r1,#0x201','cmp r0,r1',f'bne 0x{legacy:x}',f'b.w 0x{second:x}']),entry)
    tail=asm('\n'.join(['ldr.w r0,[r8,#0xc]','ldr.w r0,[r0,#0x6b0]',f'cbz r0,0x{legacy:x}',
        'b.w 0x23d56c','movw r0,#0x29b0','b.w 0x23d53e']),second)
    if len(first)!=18 or len(tail)!=22:raise ValueError('Retry instruction extent differs')
    return [(uploadgate.OFFSET,uploadgate.NATIVE),(entry-0x108000,first),(second-0x108000,tail)]

def prepare_preview_retry(ap,cp):
    from .hooks import assembler
    if sha(ap)!=AP_SHA or sha(cp)!=CP_SWITCH_SHA:
        raise ValueError('Preview repair requires the exact six-look switch-v2 source')
    read_tables(cp);target=bytearray(cp);asm=assembler();windows=retry_windows(asm)
    if cp[0x13553a:0x13553e]!=asm('movw r0,#0x29b0',0x23d53a):raise ValueError('Hook source differs')
    _,length,start=struct.unpack_from('<3I',cp,0x20124)
    for at,data in windows:
        if at!=0x13553a and any(cp[at:at+len(data)]):raise ValueError('Retry storage is occupied')
        if not start<=at+0x108000<at+0x108000+len(data)<=start+length:raise ValueError('Retry exceeds loaded text')
        target[at:at+len(data)]=data
    if sha(uploadgate.legacy_hash_source(bytes(target)))!=CP_SHA:raise ValueError('Preview repair target fingerprint differs')
    before={'appFw.so':ap,'cpapp-b.bin':cp};after={'appFw.so':ap,'cpapp-b.bin':bytes(target)}
    regions={'appFw.so':[],'cpapp-b.bin':[(at,len(data)) for at,data in windows]}
    forward,reverse=transition(before,after,regions),transition(after,before,regions)
    if apply(apply(before,forward),reverse)!=before:raise ValueError('Preview repair inverse differs')
    return forward,reverse,after
