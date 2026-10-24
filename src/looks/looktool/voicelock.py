"""Disable the reviewed screen-reader gate and clamp its ordinary setters off.

Existing functions keep speech off; native menu mode flags keep its controls
visible but unselectable. No global menu/setter hook or new storage is added.
"""
import struct

SETTING=0x02cf0475
TRIGGER=0x02cf13c5
WINDOWS=((0x17b06ec,bytes.fromhex('807e805215eb0e14'),bytes.fromhex('00008052c0035fd6')),
         (0x1c11e20,bytes.fromhex('f303002a'),bytes.fromhex('33008052')),
         (0x2578610,bytes.fromhex('f303012a'),bytes.fromhex('33008052')),
         (0x2b2c1d4,bytes.fromhex('610240b9'),bytes.fromhex('21008052')))
# Launch, on/off, speed, volume and shortcut. Native predicates at 0x1b76520
# and 0x1b765b0 distinguish nonzero (visible) from exactly 1 (selectable).
# Thirteen supported modes become 2; the final unsupported mode stays zero.
MENU_DESCRIPTORS=tuple((0x7d0+i,0x59925f0+i*0xb8) for i in range(5))
MENU_WINDOWS=tuple((at+0x2c,b'\1\0'*13,b'\2\0'*13) for _,at in MENU_DESCRIPTORS)


def active(ap):
    return any(ap[at:at+len(old)]==new for at,old,new in WINDOWS+MENU_WINDOWS)


def patch(ap,enabled=True):
    result=bytearray(ap)
    for attribute,at in MENU_DESCRIPTORS:
        if struct.unpack_from('<2I',ap,at)!=(attribute,attribute):
            raise ValueError('Voice-guide menu descriptor differs: '+hex(attribute))
    for at,old,new in WINDOWS+MENU_WINDOWS:
        if ap[at:at+len(old)] not in (old,new):
            raise ValueError('Voice-guide disable region differs: '+hex(at))
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
