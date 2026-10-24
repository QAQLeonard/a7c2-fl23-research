"""Offline single-callback pool sample prototype; no device deployment.

Uses the already observed fixed head/tail/count locations. Three aligned reads
are not atomic, IRQ-serialized or ABA-safe; host consistency checks cannot turn
them into an ownership/completion fence. No pixels, pointers or native services
are followed. This is a separate, unapproved candidate from the four-word test.
"""
import struct
from keystone import Ks,KS_ARCH_ARM,KS_MODE_THUMB
from . import cp_metadata_probe as prior

BASE,BRANCH,ALIGN,CALL,DEFAULT,ENTRY=prior.BASE,prior.BRANCH,prior.ALIGN,prior.CALL,prior.DEFAULT,prior.ENTRY
PROBE=ALIGN+32
STORE=0x45e7b0
HEAD,TAIL,COUNT=0x22b4720,0x22b4728,0x22b4730
STATUS=0x5c


def windows(original,current):
    prior.windows(original,current)  # Same original-source callback guards.
    ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB)
    assemble=lambda text,offset:bytes(ks.asm(text,addr=BASE+offset)[0])
    # SUB recovers address low6 bits in2 bytes; its flags are overwritten
    # before the unchanged cache call. Full-register/APSR comparison required.
    compact=assemble(';'.join((
        'bic r6,r3,#63','bic r0,r1,#63','subs r1,r1,r0','subs r3,r3,r6',
        'adds r5,r1,r3','adds r5,#63','bic r5,r5,#63','movs r2,#0',
        'mov.w ip,#64','movs r3,#0','adds r1,r5,r6',f'b {BASE+CALL:#x}')),ALIGN)
    # Subtract then compare0 retains original C/V on EVERY rejected mode;
    # only e2 reaches the three immediate-address reads and private status5c.
    body=assemble(';'.join((
        'subs r1,#0xe1','cmp r1,#0',f'bhi {BASE+DEFAULT:#x}',
        'movw r0,#0x4720','movt r0,#0x22b','ldr r2,[r0,#8]',
        'ldr r3,[r0,#16]','ldr r0,[r0]',f'movs r1,#{STATUS}',f'b {BASE+STORE:#x}')),PROBE)
    jump=assemble(f'bhi {BASE+PROBE:#x}',BRANCH)
    if (len(jump),len(compact),len(body))!=(2,32,24) or ALIGN+len(compact)+len(body)!=CALL:
        raise ValueError('Exact existing callback extent differs')
    return [(BRANCH,jump),(ALIGN,compact+body)]


def apply_for_emulator(original,current):
    changes=windows(original,current);out=bytearray(current)
    for at,raw in changes:out[at:at+len(raw)]=raw
    inverse=bytearray(out)
    for at,raw in changes:inverse[at:at+len(raw)]=current[at:at+len(raw)]
    if bytes(inverse)!=current:raise ValueError('Exact pool-prototype inverse failed')
    return bytes(out),changes


def decode_sample(raw,nonce):
    if not isinstance(raw,bytes) or len(raw)!=24 or type(nonce) is not int or not 0<nonce<=0xffffffff:
        raise ValueError('Exact24-byte sample and nonce required')
    mode,status,pad,head,tail,count,actual_nonce=struct.unpack('<BB6s4I',raw)
    if mode!=0xe2 or status!=STATUS or any(pad) or actual_nonce!=nonce:
        raise ValueError('Wrong/foreign/refused sample')
    if max(head,tail,count)>1023 or ((tail-head)&1023)!=count:
        raise ValueError('Out-of-range or inconsistent pool sample')
    return dict(head=head,tail=tail,free_metadata_records=count,physical_pixels_proven=False,
        atomic_or_owner_serialized_snapshot=False,ABA_excluded=False,terminal_resource_fence=False)
