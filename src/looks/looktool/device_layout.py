"""Reviewed layouts, edited-byte checks, and independent custom tables.

Legacy jobs still record their complete source identities. First activation
checks its actual windows, and legacy code matching normalizes only reviewed
native FL23 updates. Desktop transactions use structural checks directly.
"""
import hashlib,struct,json
from pathlib import Path
from . import firmware,six,uploadgate

CODE_SHA='5434cd40a746fef421fbe6825ebbdc1d41aa5304a686a162bb56378a6e94c4b5'  # Filled from the known complete v4 private fixture during build.

def runtime():
    data=json.loads((Path(__file__).resolve().parents[1]/'assets/runtime-v1.json').read_text(encoding='utf-8'))
    if data['schema']!='a7c2-lut-runtime/1':raise ValueError('Unknown runtime patch schema')
    # Both CP hash fields describe historical hash inputs, not raw new output.
    if data.get('cp_hash_canonical_upload_entry')!=uploadgate.FORCED.hex():
        raise ValueError('Unknown canonical CP upload entry for runtime hashes')
    return data

def _ap_target(source,mask):
    asset=runtime();result=bytearray(source)
    result[0x35287f0:0x3528874]=bytes.fromhex(asset['ap_templates'][mask])
    result[0x1b5cd7c:0x1b5cd80]=bytes.fromhex(asset['title_branch'])
    result[0x4c7cf7c:0x4c7cf88]=bytes.fromhex(asset['map'])
    for i in range(6):
        if mask&(1<<i):struct.pack_into('<I',result,0x59896f0+i*0xb8,0x0200ab2c+i)
    return bytes(result)

def identify_ap(ap):
    digest=firmware.sha(ap)
    if digest==six.AP_SHA:return {'kind':'legacy-six','mask':63,'label_ids':list(__import__(__package__+'.resources',fromlist=['LABEL_IDS']).LABEL_IDS)}
    for spec in runtime()['ap_sources']:
        if len(ap)!=spec['bytes']:continue
        restored=bytearray(ap)
        for window in spec['restore']:
            at=window['offset'];raw=bytes.fromhex(window['hex']);restored[at:at+len(raw)]=raw
        if firmware.sha(restored)!=spec['sha256']:continue
        if digest==spec['sha256']:return {'kind':spec['kind'],'mask':0,'label_ids':list(range(0x0200ab2c,0x0200ab32)),'first_install':True}
        # Masks are checked against a complete rebuilt AP, not merely ignored.
        template=ap[0x35287f0:0x3528874].hex();templates=runtime()['ap_templates']
        if template not in templates:continue
        mask=templates.index(template)
        if _ap_target(bytes(restored),mask)==ap:return {'kind':spec['kind']+'-lut','mask':mask,'label_ids':list(range(0x0200ab2c,0x0200ab32))}
    raise ValueError('Unsupported AP identity; no firmware/settings writes performed')

def code_hash(cp):
    # Retain the published complete-code fingerprint. Exact reviewed upload
    # layouts normalize to the historical representation; unknown/partial
    # layouts and all other code changes still fail.
    cp=uploadgate.legacy_hash_source(normalize_fl23_native(cp))
    start=six.TABLE_FILE+8;end=six.TABLE_FILE+32+6*six.TABLE_BYTES
    if len(cp)<end:raise ValueError('Truncated CP program')
    h=hashlib.sha256();h.update(cp[:start]);h.update(bytes(end-start));h.update(cp[end:]);return h.hexdigest()

def fl23_native_windows():
    """Reviewed native FL23 fields that remain independent of custom slots."""
    root=Path(__file__).resolve().parents[3]
    folder=root/'src/camera_runtime/assets'
    if not folder.is_dir():folder=root/'src/fl23/assets'
    manifest=json.loads((folder/'patches.json').read_text(encoding='utf-8'))[1]['writes']
    stock=next(s for s in runtime()['cp_sources'] if s['kind']=='stock')
    result=[]
    for w in manifest:
        at=int(w['file_offset'],16)
        if at not in (0x138832,0x1100b80):continue
        old,new=bytes.fromhex(w['before_hex']),bytes.fromhex(w['after_hex'])
        legacy=bytearray(old)
        for patch in stock['windows']:
            pos=patch['offset'];raw=bytes.fromhex(patch['after'])
            a,b=max(at,pos),min(at+len(old),pos+len(raw))
            if a<b:legacy[a-at:b-at]=raw[a-pos:b-pos]
        result.append((at,old,new,bytes(legacy)))
    return result

def normalize_fl23_native(cp):
    result=None
    for at,old,new,legacy in fl23_native_windows():
        if cp[at:at+len(new)] in (new,*fl23_previous_values(at)) and cp[at:at+len(new)]!=legacy:
            if result is None:result=bytearray(cp)
            result[at:at+len(new)]=legacy
    return bytes(result) if result is not None else cp


def fl23_previous_values(offset):
    """Known published native-field revisions, never full firmware admission."""
    path=Path(__file__).resolve().parents[3]/'src/camera_runtime/assets/fl23-native-history.json'
    if not path.is_file():return ()
    history=json.loads(path.read_text(encoding='utf-8'))
    if history.get('schema')!='a7c2-reviewed-fl23-native-history/1':raise ValueError('Unknown native FL23 migration data')
    if offset not in (0x138832,0x1100b80):return ()
    return tuple(bytes.fromhex(row['after_hex']) for row in history['windows'] if int(row['file_offset'],16)==offset)

def structural_ap(ap):
    """Recognize actual converter bytes/slot mask, without a file digest."""
    template=ap[0x35287f0:0x3528874].hex();asset=runtime()
    base='fl23' if ap[0x4b2ed19:0x4b2ed1b]==b'\x01\x01' else 'stock'
    labels=list(range(0x0200ab2c,0x0200ab32))
    if template in asset['ap_templates']:
        return {'kind':base+'-lut','mask':asset['ap_templates'].index(template),'label_ids':labels}
    legacy=bytes.fromhex('e1000035002800511f1400718800005400e4031140000039c0035fd63f2c007188020054800000100048613840000039c0035fd600030201100f1112050d13141f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d5')
    if ap[0x3528804:0x3528874]==legacy:
        from .resources import LABEL_IDS
        return {'kind':'legacy-six','mask':63,'label_ids':list(LABEL_IDS)}
    spec=next(s for s in asset['ap_sources'] if s['kind']==base)
    converter=next(w for w in spec['restore'] if w['offset']==0x35287f0)
    raw=bytes.fromhex(converter['hex'])
    if ap[converter['offset']:converter['offset']+len(raw)]!=raw:
        raise ValueError('Custom-slot converter bytes conflict; no writes')
    return {'kind':base,'mask':0,'label_ids':labels,'first_install':True}

def structural(ap,cp):
    identity=structural_ap(ap)
    from . import photoio
    photo=photoio.inspect(cp)
    if not identity.get('first_install'):
        uploadgate.validate(cp)
        if len(cp)<six.TABLE_FILE+32+6*six.TABLE_BYTES or struct.unpack_from('<2I',cp,six.TABLE_FILE)!=(six.MAGIC,six.VERSION):
            raise ValueError('Custom table header/size differs')
    return dict(identity,layout='full7-v4' if identity['kind']=='legacy-six' else 'standalone-v1',
                native_photo=photo)

def tables(cp):
    """Read native-grid payloads, without comparing source table digests."""
    if len(cp)<six.TABLE_FILE+32+6*six.TABLE_BYTES or struct.unpack_from('<2I',cp,six.TABLE_FILE)!=(six.MAGIC,six.VERSION):
        raise ValueError('Custom table header/size differs')
    return [cp[six.TABLE_FILE+32+i*six.TABLE_BYTES:six.TABLE_FILE+32+(i+1)*six.TABLE_BYTES] for i in range(6)]


def same_selected_programs(expected,actual,slot):
    """Post-reload only: permit later data updates to the other five slots.

    Also accept the reviewed forward native-entry/acknowledgment migration.
    AP and all other CP code remain exact; old job evidence is never rewritten.
    This never relaxes pre-write checks or immediate installation readback.
    """
    from . import photoio,photobuild,photobasis
    if actual['appFw.so']!=expected['appFw.so']:return False
    before,current=expected['cpapp-b.bin'],actual['cpapp-b.bin']
    if len(before)!=len(current):return False
    try:
        from . import uploadpending
        if not uploadpending.active(before) and uploadpending.active(current):
            current=uploadpending.normalize(current)
        entry=slice(uploadgate.OFFSET,uploadgate.OFFSET+len(uploadgate.NATIVE))
        if before[entry]!=current[entry]:
            if before[entry]!=uploadgate.FORCED or current[entry]!=uploadgate.NATIVE:
                return False
            # Validate both contexts and the reachable historical stubs. Only
            # normalize this in-memory comparison; restoration uses fresh CP.
            uploadgate.validate(current)
            before=uploadgate.restore(before)
        tables(before);tables(current)
        a,b=photoio.inspect(before),photoio.inspect(current)
    except (ValueError,struct.error):return False
    if (a is None)!=(b is None):return False
    result=bytearray(current)
    if a is not None:
        if (a['mask']^b['mask'])&(1<<(slot-1)):return False
        at=photobuild.DATA_FILE+8;result[at:at+4]=before[at:at+4]
    for other in range(1,7):
        if other==slot:continue
        for at,size in [(six.TABLE_FILE+8+(other-1)*4,4),
                        (six.TABLE_FILE+32+(other-1)*six.TABLE_BYTES,six.TABLE_BYTES)]:
            result[at:at+size]=before[at:at+size]
        if a is not None:
            at=photobuild.PARAMS_VA-photobuild.BASE+(other-1)*photobasis.STRIDE
            result[at:at+photobasis.STRIDE]=before[at:at+photobasis.STRIDE]
    return result==before

def identify(ap,cp):
    from . import photoio
    if photoio.present(cp):return structural(ap,cp)
    a=identify_ap(ap);c=firmware.sha(cp);asset=runtime()
    if a['kind']=='legacy-six':
        if code_hash(cp)!=CODE_SHA:raise ValueError('Unsupported legacy CP code identity')
        six.read_tables(cp)
    elif a.get('first_install'):
        spec=next((s for s in asset['cp_sources'] if s['kind']==a['kind']),None)
        if spec is None or len(cp)!=spec['bytes']:raise ValueError('First import needs matching A7C II 2.01 program extents')
        # FL23 curve improvements change its full CP digest. Admission uses
        # the identified AP and every actual CP window we will replace.
        for w in spec['windows']:
            at=w['offset'];old=bytes.fromhex(w['before'])
            if cp[at:at+len(old)]!=old:raise ValueError('First-import CP window conflicts at '+hex(at))
    else:
        if code_hash(cp)!=asset['cp_code_sha256']:raise ValueError('Unsupported standalone CP code identity')
        six.read_tables(cp)
    return dict(a,layout='full7-v4' if a['kind']=='legacy-six' else 'standalone-v1',AP=firmware.sha(ap),CP=c,
        physical_first_install_tested=False if a['kind']!='legacy-six' else None)

def replace(ap,cp,replacements,*,hash_checks=True,native_photo=None,native_bank=None,transitions=True):
    identify_current=identify if hash_checks else structural
    identity=identify_current(ap,cp)
    if not replacements or any(type(s) is not int or s not in range(1,7) for s in replacements):raise ValueError('Select custom slots 1..6')
    result=bytearray(cp);spans=[];ap_result=ap;ap_spans=[]
    if identity.get('first_install'):
        spec=next(s for s in runtime()['cp_sources'] if s['kind']==identity['kind'])
        for w in spec['windows']:
            at=w['offset'];old,new=bytes.fromhex(w['before']),bytes.fromhex(w['after'])
            if cp[at:at+len(old)]!=old:raise ValueError('Bootstrap source window differs')
            result[at:at+len(new)]=new
        # The final code/layout check below also permits the reviewed updated
        # native FL23 curves. Do not reject them with the old full-file digest.
    # Existing v4 runtimes keep their tables/photo data and dormant stubs.
    # Migrate only the reviewed forced-repeat entry, inside this transaction.
    native=uploadgate.restore(bytes(result))
    if native!=result:
        spans.append((uploadgate.OFFSET,4))
    result=bytearray(native)
    if identity['kind']!='legacy-six':
        source=bytearray(ap)
        spec=next(s for s in runtime()['ap_sources'] if identity['kind'].startswith(s['kind']))
        for w in spec['restore']:
            raw=bytes.fromhex(w['hex']);source[w['offset']:w['offset']+len(raw)]=raw
        mask=identity['mask']|sum(1<<(s-1) for s in replacements)
        ap_result=_ap_target(bytes(source),mask)
        ap_spans=[(w['offset'],len(bytes.fromhex(w['hex']))) for w in spec['restore']]
    for slot,raw in sorted(replacements.items()):
        six.decode(raw);at=six.TABLE_FILE+32+(slot-1)*six.TABLE_BYTES;check=six.TABLE_FILE+8+(slot-1)*4
        result[at:at+six.TABLE_BYTES]=raw;struct.pack_into('<I',result,check,six.fnv(raw));spans.extend([(at,six.TABLE_BYTES),(check,4)])
    if identity.get('first_install'):
        # Derive disjoint bounded windows including bootstrap and user data.
        spans=[];start=None;last=None
        for at,(a,b) in enumerate(zip(cp,result)):
            if a!=b:
                if start is None:start=at
                elif at-last>16 or at-start>=4096:spans.append((start,last-start+1));start=at
                last=at
        if start is not None:spans.append((start,last-start+1))
    from . import photoio
    stages={slot:(native_photo or {}).get(slot) for slot in replacements}
    if photoio.present(cp) or any(value is not None for value in stages.values()):
        result=photoio.update(bytes(result),stages,native_bank,allocation_proved=True)
        from .checkpointworker import differences
        spans=[(at,len(old)) for at,old,_ in differences(cp,result)]
    after={'appFw.so':ap_result,'cpapp-b.bin':bytes(result)};before={'appFw.so':ap,'cpapp-b.bin':cp}
    identify_current(after['appFw.so'],after['cpapp-b.bin'])
    if not transitions:return None,None,after
    regions={'appFw.so':ap_spans,'cpapp-b.bin':spans}
    f=firmware.transition(before,after,regions)
    r=firmware.transition(after,before,regions)
    if firmware.apply(after,r,hash_checks=hash_checks)!=before:raise ValueError('Complete table inverse differs')
    return f,r,after

def before_first_table(ap,cp,slot,*,hash_checks=True):
    """Dormant canonical data for a slot that originally used native looks."""
    identity=(identify if hash_checks else structural)(ap,cp)
    read_tables=six.read_tables if hash_checks else tables
    if not identity.get('first_install'):return read_tables(cp)[slot-1]
    result=bytearray(cp)
    spec=next(s for s in runtime()['cp_sources'] if s['kind']==identity['kind'])
    for w in spec['windows']:
        raw=bytes.fromhex(w['after']);result[w['offset']:w['offset']+len(raw)]=raw
    return read_tables(bytes(result))[slot-1]

def deactivate(ap,cp,slot,raw,*,hash_checks=True,native_bank=None,transitions=True):
    """Restore one native custom slot, retaining other LUTs and current FL23.

    Mask zero leaves the shared CP runtime dormant. The independent recovery
    tool removes shared programs when the owner wants a full rollback.
    """
    identify_current=identify if hash_checks else structural
    identity=identify_current(ap,cp)
    if identity['kind']=='legacy-six':raise ValueError('First-activation undo requires the standalone slot layout')
    spec=next(s for s in runtime()['ap_sources'] if identity['kind'].startswith(s['kind']))
    base=bytearray(ap)
    for w in spec['restore']:
        value=bytes.fromhex(w['hex']);base[w['offset']:w['offset']+len(value)]=value
    after_ap=_ap_target(bytes(base),identity['mask']&~(1<<(slot-1)))
    six.decode(raw);result=bytearray(cp)
    at=six.TABLE_FILE+32+(slot-1)*six.TABLE_BYTES;check=six.TABLE_FILE+8+(slot-1)*4
    result[at:at+six.TABLE_BYTES]=raw;struct.pack_into('<I',result,check,six.fnv(raw))
    from . import photoio
    result=photoio.update(bytes(result),{slot:None},native_bank)
    before={'appFw.so':ap,'cpapp-b.bin':cp};after={'appFw.so':after_ap,'cpapp-b.bin':bytes(result)}
    if not transitions:
        identify_current(after_ap,bytes(result))
        return None,None,after
    from .checkpointworker import differences
    regions={'appFw.so':[(w['offset'],len(bytes.fromhex(w['hex']))) for w in spec['restore']],
        'cpapp-b.bin':[(offset,len(old)) for offset,old,_ in differences(cp,result)]}
    forward,reverse=firmware.transition(before,after,regions),firmware.transition(after,before,regions)
    identify_current(after_ap,after['cpapp-b.bin'])
    return forward,reverse,after
