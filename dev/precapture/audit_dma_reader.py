"""Original kernel DMA ioctl lifetime boundaries, offline on synthetic RAM.

This evaluates a proposed CP-reader alternative, not a device operator. Copy,
transfer, scheduler and lock calls always stop BEFORE execution. Independent
post-operation slices never claim those operations completed on a camera.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from types import SimpleNamespace
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,arm64_const as R
from support.boundaries import BoundaryRunner

SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
CODE,MEM,STACK,STOP=0x10000000,0x30000000,0x40000000,0x50000000


def audit(raw):
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Exact original2.01 kernel required')
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(CODE,(len(raw)+4095)&~4095);u.mem_write(CODE,raw)
    for address in (MEM,STACK,STOP):u.mem_map(address,65536)
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);calls={}
    # Decode every direct service call in these original functions, not just
    # the calls a chosen positive input is expected to visit.
    for instruction in decoder.disasm(raw[0x2a2eb8:0x2a3090],0x2a2eb8):
        if instruction.mnemonic=='bl':calls[CODE+instruction.address]=instruction.op_str
        if instruction.mnemonic in ('blr','br'):raise ValueError('Unexpected indirect native service')
    expected={0x2a2ed4:0x4239d0,0x2a2ee4:0x457a8,0x2a2ef0:0x423c80,
        0x2a2f68:0x1ef640,0x2a2fe4:0x2a20c8,0x2a2ff8:0x422e18,
        0x2a3008:0x4239d0,0x2a3028:0x423c80,0x2a3040:0x4239d0,0x2a3058:0x423c80}
    assert calls=={CODE+at:f'#{target:#x}' for at,target in expected.items()}
    runner=BoundaryRunner(u,[SimpleNamespace(calls=calls)],stop=STOP,stack=STACK)
    A=lambda at:CODE+at
    cases=[]
    for direction,size in ((0,24),(1,24),(0,0)):
        u.mem_write(STACK,b'\xa5'*65536)
        got=runner.call(A(0x2a2f50),())
        assert got['at']==A(0x2a2f68) and got['args'][2]==24
        frame=u.reg_read(R.UC_ARM64_REG_X29)
        # Typed copy result supplied to a separately entered post-copy slice;
        # the user-copy service itself was not run or made to return success.
        u.mem_write(frame+0x30,struct.pack('<4BIQQ',0,4,direction,0, size,0x5000000,0x405780000))
        got=runner.run(A(0x2a2f70))
        request=bytes(u.mem_read(frame+0x60,40))
        pcie,channel,got_dir,padding,n,src,dst,callback,cookie=struct.unpack('<4BI4Q',request)
        assert (pcie,channel,got_dir,n,src,dst,callback,cookie)==(0,4,direction,size,0x5000000,0x405780000,A(0x2a2eb8),frame+0x48)
        assert got['at']==(A(0x2a2fe4) if size else STOP)
        cases.append(dict(kind='post_copy_descriptor',direction=direction,bytes=size,
            callback_file='0x2a2eb8',cookie_is_stack_frame_plus_0x48=True,
            transfer_service_executed=False,zero_length_returns_without_transfer=not size))
        if not size:continue
        # Timeout selection still reaches a lock boundary, not cancellation.
        u.mem_write(frame+0x58,struct.pack('<I',0))
        got=runner.run(A(0x2a3078))
        assert got['at']==A(0x2a3040) and u.reg_read(R.UC_ARM64_REG_X19)&0xffffffff==0xffffffff
        cases.append(dict(kind='post_wait_timeout',next_native_call='spin_lock',transfer_or_cancel_executed=False))
        # Independent post-unlock tails return while the request retains a
        # callback cookie into this frame. No successful lock return supplied.
        for pending,err in ((True,0),(False,0),(False,7)):
            u.mem_write(frame+0x5c,struct.pack('<I',err))
            before=bytes(u.mem_read(frame+0x60,40))
            got=runner.run(A(0x2a305c),inputs=[(R.UC_ARM64_REG_X29,frame),
                (R.UC_ARM64_REG_SP,frame),(R.UC_ARM64_REG_X19,0xffffffff if pending else 0)])
            assert got['at']==STOP
            result=u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
            assert result==(-110 if pending else -5 if err else 0)&0xffffffff
            assert u.reg_read(R.UC_ARM64_REG_SP)==frame+0xa0
            assert bytes(u.mem_read(frame+0x60,40))==before
            cases.append(dict(kind='post_unlock_return',pending_input=pending,error_input=err,
                result_signed=result if result<0x80000000 else result-0x100000000,
                callback_cookie_unchanged=True,native_quiescence_proven=False))
    # Original callback writes cond/error BEFORE its first lock. The cookie
    # here is synthetic allocated storage; this does not invoke a late callback.
    cookie=MEM+0x1000;u.mem_write(cookie,bytes(24))
    got=runner.call(A(0x2a2eb8),(7,cookie))
    assert got['at']==A(0x2a2ed4)
    assert struct.unpack('<2I',bytes(u.mem_read(cookie+0x10,8)))==(1,7)
    cases.append(dict(kind='callback_prefix',writes_before_first_lock=True,wake_or_lock_executed=False))
    return dict(schema='OFFLINE_NATIVE_DMA_READER_BOUNDARIES/1',kernel_sha256=SHA,cases=cases,
        spans=[dict(file_offset=hex(at),bytes=n,sha256=hashlib.sha256(raw[at:at+n]).hexdigest())
               for at,n in ((0x2a2eb8,0x48),(0x2a2f00,0x190))],
        camera_IO=False,CP_reader_admitted=False,
        reason='Timeout return does not cancel the DMA or establish terminal callback lifetime',
        limits=['Independent post-copy/wait/unlock inputs are not executed native services',
            'No real late callback, use-after-free or firmware defect reproduced',
            'No endpoints, physical memory, cache ownership or native module loading admitted'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.kernel.read_bytes())
    with args.output.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(len(report['cases']),'original kernel slices; DMA/callback lifetime not admitted; no device I/O')
if __name__=='__main__':main()
