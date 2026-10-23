"""Combined generated-child ownership models. No real device or CP operation."""
import argparse,hashlib,json,struct
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM
from support.ap_model import call_component,return_modeled_service
from support.aarch64_abi import context_abi,client_binding_abi,client_cpuset_abi
from support.uipc import original_header

CALL,IOCTL,WORK=0x21000000,0x22000000,MEM+0x1000
SHARED,MESSAGE=0x60000000,0x60001040
ORIGINAL=b'1:cpuset:/cpu0_1_2_3rt\n'
TARGET=b'1:cpuset:/cpu2\n'
CATCHABLE=((1<<64)-1)^((1<<8)|(1<<18))

def model(elf,header,abi,kind):
    u,symbols=image_loader(elf,'aarch64',('precapture_client_context_cancel_once',))
    u.mem_map(CALL,4096);u.mem_map(IOCTL,4096);u.mem_map(WORK,4096);u.mem_write(MEM,bytes(536))
    if kind=='used':u.mem_write(MEM+535,b'\1')
    initial=bytes(u.mem_read(MEM,536));group=ORIGINAL;mask=7;signals=0x10
    fds={};calls=[];writes=[];mapped=False
    failure=int(kind.split('-')[-1]) if kind.startswith('fail-') else 0
    def text(p):return bytes(u.mem_read(p,160)).split(b'\0',1)[0].decode()
    def word(at):return struct.unpack('<I',bytes(u.mem_read(at,4)))[0]
    def value(at):return struct.unpack('<Q',bytes(u.mem_read(at,8)))[0]
    def stat(p):
        raw=bytearray(abi['stat_bytes'])
        for field,v,fmt in [('mode_offset',abi['char_type']|0o600,'I'),
                            ('dev_offset',11,'Q'),('inode_offset',22,'Q'),('rdev_offset',33,'Q')]:
            struct.pack_into('<'+fmt,raw,abi[field],v)
        u.mem_write(p,bytes(raw))
    def hook(cpu,at,size,_):
        nonlocal group,mask,signals,mapped
        if at not in (CALL,IOCTL):return
        # No guard inverse may begin while the inner context owns resources.
        phase=word(MEM+8)
        if phase in (4,5):assert word(MEM+288+12)==0
        if phase==5:assert word(MEM+128+12)==0
        args=[u.reg_read(getattr(R,f'UC_ARM64_REG_X{i}')) for i in range(7)]
        n=args[0] if at==CALL else args[1];a=args[1:] if at==CALL else args[:1]+args[2:]
        calls.append(('sys' if at==CALL else 'ioctl',n,phase))
        def ret(v):return_modeled_service(u,v)
        if len(calls)==failure:ret(-22);return
        if at==IOCTL:
            fd,ptr=a[:2];assert fd in fds and fds[fd]=='/dev/uipc'
            route,pad,p=struct.unpack('<IIQ',bytes(u.mem_read(ptr,16)));assert not pad
            assert n in (0x80000010,0x8000000a,0x8000000b),'No RPC/send allowed'
            assert group==TARGET and mask==4 and signals==CATCHABLE
            if n==0x80000010:
                assert route==0;u.mem_write(p,struct.pack('<4I',0x200000,0x80000,0x20000,0x803f6111));ret(0)
            elif n==0x8000000a:
                out,count,wait=struct.unpack('<QII',bytes(u.mem_read(p,16)))
                assert route==0x90030001 and (count,wait)==(16,0)
                u.mem_write(out,struct.pack('<Q',MESSAGE));ret(0)
            else:assert route==0x90030001 and p==MESSAGE;ret(0)
            return
        assert n in (172,178,173,120,121,123,122,135,168,56,63,64,57,79,80,222,215),n
        if n==172:ret(1353);return
        if n==178:ret(1353);return
        if n==173:ret(518);return
        if n==120:assert a[0]==0;ret(0);return
        if n==121:u.mem_write(a[1],bytes(4));ret(0);return
        if n==123:
            assert a[:2]==[0,8];u.mem_write(a[2],struct.pack('<Q',mask));ret(8);return
        if n==122:
            assert a[:2]==[0,8];requested=value(a[2]);assert requested==4 and group==TARGET
            mask=requested;ret(0);return
        if n==135:
            how,new,old,bytes_=a[:4];assert how in (0,2) and bytes_==8
            before=signals
            if new:
                requested=value(new);assert requested==(0x10 if how==2 else CATCHABLE)
                signals=requested if how==2 else signals|requested
            if old:u.mem_write(old,struct.pack('<Q',before))
            ret(0);return
        if n==168:u.mem_write(a[0],struct.pack('<I',2));assert mask==4;ret(0);return
        if n==56:
            path=text(a[1]);assert path in ('/proc/self/cgroup','/dev/cgroup/cpu2/tasks',
                '/dev/cgroup/cpu0_1_2_3rt/tasks','/dev/uipc')
            flags=abi['rdwr_flags'] if path=='/dev/uipc' else 0x88000 if path=='/proc/self/cgroup' else 0x88001
            assert a[0]==(-100&((1<<64)-1)) and a[2:]==[flags,0,0,0]
            fd=10;assert fd not in fds;fds[fd]=path;ret(fd);return
        if n==63:
            assert fds[a[0]]=='/proc/self/cgroup' and a[2]==128
            u.mem_write(a[1],group);ret(len(group));return
        if n==64:
            path=fds[a[0]];assert path in ('/dev/cgroup/cpu2/tasks','/dev/cgroup/cpu0_1_2_3rt/tasks')
            assert a[2]==2 and bytes(u.mem_read(a[1],2))==b'0\n'
            restoring=path.endswith('cpu0_1_2_3rt/tasks');writes.append(path)
            group=ORIGINAL if restoring else TARGET;mask=7 if restoring else 4
            ret(1 if kind==('short-inverse' if restoring else 'short-move') else 2);return
        if n==57:assert a[0] in fds;fds.pop(a[0]);ret(0);return
        if n in (79,80):
            if n==79:assert text(a[1])=='/dev/uipc' and a[3]==abi['at_nofollow'];p=a[2]
            else:assert fds[a[0]]=='/dev/uipc';p=a[1]
            stat(p);ret(0);return
        if n==222:
            assert a==[0,0x200000,abi['prot_rw'],abi['map_shared'],10,0]
            assert group==TARGET and mask==4 and signals==CATCHABLE
            u.mem_map(SHARED,0x200000);mapped=True;u.mem_write(SHARED+0x1000,header);ret(SHARED);return
        if n==215:
            assert a==[SHARED,0x200000,0,0,0,0] and mapped
            u.mem_unmap(SHARED,0x200000);mapped=False;ret(0);return
    u.hook_add(UC_HOOK_CODE,hook)
    args=[MEM,WORK,518,2,0x73693102,CALL,IOCTL]
    invalid={'null-result':(0,0),'null-work':(1,0),'overlap':(1,MEM+128),
        'zero-parent':(2,0),'invalid-CPU':(3,64),'zero-nonce':(4,0),'null-syscall':(5,0),'null-ioctl':(6,0)}
    if kind in invalid:i,v=invalid[kind];args[i]=v
    status=call_component(u,symbols['precapture_client_context_cancel_once'],args,count=200000)
    raw=bytes(u.mem_read(MEM,536));phase=word(MEM+8)
    if kind in invalid or kind=='used':
        assert not calls and raw==initial and status==(-16 if kind=='used' else -22)&0xffffffff
    else:
        owners=[word(MEM+28),word(MEM+140),word(MEM+300)]
        assert word(MEM+288+176+28)==0 # nested probe send_attempts
        assert len(writes)<=2
        if kind=='normal':
            assert not status and phase==6 and owners==[0,0,0] and not fds and not mapped
            assert group==ORIGINAL and mask==7 and signals==0x10 and len(calls)==50
        elif phase==8:
            assert status==(-5&0xffffffff) and any(owners),(kind,owners)
        else:
            assert phase==7 and status and owners==[0,0,0] and group==ORIGINAL and signals==0x10,(kind,phase,owners)
        before=list(calls);assert call_component(u,symbols['precapture_client_context_cancel_once'],args)==(-16&0xffffffff)
        assert calls==before and bytes(u.mem_read(MEM,536))==raw
    return dict(case=kind,calls=len(calls),phase=phase,CP_send=False,models_only=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('zig','uipc-kernel','uipc','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    abi=context_abi(a.zig,a.output/'context-ABI')
    binding=client_binding_abi(a.zig,a.output/'binding-ABI');cpuset=client_cpuset_abi(a.zig,a.output/'cpuset-ABI')
    header,_=original_header(a.uipc_kernel.read_bytes(),a.uipc.read_bytes())
    root=Path(__file__).parent
    sources=[root/name for name in ('ap_client_context.c','ap_client_cpuset.c','ap_client_binding.c','ap_ipc_context.c','ap_probe_once.c')]
    elf=a.output/'NOT-INSTALLABLE-client-context.elf';compile_shared(a.zig,'aarch64',elf,sources)
    kinds=['normal','short-move','short-inverse',*['fail-'+str(i) for i in range(1,51)],
        'used','null-result','null-work','overlap','zero-parent','invalid-CPU','zero-nonce','null-syscall','null-ioctl']
    cases=[model(elf,header,abi,kind) for kind in kinds]
    report=dict(cases=cases,models_only=True,camera_IO=False,CP_send=False,physical_combined_context=False,
        independent_ABI=dict(context=abi,binding=binding,cpuset=cpuset),
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sources,root/'ap_client_context.h',Path(__file__)]})
    with (a.output/'report.private.json').open('x') as stream:json.dump(report,stream,indent=2)
    print(len(cases),'combined generated-code models; no camera/UIPC/CP native operation')

if __name__=='__main__':main()
