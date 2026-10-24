"""Disable the reviewed screen-reader gate and clamp its ordinary setters off.

Only existing function instructions change. No new storage or global setter
hook is added. Offline entry replay does not establish full camera boot safety.
"""
import struct

SETTING=0x02cf0475
TRIGGER=0x02cf13c5
WINDOWS=((0x17b06ec,bytes.fromhex('807e805215eb0e14'),bytes.fromhex('00008052c0035fd6')),
         (0x1c11e20,bytes.fromhex('f303002a'),bytes.fromhex('33008052')),
         (0x2578610,bytes.fromhex('f303012a'),bytes.fromhex('33008052')),
         (0x2b2c1d4,bytes.fromhex('610240b9'),bytes.fromhex('21008052')))


def active(ap):
    return any(ap[at:at+len(old)]==new for at,old,new in WINDOWS)


def patch(ap,enabled=True):
    result=bytearray(ap)
    for at,old,new in WINDOWS:
        if ap[at:at+len(old)] not in (old,new):
            raise ValueError('Voice-guide disable instructions differ: '+hex(at))
        result[at:at+len(old)]=new if enabled else old
    return bytes(result)


def settings(ap,records):
    fields=((SETTING,0x57bb990,0x7d2,b'\1'),(TRIGGER,0x57bb9f0,0x7d5,b'\0'))
    result={}
    for key,at,attribute,value in fields:
        row=struct.unpack_from('<8I',ap,at)
        if row[:3]!=(3,key,0x10000) or row[6]!=attribute or len(records[0][key].data)!=1:
            raise ValueError('Voice-guide setting descriptor differs: '+hex(key))
        result[key]=value
    return result
