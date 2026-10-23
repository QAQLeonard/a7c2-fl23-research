"""Fresh-context allocate/cancel UNIT MODELS, not real native context evidence.

Syscall/driver results are deliberately modeled. Original constructors provide
the buffer fixture; target headers independently provide ABI constants.
No device, process, CP message, kernel API or firmware write executes.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM,STACK,STOP
from support.uipc import original_header
from support.aarch64_abi import context_abi

STATE,WORK=MEM,MEM+0x400
SCALL,IOCTL=0x22000000,0x21000000
SHARED,SIZE=0x60000000,0x200000
BLOCK,MESSAGE=SHARED+0x1000,SHARED+0x1040
NONCE=0x73693102


def decode(raw):
    v=struct.unpack_from('<12I8q5Q4Iq',raw)
    p=struct.unpack_from('<10I3qQ',raw,176)
    return dict(phase=v[2],ownership=v[3],nonce=v[4],stat_attempts=v[5],open_attempts=v[6],query_attempts=v[7],
        map_attempts=v[8],unmap_attempts=v[9],close_attempts=v[10],descriptor=v[12],path_stat_status=v[13],
        open_status=v[14],fd_stat_status=v[15],query_status=v[16],map_status=v[17],unmap_status=v[18],close_status=v[19],
        device=v[20],inode=v[21],rdev=v[22],shared_begin=v[23],shared_bytes=v[24],info=list(v[25:29]),return_status=v[29],
        probe=dict(phase=p[2],ownership=p[3],send_query=p[4],allocation_attempts=p[6],send_attempts=p[7],release_attempts=p[8]))


def model(elf,header,abi,kind):
    u,symbols=image_loader(elf,'aarch64',('precapture_ipc_context_cancel_once',))
    u.mem_map(SCALL,4096);u.mem_map(IOCTL,4096);u.mem_write(STATE,bytes(248));u.mem_write(WORK,b'\xa5'*256)
    if kind=='used-result':u.mem_write(STATE+247,b'\1')
    initial=bytes(u.mem_read(STATE,248));calls=[];mapped=False;fd=0 if kind=='descriptor-zero' else 77
    def ret(value):
        for i in range(1,18):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        u.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1));u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    def text(p):return bytes(u.mem_read(p,160)).split(b'\0',1)[0].decode()
    def stat_bytes(mode):
        raw=bytearray(abi['stat_bytes'])
        for name,value,size in (('mode_offset',mode,4),('dev_offset',11,8),('inode_offset',22,8),('rdev_offset',33,8)):
            struct.pack_into('<I' if size==4 else '<Q',raw,abi[name],value)
        return raw
    def hook(cpu,at,size,_):
        nonlocal mapped
        if at not in (SCALL,IOCTL):return
        r=decode(bytes(u.mem_read(STATE,248)))
        if at==SCALL:
            values=[u.reg_read(getattr(R,f'UC_ARM64_REG_X{i}')) for i in range(7)];nr=values[0];a=values[1:];calls.append(('sys',nr))
            assert nr in [abi[k] for k in ('nr_statat','nr_openat','nr_stat','nr_mmap','nr_munmap','nr_close')],nr
            if nr==abi['nr_statat']:
                assert r['phase']==1 and a[0]==(-100&((1<<64)-1)) and text(a[1])=='/dev/uipc'
                assert a[2:]==[WORK,abi['at_nofollow'],0,0] and bytes(u.mem_read(WORK,256))==bytes(256)
                if kind=='path-missing':ret(-2);return
                mode=0xa000 if kind=='path-symlink' else 0x8000 if kind=='path-regular' else abi['char_type']|0o600
                u.mem_write(a[2],bytes(stat_bytes(mode)));ret(0)
            elif nr==abi['nr_openat']:
                assert r['phase']==2 and a[0]==(-100&((1<<64)-1)) and text(a[1])=='/dev/uipc'
                assert a[2:]==[abi['rdwr_flags'],0,0,0]
                ret(-13 if kind=='open-denied' else 0x80000000 if kind=='oversized-descriptor' else fd)
            elif nr==abi['nr_stat']:
                assert r['phase']==3 and a==[fd,WORK+128,0,0,0,0] and r['ownership']==1
                if kind in ('fd-stat-error','fd-error-close-error'):ret(-5);return
                raw=stat_bytes(0x8000 if kind=='fd-type-changed' else abi['char_type']|0o600)
                if kind in ('fd-inode-changed','fd-device-changed','fd-rdev-changed'):
                    key={'fd-inode-changed':'inode_offset','fd-device-changed':'dev_offset','fd-rdev-changed':'rdev_offset'}[kind]
                    struct.pack_into('<Q',raw,abi[key],99)
                u.mem_write(a[1],bytes(raw));ret(0)
            elif nr==abi['nr_mmap']:
                assert r['phase']==5 and a==[0,SIZE,abi['prot_rw'],abi['map_shared'],fd,0] and r['ownership']==1
                if kind=='mmap-error':ret(-12);return
                if kind=='mmap-invalid-error':ret(-5000);return
                result=0 if kind=='mmap-zero' else SHARED+1 if kind=='mmap-unaligned' else MEM if kind=='mmap-overlap' else SHARED
                if result==SHARED:
                    u.mem_map(SHARED,SIZE);mapped=True;u.mem_write(BLOCK,header)
                    if kind=='bad-message-header':u.mem_write(MESSAGE-8,struct.pack('<I',15))
                ret(result)
            elif nr==abi['nr_munmap']:
                assert r['phase']==7 and a==[r['shared_begin'],SIZE,0,0,0,0]
                assert r['probe']['ownership']==0 and not r['probe']['send_attempts']
                if kind=='unmap-error':ret(-22);return
                if mapped:u.mem_unmap(SHARED,SIZE);mapped=False
                ret(0)
            elif nr==abi['nr_close']:
                assert r['phase']==8 and a==[fd,0,0,0,0,0] and r['ownership']==1
                assert r['probe']['ownership']==0 and not r['probe']['send_attempts']
                ret(-4 if kind in ('close-error','fd-error-close-error') else 0)
        else:
            descriptor,command,arg=[u.reg_read(reg) for reg in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
            calls.append(('ioctl',command));assert descriptor==fd
            route,pad,ptr=struct.unpack('<IIQ',bytes(u.mem_read(arg,16)));assert not pad
            assert command in (0x80000010,0x8000000a,0x8000000b),'No send/RPC ioctl is permitted'
            if command==0x80000010:
                assert route==0 and ptr==STATE+152 and r['phase']==4 and r['ownership']==1
                if kind in ('query-error','query-busy'):ret(-22 if kind=='query-error' else -1021);return
                info=[0x1000 if kind=='query-shape' else SIZE,0x80000,0x20000,0x803f6111]
                u.mem_write(ptr,struct.pack('<4I',*info));ret(1 if kind=='query-positive' else 0)
            elif command==0x8000000a:
                assert route==0x90030001 and r['phase']==6 and r['ownership']==2
                output,count,wait=struct.unpack('<QII',bytes(u.mem_read(ptr,16)));assert(count,wait)==(16,0)
                status=-1023 if kind=='allocate-rejected' else -5 if kind=='allocate-unknown' else -1021 if kind=='allocate-busy' else 0
                message=MESSAGE if not status or kind=='allocate-with-pointer-error' else 0
                if kind=='allocate-with-pointer-error':status=-1023
                if kind=='allocate-null':message=0
                u.mem_write(output,struct.pack('<Q',message));ret(status)
            else:
                assert route==0x90030001 and ptr==MESSAGE and r['probe']['send_query']==0 and not r['probe']['send_attempts']
                if kind in ('release-error','mapping-removed-after-free'):
                    u.mem_unmap(SHARED,SIZE);mapped=False
                ret(-5 if kind=='release-error' else 0)
    u.hook_add(UC_HOOK_CODE,hook)
    def run():
        for reg,value in ((R.UC_ARM64_REG_X0,0 if kind=='null-result' else STATE),
            (R.UC_ARM64_REG_X1,0 if kind=='null-workspace' else STATE if kind=='overlap-workspace' else WORK),
            (R.UC_ARM64_REG_X2,0 if kind=='zero-nonce' else NONCE),
            (R.UC_ARM64_REG_X3,0 if kind=='null-syscall' else SCALL),(R.UC_ARM64_REG_X4,0 if kind=='null-ioctl' else IOCTL),
            (R.UC_ARM64_REG_SP,STACK+0x3000),(R.UC_ARM64_REG_LR,STOP)):
            u.reg_write(reg,value)
        u.emu_start(symbols['precapture_ipc_context_cancel_once'],STOP,count=100000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    result=run();raw=bytes(u.mem_read(STATE,248));r=decode(raw)
    invalid=kind in ('null-result','null-workspace','overlap-workspace','zero-nonce','null-syscall','null-ioctl','used-result')
    if invalid:
        assert not calls and raw==initial and result==(-16 if kind=='used-result' else -22)&0xffffffff
        return dict(case=kind,calls=[],result_untouched=True,native_operation=False)
    expected_status={
        'path-missing':-2,'path-symlink':-95,'path-regular':-95,'open-denied':-13,'fd-stat-error':-5,
        'fd-type-changed':-84,'fd-inode-changed':-84,'fd-device-changed':-84,'fd-rdev-changed':-84,
        'query-error':-22,'query-busy':-1021,'query-positive':-5,'query-shape':-84,
        'mmap-error':-12,'mmap-zero':-84,'allocate-rejected':-5,'allocate-busy':-5}.get(kind,0)
    unknowns=('oversized-descriptor','mmap-invalid-error','mmap-unaligned','mmap-overlap','allocate-unknown',
        'allocate-with-pointer-error','allocate-null','bad-message-header','release-error','unmap-error','close-error','fd-error-close-error')
    if kind in unknowns:
        assert result==(-5&0xffffffff) and r['phase']==11 and r['ownership']==3,(kind,r)
    else:
        assert result==expected_status&0xffffffff and r['return_status']==expected_status and r['ownership']==0,(kind,r)
        assert r['phase']==(10 if expected_status else 9)
    assert r['open_attempts']<=1 and r['query_attempts']<=1 and r['map_attempts']<=1 and r['close_attempts']<=1 and r['unmap_attempts']<=1
    assert r['probe']['send_attempts']==0 and not any(c in (0x80000004,0x80000005) for t,c in calls if t=='ioctl')
    if kind in ('path-missing','path-symlink','path-regular'):
        assert not r['open_attempts'] and not r['query_attempts'] and not r['close_attempts']
    if kind in ('open-denied','oversized-descriptor'):
        assert r['stat_attempts']==1 and not r['query_attempts'] and not r['close_attempts']
    if kind in ('fd-stat-error','fd-type-changed','fd-inode-changed','fd-device-changed','fd-rdev-changed','fd-error-close-error'):
        assert not r['query_attempts'] and not r['map_attempts'] and r['close_attempts']==1
    if kind in ('query-error','query-busy','query-positive','query-shape'):
        assert r['query_attempts']==1 and not r['map_attempts'] and r['close_attempts']==1
    if kind in ('success','descriptor-zero','mapping-removed-after-free'):
        expected=[('sys',abi['nr_statat']),('sys',abi['nr_openat']),('sys',abi['nr_stat']),('ioctl',0x80000010),
            ('sys',abi['nr_mmap']),('ioctl',0x8000000a),('ioctl',0x8000000b),('sys',abi['nr_munmap']),('sys',abi['nr_close'])]
        assert calls==expected
    if kind in ('allocate-unknown','allocate-with-pointer-error','allocate-null','bad-message-header','release-error'):
        assert not r['unmap_attempts'] and not r['close_attempts']
    if kind=='unmap-error':assert not r['close_attempts']
    if kind=='query-busy':assert sum(c==0x80000010 for t,c in calls if t=='ioctl')==1
    if kind=='fd-error-close-error':assert r['fd_stat_status']==-5 and r['close_status']==-4
    old=list(calls);workspace_before=bytes(u.mem_read(WORK,256))
    assert run()==(-16&0xffffffff) and calls==old and bytes(u.mem_read(STATE,248))==raw and bytes(u.mem_read(WORK,256))==workspace_before
    return dict(case=kind,calls=[dict(kind=t,value=hex(c)) for t,c in calls],phase=r['phase'],ownership=r['ownership'],
        send_attempts=0,reentry_rejected=True,native_operation=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zig',type=Path,required=True)
    p.add_argument('--uipc-kernel',type=Path,required=True);p.add_argument('--uipc',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    abi=context_abi(a.zig,a.output/'target-context-abi')
    wrong=a.output/'wrong-syscall-header';wrong.mkdir()
    header_source=Path(__file__).with_name('ap_linux_aarch64.h').read_text()
    poisoned=header_source.replace('AP_A64_SYS_MMAP=222','AP_A64_SYS_MMAP=221');assert poisoned!=header_source
    (wrong/'ap_linux_aarch64.h').write_text(poisoned)
    try:context_abi(a.zig,a.output/'rejected-context-abi',header_directory=wrong)
    except RuntimeError as error:assert 'map/ioctl/close syscall ABI' in str(error),str(error)
    else:raise AssertionError('Target ABI must reject the wrong syscall number')
    header,_=original_header(a.uipc_kernel.read_bytes(),a.uipc.read_bytes())
    source=Path(__file__).with_name('ap_ipc_context.c');elf=a.output/'NOT-INSTALLABLE-ipc-context.elf'
    compile_shared(a.zig, 'aarch64', elf,
        [source, source.with_name('ap_probe_once.c')])
    kinds=('success','descriptor-zero','mapping-removed-after-free','path-missing','path-symlink','path-regular',
        'open-denied','oversized-descriptor','fd-stat-error','fd-type-changed','fd-inode-changed','fd-device-changed','fd-rdev-changed',
        'query-error','query-busy','query-positive','query-shape','mmap-error','mmap-invalid-error','mmap-zero','mmap-unaligned','mmap-overlap',
        'allocate-rejected','allocate-busy','allocate-unknown','allocate-with-pointer-error','allocate-null','bad-message-header',
        'release-error','unmap-error','close-error','fd-error-close-error',
        'null-result','null-workspace','overlap-workspace','zero-nonce','null-syscall','null-ioctl','used-result')
    cases=[model(elf,header,abi,kind) for kind in kinds]
    report=dict(schema='OFFLINE_ISOLATED_IPC_CONTEXT_MODELS/1',camera_io=False,cases=cases,target_abi=abi,
        independent_target_rejects_wrong_syscall=True,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        source_headers={name:hashlib.sha256(source.with_name(name).read_bytes()).hexdigest()
            for name in ('ap_ipc_transport.h','ap_ipc_context.h','ap_linux_aarch64.h','ap_probe_once.h')},
        limits=['All native results are explicit unit models, not real open/init/mmap/allocator successes',
            'Source/kernel/device/isolated-process admission and durable private result writer are not supplied',
            'No send/RPC exists in this orchestration; unknown buffer/map/FD ownership retains process lifetime',
            'A bounded call count does not establish native wall-time bounds or camera safety',
            'No actual standalone context, CP response, physical pre-capture or restoration is proven'])
    (a.output/'models.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Isolated context: {len(cases)} explicit ownership/cleanup models; no native operation or CP send.')
if __name__=='__main__':main()
