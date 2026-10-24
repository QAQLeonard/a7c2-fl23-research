"""Offline fixed-pointer diagnostic prototype in the existing callback extent.

This is not an installer, CP RAM writer or permission to change a camera. The
exact current source is bound by a private operator, separately from original
callback byte equivalence. It does not allocate/retain RAWs or follow pointers.
"""
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from keystone import Ks,KS_ARCH_ARM,KS_MODE_THUMB
from .reference import CP_LOAD_BASE

BASE=CP_LOAD_BASE
BRANCH=0x45e6f4
ALIGN=0x45e76c
CALL=0x45e7a4
PROBE=ALIGN+34
DEFAULT=0x45e724
REPLY=0x45e750
ENTRY=0x45e6d8
POINTERS=0x1a8c558
STATUS=0x5b  # Private metadata response; never a native log-buffer status1.
SPANS=((0x45e680,0x148),(0x4fe52c,0x18))


def windows(original,current):
    if len(original)!=len(current) or any(original[a:a+n]!=current[a:a+n] for a,n in SPANS):
        raise ValueError('Current callback or cache wrapper differs from original source')
    ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB)
    assemble=lambda text,offset:bytes(ks.asm(text,addr=BASE+offset)[0])
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    branch=next(md.disasm(original[BRANCH:BRANCH+2],BASE+BRANCH))
    if (branch.mnemonic,branch.op_str)!=('bhi',f'#{BASE+DEFAULT:#x}'):
        raise ValueError('Original callback default branch differs')
    # Preserve all r0-r12/SP/LR and APSR values at the UNCHANGED native cache
    # call site. r5 is64*ceil(((address&63)+(size&63))/64), r6=size&~63.
    # This reclaims instructions with proven equivalent outputs, not padding.
    short=assemble(';'.join((
        'bic r6,r3,#63','bic r0,r1,#63','and r1,r1,#63','subs r3,r3,r6',
        'adds r5,r1,r3','adds r5,#63','bic r5,r5,#63','movs r2,#0',
        'mov.w ip,#64','movs r3,#0','adds r1,r5,r6',f'b {BASE+CALL:#x}')),ALIGN)
    if len(short)!=34:raise ValueError('Compressed cache prefix extent differs')
    # Only e2..e5 are new. Four fixed aligned BSS words, no address from the
    # packet, no dereference of the returned pointer, no new persistent state.
    probe=assemble(';'.join((
        'subs r1,#0xe1','cmp r1,#3',f'bhi {BASE+DEFAULT:#x}',
        'movw r0,#0xc558','movt r0,#0x1a8','ldr.w r0,[r0,r1,lsl #2]',
        f'movs r1,#{STATUS}',f'b {BASE+REPLY:#x}')),PROBE)
    if len(probe)!=22:raise ValueError('Fixed-pointer probe extent differs')
    jump=assemble(f'bhi {BASE+PROBE:#x}',BRANCH)
    if len(jump)!=2 or ALIGN+len(short)+len(probe)!=CALL:
        raise ValueError('Callback extent/branch changed')
    return [(BRANCH,jump),(ALIGN,short+probe)]


def apply_for_emulator(original,current):
    changes=windows(original,current);result=bytearray(current)
    for offset,raw in changes:result[offset:offset+len(raw)]=raw
    restored=bytearray(result)
    for offset,raw in changes:restored[offset:offset+len(raw)]=current[offset:offset+len(raw)]
    if bytes(restored)!=current:raise ValueError('Exact source inverse differs')
    return bytes(result),changes
