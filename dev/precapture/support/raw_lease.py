"""Compose the new native lease with an already allocated original resource.

The caller supplies original CP execution and qualified synthetic storage.
This maps a component in an emulator only,never in a camera or deployable file.
"""
import hashlib
import struct
from elftools.elf.elffile import ELFFile

from unicorn import arm_const as R
from .elf import image_loader
from .capture_native import OWNER,STACK,STOP

CONTEXT,LOCK=0x33000000,0x33001000
REGIONS=((CONTEXT,0x5000),(0x1b30708&~4095,4096),(0x1b29194&~4095,4096))
NAMES=('precapture_raw_hold','precapture_raw_drop')


def load(native,path):
    u,symbols=image_loader(path,'thumb',NAMES,emulator=native.u)
    put=lambda at,v:u.mem_write(at,struct.pack('<I',v))
    put(0x1b30708,CONTEXT);put(0x1b30d30,CONTEXT+0x2000)
    put(CONTEXT,CONTEXT+0x2000+135*88)
    put(0x1b29194+107*4,LOCK)
    with path.open('rb') as f:
        elf=ELFFile(f)
        regions=tuple((p['p_vaddr'],p['p_memsz'],p['p_flags'])
            for p in elf.iter_segments() if p['p_type']=='PT_LOAD' and p['p_memsz'])
    return symbols,regions


def roundtrip(native,path,symbols,handle):
    u=native.u;lease=OWNER+0x1000
    record=0x22a4760+(handle&1023)*64
    before=bytes(u.mem_read(record,64))
    count=lambda:tuple(bytes(u.mem_read(record+8,2)))
    initial=count()
    def call(name):
        native.stops={STOP};native.observed.clear()
        for reg,value in zip((R.UC_ARM_REG_R0,R.UC_ARM_REG_R1,R.UC_ARM_REG_R2,R.UC_ARM_REG_R3),
            (lease,9,1,handle)):
            u.reg_write(reg,value)
        u.reg_write(R.UC_ARM_REG_CPSR,0x13)
        u.reg_write(R.UC_ARM_REG_SP,STACK+0x8000);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        u.emu_start(symbols[name],0xffffffff,count=50000)
        assert len(native.observed)==1 and native.observed[0]['address']==STOP
        assert u.reg_read(R.UC_ARM_REG_R0)==0
    call(NAMES[0]);held=count()
    assert held==(initial[0]+1,initial[1]+1)
    assert int.from_bytes(u.mem_read(lease,4),'little')==1
    assert struct.unpack('<3I',u.mem_read(lease+32,12))==(0,5,0x1180000)
    call(NAMES[1]);assert count()==initial
    assert bytes(u.mem_read(record,64))==before
    assert int.from_bytes(u.mem_read(lease,4),'little')==2
    return dict(compiled_adapter_executed=True,original_allocator_handle=hex(handle),
        original_record_before_restored=True,owner_pin_before=list(initial),
        owner_pin_held=list(held),owner_pin_after=list(count()),
        physical_RAW_lifetime_verified=False,installed=False,
        ELF_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
