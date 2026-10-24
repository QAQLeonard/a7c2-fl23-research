"""Experimental native-photo call wrappers for the reviewed full7/FL23 layout.

Offline only. Reuses project-owned retired arrays inside unchanged loaded
segments. The caller must supply fresh ST records and independently establish
storage ownership, backup, inverse and hardware test authorization. This is
not a generic stock installer or a declaration of camera safety.
"""
import struct
from . import photoformat, photobasis

BASE = 0x108000
TABLE_FILE, TABLE_VA = 0xb27590, 0xc2f590
GAMMA_ROWS = 62  # fifty original rows plus two original ST domains per slot
CODE_FILE, CODE_VA = TABLE_FILE + GAMMA_ROWS * 28, TABLE_VA + GAMMA_ROWS * 28
CODE_END = 0xc2ff0e
DATA_FILE, DATA_VA = 0x1101ae0, 0x1209ae0
MODE_VA = DATA_VA + 16
PARAMS_VA = DATA_VA + 64
LEGACY_MODE_VA = PARAMS_VA + 6 * photobasis.STRIDE
MAGIC = 0x34504841
REVISION = 'native-ST-dual-domain-v2'


def build(source, baseline, knobs, *, active_mask=0x3f):
    if len(knobs) != 6 or active_mask not in range(64):
        raise ValueError('Six native parameter sets and a six-bit activation mask required')
    # Enable the assembler's IDIV feature. UDIV already occurs in the native
    # CP gamma builder; this does not introduce a new camera ISA requirement.
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB, KS_MODE_V8
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB | KS_MODE_V8)
    asm = lambda text, address: bytes(ks.asm(text, addr=address)[0])
    target = bytearray(source)
    code = bytearray()
    labels = {}

    def allocate(name, text):
        while len(code) % 4:
            code.extend(b'\0\xbf')
        address = CODE_VA + len(code)
        data = asm(text, address)
        labels[name] = {'address': address, 'bytes': len(data)}
        code.extend(data)
        return address

    def literal(reg, address):
        return [f'movw {reg},#{address & 65535}', f'movt {reg},#{address >> 16}']

    # The native data table is relocated into two retired, formerly authored
    # raw correction arrays; all original rows remain byte-exact.
    old_table = source[0x1209480 - BASE:0x1209480 - BASE + 50 * 28]
    table = bytearray(old_table)
    # ST selects row0 or row10 before one of seven curve columns. Preserve
    # both domains and resolve null entries by Sony's row0,column6 fallback.
    table.extend(photoformat.custom_gamma_rows(old_table))
    target[TABLE_FILE:CODE_FILE] = table
    pointers = {struct.unpack_from('<I', old_table, row*28+column*4)[0]
                for row in (0, 10) for column in range(7)} - {0}
    # The same measured Q10 controls apply to every native ST variant, not
    # merely the two representative records carried by the portable format.
    for spec in knobs:
        for pointer in pointers:
            photobasis.curve(source[pointer-BASE:pointer-BASE+576], spec.get('tone', (0,0,0)))

    data = bytearray(struct.pack('<4I', MAGIC, 1, active_mask, photobasis.STRIDE))
    data.extend(b''.join(struct.pack('<2I', 50 + 2*i, 51 + 2*i) for i in range(6)))
    for spec in knobs:
        raw, _ = photobasis.pack(baseline, **spec)
        data.extend(raw)
    legacy_at = 0x12099f8 - BASE + 29 * 8
    data.extend(source[legacy_at:legacy_at + 4 * 8])
    if len(data) > 1216:
        raise ValueError('Native basis exceeds the owned retired NN array')
    target[DATA_FILE:DATA_FILE + len(data)] = data

    # Trampolines preserve the original, complete four-byte function prologues.
    primary_tramp = allocate('primary_trampoline',
        'push {r4,r5,r6,r7,lr};add r7,sp,#12;b.w 0x7512e8')
    secondary_tramp = allocate('secondary_trampoline',
        'push {r4,r5,r6,r7,lr};add r7,sp,#12;b.w 0x751640')

    def add_wrapper(name, native_entry, context_reg, parameter_reg, offset, count):
        lines = [f'cmp {parameter_reg},#0', 'bne native', f'cmp {context_reg},#0', 'beq native',
                 f'ldr ip,[{context_reg}]', 'cmp.w ip,#0', 'beq native',
                 'ldrb.w ip,[ip,#1]', 'cmp.w ip,#1', 'bhi native', f'ldr ip,[{context_reg}]',
                 'ldrb.w ip,[ip,#0x2e]', 'sub.w ip,ip,#249', 'cmp.w ip,#5', 'bhi native',
                 'push {r4,r5,r6,lr}', 'mov r4,r0', 'mov r5,ip']
        lines += literal('r6', DATA_VA)
        lines += ['ldr ip,[r6,#8]', 'lsr.w ip,ip,r5', 'tst ip,#1', 'beq inactive',
                  f'bl 0x{native_entry:x}']
        # Native callees preserve r6; retain the data-base pointer across the
        # call rather than loading another absolute address afterwards.
        lines += ['adds r6,#64']
        lines += [f'movs r0,#{photobasis.STRIDE}', 'mla r6,r5,r0,r6', f'adds r6,#{offset}',
                  f'movs r3,#{count}', 'loop:', 'ldrh r0,[r4]', 'ldrsh r1,[r6],#2',
                  'add r0,r1', 'strh r0,[r4],#2', 'subs r3,#1', 'bne loop',
                  'pop {r4,r5,r6,pc}', 'inactive:', 'pop {r4,r5,r6,lr}',
                  'native:', f'b.w 0x{native_entry:x}']
        return allocate(name, '\n'.join(lines))

    matrix = add_wrapper('matrix', 0x751092, 'r2', 'r3', 6, 27)
    primary = add_wrapper('primary_chroma', primary_tramp, 'r2', 'r1', 60, 24)
    secondary = add_wrapper('secondary_chroma', secondary_tramp, 'r3', 'r1', 60, 8)

    # The ordinary gamma paths retain their original table and mode behavior.
    # A distinct table is returned only for active imported markers.
    gamma_selector = allocate('gamma_selector', '\n'.join([
        'sub.w r1,r0,#249', 'cmp r1,#5', 'bhi native', *literal('ip', DATA_VA),
        'ldr ip,[ip,#8]', 'lsr.w ip,ip,r1', 'tst.w ip,#1', 'beq inactive',
        'mov r0,r1', *literal('r1', MODE_VA), 'bx lr',
        'inactive:', 'movs r0,#0', 'native:',
        'cmp r0,#29', 'blo old', 'cmp r0,#32', 'bhi old', 'subs r0,#29',
        *literal('r1', LEGACY_MODE_VA), 'bx lr', 'old:', 'b.w 0x240832']))

    # The wrapper supplies its temporary record in r8, which native gamma
    # saves but does not otherwise read before this load. The saved incoming
    # LR proves the call came through our wrapper; all other callers retain
    # the native ROM pointer. No extra fields are read from the info object.
    def record_hook(return_address, address):
        displacement = return_address-((address+16)&~3) if return_address else 0
        if not 0 <= displacement < 4096:raise ValueError('Gamma return guard exceeds its ADR range')
        return '\n'.join(['cmp r2,#50', 'blo native', 'cmp r2,#61', 'bhi native',
            'ldr.w ip,[sp,#124]', f'addw r6,pc,#{displacement}', 'cmp ip,r6',
            'bne native', 'mov r6,r8', 'bx lr', 'native:',
            'ldr.w r6,[r0,r3,lsl #2]', 'bx lr'])
    record_load = allocate('gamma_record_load', record_hook(0, CODE_VA+((len(code)+3)&~3)))

    gamma_lines = [
        'ldr.w ip,[r2,#0x10]', 'sub.w ip,ip,#50', 'cmp.w ip,#11', 'bhi native',
        'push {r4,r5,r6,r7,r8,r9,r10,r11,lr}', 'sub sp,#4',
        'mov r4,r2', 'mov r5,r3', 'lsr.w r6,ip,#1', 'mov r7,r1', 'mov r8,r0',
        'sub.w sp,sp,#0x240',
        'ldr r0,[r4,#0x10]', 'movs r1,#28', 'mul r0,r1,r0',
        *literal('r1', TABLE_VA), 'add r1,r0', 'ldrb.w r2,[r4,#0x18]',
        'ldr.w r1,[r1,r2,lsl #2]', 'mov r0,sp', 'movw r2,#576', 'blx 0x61e60c',
        *literal('r0', PARAMS_VA), f'movs r1,#{photobasis.STRIDE}', 'mla r0,r6,r1,r0',
        'ldrsh.w r9,[r0]', 'ldrsh.w r10,[r0,#2]', 'ldrsh.w r11,[r0,#4]',
        'mov r6,sp', 'mov.w ip,#129', 'loop:',
        'ldr r0,[r6]', 'ldr r1,[sp,#0x200]', 'lsl.w r2,r0,#12',
        'udiv r1,r2,r1', 'rsb.w r2,r1,#4096',
        'mul r3,r0,r9', 'asrs r3,#10', 'add.w lr,r0,r3',
        'mul r3,r0,r10', 'asrs r3,#10', 'muls r3,r2,r3', 'asrs r3,#12',
        'muls r3,r2,r3', 'asrs r3,#12', 'add lr,r3',
        'mul r3,r0,r11', 'asrs r3,#10', 'muls r3,r1,r3', 'asrs r3,#12',
        'muls r3,r2,r3', 'asrs r3,#12', 'add lr,r3',
        'cmp.w lr,#0', 'bge low_ok', 'mov.w lr,#0', 'low_ok:',
        'movw r3,#65535', 'movt r3,#3', 'cmp lr,r3', 'bls high_ok', 'mov lr,r3', 'high_ok:',
        'str lr,[r6],#4', 'subs.w ip,ip,#1', 'bne loop',
        'ldr r0,[sp,#0x200]', 'str r0,[sp,#0x220]',
        'mov r0,r8', 'mov r1,r7', 'mov r2,r4', 'mov r3,r5', 'mov r8,sp',
        'bl 0x42b44c',
        'add.w sp,sp,#0x240', 'add sp,#4', 'pop {r4,r5,r6,r7,r8,r9,r10,r11,pc}',
        'native:', 'b.w 0x42b44c']
    gamma = allocate('gamma', '\n'.join(gamma_lines))
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    calls = [i for i in decoder.disasm(bytes(code[gamma-CODE_VA:]), gamma)
             if i.mnemonic == 'bl' and i.op_str == '#0x42b44c']
    if len(calls) != 1:
        raise ValueError('Expected exactly one native gamma call')
    after_call = (calls[0].address + calls[0].size) | 1
    replacement = asm(record_hook(after_call, record_load), record_load)
    if len(replacement) != labels['gamma_record_load']['bytes']:
        raise ValueError('Gamma call-frame guard changed code extent')
    code[record_load-CODE_VA:record_load-CODE_VA+len(replacement)] = replacement
    import re
    instructions = list(decoder.disasm(bytes(code), CODE_VA))
    boundaries = {i.address for i in instructions}
    if sum(i.size for i in instructions) != len(code):
        raise ValueError('Wrapper code contains undecodable bytes')
    for instruction in instructions:
        if instruction.mnemonic.startswith(('b', 'cb')):
            for token in re.findall(r'#(0x[0-9a-f]+)', instruction.op_str):
                target_address = int(token, 16)
                if CODE_VA <= target_address < CODE_VA + len(code) and target_address not in boundaries:
                    raise ValueError('Wrapper branch enters the middle of an instruction')

    if CODE_VA + len(code) > CODE_END:
        raise ValueError(f'Wrapper code exceeds owned retired text: {len(code)} > {CODE_END-CODE_VA}')
    target[CODE_FILE:CODE_FILE + len(code)] = code
    patches = [(0xb27500, asm(f'b.w 0x{gamma_selector:x}', 0xc2f500)),
               (0x323474, asm(f'bl 0x{record_load:x}', 0x42b474)),
               (0x6492e4, asm(f'b.w 0x{primary:x}', 0x7512e4)),
               (0x64963c, asm(f'b.w 0x{secondary:x}', 0x75163c)),
               (0x64836c, asm(f'bl 0x{matrix:x}', 0x75036c))]
    expected = {0xb27500: 'subw r1,r0,#249',
                0x323474: 'ldr.w r6,[r0,r3,lsl #2]',
                0x6492e4: 'push {r4,r5,r6,r7,lr};add r7,sp,#12',
                0x64963c: 'push {r4,r5,r6,r7,lr};add r7,sp,#12',
                0x64836c: 'bl 0x751092'}
    for at, text in expected.items():
        old = asm(text, at + BASE)
        if source[at:at + len(old)] != old:
            raise ValueError('Native photo hook instruction differs at ' + hex(at))
    for at in (0x323c64, 0x9ce8b8):
        if source[at:at + 4] != asm('bl 0x42b44c', at + BASE):
            raise ValueError('Native gamma caller instruction differs')
        patches.append((at, asm(f'bl 0x{gamma:x}', at + BASE)))
    for low, high, reg in [(0x32345a, 0x323464, 'r11'), (0x323d82, 0x323d8a, 'r1'),
                           (0x323dd0, 0x323dd8, 'r1'), (0x323eb6, 0x323eba, 'r0'),
                           (0x9cf436, 0x9cf43e, 'r1')]:
        for at, text in ((low, f'movw {reg},#{0x9480}'), (high, f'movt {reg},#{0x120}')):
            old = asm(text, at + BASE)
            if source[at:at + len(old)] != old:
                raise ValueError('Gamma table constructor differs at ' + hex(at))
        patches.extend([(low, asm(f'movw {reg},#{TABLE_VA & 65535}', low + BASE)),
                        (high, asm(f'movt {reg},#{TABLE_VA >> 16}', high + BASE))])
    for at in (0x32325c, 0x323278, 0x9cf404):
        if source[at:at + 2] != asm('cmp r0,#50', at + BASE):
            raise ValueError('Native gamma bound instruction differs')
        patches.append((at, asm('cmp r0,#62', at + BASE)))
    for at, patch in patches:
        target[at:at + len(patch)] = patch
    if target[0x20124:0x20154] != source[0x20124:0x20154]:
        raise ValueError('Segment headers must remain unchanged')
    regions = [(TABLE_FILE, GAMMA_ROWS * 28 + len(code)), (DATA_FILE, len(data))]
    regions += [(at, len(patch)) for at, patch in patches]
    report = {'camera_io': False, 'installable': False, 'active_mask': active_mask,
              'runtime_patch_revision': REVISION,
              'segment_headers_unchanged': True, 'AP_names_calibration_untouched': True,
              'code_bytes': len(code), 'code_capacity': CODE_END - CODE_VA,
              'basis_bytes': len(data), 'labels': labels,
              'complete_ST_gamma_domains_preserved': True, 'gamma_rows': GAMMA_ROWS,
              'regions': regions, 'gamma_extra_stack_bytes': 616,
              'gamma_native_return_address': hex(after_call),
              'storage_ownership_audit_required': True, 'native_ABI_tests_required': True}
    return bytes(target), report
