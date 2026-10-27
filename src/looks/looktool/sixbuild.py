"""Reproduce guarded full7-v4 programs offline from pinned three-look files.

No USB or profile payloads. Resources, settings and retained-image state need
separate verified transactions; a program build does not perform them.
"""
import struct
from .firmware import AP_SHA,CP_SHA,sha,transition,apply
from .hooks import assembler,ap_converter,HELPER
from .six import TABLE_FILE,TABLE_VA,PREFIX_VA,MAGIC,prefix,read_tables,retry_windows
CHECKER=0xc2ff10
LEGACY=HELPER+0x4c
LABEL_IDS=[0x0200ab2d,0x0200ab2c,0x0200ab2e,0x0200ab2f,0x0200ab30,0x0200ab31]

def checker(asm):
 lines=['push {r0,r1,r2,r4,r5,r6,r7,lr}',
  f'movw r4,#{PREFIX_VA&65535}',f'movt r4,#{PREFIX_VA>>16}',
  'ldr r5,[r4]',f'movw r6,#{MAGIC&65535}',f'movt r6,#{MAGIC>>16}',
  'cmp r5,r6','bne invalid','ldr r5,[r4,#4]','movw r6,#6','movt r6,#1','cmp r5,r6','bne invalid',
  'add.w r4,r4,#8','ldr.w r4,[r4,r3,lsl #2]',
  'movw r5,#40389','movt r5,#33052','movw r6,#403','movt r6,#256','movw r1,#1215',
  'loop:','ldrb r0,[r2],#1','eors r5,r0','muls r5,r6,r5','subs r1,#1','bne loop',
  'cmp r5,r4','ite eq','moveq r3,#1','movne r3,#0','pop {r0,r1,r2,r4,r5,r6,r7,pc}',
  'invalid:','movs r3,#0','pop {r0,r1,r2,r4,r5,r6,r7,pc}']
 code=asm('\n'.join(lines),CHECKER)
 if len(code)>160:raise ValueError('Checker exceeds existing metadata tail mapping')
 return code

def helper(asm,settle=False):
 gate=HELPER+0xc8
 lines=['push {r0,r1,r2,lr}','ldrb.w r3,[sl,#1]','cmp r3,#1',f'bne 0x{gate:x}',
 'ldrb.w r3,[sl,#0x2e]','sub.w r3,r3,#249','cmp r3,#5',f'bhi 0x{LEGACY:x}',
 'ldr.w r3,[sb,#4]','ldrb r3,[r3,#6]','cmp r3,#1',f'bhi 0x{LEGACY:x}',
 'ldrb.w r3,[sl,#0x2e]','sub.w r3,r3,#249',
 f'movw r2,#{TABLE_VA&65535}',f'movt r2,#{TABLE_VA>>16}',
 'movw r0,#1215','mla r2,r3,r0,r2',f'bl 0x{CHECKER:x}','cmp r3,#0',f'beq 0x{LEGACY:x}',
 'ldr lr,[sp,#12]','add sp,#16','movs r0,#2','movs r1,#1','b store',
 'legacy:','pop {r0,r1,r2,lr}','store:','cmp r2,#0','it eq','moveq r1,r2',
 'str.w r2,[r5,#0x184]','strb.w r1,[r5,#0x188]','strb.w r0,[r5,#0x189]','bx lr']
 code=asm('\n'.join(lines),HELPER)
 if len(code)!=100 or code[0x4c:0x50]!=asm('pop {r0,r1,r2,lr}',LEGACY):raise ValueError('Legacy frame restore differs')
 blob=bytearray(256);blob[:len(code)]=code
 gamma=asm('subw r1,r0,#249;cmp r1,#5;it ls;movls r0,#0;b.w 0x240832',HELPER+0x70)
 blob[0x70:0x70+len(gamma)]=gamma
 if settle:
  # A custom marker that takes over from the native counter state machine ends
  # that machine first: LUT-update flag (desc+0x28) and counter (ctx+0x27) to
  # idle, like the native completion step. r1-r3 are dead at both exits.
  skip=HELPER+0x64
  blob[0x64:0x68]=asm('b.w 0x23d516',skip)
  guard=asm('\n'.join(['cbnz r4,build','ldrb.w r0,[sl,#0x2e]',
  'subs r0,#249','cmp r0,#5',f'bhi 0x{skip:x}','ldr.w r0,[sb,#4]','ldrb r0,[r0,#6]',
  'cmp r0,#1','beq take',f'bhi 0x{skip:x}','ldr.w r0,[r8,#0xc]','ldr.w r0,[r0,#0x6b0]',
  'cmp r0,#0',f'beq 0x{skip:x}','take:','ldrd r0,r1,[r8,#8]','movs r2,#0',
  'strb.w r2,[r0,#0x28]','strb.w r2,[r1,#0x27]','build:','mov r0,sb','b.w 0x23d4e8']),HELPER+0x90)
 else:
  guard=asm('\n'.join(['cmp r4,#0','bne build','ldrb.w r0,[sl,#0x2e]',
  'sub.w r0,r0,#249','cmp r0,#5','bhi skip','ldr.w r0,[sb,#4]','ldrb r0,[r0,#6]',
  'cmp r0,#1','beq build','bhi skip','ldr.w r0,[r8,#0xc]','ldr.w r0,[r0,#0x6b0]',
  'cmp r0,#0','beq skip','build:','mov r0,sb','b.w 0x23d4e8','skip:','b.w 0x23d516']),HELPER+0x90)
 if len(guard)>0x38:raise ValueError('Preview guard overlaps helper gate')
 blob[0x90:0x90+len(guard)]=guard
 availability=asm('\n'.join(['cmp r3,#0',f'bne 0x{LEGACY:x}',
 'ldr.w r3,[sb,#4]','ldrb r3,[r3,#6]','cmp r3,#1','beq resume',f'bhi 0x{LEGACY:x}',
 'ldr.w r3,[r8,#0xc]','ldr.w r3,[r3,#0x6b0]','cmp r3,#0',f'beq 0x{LEGACY:x}',
 'resume:',f'b.w 0x{HELPER+10:x}']),gate)
 if 0xc8+len(availability)>256:raise ValueError('Availability guard exceeds helper region')
 blob[0xc8:0xc8+len(availability)]=availability
 return bytes(blob)

def build(ap,cp,tables,native_cp_original):
    if sha(ap)!=AP_SHA or sha(cp)!=CP_SHA:raise ValueError('Exact historical three-look preview-v2 AP/CP required')
    if sha(native_cp_original)!='60a9de1a0636c7f6b5b98607a4d25eeb48634e25294f632743a6d256e583b370':raise ValueError('Exact original FL2/FL3 CP required')
    payload=prefix(tables)
    if any(cp[TABLE_FILE:TABLE_FILE+len(payload)]):raise ValueError('Prefix source storage differs')
    a,c=bytearray(ap),bytearray(cp);asm=assembler()
    a[0x3528804:0x3528874]=ap_converter()
    for selector in range(10,16):struct.pack_into('<I',a,0x4b4a564+selector*8,0)
    for i,label in enumerate(LABEL_IDS):struct.pack_into('<I',a,0x59896f0+i*0xb8,label)
    c[TABLE_FILE:TABLE_FILE+len(payload)]=payload;c[0xb27490:0xb27590]=helper(asm)
    check=checker(asm)
    if len(check)>96:raise ValueError('Checker overlaps switch bridge')
    # This exact pinned source owns retired CC/NC-only metadata trampolines
    # here. Both callers below are restored before their storage is reused.
    c[CHECKER-0x108000:CHECKER-0x108000+160]=check+bytes(160-len(check))
    for at in (0x148e5e,0x149e14):c[at:at+4]=native_cp_original[at:at+4]
    # Retain the genuine branch-boundary repair; never target the second
    # half of the existing wide branch at0x23d4e4.
    for at,old,new in [(0x1354d2,'cbz r4,0x23d516','cbz r4,0x23d4e4'),
                       (0x1354e2,'b 0x23d4e6','b 0x23d4e4'),
                       (0x1358c8,'movs r5,#0;b 0x23db98','b.w 0xc2ff70')]:
        original=asm(old,at+0x108000)
        if c[at:at+len(original)]!=original:raise ValueError('Switch source instruction differs')
        c[at:at+len(original)]=asm(new,at+0x108000)
    bridge=asm('\n'.join(['ldr.w r0,[r8]','ldrb r2,[r0,#1]','cmp r2,#0','bne legacy',
        'ldrb.w r2,[r0,#0x2e]','sub.w r2,r2,#249','cmp r2,#5','bhi legacy',
        'ldr r0,[sp,#0x38]','ldr r0,[r0,#8]','ldrb.w r2,[r0,#0x188]','cmp r2,#1','bne legacy',
        'ldrb.w r2,[r0,#0x189]','cmp r2,#2','bne legacy',
        'movs r1,#4','mov.w lr,#4','b.w 0x23d8cc','legacy:','movs r5,#0','b.w 0x23db98']),CHECKER+0x60)
    if len(bridge)!=58:raise ValueError('Switch bridge extent differs')
    c[CHECKER+0x60-0x108000:CHECKER+0x60-0x108000+58]=bridge
    if c[0x13553a:0x13553e]!=asm('movw r0,#0x29b0',0x23d53a):raise ValueError('Retry hook source differs')
    for at,data in retry_windows(asm):
        if at!=0x13553a and any(c[at:at+len(data)]):raise ValueError('Retry storage occupied')
        c[at:at+len(data)]=data
    before={'appFw.so':ap,'cpapp-b.bin':cp};after={'appFw.so':bytes(a),'cpapp-b.bin':bytes(c)}
    regions={'appFw.so':[(0x3528804,112)]+[(0x4b4a564+i*8,4) for i in range(10,16)]+[(0x59896f0+i*0xb8,4) for i in range(6)],
        'cpapp-b.bin':[(TABLE_FILE,3661),(TABLE_FILE+3661,3661),(0xb27490,256),(CHECKER-0x108000,160),(0x148e5e,4),(0x149e14,4),
                      (0x1354d2,2),(0x1354e2,2),(0x1358c8,4),(0x13553a,4)]}
    if c[0x20124:0x20154]!=cp[0x20124:0x20154]:raise ValueError('Segment headers changed')
    _,length,start=struct.unpack_from('<3I',cp,0x20124)
    for at,n in [(HELPER,256),(CHECKER,160)]:
        if not start<=at<at+n<=start+length:raise ValueError('Executable storage exceeds loaded text')
    read_tables(after['cpapp-b.bin'])
    forward,reverse=transition(before,after,regions),transition(after,before,regions)
    if apply(apply(before,forward),reverse)!=before:raise ValueError('Six-look inverse differs')
    report={'status':'OFFLINE_SIX_PROGRAM_TRANSITION_REQUIRES_SEPARATE_INTEGRATION','camera_io':False,
        'additional_quantization':False,'raw_table_bytes':7290,'header_bytes':32,'native_grid':[5,9,9],'native_signed_bits':7,
        'per_use_integrity_gate':True,'preview_revision':'native-upload-gate','segment_headers_unchanged':True,
        'resource_label_ids':[hex(v) for v in LABEL_IDS],
        'remaining_integration':['68 validated language/layout resource files','Fresh per-body ST settings provisioning and preservation',
            'Exact native worker transaction and tested inverse','Retained-image evidence and physical cold-load testing'],
        'CP_running_memory_directly_read':False,'universal_installer':False}
    return after,forward,reverse,report
