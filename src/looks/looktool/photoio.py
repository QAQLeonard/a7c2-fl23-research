"""Selected-slot native stages over the existing six-table runtime, no USB.

Use the same loaded extents and machine-code revision tested by the photo
lab. Installed code is reconstructed and compared as bytes; a magic word
alone does not establish that another patch is compatible.
"""
import struct
import json
from pathlib import Path
from . import photobasis, photobuild, photoformat


def present(cp):
    return cp[photobuild.DATA_FILE:photobuild.DATA_FILE+4]==struct.pack('<I',photobuild.MAGIC)


def refresh_gamma_table(cp):
    """Keep the active native rows in sync after an independent FL23 update.

    Native-photo hooks read this relocated table, not the original table
    changed by FL23. Refresh the added ST rows with the native null fallback,
    keeping all slot controls intact. Accept the exact older nullable layout.
    """
    original=0x1209480-photobuild.BASE
    size=50*28
    result=bytearray(cp)
    result[photobuild.TABLE_FILE:photobuild.TABLE_FILE+size]=cp[original:original+size]
    result[photobuild.TABLE_FILE+size:photobuild.CODE_FILE]=photoformat.custom_gamma_rows(
        cp[original:original+size])
    result=bytes(result)
    inspect(result)
    return result


def neutral_bank(cp):
    def record(row,column):
        pointer=struct.unpack_from('<I',cp,0x1209480-photobuild.BASE+row*28+column*4)[0]
        return cp[pointer-photobuild.BASE:pointer-photobuild.BASE+576]
    return photoformat.PhotoBank(record(0,0),record(10,6),bytes(576),bytes(64))


def unpack(raw):
    if len(raw)!=photobasis.STRIDE:raise ValueError('Native slot parameter length differs')
    values=struct.unpack('<54h',raw)
    matrices=[]
    for plane in range(3):
        encoded=photoformat.encode_matrix(values[3+plane*9:12+plane*9],(0,0,0))
        matrices.append(list(struct.unpack('<6h',encoded)))
    return dict(tone=list(values[:3]),matrices=matrices,
                chroma=[list(values[30+p*8:38+p*8]) for p in range(3)])


def underlay(cp):
    """Restore only known hook instructions for deterministic reconstruction.

    Retired bytes stay local to this source. This is not an original-firmware
    restoration; full Recovery uses the owner's complete checkpoint.
    """
    result=bytearray(cp)
    for hook in template()['hooks']:
        at,raw=hook['offset'],bytes.fromhex(hook['before'])
        result[at:at+len(raw)]=raw
    # The builder retains the former selector records at the end of its data.
    result[photobuild.DATA_FILE:photobuild.DATA_FILE+32]=cp[photobuild.LEGACY_MODE_VA-photobuild.BASE:photobuild.LEGACY_MODE_VA-photobuild.BASE+32]
    return bytes(result)


def template():
    value=json.loads((Path(__file__).resolve().parents[1]/'assets/native-photo-v2.json').read_text(encoding='utf-8'))
    if value.get('schema')!='a7c2-native-photo-code-template/1' or value.get('revision')!=photobuild.REVISION:
        raise ValueError('Native-photo code template revision differs')
    return value


def build(source,baseline,knobs,*,active_mask):
    """Data-only assembly of the reviewed wrapper; no assembler dependency."""
    value=template();target=bytearray(source)
    original=source[0x1209480-photobuild.BASE:0x1209480-photobuild.BASE+50*28]
    table=original+photoformat.custom_gamma_rows(original)
    for pointer in {struct.unpack_from('<I',original,row*28+column*4)[0]
                    for row in (0,10) for column in range(7)}-{0}:
        for spec in knobs:photobasis.curve(source[pointer-photobuild.BASE:pointer-photobuild.BASE+576],spec.get('tone',(0,0,0)))
    data=struct.pack('<4I',photobuild.MAGIC,1,active_mask,photobasis.STRIDE)
    data+=b''.join(struct.pack('<2I',50+2*i,51+2*i) for i in range(6))
    data+=b''.join(photobasis.pack(baseline,**spec)[0] for spec in knobs)
    old_modes=0x12099f8-photobuild.BASE+29*8
    data+=source[old_modes:old_modes+32]
    code=bytes.fromhex(value['code'])
    if len(knobs)!=6 or active_mask not in range(64) or len(code)!=value['code_bytes'] or len(data)!=value['basis_bytes']:
        raise ValueError('Native-photo template/data dimensions differ')
    target[photobuild.TABLE_FILE:photobuild.CODE_FILE]=table
    target[photobuild.CODE_FILE:photobuild.CODE_FILE+len(code)]=code
    target[photobuild.DATA_FILE:photobuild.DATA_FILE+len(data)]=data
    regions=[(photobuild.TABLE_FILE,len(table)+len(code)),(photobuild.DATA_FILE,len(data))]
    for hook in value['hooks']:
        at,old,new=hook['offset'],bytes.fromhex(hook['before']),bytes.fromhex(hook['after'])
        if source[at:at+len(old)]!=old:raise ValueError('Native photo hook instruction differs at '+hex(at))
        target[at:at+len(new)]=new;regions.append((at,len(new)))
    return bytes(target),dict(regions=regions)


def loaded_storage(cp):
    """Require the existing project's allocated text/data extension, not BSS."""
    if len(cp)<photobuild.DATA_FILE+1216:raise ValueError('Truncated native-photo storage')
    for header,start,end in [(0x20124,photobuild.TABLE_FILE,0xb27f0e),
                             (0x2013c,photobuild.DATA_FILE,0x1101fa0)]:
        offset,size,va=struct.unpack_from('<3I',cp,header)
        if not (0x20000+offset<=start<end<=0x20000+offset+size and
                va<=start+photobuild.BASE<end+photobuild.BASE<=va+size):
            raise ValueError('Native-photo storage is outside the existing allocated loaded segments')
        # Containment in both spaces is insufficient: shifted segment headers
        # can still contain the ranges while loading their bytes elsewhere.
        if va-(0x20000+offset)!=photobuild.BASE:
            raise ValueError('Native-photo segment file/virtual mapping differs')
    data_end=sum(struct.unpack_from('<2I',cp,0x20140))
    if data_end>0x120a000:raise ValueError('Native-photo storage must not extend into BSS')


def allocation(cp):
    from .device_layout import runtime
    from . import uploadpending
    if uploadpending.active(cp):
        cp=uploadpending.normalize(cp)
    loaded_storage(cp)
    spec=next(row for row in runtime()['cp_sources'] if row['kind']=='fl23')
    # These authored entry/selector and retry blocks establish which runtime
    # owns the extension. Empty bytes alone are never an allocation proof.
    for window in spec['windows']:
        if window['offset'] not in (0xb27490,0xb27f10):continue
        raw=bytes.fromhex(window['after']);at=window['offset']
        if cp[at:at+len(raw)]!=raw:raise ValueError('Six-table runtime allocation conflicts at '+hex(at))


def inspect(cp,baseline=None):
    if not present(cp):return None
    loaded_storage(cp)
    magic,version,mask,stride=struct.unpack_from('<4I',cp,photobuild.DATA_FILE)
    if (magic,version,stride)!=(photobuild.MAGIC,1,photobasis.STRIDE) or mask not in range(64):
        raise ValueError('Unsupported native-photo runtime header')
    knobs=[]
    for slot in range(6):
        at=photobuild.PARAMS_VA-photobuild.BASE+slot*stride
        knobs.append(unpack(cp[at:at+stride]))
    base=underlay(cp);allocation(base)
    expected,report=build(base,baseline or neutral_bank(cp),knobs,active_mask=mask)
    # Recognize the exact old nullable copies without accepting arbitrary
    # table/code differences. Every subsequent update builds resolved rows.
    legacy=bytearray(expected)
    original=base[0x1209480-photobuild.BASE:0x1209480-photobuild.BASE+50*28]
    legacy[photobuild.TABLE_FILE+50*28:photobuild.CODE_FILE]=photoformat.custom_gamma_rows(
        original,resolve_null=False)
    for at,length in report['regions']:
        if cp[at:at+length] not in (expected[at:at+length],legacy[at:at+length]):
            raise ValueError('Native-photo runtime bytes conflict at '+hex(at))
    return dict(revision=photobuild.REVISION,mask=mask,knobs=knobs)


def update(cp,changes,baseline=None,*,allocation_proved=False):
    """None clears only that slot's native stage; other slots retain theirs."""
    state=inspect(cp,baseline)
    if state is None and not any(value is not None for value in changes.values()):return cp
    loaded_storage(cp)
    if state is None and not allocation_proved:
        raise ValueError('Establish the canonical six-table allocation before native stages')
    if state is None:allocation(cp)
    bank=baseline or neutral_bank(cp)
    knobs=state['knobs'] if state else [{} for _ in range(6)]
    mask=state['mask'] if state else 0
    for slot,delta in changes.items():
        if slot not in range(1,7):raise ValueError('Select custom slots 1..6')
        if delta is None:
            knobs[slot-1]={};mask&=~(1<<(slot-1))
        else:
            if baseline is None:raise ValueError('Fresh body ST records are required for native stages')
            blob=photobasis.compile_delta(baseline,delta)
            knobs[slot-1]=unpack(blob);mask|=1<<(slot-1)
    result,_=build(underlay(cp) if state else cp,bank,knobs,active_mask=mask)
    if len(result)!=len(cp) or result[0x20124:0x20154]!=cp[0x20124:0x20154]:
        raise ValueError('Native stages must preserve file length and loaded segment headers')
    inspect(result,bank)
    return result


def slot_bytes(cp,slot):
    state=inspect(cp)
    if state is None or not state['mask']&(1<<(slot-1)):return None
    at=photobuild.PARAMS_VA-photobuild.BASE+(slot-1)*photobasis.STRIDE
    return cp[at:at+photobasis.STRIDE]


def slot_delta(cp,slot,baseline):
    raw=slot_bytes(cp,slot)
    return photobasis.pack(baseline,**unpack(raw))[1] if raw is not None else None


def signature(cp,slot):
    from .device_layout import tables
    raw=slot_bytes(cp,slot)
    return dict(table_hex=tables(cp)[slot-1].hex(),native_hex=raw.hex() if raw else None)


def window_priority(window):
    chip,at=window['chip'],int(window['offset'],16)
    if chip==0:return (3,at)
    if photobuild.TABLE_FILE<=at<0xb27f0e or photobuild.DATA_FILE<=at<0x1101fa0:return (0,at)
    return (2 if at<=0xb27500<at+window['bytes'] else 1,at)
