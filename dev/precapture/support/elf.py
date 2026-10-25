"""Integer-only compiler policy and strict generated-ELF emulator loader.

No dynamic initialization, dependencies or unresolved runtime relocations
are accepted by image_loader. These helpers never load code on a camera.
"""

import io
import re
from elftools.elf.elffile import ELFFile
from .memory import MEM, STACK, STOP


def standalone_entry(raw, arch):
    """Validate a little-endian MMU-off fixture entry in executable file bytes.

    This is metadata admission, not an executable/source hash check or a Linux
    loader. These ARM/AArch64 fixtures enter ARM state and require identity
    virtual/physical load addresses. No camera admission is supplied.
    """
    machines = {"arm": (32, "EM_ARM"), "aarch64": (64, "EM_AARCH64")}
    if arch not in machines:
        raise ValueError("Unsupported standalone fixture architecture")
    elf = ELFFile(io.BytesIO(raw))
    if not elf.little_endian or (elf.elfclass, elf["e_machine"]) != machines[arch]:
        raise ValueError("Standalone fixture architecture or byte order differs")
    if elf["e_type"] != "ET_EXEC":
        raise ValueError("Standalone fixture requires a static executable")
    entry = elf["e_entry"]
    if entry & 3:
        raise ValueError("Standalone fixture entry is not ARM instruction aligned")
    admitted = []
    for segment in elf.iter_segments():
        if segment["p_type"] == "PT_INTERP":
            raise ValueError("Standalone fixture requires no interpreter")
        if segment["p_type"] != "PT_LOAD":
            continue
        if segment["p_offset"] + segment["p_filesz"] > len(raw) or segment["p_filesz"] > segment["p_memsz"]:
            raise ValueError("Standalone fixture load segment is out of range")
        start = segment["p_vaddr"]
        if segment["p_paddr"] != start:
            raise ValueError("Standalone fixture lacks identity physical placement")
        if start + segment["p_memsz"] > 1 << elf.elfclass:
            raise ValueError("Standalone fixture load address overflows target width")
        if segment["p_flags"] & 1 and start <= entry and entry + 4 <= start + segment["p_filesz"]:
            admitted.append(segment)
    if len(admitted) != 1:
        raise ValueError("Standalone fixture entry is not in one initialized executable segment")
    return entry


def codegen_flags(arch):
    # Zig0.13 chooses the ARM ISA from its target triple: -mthumb alone
    # with arm-linux does not establish Thumb output. Keep FP/SIMD out of
    # these integer-only primitives and assert the generated ELF symbols.
    common = ["-fno-vectorize", "-fno-slp-vectorize"]
    return common + (
        ["-mcpu=cortex_a9-neon-vfp2-vfp3-d32-fpregs"]
        if arch == "thumb"
        # Zig0.13 appends its target features after Clang's general-regs
        # switch. Explicitly remove FP/NEON from that target too; otherwise
        # aggregate copies can still lower to ldr/str q registers.
        else ["-mcpu=generic-neon-fp_armv8", "-mgeneral-regs-only"]
    )


def check_integer_isa(elf, arch):
    """Validate code mapping symbols, excluding embedded data/literal pools."""
    from capstone import Cs, CS_ARCH_ARM, CS_ARCH_ARM64, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN

    md = (
        Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        if arch == "thumb"
        else Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    )
    mappings = {}
    table = elf.get_section_by_name(".symtab")
    if table is None:
        raise ValueError("Research ELF must retain symbols for ISA verification")
    for sym in table.iter_symbols():
        if sym.name.startswith(("$t", "$a", "$x", "$d")) and isinstance(sym["st_shndx"], int):
            section = elf.get_section(sym["st_shndx"])
            if section["sh_flags"] & 4:
                mappings.setdefault(sym["st_shndx"], []).append((sym["st_value"], sym.name[1]))
    if not mappings:
        raise ValueError("No ISA mapping symbols in research ELF")
    instructions = 0
    for index, points in mappings.items():
        section = elf.get_section(index)
        raw = section.data()
        base = section["sh_addr"]
        points = sorted(set(points)) + [(base + section["sh_size"], "end")]
        for (start, kind), (end, _) in zip(points, points[1:]):
            if kind == "d" or start == end:
                continue
            if kind != ("t" if arch == "thumb" else "x"):
                raise ValueError("Unexpected code ISA in generated ELF")
            part = raw[start - base : end - base]
            decoded = list(md.disasm(part, start))
            if sum(i.size for i in decoded) != len(part):
                raise ValueError("Undecodable generated code")
            for ins in decoded:
                if (arch == "thumb" and ins.mnemonic.startswith("v")) or (
                    arch == "aarch64" and re.search(r"\b[vsdqhb][0-9]+\b", ins.op_str)
                ):
                    raise ValueError("FP/SIMD dependency in integer-only research ELF")
            instructions += len(decoded)
    return instructions


def image_loader(path, arch, wanted=("encode_setting", "encode_shooting"), *, cpu_model=None, emulator=None):
    from unicorn import Uc, UC_ARCH_ARM64, UC_ARCH_ARM, UC_MODE_ARM, UC_MODE_THUMB

    if emulator is not None and cpu_model is not None:
        raise ValueError('Configure a composed CPU model before loading either image')
    u = emulator if emulator is not None else (
        Uc(UC_ARCH_ARM64, UC_MODE_ARM) if arch == "aarch64" else Uc(UC_ARCH_ARM, UC_MODE_THUMB))
    if cpu_model is not None:
        u.ctl_set_cpu_model(cpu_model)
    symbols = {}
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        pages = set()
        assert elf["e_type"] == "ET_DYN"
        assert elf["e_machine"] == ("EM_AARCH64" if arch == "aarch64" else "EM_ARM")
        check_integer_isa(elf, arch)
        for section in elf.iter_sections():
            if section["sh_type"] in ["SHT_REL", "SHT_RELA"] and section["sh_flags"] & 2:
                assert section.num_relocations() == 0, "Emulator does not apply dynamic relocations"
        tags = list(elf.get_section_by_name(".dynamic").iter_tags())
        assert not any(t.entry.d_tag in ["DT_INIT", "DT_INIT_ARRAY", "DT_NEEDED"] for t in tags)
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD" or not seg["p_memsz"]:
                continue
            start = seg["p_vaddr"] & ~4095
            end = (seg["p_vaddr"] + seg["p_memsz"] + 4095) & ~4095
            for page in range(start, end, 4096):
                if page not in pages:
                    if any(a<=page<=b for a,b,_ in u.mem_regions()):
                        raise ValueError('Generated component overlaps existing image storage')
                    u.mem_map(page, 4096)
                    pages.add(page)
            u.mem_write(seg["p_vaddr"], seg.data())
        for sym in elf.get_section_by_name(".symtab").iter_symbols():
            if sym.name in wanted:
                assert sym["st_info"]["type"] == "STT_FUNC"
                assert bool(sym["st_value"] & 1) == (
                    arch == "thumb"
                ), "ELF function ISA does not match requested architecture"
                symbols[sym.name] = sym["st_value"]
    assert set(symbols) == set(wanted)
    for address, size in [(MEM, 0x1000), (STOP, 0x1000), (STACK, 0x4000)]:
        regions=list(u.mem_regions())
        if any(a<=address and address+size-1<=b for a,b,_ in regions):
            if emulator is None:
                raise ValueError('Generated image overlaps reserved component state')
        else:
            u.mem_map(address, size)
    return u, symbols
