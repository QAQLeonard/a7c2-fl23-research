"""Execute only the reviewed voice-setting setter fragments, without USB."""
import struct
import pytest
from looktool import voicelock,capturedefaults

AP_CODE = {
    0x1c11e0c: "fd7bb9a9fd030091f55b02a9b5030191f35301a9f303002ae00315aacaf6ed97b42740f9686a3194f60300aa6b6a3194020440f921fa8052bf930139bf970139a3f30091b33f00b9840080d2b60305a9a16300b9b43700f9c20200b4e00314aa8fc46994a02f40f9000440f9130000b920008052a0970139a02b40f9130000b920008052a0930139a0430191d0ffff9720fa8052ded02394e00315aab3f6ed97f35341a9f55b42a9fd7bc7a8c0035fd6e20316aae00314aa79c46994efffff17",
    0x25785f8: "fd7bb9a9fd030091f55b02a9b5030191e00315aaf35301a9f303012acf5cc897b42740f96dd00b94f60300aa70d00b94020440f921fa8052bf930139bf970139a3f30091b33f00b9840080d2b60305a9a16300b9b43700f9820200b4e00314aa942a4494a02f40f9000440f9130000b920008052a0970139a02b40f9130000b920008052a0930139a0430191d565da97e00315aaba5cc897f35341a9f55b42a9fd7bc7a8c0035fd6e20316aae00314aa802a4494f1ffff17",
    0x2b2c1b8: "fd7bb9a9fd030091f35301a9f30300aaf51300f9b40301918501f597610240b9011000b9e00314aadc8db197b32740f97a01f597f50300aa7d01f597b50305a920fa8052b33700f9bf930139bf970139a06300b97601f597131040b9a3f30091a02f40f9840080d2a16340b9020440f9b33f00b9a03740f9620200b49d5b2d94a02f40f9000440f9130000b920008052a0970139a02b40f9130000b920008052a0930139a0430191de96c397e00314aac38db197f51340f9f35341a9fd7bc7a8c0035fd6a22b40f98a5b2d94f2ffff17fd7bb9a9fd030091f35301a9f30300aa",
    0x1c11dd8: "015040396101003401544039e1000035010440f9210440f9810000b4020040f9420040b9220000b9001040b97bd42314c0035fd6",
}


@pytest.mark.parametrize('entry',[0x1c11e0c,0x25785f8,0x2b2c1b8])
@pytest.mark.parametrize('requested',[0,1,2,255])
def test_native_setting_writers_keep_on_and_off_requests_off(entry,requested):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X19,
        UC_ARM64_REG_X20,UC_ARM64_REG_X21,UC_ARM64_REG_X22,UC_ARM64_REG_X30,
        UC_ARM64_REG_SP,UC_ARM64_REG_PC)
    cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM);mapped=set()
    def put(at,data):
        for page in range(at&~4095,(at+len(data)+4095)&~4095,4096):
            if page not in mapped:cpu.mem_map(page,4096);mapped.add(page)
        cpu.mem_write(at,data)
    for at,data in AP_CODE.items():put(at,bytes.fromhex(data))
    for at,old,new in voicelock.WINDOWS:put(at,new)
    put(0x30000000,bytes(0x10000));put(0x31000000,bytes(4096));put(0x50000000,bytes(4096))
    # The three ordinary setters use the same model cell and optional saved-value pointer.
    cpu.mem_write(0x31000008,struct.pack('<Q',0x31000100))
    cpu.mem_write(0x31000300,struct.pack('<I',requested))
    for at in (0x178f950,0x178f974,0x286c7d0,0x286c7e4,0x36830a8,0x2506ff0,0x2506218):put(at,bytes(4))
    def call(u,at,size,data):
        if at==0x178f950:u.mem_write(u.reg_read(UC_ARM64_REG_X0)+8,struct.pack('<Q',0x31000400))
        elif at==0x286c7d0:u.reg_write(UC_ARM64_REG_X0,0x31000200)
        elif at==0x286c7e4:u.reg_write(UC_ARM64_REG_X0,0x31000000)
        elif at==0x50000000:u.emu_stop();return
        elif at not in (0x178f974,0x36830a8,0x2506ff0,0x2506218):return
        u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_X30))
    cpu.hook_add(UC_HOOK_CODE,call)
    for i,r in enumerate((UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21,UC_ARM64_REG_X22)):
        cpu.reg_write(r,0x61000000+i*256)
    cpu.reg_write(UC_ARM64_REG_X0,0x31000300 if entry==0x2b2c1b8 else requested)
    cpu.reg_write(UC_ARM64_REG_X1,requested)
    cpu.reg_write(UC_ARM64_REG_SP,0x3000f000);cpu.reg_write(UC_ARM64_REG_X30,0x50000000)
    cpu.emu_start(entry,0x50000004,count=400)
    assert cpu.reg_read(UC_ARM64_REG_PC)==0x50000000
    assert cpu.mem_read(0x31000200,4)==b'\1\0\0\0'
    assert cpu.mem_read(0x31000100,4)==b'\1\0\0\0'
    assert cpu.reg_read(UC_ARM64_REG_SP)==0x3000f000
    assert [cpu.reg_read(r) for r in (UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21,UC_ARM64_REG_X22)]==[0x61000000+i*256 for i in range(4)]


def test_mechanical_defaults_are_descriptor_bound_and_do_not_target_af_audio():
    from types import SimpleNamespace
    ap=bytearray(0x57b8600);records=[{},{}]
    for key,at,attribute,value in capturedefaults.FIELDS:
        struct.pack_into('<8I',ap,at,3,key,0x10000,0,0,0,attribute,0)
        records[0][key]=SimpleNamespace(data=b'\1')
    fields=capturedefaults.mechanical(bytes(ap),records)
    assert fields=={0x02cf02c9:b'\0',0x02cf02d9:b'\0',0x02cf02d1:b'\1'}
    assert 0x02cf048b not in fields
    ap[capturedefaults.FIELDS[0][1]]^=1
    with pytest.raises(ValueError):capturedefaults.mechanical(bytes(ap),records)
