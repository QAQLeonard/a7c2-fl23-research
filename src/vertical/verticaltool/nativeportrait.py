"""Independent portrait banks at original IDs, using the native M4 route.

Build only from this body's horizontal banks and the existing drawn geometry.
The native orientation loader selects _23 versus _32; AP layout references and
gauge instructions remain original. No donor firmware/resource bank is bundled.
"""
import struct
from hashlib import sha256
from . import imagebank,portraitbank,portraitlines

MAGIC=b'A7NP2301'


def owned(value):
    return bool(value and len(value)>=72 and value[-8:]==MAGIC
        and sha256(value[:-72]).digest()==value[-40:-8])


def prepare(source,group):
    original=portraitbank.baseline(source,group) if group<2 else bytes(source)
    parsed=imagebank.inspect(original,group)
    replacements={row['index']:row for row in portraitlines.specs() if row['group']==group}
    # Keep the original count, IDs and missing entries. Only metadata positions
    # and relative payload pointers change in this independent output file.
    result=bytearray(original[:parsed['base']])
    result[16:16+2*parsed['count']]=b'\xff\xff'*parsed['count']
    payloads=[];metadata=[]
    for index,row in sorted(parsed['records'].items()):
        at=len(result);pointer=(at-parsed['base'])//4
        if pointer>=65535:raise ValueError('Portrait metadata exceeds native 16-bit pointer range')
        spec=replacements.get(index)
        width,height=spec['portrait'] if spec else (row['width'],row['height'])
        # Preserve native nine-slice options, including the Creative Look panel.
        options=original[row['at']+12:row['at']+row['field']]
        payload=(portraitlines.compress(portraitlines.raster(spec)) if spec else
            original[row['start']:row['start']+row['size']])
        result.extend(struct.pack('<IIHH',0x1a000000+group*8192+index,row['flags'],width,height))
        result.extend(options);result.extend(struct.pack('<II',len(payload),0))
        struct.pack_into('<H',result,16+2*index,pointer)
        metadata.append((at,row['field']));payloads.append(payload)
    for (at,field),payload in zip(metadata,payloads):
        result.extend(bytes((-len(result))%4))
        struct.pack_into('<I',result,at+field+4,len(result)-at-4)
        result.extend(payload)
    result.extend(bytes((-len(result))%4))
    payload=bytes(result)
    return payload+sha256(original).digest()+sha256(payload).digest()+MAGIC


def targets(sources):
    return [prepare(source,group) for group,source in enumerate(sources)]
