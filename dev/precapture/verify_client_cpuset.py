"""Generated self-only cpuset controls. No cgroup/device/process changes occur."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.build import compile_shared
from support.aarch64_abi import client_cpuset_abi
from support.elf import image_loader
from support.memory import MEM,STACK,STOP

CALL=0x21000000
GROUP_ORIGINAL=b'1:cpuset:/cpu0_1_2_3rt\n'
GROUP_TARGET=b'1:cpuset:/cpu2\n'


def state(raw):
    v=struct.unpack('<8I6q3Q2I',raw)
    return dict(magic=v[0],version=v[1],phase=v[2],ownership=v[3],CPU=v[4],calls=v[5],
        move_writes=v[6],restore_writes=v[7],pid=v[8],tid=v[9],parent=v[10],descriptor=v[11],
        last_result=v[12],status=v[13],before=v[14],target=v[15],restored=v[16],observed_CPU=v[17],read_bytes=v[18])


def model(elf,kind):
    u,symbols=image_loader(elf,'aarch64',('precapture_client_cpuset_enter','precapture_client_cpuset_leave'))
    u.mem_map(CALL,4096);u.mem_write(MEM,bytes(112))
    if kind=='used':u.mem_write(MEM+111,b'\1')
    group=GROUP_ORIGINAL;affinity=7;fds={};closed=[];writes=[];calls=[];leaving=False
    failure=int(kind.split('-')[-1]) if kind.startswith('call-fail-') else 0
    def ret(value):
        u.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1));u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_LR))
    def text(address):return bytes(u.mem_read(address,180)).split(b'\0',1)[0].decode('ascii')
    def callback(cpu,address,size,_):
        nonlocal group,affinity
        if address!=CALL:return
        n,a,b,c,d,e,f=[u.reg_read(getattr(R,f'UC_ARM64_REG_X{i}')) for i in range(7)]
        assert n in (172,178,173,120,121,123,168,56,63,64,57) and not e and not f
        calls.append(n)
        if len(calls)==failure:ret(-22);return
        if n==172:ret(1353);return
        if n==178:ret(1354 if kind=='multi-thread' else 1353);return
        if n==173:ret(519 if kind=='wrong-parent' else 518);return
        if n==120:assert a==0;ret(1 if kind=='RT-policy' else 0);return
        if n==121:assert a==0;u.mem_write(b,bytes(4));ret(0);return
        if n==123:
            assert a==0 and b==8
            value=7 if kind=='target-affinity-drift' and group==GROUP_TARGET else affinity
            u.mem_write(c,struct.pack('<Q',value));ret(8);return
        if n==168:u.mem_write(a,struct.pack('<I',1 if kind=='CPU-drift' else 2));ret(0);return
        if n==56:
            path=text(b)
            assert path in ('/proc/self/cgroup','/dev/cgroup/cpu2/tasks','/dev/cgroup/cpu0_1_2_3rt/tasks')
            assert c==(0x88000 if path=='/proc/self/cgroup' else 0x88001) and not d
            fd=10+len(fds);fds[fd]=path;ret(fd);return
        if n==63:
            assert fds[a]=='/proc/self/cgroup' and c==128
            value=b'foreign\n' if kind=='foreign-group' else group
            if kind=='partial-group':value=value[:2]
            u.mem_write(b,value);ret(len(value));return
        if n==64:
            path=fds[a];assert path in ('/dev/cgroup/cpu2/tasks','/dev/cgroup/cpu0_1_2_3rt/tasks')
            assert c==2 and bytes(u.mem_read(b,c))==b'0\n'
            writes.append(path)
            group=GROUP_ORIGINAL if leaving else GROUP_TARGET;affinity=7 if leaving else 4
            ret(1 if kind=='short-write' else 2);return
        if n==57:assert a in fds and a not in closed;closed.append(a);ret(0);return
    u.hook_add(UC_HOOK_CODE,callback)
    def invoke(name,args):
        for i,value in enumerate(args):u.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),value)
        u.reg_write(R.UC_ARM64_REG_SP,STACK+0x3000);u.reg_write(R.UC_ARM64_REG_LR,STOP)
        u.emu_start(symbols[name],STOP,count=30000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    result=invoke('precapture_client_cpuset_enter',(MEM,518,2,CALL));bound=state(bytes(u.mem_read(MEM,112)))
    if kind=='normal' or kind.startswith('call-fail-') and failure>17:
        assert not result and bound['phase']==4 and bound['ownership']==1 and len(calls)==17
        leaving=True;result=invoke('precapture_client_cpuset_leave',(MEM,CALL));final=state(bytes(u.mem_read(MEM,112)))
        if kind=='normal':
            assert not result and final['phase']==7 and not final['ownership'] and final['calls']==24
            assert final['before']==final['restored']==7 and group==GROUP_ORIGINAL
            assert final['move_writes']==final['restore_writes']==1 and writes==[
                '/dev/cgroup/cpu2/tasks','/dev/cgroup/cpu0_1_2_3rt/tasks']
            previous=len(calls);assert invoke('precapture_client_cpuset_leave',(MEM,CALL))==0xffffffea and len(calls)==previous
        else:assert result and final['phase']==9 and final['ownership']==1
    else:
        assert result,(kind,bound)
        assert len(writes)<=1
        if kind in ('used','multi-thread','wrong-parent','RT-policy','foreign-group','partial-group'):assert not writes
    return dict(case=kind,calls=len(calls),membership_writes=len(writes),status=result,
                no_kernel_worker_or_AP_PID_written=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(exist_ok=False)
    abi=client_cpuset_abi(args.zig,args.output/'target-ABI')
    source=Path(__file__).with_name('ap_client_cpuset.c');elf=args.output/'component.elf'
    compile_shared(args.zig,'aarch64',elf,[source])
    cases=[model(elf,k) for k in ('normal','used','multi-thread','wrong-parent','RT-policy','foreign-group','partial-group',
        'target-affinity-drift','CPU-drift','short-write',*['call-fail-'+str(i) for i in range(1,25)])]
    result=dict(cases=cases,target_ABI=abi,camera_IO=False,models_only=True,cgroup_native_write=False,
        CP_send=False,physical_binding=False,
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,source.with_suffix('.h'),Path(__file__))})
    with (args.output/'report.private.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print(len(cases),'self-only cpuset models; no native membership/device change')


if __name__=='__main__':main()
