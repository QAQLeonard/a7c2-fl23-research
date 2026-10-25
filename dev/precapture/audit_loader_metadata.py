"""Offline original ODL getter and DMM proc-read contracts; no camera access.

Requires private original files. Executes only pure getters on synthetic data.
Inspects proc callbacks and config tables without running kernel/loader APIs.
No allocation, DMA, CP read, firmware patch or installable image is supplied.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from support.dmm_config import config_tables, CP_CONFIG_SHA256  # Retained-report compatibility.

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_LR, UC_ARM64_REG_PC

PINNED = {
    'odl': 'fc034bd9a78443fe9d1fbf51cc2c37380b3f0b4dd164ff461345dbe3b233fe89',
    'dmm': '295f02234a9bc39697cf1a39a13fc8c1d823b340ed3115609c89b7950d694353',
    'cp_config': CP_CONFIG_SHA256,
    'ap_config': '6c37baddaa60b6756340f77b051eed948978cea28d04f499f91263c9d270d962',
}
GETTERS = [
    ('getClientId', 0xba8c, 0, 4), ('getOption', 0xba94, 4, 2),
    ('getAlcTimeout', 0xba9c, 8, 4), ('getPrgId', 0xbaa4, 12, 1),
    ('getPrgUsrUnqId', 0xbaac, 13, 1), ('getPrgAlcMem', 0xbab4, 14, 1),
    ('getPrgLoadOffset', 0xbabc, 16, 4), ('getPrgLoadSrcOffset', 0xbac4, 20, 4),
    ('getPrgLoadSize', 0xbacc, 24, 4), ('getMemUnitHandle', 0xbad4, 28, 4),
    ('getMemUnitType', 0xbadc, 32, 4), ('getWorkUnitHandle', 0xbae4, 36, 4),
    ('getPrgLoadEnable', 0xbaec, 40, 1), ('getAstraMode', 0xbafc, 41, 1),
]
MEM, STOP = 0x30000000, 0x40000000


def getter_contract(raw):
    elf = ELFFile(io.BytesIO(raw))
    assert elf['e_type'] == 'ET_DYN' and elf['e_machine'] == 'EM_AARCH64'
    symbols = {s.name: s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
    singleton = symbols['_ZN19InfraOnDemandLoader22m_pInfraOnDemandLoaderE']
    assert singleton['st_value'] == 0x21818 and singleton['st_size'] == 8
    assert elf.get_section(singleton['st_shndx'])['sh_type'] == 'SHT_NOBITS'
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = set()
    for segment in elf.iter_segments():
        if segment['p_type'] != 'PT_LOAD' or not segment['p_memsz']:
            continue
        start, end = segment['p_vaddr'], segment['p_vaddr'] + segment['p_memsz']
        for page in range(start & ~4095, (end + 4095) & ~4095, 4096):
            if page not in pages:
                u.mem_map(page, 4096)
                pages.add(page)
        u.mem_write(start, segment.data())
    u.mem_map(MEM, 4096)
    u.mem_map(STOP, 4096)

    def call(entry, argument, second=0):
        u.reg_write(UC_ARM64_REG_X0, argument)
        u.reg_write(UC_ARM64_REG_X1, second)
        u.reg_write(UC_ARM64_REG_LR, STOP)
        u.emu_start(entry, STOP, count=20)
        assert u.reg_read(UC_ARM64_REG_PC) == STOP
        return u.reg_read(UC_ARM64_REG_X0)

    cases = []
    for name, address, offset, size in GETTERS:
        symbol = next(s for n, s in symbols.items() if 'Odl_PrgInfo' in n and name in n)
        assert symbol['st_value'] == address and symbol['st_size'] == 8
        for value in (0, 1, 0x7f, (1 << (size*8))-1):
            record = bytearray([0xa5]) * 44
            record[offset:offset+size] = value.to_bytes(size, 'little')
            u.mem_write(MEM, bytes(record))
            assert call(address, MEM) == value
            assert bytes(u.mem_read(MEM, 44)) == record
            cases.append(dict(getter=name, value=value, bytes=size, offset=offset))
    chips = []
    for remote in (False, True):
        for domain in range(8):
            argument = (int(remote) << 31) | (domain << 28) | 0x302d9
            expected = domain if remote and domain in (1, 2) else 0
            assert call(0xaac0, MEM, argument) == expected
            chips.append(dict(argument=hex(argument), chip=expected))
    handles = []
    for argument in (0, 0x751, 0x752, 0x8444, 0x844a, 0xffffffff):
        expected = (argument >> 15) & 1
        assert call(0xaae8, MEM, argument) == expected
        handles.append(dict(handle=hex(argument), chip_bit=expected))
    return dict(getters=cases, osal_chip=chips, handle_chip=handles,
        record_bytes=44, ignored_padding=[6, 7, 15, 42, 43],
        methods_executed='pure getters only; no constructor, loader or transport')


def proc_contract(raw):
    elf = ELFFile(io.BytesIO(raw))
    assert elf['e_type'] == 'ET_REL' and elf['e_machine'] == 'EM_AARCH64'
    symbols = elf.get_section_by_name('.symtab')
    relocations = {}
    for sec in elf.iter_sections():
        if sec['sh_type'] == 'SHT_RELA':
            relocations[sec.name] = {r['r_offset']: (r, symbols.get_symbol(r['r_info_sym']))
                for r in sec.iter_relocations()}
    data, text = relocations['.rela.data'], relocations['.rela.text']
    read_cases = []
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    native = elf.get_section_by_name('.text').data()
    for descriptor, name, start, end, allowed in (
        (0x1a8, 'dmm_units', 0x928, 0xdf0,
            {'memcpy', 'scnprintf', 'dmm_unit_ctrl_MakeHandle', 'dmm_unit_ctrl_GetUnitTop'}),
        (0x1f8, 'dmm_extents', 0x5d0, 0x8f0,
            {'memcpy', 'scnprintf', 'dmm_extent_ctrl_GetExtentTop'})):
        r, s = data[descriptor]
        name_bytes = elf.get_section(s['st_shndx']).data()[r['r_addend']:].split(b'\0', 1)[0]
        assert name_bytes.decode() == name
        r, s = data[descriptor + 8]
        assert elf.get_section(s['st_shndx']).name == '.text' and r['r_addend'] == start
        assert descriptor + 16 not in data  # No write handler for either endpoint.
        assert elf.get_section_by_name('.data').data()[descriptor+16:descriptor+24] == bytes(8)
        calls = []
        for ins in md.disasm(native[start:end], start):
            assert ins.mnemonic not in ('blr', 'svc', 'hvc', 'smc')
            if ins.mnemonic == 'bl':
                r, s = text[ins.address]
                assert r['r_info_type'] == 283 and s.name in allowed
                calls.append(dict(offset=hex(ins.address), symbol=s.name))
        assert {c['symbol'] for c in calls} == allowed
        read_cases.append(dict(path='/proc/udm/'+name, calls=calls,
            native_side_effects='diagnostic pagination cursors and output only; not a CP image read'))
    # The tempting generic info endpoint is not passive: it queries a native
    # synchronous service. Keep this path out of the selected live reader.
    r, s = text[0x1a08]
    assert s.name == 'dmm_timer_GetSyscnt' and r['r_info_type'] == 283
    r, s = text[0x4cf4]
    assert s.name == 'osal_snd_sync_direct' and r['r_info_type'] == 283
    return dict(selected=read_cases, excluded=dict(path='/proc/udm/dmm_info',
        reason='timer getter calls osal_snd_sync_direct'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in PINNED:
        p.add_argument('--'+name.replace('_', '-'), type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = {k: getattr(a, k).read_bytes() for k in PINNED}
    for key, data in raw.items():
        if hashlib.sha256(data).hexdigest() != PINNED[key]:
            raise ValueError('Unsupported exact original source: '+key)
    result = dict(schema='OFFLINE_LOADER_METADATA_CONTRACT/1', camera_io=False,
        source_hashes=PINNED, odl=getter_contract(raw['odl']), dmm=proc_contract(raw['dmm']))
    result['configs'] = {}
    for key in ('cp_config', 'ap_config'):
        config = config_tables(raw[key])
        result['configs'][key] = dict(root_groups=len(config['roots']),
            extent_groups=len(config['groups']), unit_types=len(config['units']),
            version=config['version'], selected=[])
        for unit in config['units']:
            if unit['type'] not in (0x401, 0x1c3d00, 0x1c3f00):
                continue
            variants = [dict(group_offset=g['offset'], parent_id=g['header'][2],
                rule_id=g['header'][3], **c) for g in config['groups']
                for c in g['children'] if c['words'][2] in unit['extent_ids']]
            assert variants
            result['configs'][key]['selected'].append(dict(**unit, variants=variants))
    result['limits'] = ['Enabled ODL records are not proof of loaded programs',
        'DMM configuration capacity is not current allocation or permission to read an address',
        'AP proc metadata does not establish current CP code bytes',
        'Main CP source freshness, payload placement, frame ownership and real pre-capture remain unproven']
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(status='OFFLINE_CONTRACTS_PASSED',
        getters=len(result['odl']['getters']), osal_chips=len(result['odl']['osal_chip']),
        handles=len(result['odl']['handle_chip']), selected_proc_paths=2,
        configs={k:{n:v[n] for n in ('root_groups','extent_groups','unit_types')}
            for k,v in result['configs'].items()})))


if __name__ == '__main__':
    main()
