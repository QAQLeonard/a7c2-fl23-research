"""Execute custom gamma across both ST domains, including Sony null entries."""
import struct

import pytest

from looktool import photoformat, photobasis, photobuild, photoio
import test_photoio as fixtures


@pytest.fixture(scope='module')
def source():
    fixtures.PhotoIOTests.setUpClass()
    original=bytearray(fixtures.PhotoIOTests.source)
    # Real 2.01 ST row10 has null pointers in columns 0..5. Column6 is
    # its still curve; native fallback for the nulls is row0,column6.
    struct.pack_into('<6I',original,0x1209480-photobuild.BASE+10*28,*([0]*6))
    return bytes(original),fixtures.PhotoIOTests.bank


def test_original_rows_and_loaded_extents_are_unchanged(source):
    cp,bank=source
    new,_=photobuild.build(cp,bank,[{} for _ in range(6)])
    built,_=photoio.build(cp,bank,[{} for _ in range(6)],active_mask=63)
    assert new==built
    table=0x1209480-photobuild.BASE
    assert new[photobuild.TABLE_FILE:photobuild.TABLE_FILE+50*28]==cp[table:table+50*28]
    assert new[0x20124:0x20154]==cp[0x20124:0x20154]
    fallback=struct.unpack_from('<I',cp,table+24)[0]
    for slot in range(6):
        for column in range(7):
            actual=struct.unpack_from('<I',new,photobuild.TABLE_FILE+(51+slot*2)*28+column*4)[0]
            expected=struct.unpack_from('<I',cp,table+10*28+column*4)[0] or fallback
            assert actual==expected


def test_legacy_layout_upgrades_without_changing_controls_other_slots_or_code(source):
    cp,bank=source
    delta=photobasis.pack(bank,tone=[32,0,0])[1]
    new=photoio.update(cp,{1:delta,6:delta},bank,allocation_proved=True)
    legacy=bytearray(new)
    original=cp[0x1209480-photobuild.BASE:0x1209480-photobuild.BASE+50*28]
    legacy[photobuild.TABLE_FILE+50*28:photobuild.CODE_FILE]=photoformat.custom_gamma_rows(original,resolve_null=False)
    legacy=bytes(legacy)
    assert photoio.inspect(legacy)['mask']==33
    repaired=photoio.update(legacy,{1:delta},bank)
    assert repaired==new
    assert photoio.refresh_gamma_table(legacy)==new
    assert photoio.slot_bytes(repaired,6)==photoio.slot_bytes(legacy,6)
    assert repaired[photobuild.CODE_FILE:]==legacy[photobuild.CODE_FILE:]
    damaged=bytearray(legacy)
    struct.pack_into('<I',damaged,photobuild.TABLE_FILE+51*28,0xdeadbeef)
    with pytest.raises(ValueError,match='runtime bytes conflict'):photoio.inspect(bytes(damaged))


def test_every_slot_domain_column_copies_and_transforms_the_native_effective_record(source):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
        UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,
        UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC)
    cp,bank=source
    tone=[32,-16,8]
    target=photoio.update(cp,{i:photobasis.pack(bank,tone=tone)[1] for i in range(1,7)},bank,allocation_proved=True)
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    cpu.mem_map(photobuild.BASE,(len(target)+4095)&~4095);cpu.mem_write(photobuild.BASE,target)
    cpu.mem_map(0x30000000,0x10000);cpu.mem_map(0x31000000,0x10000);cpu.mem_map(0x32000000,4096)
    called=[]
    def hook(u,address,size,user):
        if address==0x61e60c:
            dst,src,n=[u.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]
            assert src!=0 and n==576
            u.mem_write(dst,bytes(u.mem_read(src,n)))
            called.append(('copy',src))
            u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
        elif address==0x42b44c:
            called.append(('record',bytes(u.mem_read(u.reg_read(UC_ARM_REG_R8),576))))
            u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
    cpu.hook_add(UC_HOOK_CODE,hook)
    registers=(UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,
               UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11)
    entry=photoio.template()['labels']['gamma']['address']
    original=0x1209480-photobuild.BASE
    fallback=struct.unpack_from('<I',cp,original+24)[0]
    for slot in range(6):
        for domain in (0,1):
            for column in range(7):
                called.clear();info=0x30001000
                cpu.mem_write(info+16,struct.pack('<I',50+slot*2+domain));cpu.mem_write(info+24,bytes([column]))
                for i,r in enumerate(registers):cpu.reg_write(r,0x51000000+i*256)
                for r,v in ((UC_ARM_REG_R0,0),(UC_ARM_REG_R1,0x30002000),(UC_ARM_REG_R2,info),
                        (UC_ARM_REG_R3,0x30003000),(UC_ARM_REG_SP,0x3100f000),(UC_ARM_REG_LR,0x32000001)):
                    cpu.reg_write(r,v)
                pointer=struct.unpack_from('<I',cp,original+(10 if domain else 0)*28+column*4)[0] or fallback
                expected=photobasis.curve(cp[pointer-photobuild.BASE:pointer-photobuild.BASE+576],tone)
                cpu.emu_start(entry|1,0x32000000,count=10000)
                assert called==[('copy',pointer),('record',expected)]
                assert cpu.reg_read(UC_ARM_REG_SP)==0x3100f000
                assert [cpu.reg_read(r) for r in registers]==[0x51000000+i*256 for i in range(len(registers))]


def test_missing_native_fallback_cannot_be_used_for_custom_records():
    with pytest.raises(ValueError,match='fallback is unavailable'):
        photoformat.custom_gamma_rows(bytes(50*28))
