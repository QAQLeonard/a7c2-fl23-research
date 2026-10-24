"""Reviewed 2.01 capture settings for the owner's factory-recovery contract."""
import struct

# Descriptor attribute is one greater than the runtime model attribute.
FIELDS = ((0x02cf02c9,0x57b83d0,0x5d9,b'\0'),   # actual mechanical shutter
          (0x02cf02d9,0x57b8570,0x5e8,b'\0'),   # still shutter: mechanical
          (0x02cf02d1,0x57b84f0,0x5e4,b'\1'))   # silent mode: off


def mechanical(ap,records):
    result={}
    for key,offset,attribute,value in FIELDS:
        row=struct.unpack_from('<8I',ap,offset)
        if row[:3]!=(3,key,0x10000) or row[6]!=attribute or len(records[0][key].data)!=1:
            raise ValueError('Capture setting descriptor differs: '+hex(key))
        result[key]=value
    return result
