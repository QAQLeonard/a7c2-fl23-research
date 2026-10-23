"""Original2.01 resource construction and page-root binding, offline only.

Actual instructions execute with synthetic image-offset inputs in an emulator.
Stops before native resource registration, table dereference or kernel calls.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn import arm64_const as R
from support.boundaries import BoundaryRunner
from support.kernel_mapping import SYMBOL_OFFSETS,module_walk_step

SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
BASE=0xffffff8008080000
MEM,STACK,STOP=0x30000000,0x40000000,0x50000000


def audit(raw,symbols):
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Exact original kernel required')
    names={parts[2]:int(parts[0],16) for line in symbols.splitlines() if len(parts:=line.split())>=3}
    for name,offset in SYMBOL_OFFSETS.items():
        if names.get(name)!=BASE+offset:raise ValueError('Recovered symbol offset differs: '+name)
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(BASE,(len(raw)+4095)&~4095);u.mem_write(BASE,raw)
    for at,size in ((MEM,65536),(STACK,65536),(STOP,4096)):u.mem_map(at,size)
    runner=BoundaryRunner(u,[SimpleNamespace(calls={})],stop=STOP,stack=STACK)
    cases=[]
    for physical_base in (0x400080000,0x500080000):
        offset=BASE-physical_base
        u.mem_write(BASE+SYMBOL_OFFSETS['kimage_voffset'],struct.pack('<Q',offset))
        got=runner.run(BASE+0x5b3898,(BASE+0x5b3988,),inputs=[
            (R.UC_ARM64_REG_X19,BASE),(R.UC_ARM64_REG_SP,STACK+0x8000)])
        assert got['at']==BASE+0x5b3988
        code=struct.unpack('<2Q',bytes(u.mem_read(BASE+0x60dca8,16)))
        data=struct.unpack('<2Q',bytes(u.mem_read(BASE+0x60dce8,16)))
        assert code==(physical_base,physical_base+SYMBOL_OFFSETS['__init_begin']-1)
        assert data==(physical_base+SYMBOL_OFFSETS['_sdata'],physical_base+SYMBOL_OFFSETS['_end']-1)
        cases.append(dict(kind='original_resource_extent',physical_base_fixture=hex(physical_base),
            code_extent=[hex(v) for v in code],data_extent=[hex(v) for v in data],
            resource_registration_executed=False))
    # Original vmalloc_to_page loads init_mm.pgd, then indexes that root.
    # Stop BEFORE indexing the root; its input is explicitly synthetic.
    pointer=MEM+0x1000
    u.mem_write(BASE+SYMBOL_OFFSETS['init_mm']+0x40,struct.pack('<Q',pointer))
    for virtual in (0xffffff80005c9000,0xffffff80005e3000):
        got=runner.run(BASE+SYMBOL_OFFSETS['vmalloc_to_page'],(BASE+0xf0a1c,),inputs=[
            (R.UC_ARM64_REG_X0,virtual),(R.UC_ARM64_REG_SP,STACK+0x8000)])
        assert got['at']==BASE+0xf0a1c and u.reg_read(R.UC_ARM64_REG_X1)==pointer
        assert u.reg_read(R.UC_ARM64_REG_X2)==(virtual>>30)&511
        cases.append(dict(kind='original_init_mm_root_load',virtual_fixture=hex(virtual),
            pgd_member_offset=0x40,stopped_before_root_dereference=True))
    for at in (0xffffffc000002000,0xffffffc000003000):u.mem_map(at,4096)
    u.mem_write(BASE+SYMBOL_OFFSETS['memstart_addr'],struct.pack('<Q',0x400000000))
    words=[0x400002003,0x400003003,0x440001000|3|0x10|0x400]
    ram=[dict(start=0x400000000,end=0x4ffffffff)]
    for virtual in (0xffffff80005c9000,0xffffff80005e3000):
        u.mem_write(pointer+((virtual>>30)&511)*8,struct.pack('<Q',words[0]))
        u.mem_write(0xffffffc000002000+((virtual>>21)&511)*8,struct.pack('<Q',words[1]))
        u.mem_write(0xffffffc000003000+((virtual>>12)&511)*8,struct.pack('<Q',words[2]))
        got=runner.run(BASE+SYMBOL_OFFSETS['vmalloc_to_page'],(BASE+0xf0a80,),inputs=[
            (R.UC_ARM64_REG_X0,virtual),(R.UC_ARM64_REG_SP,STACK+0x8000)])
        assert got['at']==BASE+0xf0a80 and u.reg_read(R.UC_ARM64_REG_X0)==words[2]
        steps=[module_walk_step(virtual,0x400001000,words[:i],ram) for i in range(4)]
        assert steps[-1]['physical']==0x440001000
        assert [s['physical'] for s in steps[:3]]==[0x400001000+((virtual>>30)&511)*8,
            0x400002000+((virtual>>21)&511)*8,0x400003000+((virtual>>12)&511)*8]
        cases.append(dict(kind='original_three_level_module_walk',virtual_fixture=hex(virtual),
            independent_planner_matches=True,stopped_before_page_object_conversion=True,
            real_page_tables=False,native_memory_read=False))
    return dict(schema='OFFLINE_KERNEL_MAPPING_SOURCE/1',cases=cases,kernel_sha256=SHA,
        exact_symbol_offsets_qualified=True,physical_camera_IO=False,
        limits=['Resource arithmetic uses synthetic image-offset words;no current kernel byte identity',
            'init_mm.pgd contents are not presumed equal to swapper_pg_dir',
            'No memory read path, actual physical address, root contents or page mapping admitted'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('kernel','symbols','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=audit(a.kernel.read_bytes(),a.symbols.read_text())
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(len(result['cases']),'original resource/root-binding cases;no native read or resource service')


if __name__=='__main__':main()
