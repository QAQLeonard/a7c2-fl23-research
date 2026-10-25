"""Uninstalled, separately scoped task-try-lock pool-sample prototype.

The successful path tries native lock6c once, reads three fixed words and
releases it. A failed try never samples or waits. Any native failure is an
unqualified reply for a future client, not permission to retry or free.
Does not prove all pool writers use this lock, physical IRQ latency or safe boot.
"""
from keystone import Ks,KS_ARCH_ARM,KS_MODE_THUMB
from . import cp_pool_probe as sample

BASE=sample.BASE
TRY_FILE,UNLOCK_FILE=0x4e66f0,0x4e68a8
TRY,UNLOCK=BASE+TRY_FILE,BASE+UNLOCK_FILE
TAIL=0x45e7d0
FORMAT=0x45e7c8
END=0x45e7f8
ERROR=0x45e74c
EPILOGUE=0x45e7b8
FAULT=sample.PROBE+18
STATUS=0x5d
OLD_FORMAT=b'[ulogio] ulogio_read_backup:0x%x error:0x%x\n\0\0\0\0'
NEW_FORMAT=b'E%x:%x\n\0'


def windows(original,current):
    source_windows=sample.windows(original,current)
    if current[FORMAT:END]!=OLD_FORMAT or len(OLD_FORMAT)!=48 or len(NEW_FORMAT)!=8:
        raise ValueError('Exact callback diagnostic format extent required')
    ks=Ks(KS_ARCH_ARM,KS_MODE_THUMB)
    assemble=lambda text,at:bytes(ks.asm(text,addr=BASE+at)[0])
    for at,size in ((TRY_FILE,0xdc),(UNLOCK_FILE,0xe0)):
        if current[at:at+size]!=original[at:at+size]:raise ValueError('Native try/release source differs')
    compact=source_windows[1][1][:32]
    body=assemble(';'.join((
        'subs r1,#0xe1','cmp r1,#0',f'bhi {BASE+sample.DEFAULT:#x}',
        'movs r0,#0x6c',f'blx {TRY:#x}',
        'cmp r0,#0',f'bne {BASE+ERROR:#x}',f'b {BASE+TAIL:#x}',
        'movs r1,#0x82','strb r1,[r4,#1]',f'b {BASE+EPILOGUE:#x}')),sample.PROBE)
    tail=assemble(';'.join((
        'movw r6,#0x4720','movt r6,#0x22b',
        'ldr r0,[r6]','str r0,[r4,#8]','ldr r0,[r6,#8]','str r0,[r4,#12]',
        'ldr r0,[r6,#16]','str r0,[r4,#16]',
        'movs r0,#0x6c',f'blx {UNLOCK:#x}',
        'cmp r0,#0',f'bne {BASE+FAULT:#x}',
        f'movs r1,#{STATUS}','strb r1,[r4,#1]',f'b {BASE+EPILOGUE:#x}',
        'nop','nop')),TAIL)
    if (len(compact),len(body),len(tail))!=(32,24,40):raise ValueError('Callback prototype does not fit exact original extents')
    return [source_windows[0],(sample.ALIGN,compact+body),(FORMAT,NEW_FORMAT+tail)]


def apply_for_emulator(original,current):
    changes=windows(original,current);target=bytearray(current)
    for at,raw in changes:target[at:at+len(raw)]=raw
    inverse=bytearray(target)
    for at,raw in changes:inverse[at:at+len(raw)]=current[at:at+len(raw)]
    if bytes(inverse)!=current:raise ValueError('Exact inverse failed')
    return bytes(target),changes
