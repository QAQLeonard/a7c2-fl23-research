"""Offline plans from live proc metadata; never opens devices or reads memory.

Exact2.01 symbol offsets are independently checked by audit_kernel_mapping.py.
An internally consistent plan is not loaded-byte, RAM-access or CP admission.
"""
import re
import uuid

SYMBOL_OFFSETS = {
    '_text':0, '__init_begin':0x5b0000, '_sdata':0x600000, '_end':0x6af000,
    'swapper_pg_dir':0x6ac000, 'kimage_voffset':0x5699d8, 'memstart_addr':0x5699c8,
    'init_mm':0x61ebf8, 'read_mem':0x2780a0, 'valid_phys_addr_range':0x16888,
    'vmalloc_to_page':0xf0a10,
}
U64 = (1 << 64)-1


def parse_symbols(raw):
    if not isinstance(raw,bytes) or not raw or len(raw)>4096:
        raise ValueError('Bounded selected kallsyms bytes required')
    result={}
    for line in raw.decode('ascii').splitlines():
        match=re.fullmatch(r'([0-9a-f]{16}) ([A-Za-z]) ([A-Za-z_][A-Za-z_0-9]*)',line)
        if not match or match[3] not in SYMBOL_OFFSETS or match[3] in result:
            raise ValueError('Unexpected, duplicate or malformed selected symbol')
        address=int(match[1],16)
        if address<0xffffff8000000000 or address&3:
            raise ValueError('Missing/unaligned kernel symbol address')
        result[match[3]]=address
    if set(result)!=set(SYMBOL_OFFSETS):raise ValueError('Missing kernel symbol')
    base=result['_text']
    if any(result[name]-base!=offset for name,offset in SYMBOL_OFFSETS.items()):
        raise ValueError('Current symbol layout differs from original2.01')
    return result


def parse_resources(raw):
    if not isinstance(raw,bytes) or not raw or len(raw)>8192:
        raise ValueError('Bounded iomem bytes required')
    stack=[];ram=[];wanted={}
    for line in raw.decode('ascii').splitlines():
        match=re.fullmatch(r'( *)([0-9a-f]{8,16})-([0-9a-f]{8,16}) : (\S.*)',line)
        if not match:raise ValueError('Malformed iomem line')
        depth=len(match[1]);start=int(match[2],16);end=int(match[3],16)
        if depth%2 or end<start or end==U64:raise ValueError('Invalid resource extent')
        while stack and stack[-1]['depth']>=depth:stack.pop()
        if depth and (not stack or stack[-1]['depth']!=depth-2):
            raise ValueError('Broken resource hierarchy')
        parent=stack[-1] if stack else None
        if parent and not(parent['start']<=start<=end<=parent['end']):
            raise ValueError('Child outside parent resource')
        row=dict(start=start,end=end,depth=depth,name=match[4])
        if row['name']=='System RAM':
            if depth or not start or start&4095 or (end+1)&4095:
                raise ValueError('Hidden or unqualified System RAM resource')
            if any(start<=r['end'] and r['start']<=end for r in ram):
                raise ValueError('Overlapping System RAM')
            ram.append(row)
        if row['name'] in ('Kernel code','Kernel data'):
            if row['name'] in wanted or not parent or parent['name']!='System RAM':
                raise ValueError('Kernel resource lacks unique direct RAM parent')
            if not start:raise ValueError('Hidden kernel resource')
            wanted[row['name']]=row
        stack.append(row)
    if set(wanted)!={'Kernel code','Kernel data'}:raise ValueError('Missing kernel resources')
    code,data=wanted['Kernel code'],wanted['Kernel data']
    if code['end']>=data['start']:raise ValueError('Overlapping or reversed kernel resources')
    return ram,wanted


def bootstrap_plan(iomem,symbols,boot_id):
    """Pure metadata consistency plan. Never call a device from this function."""
    if not isinstance(boot_id,bytes) or len(boot_id)!=37 or not boot_id.endswith(b'\n'):
        raise ValueError('Exact boot UUID text required')
    boot=boot_id[:-1].decode('ascii')
    if str(uuid.UUID(boot))!=boot:raise ValueError('Noncanonical boot UUID')
    sym=parse_symbols(symbols);ram,resources=parse_resources(iomem)
    code,data=resources['Kernel code'],resources['Kernel data']
    if code['end']-code['start']+1!=sym['__init_begin']-sym['_text'] or \
       data['end']-data['start']+1!=sym['_end']-sym['_sdata']:
        raise ValueError('Native kernel resource lengths differ from symbol spans')
    offset=sym['_text']-code['start']
    if offset<0 or sym['_sdata']-data['start']!=offset:
        raise ValueError('Code and data disagree on image offset')
    reads=[]
    # +0x40 is independently checked against original vmalloc_to_page's
    # load of init_mm.pgd. The root CONTENTS are not presumed equal to a symbol.
    for name,address,size in (('image_header',sym['_text'],64),
            ('image_offset',sym['kimage_voffset'],8),('memstart',sym['memstart_addr'],8),
            ('init_mm_pgd',sym['init_mm']+0x40,8),('root_first_word',sym['swapper_pg_dir'],8)):
        physical=address-offset
        if not any(r['start']<=physical and physical+size-1<=r['end'] for r in (code,data)):
            raise ValueError('Bootstrap word outside qualified image resources')
        reads.append(dict(name=name,virtual=address,physical=physical,bytes=size))
    return dict(schema='OFFLINE_KERNEL_BOOTSTRAP_PLAN/1',boot_id=boot,symbols=sym,
        image_offset_candidate=offset,resources=resources,RAM=ram,reads=reads,
        source_facts_verified=False,native_memory_read_admitted=False,loaded_code_verified=False)


def module_walk_step(virtual,root_physical,descriptors,ram):
    """Plan one 39-bit/4K page-table read or decode its leaf; never performs I/O.

    This intentionally accepts only ordinary executable kernel pages and table
    descriptors, a strict subset of the original vmalloc_to_page behavior.
    Root/epoch/source and read atomicity remain independent caller duties.
    """
    if not isinstance(virtual,int) or not 0xffffff8000000000<=virtual<0xffffff8008000000:
        raise ValueError('Original2.01 module virtual range required')
    if not isinstance(root_physical,int) or root_physical&4095 or not 0<root_physical<U64:
        raise ValueError('Qualified aligned root physical address required')
    if len(descriptors)>3:raise ValueError('Three-level walk only')
    def memory(address,size):
        if not 0<address<=U64-size or not any(r['start']<=address and address+size-1<=r['end'] for r in ram):
            raise ValueError('Read outside qualified System RAM')
        return address
    table=memory(root_physical,4096)
    for level,entry in enumerate(descriptors):
        if not isinstance(entry,int) or not 0<=entry<=U64:raise ValueError('Invalid descriptor word')
        if entry&3!=3:raise ValueError('No invalid, block or software-only descriptors')
        physical=entry&0x0000fffffffff000
        if level<2:
            if entry&0xffff000000000000:raise ValueError('Unqualified table attributes')
            table=memory(physical,4096)
        else:
            if (entry>>2)&7!=4 or entry&(1<<6) or entry&(1<<53) or not entry&(1<<10):
                raise ValueError('Require accessed normal-memory kernel executable leaf')
            physical=memory(physical,4096)+(virtual&4095)
            return dict(kind='leaf',physical=physical,page_bytes_left=4096-(virtual&4095),
                native_memory_read_admitted=False)
    shift=(30,21,12)[len(descriptors)]
    address=table+((virtual>>shift)&511)*8
    return dict(kind='table',physical=memory(address,8),bytes=8,level=len(descriptors),
        native_memory_read_admitted=False)
