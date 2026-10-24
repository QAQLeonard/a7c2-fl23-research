"""Reviewable Thumb sources for the isolated EVF trial; no camera or firmware.

The production planner carries fixed bytes and does not import this assembler.
All storage replaces exact native instruction ranges, never zero-filled space.
"""
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB


def build():
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)

    def block(address, size, source):
        raw = bytes(ks.asm(source, addr=address)[0])
        if len(raw) > size or len(raw) % 2:
            raise ValueError(f'EVF code extent differs at {address:x}: {len(raw)}/{size}')
        return raw + bytes.fromhex('00bf') * ((size - len(raw)) // 2)

    resolver = block(0x42cd72, 52, '''
        lsls r1, r0, #24
        bpl 0x42cde8
        bl 0x74c1f0
        addw r5, r0, #0x664
        ldrb r0, [r5, #0x24]
        lsls r1, r0, #24
        bpl 0x42cde8
        ldr r1, [r5, #0x20]
        ldr r2, [r6, #0x14]
        cmp r1, r2
        bne 0x42cde8
        ldr r1, [r4, #4]
        ubfx r1, r1, #20, #3
        cmp r1, #3
        beq 0x42cde8
        cmp r1, #4
        bhi 0x42cde8
        movs r2, #2
        lsls r2, r1
        tst r0, r2
        bne 0x42ce1e
        b 0x42cdea
    ''')
    consume = block(0x42cde4, 58, '''
        cbz r0, 0x42ce1e
        b 0x42cd72
        movs r2, #0
        ldr r0, [r6, #0x14]
        cbz r0, 0x42ce1e
        movs r1, #0
        str r1, [sp, #4]
        str r0, [sp, #8]
        add r1, sp, #4
        mov r0, r4
        mov r4, r2
        nop; nop; nop; nop; nop
        bl 0x78aa20
        b 0x42ce1e
    ''')
    # Preserve the native override's source-read order: 95,96,98..a6,97.
    # The two holes and all stack destinations match the original unroll.
    override = block(0x42ce62, 48, '''
        ldrb r1, [r0, #0x95]
        strb.w r1, [sp, #0xc]
        ldrb r1, [r0, #0x96]
        strb.w r1, [sp, #0xd]
        addw r0, r0, #0x98
        add r1, sp, #0xe
        movs r2, #15
    loop:
        ldrb r3, [r0], #1
        strb r3, [r1], #1
        subs r2, #1
        bne loop
        ldrb r0, [r0, #-16]
        strb.w r0, [sp, #0x1d]
        b 0x42cef2
    ''')
    ack = block(0x42ce92, 96, '''
        push {r4, r6, r7, lr}
        ldr r0, [sp, #36]
        subw r1, pc, #0x8f
        cmp r0, r1
        bne unlock
        ldr r6, [sp, #20]
        cbz r6, unlock
        movw r2, #0x3da8
        movt r2, #0x200
        movs r3, #2
    frame:
        ldrb r0, [r2, #0x18]
        lsls r1, r0, #24
        bpl next
        ldr r1, [r2, #0x14]
        ldr r4, [r5, #4]
        cmp r1, r4
        bne next
        orrs r0, r6
        strb r0, [r2, #0x18]
    next:
        movw r4, #0x19fc
        add r2, r4
        subs r3, #1
        bne frame
    unlock:
        blx 0x6073c4
        pop {r4, r6, r7, pc}
    ''')
    hook = block(0x78aac8, 4, 'bl 0x42ce92')
    return dict(resolver=resolver, consume=consume, override=override + ack, unlock_hook=hook)
