"""Native same-ID portrait bank construction; original horizontal data survives."""
from pathlib import Path
import sys,struct
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/vertical'))
from verticaltool import imagebank,nativeportrait,portraitlines


def sample():
    count=16;raw=bytearray(struct.pack('<8sHHI',imagebank.MAGIC,8,0,count|(count<<12)))
    raw.extend(b'\xff\xff'*count)
    struct.pack_into('<H',raw,16+2*3,0)
    raw.extend(struct.pack('<IIHHII',0x1a000003,0x40000000,8,8,128,16))
    raw.extend(bytes(range(128)))
    return bytes(raw)


def test_repack_uses_original_ids_and_retains_unselected_record_payload(monkeypatch):
    monkeypatch.setattr(portraitlines,'specs',lambda:[])
    original=sample();target=nativeportrait.prepare(original,0)
    before=imagebank.inspect(original,0);after=imagebank.inspect(target,0)
    assert set(before['records'])==set(after['records'])=={3}
    a,b=before['records'][3],after['records'][3]
    assert target[b['start']:b['start']+b['size']]==original[a['start']:a['start']+a['size']]
    assert (a['flags'],a['width'],a['height'])==(b['flags'],b['width'],b['height'])
    assert nativeportrait.owned(target) and not nativeportrait.owned(original)
    damaged=bytearray(target);damaged[30]^=1
    assert not nativeportrait.owned(damaged)


def test_replacement_keeps_the_same_id_without_changing_horizontal_bytes(monkeypatch):
    monkeypatch.setattr(portraitlines,'specs',lambda:[dict(group=0,index=3,portrait=[4,2],rectangles=[[0,0,4,2,15]])])
    original=sample();saved=bytes(original);target=nativeportrait.prepare(original,0)
    row=imagebank.inspect(target,0)['records'][3]
    assert (row['width'],row['height'])==(4,2)
    assert original==saved and set(imagebank.inspect(target,0)['records'])=={3}
    assert nativeportrait.prepare(original,0)==target


@pytest.mark.skipif(not __import__('os').environ.get('A7C2_NATIVE_PORTRAIT_FIXTURES'),reason='Private Sony images optional; no USB')
def test_real_c2_bank_records_and_native_m4_line_geometry():
    import io
    sys.path.insert(0,str(ROOT/'src/desktopapp/vendor'))
    from fwtool.lz77 import inflateLz77
    root=Path(__import__('os').environ['A7C2_NATIVE_PORTRAIT_FIXTURES'])
    def pixels(blob,row):
        stream=io.BytesIO(blob[row['start']:row['start']+row['size']]);blocks=[]
        while stream.tell()<len(stream.getbuffer()):blocks.append(inflateLz77(stream))
        return b''.join(blocks)
    for group in range(3):
        source=(root/'a7c2-2.01'/f'image_{group:02d}_32_IPSX.uxc').read_bytes()
        target=nativeportrait.prepare(source,group)
        a,b=imagebank.inspect(source,group),imagebank.inspect(target,group)
        assert a['count']==b['count'] and a['records'].keys()==b['records'].keys()
        specs={r['index']:r for r in portraitlines.specs() if r['group']==group}
        m4=(root/'a7m4-6.02'/f'image_{group:02d}_23_IPSX.uxc').read_bytes();reference=imagebank.inspect(m4,group)
        for index,row in a['records'].items():
            new=b['records'][index]
            if index in specs:
                native=reference['records'][index]
                assert pixels(target,new)==pixels(m4,native)
                assert (new['width'],new['height'])==(native['width'],native['height'])
            else:assert source[row['start']:row['start']+row['size']]==target[new['start']:new['start']+new['size']]
            assert row['flags']==new['flags']
            assert source[row['at']+12:row['at']+row['field']]==target[new['at']+12:new['at']+new['field']]


@pytest.mark.skipif(not __import__('os').environ.get('A7C2_NATIVE_PORTRAIT_FIRMWARE'),reason='Private original AP images optional; no USB')
@pytest.mark.parametrize('portrait',[False,True])
@pytest.mark.parametrize('index',range(4))
def test_original_c2_and_m4_vertical_control_choose_same_native_ids(portrait,index):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X19,
        UC_ARM64_REG_X20,UC_ARM64_REG_X21,UC_ARM64_REG_X30,UC_ARM64_REG_SP,UC_ARM64_REG_PC)
    root=Path(__import__('os').environ['A7C2_NATIVE_PORTRAIT_FIRMWARE'])
    results=[]
    for model,entry,end,table,calls in (
        ('a7c2-2.01',0x17e3460,0x17e351c,0x375e278,(0x17d10c0,0x17e9b98,0x17eb1a4)),
        ('a7m4-6.02',0x187f628,0x187f6e4,0x37f77b0,(0x186d410,0x1885ea8,0x1887460))):
        ap=(root/model/'components/appFw.so').read_bytes()
        cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM);mapped=set()
        def put(at,data):
            for page in range(at&~4095,(at+len(data)+4095)&~4095,4096):
                if page not in mapped:cpu.mem_map(page,4096);mapped.add(page)
            cpu.mem_write(at,data)
        put(entry,ap[entry:end]);put(table,ap[table:table+48])
        put(0x30000000,bytes(0x10000));put(0x31000000,bytes(0x10000));put(0x50000000,bytes(4096))
        for address in calls:put(address,bytes(4))
        obj=0x31000000
        cpu.mem_write(obj+0xc3c,bytes([portrait]));cpu.mem_write(obj+0x208,struct.pack('<I',index))
        cpu.mem_write(obj+0x1d8,struct.pack('<I',1));cpu.mem_write(obj+0x1e0,struct.pack('<Q',0x12340000))
        cpu.mem_write(obj+0x1e8,struct.pack('<Q',0x12350000))
        for offset,value in ((0x1f8,8),(0x1fc,9),(0x200,10)):cpu.mem_write(obj+offset,struct.pack('<I',value))
        setup=[]
        def hook(u,at,size,data):
            if at in calls:
                if at==calls[0]:setup.append(bytes(u.mem_read(u.reg_read(UC_ARM64_REG_X1),48)))
                u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_X30))
            elif at==0x50000000:u.emu_stop()
        cpu.hook_add(UC_HOOK_CODE,hook)
        cpu.reg_write(UC_ARM64_REG_X0,obj);cpu.reg_write(UC_ARM64_REG_SP,0x3000f000)
        cpu.reg_write(UC_ARM64_REG_X30,0x50000000)
        for reg in (UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21):cpu.reg_write(reg,0x61000000)
        cpu.emu_start(entry,0x50000004,count=100)
        assert cpu.reg_read(UC_ARM64_REG_PC)==0x50000000
        assert cpu.reg_read(UC_ARM64_REG_SP)==0x3000f000
        assert all(cpu.reg_read(reg)==0x61000000 for reg in (UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21))
        results.append((setup,bytes(cpu.mem_read(obj+0x42c,4))))
    assert results[0]==results[1]
