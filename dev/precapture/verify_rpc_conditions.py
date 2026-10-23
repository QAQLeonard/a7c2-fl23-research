"""Execute actual read-only condition code inside generated RPC orchestration.

All syscall/driver values are deliberate models. Successful necessary checks
still refuse send at gate2. Never opens a real device or accepts a live sender.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.aarch64_abi import context_abi, client_binding_abi, open_flags
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP
from support.uipc import original_header

STATE, CONDITIONS, EXPECTED = MEM, MEM+0x200, MEM+0x300
WORK, IPC_WORK, GATE_CONTEXT = MEM+0x400, MEM+0x700, MEM+0x900
SCALL, IOCTL, SHARED, MESSAGE = 0x22000000, 0x21000000, 0x60000000, 0x60001040
NONCE, CATCHABLE = 0x73803203, ((1<<64)-1)^((1<<8)|(1<<18))


def model(elf, header, abi, sched, flags, kind):
    u, sym = image_loader(elf, 'aarch64', ('precapture_rpc_context_once','precapture_rpc_conditions_gate'))
    u.mem_map(SCALL,4096);u.mem_map(IOCTL,4096)
    u.mem_write(STATE,bytes(360));u.mem_write(CONDITIONS,bytes(256))
    u.mem_write(EXPECTED,struct.pack('<4IQ2I',1003,519,407,2,141,0,0))
    u.mem_write(GATE_CONTEXT,struct.pack('<5Q',EXPECTED,CONDITIONS,WORK,STATE,SCALL))
    if kind == 'used-condition': u.mem_write(CONDITIONS+255,b'\1')
    if kind == 'bad-expected': u.mem_write(EXPECTED+4,struct.pack('<I',1003))
    if kind == 'overlap-condition': u.mem_write(GATE_CONTEXT+8,struct.pack('<Q',STATE+248))
    if kind == 'wrapped-expected': u.mem_write(GATE_CONTEXT,struct.pack('<Q',0xfffffffffffffff0))
    calls, gate_calls, files, ioctls = [], [], [], []
    mapped=False;file_fd=None;file_data=b'';file_pos=0;gate_index=0;stat_reads=0
    worker_policy_reads=0;self_policy_reads=0
    failure = int(kind.split('-')[-1]) if kind.startswith('fail-') else 0
    def word(p):return struct.unpack('<I',bytes(u.mem_read(p,4)))[0]
    def qword(p):return struct.unpack('<Q',bytes(u.mem_read(p,8)))[0]
    def ret(value):
        for i in range(1,18):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        u.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1))
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    def text(p):return bytes(u.mem_read(p,160)).split(b'\0',1)[0].decode()
    def stat(p,mode):
        raw=bytearray(abi['stat_bytes'])
        for key,value,size in (('mode_offset',mode,4),('dev_offset',11,8),('inode_offset',22,8),('rdev_offset',33,8)):
            struct.pack_into('<I' if size==4 else '<Q',raw,abi[key],value)
        u.mem_write(p,bytes(raw))
    def worker_stat():
        fields={i:'0' for i in range(4,53)};fields[9]=str(0x200040);fields[22]='141'
        if kind=='reused-worker' and stat_reads in (2,4):fields[22]='142'
        if kind=='wrong-worker-start':fields[22]='140'
        if kind=='not-kthread':fields[9]='64'
        if kind=='stat-overflow':fields[22]='18446744073709551616'
        if kind=='negative-start':fields[22]='-141'
        if kind=='flags-overflow':fields[9]='4297064512'
        value=('407 (pcieif_esynsnd) D '+' '.join(fields.values())+'\n').encode()
        if kind=='stat-wrong-name':value=value.replace(b'esynsnd',b'esynsndR')
        if kind=='stat-wrong-pid':value=value.replace(b'407 ',b'408 ',1)
        if kind=='worker-zombie':value=value.replace(b') D ',b') Z ')
        if kind=='stat-truncated':value=value[:60]
        if kind=='stat-no-newline':value=value.rstrip(b'\n')
        if kind=='stat-extra-data':value+=b'\0junk'
        if kind=='oversized-file':value+=b' '*600
        return value
    def hook(cpu,at,size,_):
        nonlocal mapped,file_fd,file_data,file_pos,gate_index,stat_reads,worker_policy_reads,self_policy_reads
        if at==sym['precapture_rpc_conditions_gate']:
            gate_calls.append(u.reg_read(R.UC_ARM64_REG_X0));return
        if at not in (SCALL,IOCTL):return
        if at==IOCTL:
            fd,cmd,arg=[u.reg_read(r) for r in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
            ioctls.append(cmd);calls.append(('ioctl',cmd));assert fd==77
            assert cmd in (0x80000010,0x8000000a,0x8000000b),'Actual gate must never reach a send ioctl'
            route,pad,ptr=struct.unpack('<IIQ',bytes(u.mem_read(arg,16)));assert not pad
            if cmd==0x80000010:
                assert route==0 and ptr==STATE+152
                u.mem_write(ptr,struct.pack('<4I',0x200000,0x80000,0x20000,0x803f6112));ret(0)
            elif cmd==0x8000000a:
                assert route==0x908f084b and gate_calls==[1]
                output,count,wait=struct.unpack('<QII',bytes(u.mem_read(ptr,16)));assert(count,wait)==(24,0)
                assert word(CONDITIONS+12)==2
                u.mem_write(output,struct.pack('<Q',MESSAGE));ret(0)
            else:
                assert route==0x908f084b and ptr==MESSAGE and gate_calls==[1,2]
                assert bytes(u.mem_read(MESSAGE-64,len(header)))==header,'Refusal must precede all message writes'
                assert word(STATE+248+24)==0
                ret(0)
            return
        nr,*a=[u.reg_read(getattr(R,f'UC_ARM64_REG_X{i}')) for i in range(7)]
        calls.append(('sys',nr));assert a[4:]==([77,0] if nr==abi['nr_mmap'] else [0,0])
        in_gate=word(CONDITIONS+12)==1
        if in_gate:
            gate_index+=1
            if failure==gate_index:ret(-5);return
        if nr==abi['nr_statat']:
            assert text(a[1])=='/dev/uipc' and a[2:4]==[IPC_WORK,abi['at_nofollow']]
            stat(a[2],abi['char_type']|0o600);ret(0)
        elif nr==abi['nr_openat']:
            name=text(a[1]);assert a[0]==(-100&((1<<64)-1)) and a[3]==0
            if name=='/dev/uipc':assert a[2]==abi['rdwr_flags'];ret(77);return
            assert in_gate and file_fd is None and a[2]==flags['read_flags']
            files.append(name);file_pos=0
            if kind=='oversized-fd':ret(0x80000000);return
            if kind=='impossible-negative-fd':ret(-5000);return
            file_fd=88
            if name=='/proc/407/stat':stat_reads+=1;file_data=worker_stat()
            elif name=='/proc/407/comm':file_data=b'pcieif_esynsndR\n' if kind=='wrong-comm' else b'pcieif_esynsnd\n'
            elif name=='/proc/sys/kernel/sched_rt_runtime_us':file_data=b'950000\n' if kind=='throttled-RT' or kind=='gate2-RT-drift' and word(CONDITIONS+8)==2 else b'-1\n'
            elif name=='/proc/sys/kernel/sched_rt_period_us':file_data=b'100000\n' if kind=='wrong-period' else b'1000000\n'
            else:raise AssertionError(name)
            ret(file_fd)
        elif nr==abi['nr_stat']:
            if a[0]==77:
                assert a[1]==(WORK if in_gate else IPC_WORK+128)
                stat(a[1],abi['char_type']|0o600)
                if in_gate and (kind=='replaced-descriptor' or kind=='gate2-descriptor-drift' and word(CONDITIONS+8)==2):
                    u.mem_write(a[1]+abi['inode_offset'],struct.pack('<Q',23))
            else:
                assert a[0]==file_fd==88 and a[1]==WORK
                stat(a[1],0x2000 if kind=='non-regular-file' else 0x8000|0o400)
            ret(0)
        elif nr==63:
            assert a[0]==file_fd==88 and 0<a[2]<=512
            if kind=='oversized-read':ret(a[2]+1);return
            n=min(a[2],len(file_data)-file_pos,1 if kind=='short-reads' else 512)
            if n:u.mem_write(a[1],file_data[file_pos:file_pos+n]);file_pos+=n
            ret(n)
        elif nr==abi['nr_close']:
            if a[0]==77:assert not mapped;ret(0);return
            assert a[0]==file_fd==88
            if kind=='close-unknown' or kind=='second-gate-close-unknown' and word(CONDITIONS+8)==2:
                ret(-4);return
            file_fd=None;ret(0)
        elif nr==abi['nr_mmap']:
            assert a==[0,0x200000,abi['prot_rw'],abi['map_shared'],77,0]
            u.mem_map(SHARED,0x200000);mapped=True;u.mem_write(MESSAGE-64,header);ret(SHARED)
        elif nr==abi['nr_munmap']:
            assert a[:2]==[SHARED,0x200000] and file_fd is None
            u.mem_unmap(SHARED,0x200000);mapped=False;ret(0)
        elif nr==sched['getpid']:ret(1004 if kind=='wrong-self' else 1003)
        elif nr==sched['getppid']:ret(520 if kind=='wrong-parent' else 519)
        elif nr==sched['getpolicy']:
            assert a[0] in (0,407)
            if a[0]==407:
                worker_policy_reads+=1;ret(2 if kind=='wrong-worker-policy' else 1)
            else:
                self_policy_reads+=1;ret(1 if kind=='self-RT' or kind=='recheck-policy' and self_policy_reads==2 else 0)
        elif nr==sched['getparam']:
            assert a[0] in (0,407)
            value=(147 if kind=='wrong-worker-priority' or kind=='gate2-priority-drift' and word(CONDITIONS+8)==2 else 148) if a[0] else (1 if kind=='self-priority' else 0)
            u.mem_write(a[1],struct.pack('<i',value));ret(0)
        elif nr==sched['getaffinity']:
            assert a[0] in (0,407) and a[1]==8
            value=8 if a[0] and kind=='wrong-worker-mask' else 7 if not a[0] and kind=='wrong-self-mask' else 4
            u.mem_write(a[2],struct.pack('<Q',value));ret(8)
        elif nr==sched['getcpu']:
            u.mem_write(a[0],struct.pack('<I',1 if kind=='wrong-CPU' or kind=='gate2-CPU-drift' and word(CONDITIONS+8)==2 else 2));ret(0)
        elif nr==sched['sigmask']:
            assert a[0:2]==[0,0] and a[3]==8,'Signal query must never modify the mask'
            u.mem_write(a[2],struct.pack('<Q',0 if kind=='unblocked-signals' or kind=='gate2-signal-drift' and word(CONDITIONS+8)==2 else CATCHABLE));ret(0)
        else:raise AssertionError(('Unexpected or mutating syscall',nr))
    u.hook_add(UC_HOOK_CODE,hook)
    args=[STATE,IPC_WORK,NONCE,SCALL,IOCTL,sym['precapture_rpc_conditions_gate'],GATE_CONTEXT]
    def run():
        for i,v in enumerate(args):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),v)
        u.reg_write(R.UC_ARM64_REG_SP,STACK+0x3000);u.reg_write(R.UC_ARM64_REG_LR,STOP)
        u.emu_start(sym['precapture_rpc_context_once'],STOP,count=300000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    status=run();rpc=bytes(u.mem_read(STATE,360));condition=bytes(u.mem_read(CONDITIONS,256))
    phase,ownership=struct.unpack_from('<II',rpc,8)
    condition_phase=word(CONDITIONS+12);pending=qword(CONDITIONS+32)
    unknown=condition_phase==4 or kind=='used-condition'
    if unknown:
        assert status==(-5&0xffffffff) and phase==11 and ownership==3 and mapped
        assert 0x8000000b not in ioctls
        assert word(STATE+248+12)==3 and word(STATE+248+108)==(-117&0xffffffff)
    else:
        assert status==(-95&0xffffffff) and phase==10 and ownership==0 and not mapped and file_fd is None
        assert not word(STATE+248+12)
    assert not word(STATE+248+24)
    if kind=='normal':
        assert condition_phase==3 and gate_calls==[1,2] and pending==((1<<64)-1)
        assert word(CONDITIONS+48+96)==1 and word(CONDITIONS+48+104+96)==1
        assert word(CONDITIONS+48+104+100)==13
        assert ioctls==[0x80000010,0x8000000a,0x8000000b]
        assert len(files)==10
    if kind=='second-gate-close-unknown':assert gate_calls==[1,2] and ioctls==[0x80000010,0x8000000a]
    if kind=='gate2-CPU-drift':assert gate_calls==[1,2] and ioctls==[0x80000010,0x8000000a,0x8000000b]
    before=list(calls),list(gate_calls)
    assert run()==(-16&0xffffffff) and (calls,gate_calls)==before
    assert bytes(u.mem_read(STATE,360))==rpc and bytes(u.mem_read(CONDITIONS,256))==condition
    return dict(case=kind,status=status,condition_phase=condition_phase,gate_calls=gate_calls,
        gate_syscalls=gate_index,ioctls=ioctls,pending_fd=pending,models_only=True,CP_send=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('zig','uipc-kernel','uipc','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    abi=context_abi(a.zig,a.output/'context-ABI');sched=client_binding_abi(a.zig,a.output/'scheduler-ABI')
    flags=open_flags(a.zig,a.output/'open-ABI')
    header,_=original_header(a.uipc_kernel.read_bytes(),a.uipc.read_bytes(),24)
    root=Path(__file__).parent;sources=[root/n for n in ('ap_rpc_conditions.c','ap_rpc_context.c','ap_rpc_probe_once.c')]
    elf=a.output/'NOT-INSTALLABLE-rpc-conditions.elf';compile_shared(a.zig,'aarch64',elf,sources)
    normal=model(elf,header,abi,sched,flags,'normal')
    kinds=['wrong-self','wrong-parent','wrong-CPU','self-RT','self-priority','wrong-self-mask','unblocked-signals',
        'wrong-worker-start','wrong-worker-policy','wrong-worker-priority','wrong-worker-mask','wrong-comm','reused-worker',
        'not-kthread','stat-overflow','negative-start','flags-overflow','stat-wrong-name','stat-wrong-pid','worker-zombie',
        'stat-truncated','stat-no-newline','stat-extra-data','oversized-file','short-reads','oversized-read',
        'non-regular-file','throttled-RT','wrong-period','recheck-policy','close-unknown','second-gate-close-unknown',
        'oversized-fd','impossible-negative-fd','gate2-CPU-drift','used-condition','bad-expected',
        'overlap-condition','wrapped-expected','replaced-descriptor','gate2-descriptor-drift',
        'gate2-RT-drift','gate2-priority-drift','gate2-signal-drift']
    cases=[normal]+[model(elf,header,abi,sched,flags,k) for k in kinds]
    cases += [model(elf,header,abi,sched,flags,f'fail-{i}') for i in range(1,normal['gate_syscalls']+1)]
    pins=[*sources,*[root/n for n in ('ap_rpc_conditions.h','ap_rpc_context.h','ap_rpc_probe_once.h',
        'ap_ipc_context.h','ap_ipc_transport.h','ap_binding_guard.h','ap_linux_aarch64.h','ap_probe_once.h')],Path(__file__)]
    report=dict(schema='OFFLINE_RPC_NATIVE_CONDITION_MODELS/1',cases=cases,physical_camera_IO=False,
        live_send_admitted=False,stage2_unconditionally_denied=True,source_and_lifetime_unqualified=True,
        gate_resource_unknown_retains_RPC_context=True,
        target_ABI=dict(context=abi,scheduler=sched,open=flags),
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in pins})
    (a.output/'report.private.json').write_text(json.dumps(report,indent=2)+'\n')
    print(len(cases),'native condition/integrated RPC MODELS; stage2 never admits send')


if __name__=='__main__':main()
