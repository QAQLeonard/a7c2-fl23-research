"""Pinned AArch64 ET_REL image in synthetic emulator memory only.

Apply own-section ABS64 relocations; expose external call boundaries instead
of executing kernel APIs. This is not a live or general kernel loader.
"""

import hashlib
import io
import struct
from elftools.elf.elffile import ELFFile

UIPC_SHA = "f0eb3a32a9d339066600e012aa3e91de31419c173e3fe5c1cc44aa9188763095"
PCIE_SHA = "26f376a9025f0b56b5ede7ebabdbf5dd8a5235d6627abe2abfd1430e2af578bc"


def q(value):
    return struct.pack("<Q", value)


class Module:
    def __init__(self, u, raw, digest, base):
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Unsupported original kernel module")
        self.u = u
        e = self.elf = ELFFile(io.BytesIO(raw))
        assert e["e_type"] == "ET_REL" and e["e_machine"] == "EM_AARCH64"
        symbols = e.get_section_by_name(".symtab")
        self.names, self.bases, self.calls, self.rel = {}, {}, {}, {}
        for i, sec in enumerate(e.iter_sections()):
            if not sec["sh_flags"] & 2 or not sec["sh_size"]:
                continue
            address = base + len(self.bases) * 0x100000
            assert sec["sh_size"] <= 0x100000
            self.names[sec.name] = address
            self.bases[i] = address
            u.mem_map(address, (sec["sh_size"] + 4095) & ~4095)
            if sec["sh_type"] != "SHT_NOBITS":
                u.mem_write(address, sec.data())
        for sec in e.iter_sections():
            if sec["sh_type"] != "SHT_RELA" or sec["sh_info"] not in self.bases:
                continue
            for r in sec.iter_relocations():
                sym = symbols.get_symbol(r["r_info_sym"])
                at = self.bases[sec["sh_info"]] + r["r_offset"]
                self.rel[at] = dict(
                    type=r["r_info_type"],
                    name=sym.name,
                    section=sym["st_shndx"],
                    addend=r["r_addend"],
                )
                if r["r_info_type"] == 257 and sym["st_shndx"] in self.bases:
                    u.mem_write(
                        at, q(self.bases[sym["st_shndx"]] + sym["st_value"] + r["r_addend"])
                    )
                elif r["r_info_type"] in (282, 283):
                    self.calls[at] = sym.name
        self.functions = {
            sym.name: (self.bases[sym["st_shndx"]] + sym["st_value"], sym["st_size"])
            for sym in symbols.iter_symbols()
            if sym["st_info"]["type"] == "STT_FUNC" and sym["st_shndx"] in self.bases
        }

    def at(self, section, offset):
        return self.names[section] + offset


def text_literal_dependencies(module, ranges):
    """Find scalar LDR literals in explicit original .text instruction slices.

    Module already pins the original ELF. Mapping symbols distinguish code from
    inline data; decoded targets are cross-checked against the instruction word.
    Results are section offsets, never a memory-read or loaded-source permit.
    This covers direct literal loads only, not arbitrary address computations
    or the contents subsequently reached through a pointer.
    """
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    from capstone.arm64_const import ARM64_OP_IMM

    elf = module.elf
    section = elf.get_section_by_name('.text')
    raw = section.data()
    section_index = elf.get_section_index('.text')
    symbols = elf.get_section_by_name('.symtab')
    markers = {}
    for symbol in symbols.iter_symbols():
        if symbol['st_shndx'] == section_index and symbol.name.split('.')[0] in ('$x', '$d'):
            at, kind = symbol['st_value'], symbol.name[1]
            if at in markers and markers[at] != kind:
                raise ValueError('Conflicting original mapping symbols')
            markers[at] = kind
    ordered = sorted(markers)

    def extent(begin, end, kind):
        if not 0 <= begin < end <= len(raw):
            raise ValueError('Original .text extent required')
        preceding = [at for at in ordered if at <= begin]
        if not preceding or markers[preceding[-1]] != kind:
            raise ValueError('Code/literal mapping differs')
        if any(markers[at] != kind for at in ordered if begin < at < end):
            raise ValueError('Span crosses code/literal mapping')

    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    dependencies = {}
    for begin, end in ranges:
        if type(begin) is not int or type(end) is not int or begin & 3 or end & 3:
            raise ValueError('Aligned instruction offsets required')
        extent(begin, end, 'x')
        instructions = list(decoder.disasm(raw[begin:end], begin))
        if len(instructions)*4 != end-begin or any(i.size != 4 for i in instructions):
            raise ValueError('Incomplete original instruction decoding')
        for instruction in instructions:
            word = struct.unpack_from('<I', raw, instruction.address)[0]
            if word & 0x3b000000 != 0x18000000:
                continue
            opcode = word >> 30
            if word & (1 << 26) or opcode == 3:
                raise ValueError('Unsupported vector/prefetch literal')
            width = 8 if opcode == 1 else 4
            displacement = (word >> 5) & 0x7ffff
            if displacement & (1 << 18):
                displacement -= 1 << 19
            target = instruction.address + 4*displacement
            operands = instruction.operands
            if (instruction.mnemonic not in ('ldr', 'ldrsw') or len(operands) != 2
                    or operands[1].type != ARM64_OP_IMM or operands[1].imm != target):
                raise ValueError('Literal decoder and encoding disagree')
            extent(target, target+width, 'd')
            key = (target, width)
            row = dependencies.setdefault(key, dict(begin=target, end=target+width, bytes=width,
                                                    readers=[], relocations=[]))
            if instruction.address not in row['readers']:
                row['readers'].append(instruction.address)
    relocations = elf.get_section_by_name('.rela.text')
    for (begin, width), row in dependencies.items():
        for relocation in relocations.iter_relocations():
            at = relocation['r_offset']
            size = {257: 8, 282: 4, 283: 4}.get(relocation['r_info_type'], 8)
            if at < begin+width and begin < at+size:
                if relocation['r_info_type'] != 257 or at != begin or width != 8:
                    raise ValueError('Unqualified or partial literal relocation')
                symbol = symbols.get_symbol(relocation['r_info_sym'])
                index = symbol['st_shndx']
                row['relocations'].append(dict(type=257, symbol=symbol.name,
                    target_section=elf.get_section(index).name if type(index) is int else index,
                    symbol_offset=symbol['st_value'], addend=relocation['r_addend']))
        if len(row['relocations']) > 1:
            raise ValueError('Overlapping literal relocations')
    return [dependencies[key] for key in sorted(dependencies)]
