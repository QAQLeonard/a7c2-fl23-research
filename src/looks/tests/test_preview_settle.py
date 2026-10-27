"""Preview helper guard: a custom marker ends the native LUT-update state machine. Synthetic memory, no USB."""
import itertools
import struct
import unittest
try:
    import keystone,unicorn
    from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
    from unicorn.arm_const import *
except ImportError:
    raise unittest.SkipTest('Optional assembler/emulator absent')
from looktool import device_layout,hooks,six,sixbuild

HELPER=hooks.HELPER
ENTRY,BUILD,SKIP=0x23d4e4,0x23d4e8,0x23d516
ROOT,PARAM,CODE,PARAM2,DESC,CONTEXT,BANK=0x30000000,0x30001000,0x30002000,0x30003000,0x30004000,0x30005000,0x30006000
KEPT={UC_ARM_REG_R3:0x33333333,UC_ARM_REG_R5:0x55555555,UC_ARM_REG_R6:0x66666666,UC_ARM_REG_R7:0x77777777,
    UC_ARM_REG_R11:0xbbbbbbbb,UC_ARM_REG_R12:0xcccccccc,UC_ARM_REG_LR:0xeeeeeeee,UC_ARM_REG_SP:0x30009000}


def image(asm,settle):
    blob=bytearray(sixbuild.helper(asm,settle=settle))
    for at,data in six.retry_windows(asm):
        if 0xb27490<=at<0xb27590:blob[at-0xb27490:at-0xb27490+len(data)]=data
    return bytes(blob[:254])

def run(raw,asm,*,flag,marker,mode,bank=True):
    """Start at the patched wide branch 0x23d4e4 with an update in flight; stop where the guard leaves."""
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for base in (0x23d000,0xc2f000):u.mem_map(base,0x1000)
    u.mem_map(0x30000000,0x10000)
    u.mem_write(HELPER,raw);u.mem_write(ENTRY,asm('b.w 0xc2f520',ENTRY))
    u.mem_write(ROOT+1,bytes([flag]));u.mem_write(ROOT+0x2e,bytes([marker]))
    u.mem_write(PARAM,struct.pack('<2I',ROOT,CODE));u.mem_write(CODE+6,bytes([mode]))
    u.mem_write(PARAM2+8,struct.pack('<II',DESC,CONTEXT))
    u.mem_write(CONTEXT+0x6b0,struct.pack('<I',BANK if bank else 0))
    u.mem_write(DESC+0x28,b'\1');u.mem_write(CONTEXT+0x27,b'\2')
    for reg,value in {UC_ARM_REG_R4:flag,UC_ARM_REG_R10:ROOT,UC_ARM_REG_R9:PARAM,UC_ARM_REG_R8:PARAM2,
            UC_ARM_REG_R0:0x10101010,UC_ARM_REG_R1:0x11111111,UC_ARM_REG_R2:0x22222222,**KEPT}.items():u.reg_write(reg,value)
    exits=[]
    def hook(cpu,at,size,_):
        if at in (BUILD,SKIP):exits.append(at);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(ENTRY|1,0,count=200)
    return dict(exit={BUILD:'build',SKIP:'skip'}[exits[0]],updating=u.mem_read(DESC+0x28,1)[0],counter=u.mem_read(CONTEXT+0x27,1)[0],
        r0=u.reg_read(UC_ARM_REG_R0),kept={reg:u.reg_read(reg) for reg in (*KEPT,UC_ARM_REG_R4)})


class PreviewSettleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asm=staticmethod(hooks.assembler());cls.v4,cls.v5=image(cls.asm,False),image(cls.asm,True)

    def test_bundled_windows_are_the_current_image_and_the_earlier_one_is_kept(self):
        asset=device_layout.runtime()
        for spec in asset['cp_sources']:
            window=next(w for w in spec['windows'] if w['offset']==0xb27490)
            self.assertEqual(bytes.fromhex(window['after']),self.v5)
        self.assertEqual([(w['offset'],bytes.fromhex(w['after'])) for w in asset['superseded_windows']],[(0xb27490,self.v4)])

    def test_only_the_skip_stub_and_the_guard_change(self):
        changed=[i for i in range(254) if self.v4[i]!=self.v5[i]]
        self.assertTrue(changed and all(0x64<=i<0x68 or 0x90<=i<0xc8 for i in changed))

    def test_custom_marker_taking_over_ends_the_native_update(self):
        for marker,(mode,bank) in itertools.product(range(249,255),[(1,True),(1,False),(0,True)]):
            with self.subTest(marker=marker,mode=mode,bank=bank):
                result=run(self.v5,self.asm,flag=0,marker=marker,mode=mode,bank=bank)
                self.assertEqual((result['exit'],result['updating'],result['counter']),('build',0,0))
                self.assertEqual(result['r0'],PARAM)
                # The earlier guard builds the same way but leaves the update flag set.
                old=run(self.v4,self.asm,flag=0,marker=marker,mode=mode,bank=bank)
                self.assertEqual((old['exit'],old['updating'],old['counter']),('build',1,2))

    def test_other_paths_make_the_same_decision_and_leave_the_native_update_alone(self):
        for flag,marker,mode,bank in itertools.product((0,1),(0,20,27,248,249,254,255),(0,1,2),(True,False)):
            with self.subTest(flag=flag,marker=marker,mode=mode,bank=bank):
                old=run(self.v4,self.asm,flag=flag,marker=marker,mode=mode,bank=bank)
                new=run(self.v5,self.asm,flag=flag,marker=marker,mode=mode,bank=bank)
                self.assertEqual(new['exit'],old['exit'])
                takeover=flag==0 and 249<=marker<=254 and new['exit']=='build'
                self.assertEqual((new['updating'],new['counter']),(0,0) if takeover else (1,2))
                self.assertEqual(new['kept'],old['kept'])

    def test_registers_outside_r0_to_r2_are_not_touched(self):
        result=run(self.v5,self.asm,flag=0,marker=250,mode=1)
        self.assertEqual(result['kept'],{**KEPT,UC_ARM_REG_R4:0})


if __name__=='__main__':unittest.main()
