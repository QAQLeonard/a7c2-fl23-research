"""Isolated-context RPC component UNIT MODELS, not native RPC observations.

Explicit ioctl replies model ownership/protocol outcomes. An original
constructor produces the24-byte header fixture. Native library marshal
instructions independently reach ioctl before execution. No live binding,
process, kernel wait, CP message, firmware write or boot occurs.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP
from support.uipc import original_header, library

SHARED,SIZE,IOCTL,GATE,GATE_CONTEXT=0x60000000,0x200000,0x21000000,0x22000000,MEM+0x700
BLOCK,MESSAGE=SHARED+0x1000,SHARED+0x1040
BIND,STATE=MEM+0x200,MEM
NAMES=('precapture_rpc_probe_guarded_once','precapture_probe_native_ioctl','precapture_rpc_probe_once')


def decode(raw):
    v=struct.unpack('<8I3q3Q8I',raw)
    return dict(magic=v[0],version=v[1],phase=v[2],ownership=v[3],nonce=v[4],
        allocation_attempts=v[5],rpc_attempts=v[6],release_attempts=v[7],
        allocation_status=v[8],rpc_status=v[9],release_status=v[10],
        message=v[11],callback=v[12],callback_context=v[13],response_status=v[14],
        nonce_echo=v[15],tail_nonce=v[16],processor_state=v[17],reply_kind=v[18],source=v[19],
        gate_calls=v[20],gate_status=struct.unpack_from('<i',raw,108)[0])


def model(elf,header,spec):
    u,sym=image_loader(elf,'aarch64',NAMES)
    u.mem_map(SHARED,SIZE);u.mem_map(IOCTL,4096);u.mem_map(GATE,4096);u.mem_write(BLOCK,header)
    binding=[77,0,SHARED,SIZE]
    for i,v in spec.get('binding',{}).items():binding[i]=v
    binding_address=spec.get('binding_address',BIND);state_address=spec.get('state_address',STATE)
    u.mem_write(state_address,bytes(112));u.mem_write(binding_address,struct.pack('<iIQQ',*binding))
    if spec.get('used'):u.mem_write(state_address+108,b'\1')
    before=bytes(u.mem_read(state_address,112));nonce=spec.get('nonce',0xa17e1234)
    source=spec.get('source',0x803f6111);calls=[];gates=[];mapped=True
    def ret(cpu,value):
        for i in range(1,18):cpu.reg_write(getattr(R,f'UC_ARM64_REG_X{i}'),0xde000000+i)
        cpu.reg_write(R.UC_ARM64_REG_X0,value&((1<<64)-1));cpu.reg_write(R.UC_ARM64_REG_PC,cpu.reg_read(R.UC_ARM64_REG_LR))
    def callback(cpu,at,n,_):
        nonlocal mapped
        if at==GATE:
            stage,context=[cpu.reg_read(r) for r in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1)]
            state=decode(bytes(cpu.mem_read(state_address,112)))
            gates.append(stage)
            assert context==GATE_CONTEXT and stage==len(gates) and stage in (1,2)
            assert state['gate_calls']==stage and state['version']==4 and not state['rpc_attempts']
            if stage==1:assert state['phase']==9 and state['ownership']==0 and not calls
            else:
                assert state['phase']==2 and state['ownership']==1 and calls==[0x8000000a]
                assert bytes(cpu.mem_read(BLOCK,len(header)))==header,'Never write request/source before second gate'
            ret(cpu,spec.get('gate_statuses',{}).get(stage,0));return
        if at!=IOCTL:return
        fd,op,arg=[cpu.reg_read(r) for r in (R.UC_ARM64_REG_X0,R.UC_ARM64_REG_X1,R.UC_ARM64_REG_X2)]
        assert fd==77
        route,pad,ptr=struct.unpack('<IIQ',bytes(cpu.mem_read(arg,16)))
        assert route==0x908f084b and not pad;calls.append(op)
        state=decode(bytes(cpu.mem_read(state_address,112)))
        if op==0x8000000a:
            assert calls==[op] and state['phase']==1 and state['allocation_attempts']==1
            out,count,wait=struct.unpack('<QII',bytes(cpu.mem_read(ptr,16)))
            assert(count,wait)==(24,0) and bytes(cpu.mem_read(out,8))==bytes(8)
            status=spec.get('allocation_status',0);message=spec.get('message',MESSAGE if not status else 0)
            cpu.mem_write(out,struct.pack('<Q',message))
            if spec.get('bad_header'):cpu.mem_write(MESSAGE-8,struct.pack('<I',16))
            ret(cpu,status)
        elif op==0x80000005:
            assert calls==[0x8000000a,op] and state['phase']==3 and state['ownership']==2
            assert struct.unpack('<3Q',bytes(cpu.mem_read(ptr,24)))==(MESSAGE,0,0)
            expected=bytearray(24);expected[0]=0xe1;struct.pack_into('<I',expected,20,nonce)
            assert bytes(cpu.mem_read(MESSAGE,24))==bytes(expected)
            sourced=bytearray(header[:64]);struct.pack_into('<I',sourced,52,source)
            assert bytes(cpu.mem_read(BLOCK,64))==bytes(sourced)
            assert state['source']==source and state['version']==4 and gates==[1,2]
            status=spec.get('rpc_status',0)
            cb,ctx=spec.get('delegate',0),spec.get('context',0)
            changed_message=spec.get('returned_message',MESSAGE)
            cpu.mem_write(ptr,struct.pack('<3Q',changed_message,cb,ctx))
            if status or cb or ctx or changed_message!=MESSAGE:
                # Ambiguous completion may have consumed the mapping. The
                # component must neither touch nor free it afterward.
                cpu.mem_unmap(SHARED,SIZE);mapped=False;ret(cpu,status);return
            response=bytearray(expected);kind=spec.get('reply','absent')
            if kind=='absent':response[1]=0x80
            elif kind=='present':
                response[1]=0x5a;struct.pack_into('<3I',response,8,nonce,0xdeadbeef,0x60000013)
            elif kind=='wrong-echo':
                response[1]=0x5a;struct.pack_into('<3I',response,8,nonce^1,0xdeadbeef,0x60000013)
            elif kind=='wrong-tail':
                response[1]=0x5a;struct.pack_into('<I',response,8,nonce);struct.pack_into('<I',response,20,nonce^1)
            elif kind=='ordinary-address':
                response[1]=1;struct.pack_into('<QI',response,8,0x05000000,0x778000)
            elif kind.startswith('default-'):
                response[1]=0x80
                if kind=='default-wrong-mode':response[0]=0xe0
                elif kind=='default-reserved2':response[2]=1
                elif kind=='default-reserved7':response[7]=1
                elif kind=='default-word12':struct.pack_into('<I',response,12,0x05000000)
                elif kind=='default-wrong-tail':struct.pack_into('<I',response,20,nonce^1)
                elif kind=='default-wrong-status':response[1]=0x7f
                else:raise AssertionError(kind)
            elif kind=='unchanged':pass
            else:raise AssertionError(kind)
            cpu.mem_write(MESSAGE,bytes(response));ret(cpu,0)
        elif op==0x8000000b:
            assert calls==([0x8000000a,op] if spec.get('gate_statuses',{}).get(2) else [0x8000000a,0x80000005,op]) and ptr==MESSAGE
            assert state['phase']==5 and state['ownership']==1 and state['release_attempts']==1
            if spec.get('gate_statuses',{}).get(2):
                assert bytes(cpu.mem_read(BLOCK,len(header)))==header
                assert not state['rpc_attempts'] and state['rpc_status']==-1
            cpu.mem_unmap(SHARED,SIZE);mapped=False;ret(cpu,spec.get('release_status',0))
        else:raise AssertionError('Unplanned native operation')
    u.hook_add(UC_HOOK_CODE,callback)
    def run():
        for r,v in ((R.UC_ARM64_REG_X0,0 if spec.get('null_binding') else spec.get('passed_binding',binding_address)),
                (R.UC_ARM64_REG_X1,0 if spec.get('null_result') else spec.get('passed_result',state_address)),
                (R.UC_ARM64_REG_X2,nonce),(R.UC_ARM64_REG_X3,source),
                (R.UC_ARM64_REG_X4,0 if spec.get('null_callback') else IOCTL),
                (R.UC_ARM64_REG_X5,0 if spec.get('null_gate') else GATE),
                (R.UC_ARM64_REG_X6,0 if spec.get('null_gate_context') else GATE_CONTEXT),
                (R.UC_ARM64_REG_SP,STACK+0x3000),(R.UC_ARM64_REG_LR,STOP)):
            u.reg_write(r,v&((1<<64)-1))
        u.emu_start(sym[NAMES[2] if spec.get('legacy') else NAMES[0]],STOP,count=8000)
        assert u.reg_read(R.UC_ARM64_REG_PC)==STOP
        return u.reg_read(R.UC_ARM64_REG_X0)&0xffffffff
    result=run();assert result==spec.get('return',-5)&0xffffffff,(spec,hex(result))
    raw=bytes(u.mem_read(state_address,112));state=decode(raw)
    assert calls==spec['calls']
    if calls or gates:
        assert(state['phase'],state['ownership'])==spec['terminal']
        assert state['rpc_attempts']==int(0x80000005 in calls)
        assert state['release_attempts']==int(0x8000000b in calls)
        if 'kind' in spec:assert state['reply_kind']==spec['kind']
        if 'gate_statuses' in spec:
            assert state['gate_status']==next(iter(spec['gate_statuses'].values()))
        if spec.get('reply')=='present':
            assert state['reply_kind']==3 and state['ownership']==3 and 0x8000000b not in calls
            # Historical non-default observer data stays unqualified; word12
            # must not be copied into any semantic result field.
            assert 0xdeadbeef not in struct.unpack('<28I',raw)
        old=list(calls);old_gates=list(gates);assert run()==(-16&0xffffffff)
        assert calls==old and gates==old_gates and bytes(u.mem_read(state_address,112))==raw
    else:assert raw==before
    return dict(case=spec['name'],model_calls=[hex(c) for c in calls],terminal_phase=state['phase'],
        terminal_ownership=state['ownership'],reply_kind=state['reply_kind'],mapping_removed=not mapped,
        gate_calls=len(gates),actual_RPC_or_kernel_operation=False)


def native_sync_wire(path):
    u,entry=library(path);seen=[]
    def hook(cpu,at,n,_):
        if at==entry['ioctl']:seen.append(at);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    for r,v in ((R.UC_ARM64_REG_X0,0x908f084b),(R.UC_ARM64_REG_X1,MESSAGE),
            (R.UC_ARM64_REG_SP,STACK+0x8000),(R.UC_ARM64_REG_LR,STOP)):
        u.reg_write(r,v)
    u.emu_start(0x3a98,0xffffffffffffffff,count=100)
    assert seen==[entry['ioctl']] and u.reg_read(R.UC_ARM64_REG_X0)==77
    assert u.reg_read(R.UC_ARM64_REG_X1)&0xffffffff==0x80000005
    packet=u.reg_read(R.UC_ARM64_REG_X2)
    route,inner=struct.unpack('<I4xQ',bytes(u.mem_read(packet,16)))
    assert route==0x908f084b and struct.unpack('<3Q',bytes(u.mem_read(inner,24)))==(MESSAGE,0,0)
    return dict(original_library_entry='0x3a98',command='0x80000005',inner_bytes=24,
        message_pointer_matches=True,callback_and_context_initially_zero=True,ioctl_executed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uipc-kernel',type=Path,required=True);p.add_argument('--uipc',type=Path,required=True)
    p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();header,original_sourced=original_header(a.uipc_kernel.read_bytes(),a.uipc.read_bytes(),24)
    assert struct.unpack_from('<I',header,56)[0]==24
    expected=bytearray(header);struct.pack_into('<I',expected,52,0x80020002)
    assert bytes(expected)==original_sourced  # original native setter, not a modeled API result
    wire=native_sync_wire(a.uipc)
    a.output.mkdir(parents=True,exist_ok=False);elf=a.output/'NOT-INSTALLABLE-ap-rpc-probe.elf'
    compile_shared(a.zig, 'aarch64', elf,
        [Path(__file__).with_name('ap_rpc_probe_once.c'), Path(__file__).with_name('ap_probe_once.c')])
    A,S,F=0x8000000a,0x80000005,0x8000000b
    specs=[dict(name='observer-absent',calls=[A,S,F],terminal=(6,0),kind=1,**{'return':0}),
        dict(name='observer-present',reply='present',calls=[A,S],terminal=(8,3),kind=3),
        dict(name='callback-delegation',delegate=0x72000000,calls=[A,S],terminal=(8,3)),
        dict(name='callback-context',context=0x1234,calls=[A,S],terminal=(8,3)),
        dict(name='message-changed',returned_message=MESSAGE+64,calls=[A,S],terminal=(8,3)),
        dict(name='bad-native-header',bad_header=True,calls=[A],terminal=(8,3)),
        dict(name='null-pointer',message=0,calls=[A],terminal=(8,3)),
        dict(name='outside-pointer',message=0x72000000,calls=[A],terminal=(8,3)),
        dict(name='unaligned-pointer',message=MESSAGE+1,calls=[A],terminal=(8,3)),
        dict(name='failed-with-pointer',allocation_status=-1023,message=MESSAGE,calls=[A],terminal=(8,3)),
        dict(name='free-unknown',release_status=-5,calls=[A,S,F],terminal=(8,3))]
    for reply in ('wrong-echo','wrong-tail','ordinary-address','unchanged'):
        specs.append(dict(name=reply,reply=reply,calls=[A,S],terminal=(8,3),kind=3))
    for reply in ('default-wrong-mode','default-reserved2','default-reserved7','default-word12','default-wrong-tail','default-wrong-status'):
        specs.append(dict(name=reply,reply=reply,calls=[A,S],terminal=(8,3),kind=3))
    for value in (-22,-1021,-1023,-1024):
        specs.append(dict(name=f'allocate-rejected-{value}',allocation_status=value,calls=[A],terminal=(7,0)))
    for value in (-4,-5,1):
        specs.append(dict(name=f'allocate-unknown-{value}',allocation_status=value,calls=[A],terminal=(8,3)))
    for value in (-22,-4,-5,-1021):
        specs.append(dict(name=f'RPC-unknown-{value}',rpc_status=value,calls=[A,S],terminal=(8,3)))
    for name,fields in (('negative-fd',dict(binding={0:-1})),('bad-reserved',dict(binding={1:1})),
            ('unaligned-map',dict(binding={2:SHARED+1})),('bad-size',dict(binding={3:4096})),
            ('wrapped-map',dict(binding={2:0xfffffffffffff000})),('zero-nonce',dict(nonce=0)),
            ('null-binding',dict(null_binding=True)),('null-callback',dict(null_callback=True))):
        specs.append(dict(name=name,calls=[],**fields,**{'return':-22}))
    specs.append(dict(name='used-result',used=True,calls=[],**{'return':-16}))
    for value in (0,0x00020002,0xa5a5a5a5,0xffffffff):
        specs.append(dict(name=f'invalid-source-{value:08x}',source=value,calls=[],**{'return':-22}))
    specs.append(dict(name='distinct-explicit-source',source=0x80020005,calls=[],**{'return':-22}))
    specs.append(dict(name='distinct-own-context-source',source=0x803f6112,calls=[A,S,F],terminal=(6,0),kind=1,**{'return':0}))
    for source in (0x803f0000,0x803f8001,0x903f6111):
        specs.append(dict(name=f'not-an-own-context-source-{source:08x}',source=source,calls=[],**{'return':-22}))
    for name,fields in (('result-in-shared-map',dict(state_address=SHARED+0x700)),
        ('binding-in-shared-map',dict(binding_address=SHARED+0x700)),
        ('result-overlaps-binding',dict(binding_address=STATE+32)),
        ('wrapped-result-pointer',dict(passed_result=0xfffffffffffffff0)),
        ('wrapped-binding-pointer',dict(passed_binding=0xfffffffffffffff0)),
        ('null-result',dict(null_result=True))):
        specs.append(dict(name=name,calls=[],**fields,**{'return':-22}))
    specs += [dict(name='null-gate',null_gate=True,calls=[],**{'return':-22}),
              dict(name='null-gate-context',null_gate_context=True,calls=[],**{'return':-22}),
              dict(name='retired-unguarded-entry',legacy=True,calls=[],**{'return':-95})]
    for stage in (1,2):
        for status in (-22,-4,1):
            specs.append(dict(name=f'gate{stage}-refuses-{status}',gate_statuses={stage:status},
                calls=[] if stage==1 else [A,F],terminal=(7,0),**{'return':-95}))
    specs.append(dict(name='gate2-refused-cancel-unknown',gate_statuses={2:-22},
        release_status=-5,calls=[A,F],terminal=(8,3)))
    results=[model(elf,header,s) for s in specs]
    report=dict(schema='OFFLINE_RPC_PROBE_UNIT_MODELS/4',camera_io=False,cases=results,native_wire_boundary=wire,
        kernel_header_fixture_payload_bytes=24,ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        source_setter_original_displacement=-12,source_provenance_verified=False,
        live_send_gate_supplied=False,unguarded_entry_retired=True,
        exact_original_default_reply_only=True,unexpected_reply_preserves_mapping_and_message=True,
        private_result_and_binding_spans_required=True,own_queue_ID_grammar_required=True,
        limits=['RPC success/failure/replies are deliberate unit models, not real native service observations',
            'This component can block in the kernel; never invoke it in AP service init',
            'Unknown/delegated states retain unresolved ownership; a future isolated process must preserve its lifetime',
            'No live source/FD/map adapter, isolated launcher or durable host fencing is supplied',
            'No CP response, ROM write/reload/recovery or physical pre-capture is proven'])
    (a.output/'unit-models.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'RPC component:{len(results)} ownership/protocol MODELS and original sync-wire boundary. No live RPC or camera operation.')
if __name__=='__main__':main()
