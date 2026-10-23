"""Original Sony-kernel physical-read boundaries; never reads native memory.

Synthetic registers/words qualify guards and address arithmetic only. No
memblock service, current-task register, user copy or device operation runs.
This is not admission to use /dev/mem, mmap, or a guessed physical address.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R
from support.boundaries import BoundaryRunner

SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
NATIVE=0xffffff8008080000
CODE,MEM,STACK,STOP=0x10000000,0x30000000,0x40000000,0x50000000


def audit(raw):
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Exact original Sony kernel required')
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(CODE,(len(raw)+4095)&~4095);u.mem_write(CODE,raw)
    for at,size in ((MEM,0x10000),(STACK,0x10000),(STOP,4096)):
        u.mem_map(at,size)
    A=lambda at:CODE+at
    calls={A(0x2780d0):'valid_phys_addr_range',A(0x16898):'memblock_is_region_memory',
        A(0x168a4):'memblock_is_map_memory',A(0x278168):'__arch_copy_to_user'}
    runner=BoundaryRunner(u,[SimpleNamespace(calls=calls)],stop=STOP,stack=STACK)
    cases=[];position=MEM+0x1000;destination=MEM+0x2000
    # The original branch target encoder is independently checked, not just
    # a recovered symbol name attached to a guessed FILE coordinate.
    for at,target in ((0x2780d0,0x16888),(0x16898,0xf6d50),(0x168a4,0xf6cc8),(0x278168,0x1efa00)):
        instruction=struct.unpack_from('<I',raw,at)[0]
        assert instruction>>26==0b100101
        imm=instruction&0x3ffffff
        if imm&(1<<25):imm-=1<<26
        assert at+imm*4==target
    for physical,count in ((0,0),(0x400001234,64),(0xffffff80005c9000,16)):
        u.mem_write(position,struct.pack('<Q',physical))
        got=runner.call(A(0x2780a0),(MEM,destination,count,position))
        assert got['at']==A(0x2780d0) and got['args'][:2]==[physical,count]
        cases.append(dict(kind='read_requires_physical_range_service',physical=hex(physical),bytes=count,
            stopped_before_service=True))
    for physical,count in ((0x400001234,64),(0,1),(0xffffff80005c9000,16)):
        got=runner.call(A(0x16888),(physical,count))
        assert got['at']==A(0x16898) and got['args'][:2]==[physical,count]
        cases.append(dict(kind='range_requires_memblock_region',physical=hex(physical),bytes=count,
            no_memblock_call=True))

    # Independent post-service inputs; never resume a mocked successful call.
    def frame(size):
        sp=STACK+0x8000-size
        u.mem_write(sp,bytes(size));u.mem_write(sp+8,struct.pack('<Q',STOP));return sp
    for region_result in (0,1):
        got=runner.run(A(0x1689c),inputs=[(R.UC_ARM64_REG_X0,region_result),
            (R.UC_ARM64_REG_X19,0x400001234),(R.UC_ARM64_REG_SP,frame(32)),(R.UC_ARM64_REG_LR,STOP)])
        assert got['at']==(A(0x168a4) if region_result else STOP)
        if not region_result:assert got['args'][0]==0
        else:assert got['args'][0]==0x400001234
        cases.append(dict(kind='independent_region_result',input=region_result,
            reaches_second_memblock_service=bool(region_result),service_executed=False))
    for map_result in (0,1,7,-1):
        got=runner.run(A(0x168a8),inputs=[(R.UC_ARM64_REG_X0,map_result),
            (R.UC_ARM64_REG_SP,frame(32)),(R.UC_ARM64_REG_LR,STOP)])
        assert got['at']==STOP and got['args'][0]==int(map_result!=0)
        cases.append(dict(kind='independent_map_memory_result',input=map_result,
            original_boolean=bool(map_result),service_executed=False))

    memstart=CODE+0x5699c8
    for valid,physical,count,start in ((0,0x400001234,64,0x400000000),
            (1,0x400001234,0,0x400000000),(1,0x400001234,64,0x400000000),
            (1,0x400001ff0,64,0x400000000),(1,0x400001234,4096,0x400000000),
            (1,0x3ffffff00,64,0x400000000)):
        u.mem_write(memstart,struct.pack('<Q',start));u.mem_write(position,struct.pack('<Q',physical))
        got=runner.run(A(0x2780d4),(A(0x27810c),),inputs=[(R.UC_ARM64_REG_X0,valid),
            (R.UC_ARM64_REG_X19,count),(R.UC_ARM64_REG_X20,position),(R.UC_ARM64_REG_X21,physical),
            (R.UC_ARM64_REG_X22,destination),(R.UC_ARM64_REG_SP,frame(80)),(R.UC_ARM64_REG_LR,STOP)])
        reaches=bool(valid and count and physical>=start)
        assert got['at']==(A(0x27810c) if reaches else STOP),(valid,hex(physical),count,got)
        if reaches:
            assert u.reg_read(R.UC_ARM64_REG_X1)==(0xffffffc000000000|(physical-start))
            assert u.reg_read(R.UC_ARM64_REG_X3)==min(count,4096-(physical&4095))
        else:assert got['args'][0]==((0 if valid and not count else -14)&((1<<64)-1))
        cases.append(dict(kind='independent_valid_range_input',valid=valid,physical=hex(physical),bytes=count,
            memstart_fixture=hex(start),reaches_before_current_task=reaches,task_or_copy_executed=False))
    return dict(schema='OFFLINE_KERNEL_PHYSICAL_READ_BOUNDARIES/1',cases=cases,kernel_sha256=SHA,
        physical_camera_IO=False,native_device_open=False,physical_memory_read=False,
        original_branch_targets_independently_checked=True,
        limits=['Synthetic independent post-service values are not successful native memblock returns',
            'No native RAM region, module-to-physical mapping, loaded text or kernel identity established',
            'Stops before current-task register reads and user copy; mmap/write paths are not admitted',
            'Never subtract module virtual addresses from a presumed physical offset',
            'No CP send or pre-capture implementation'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kernel',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();report=audit(a.kernel.read_bytes())
    with a.output.open('x') as f:json.dump(report,f,indent=2)
    print(len(report['cases']),'original kernel physical-read slices; no native memory/device operation')


if __name__=='__main__':main()
