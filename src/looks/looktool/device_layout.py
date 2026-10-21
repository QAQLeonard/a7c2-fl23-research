"""Reviewed full7-v4 code identity with independently variable checked tables.

The original exact-SHA adapter remains unchanged. This additional adapter
recognizes a pinned program layout and still binds every job to full hashes.
"""
import hashlib,struct,json
from pathlib import Path
from . import firmware,six,fl23compat

CODE_SHA='5434cd40a746fef421fbe6825ebbdc1d41aa5304a686a162bb56378a6e94c4b5'  # Filled from the known complete v4 private fixture during build.

def runtime():
    data=json.loads((Path(__file__).resolve().parents[1]/'assets/runtime-v1.json').read_text(encoding='utf-8'))
    if data['schema']!='a7c2-lut-runtime/1':raise ValueError('Unknown runtime patch schema')
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
    start=six.TABLE_FILE+8;end=six.TABLE_FILE+32+6*six.TABLE_BYTES
    if len(cp)<end:raise ValueError('Truncated CP program')
    h=hashlib.sha256();h.update(cp[:start]);h.update(bytes(end-start));h.update(cp[end:]);return h.hexdigest()

def first_source(cp,kind,*,hash_checks=True):
    asset=runtime();current=fl23compat.runtime()
    spec=dict(next(s for s in asset['cp_sources'] if s['kind']==kind))
    spec['target_sha256']=asset['cp_zero_tables_sha256']
    spec['upgrade_gamma']=False
    digest=firmware.sha(cp) if hash_checks else None
    if kind=='stock':
        if hash_checks and digest!=spec['sha256']:raise ValueError('First import needs the exact matching stock AP+CP pair')
        spec.update(target_sha256=current['cp_zero_tables_sha256'],upgrade_gamma=True)
    elif digest==current['fl23_cp_sha256']:
        spec.update(sha256=digest,target_sha256=current['cp_zero_tables_sha256'])
    elif hash_checks and digest!=spec['sha256']:
        raise ValueError('First import needs the exact matching stock/FL23 AP+CP pair')
    return spec

def first_program(cp,kind,*,hash_checks=True):
    spec=first_source(cp,kind,hash_checks=hash_checks);result=bytearray(cp)
    for w in spec['windows']:
        at=w['offset'];old,new=bytes.fromhex(w['before']),bytes.fromhex(w['after'])
        if len(old)!=len(new) or cp[at:at+len(old)]!=old:raise ValueError('Bootstrap source window differs')
        result[at:at+len(new)]=new
    result=fl23compat.transform(bytes(result)) if spec['upgrade_gamma'] else bytes(result)
    if hash_checks and firmware.sha(result)!=spec['target_sha256']:raise ValueError('Canonical runtime differs')
    return result

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
    if not identity.get('first_install'):
        if len(cp)<six.TABLE_FILE+32+6*six.TABLE_BYTES or struct.unpack_from('<2I',cp,six.TABLE_FILE)!=(six.MAGIC,six.VERSION):
            raise ValueError('Custom table header/size differs')
    return dict(identity,layout='full7-v4' if identity['kind']=='legacy-six' else 'standalone-v1')

def tables(cp):
    """Read native-grid payloads, without comparing source table digests."""
    if len(cp)<six.TABLE_FILE+32+6*six.TABLE_BYTES or struct.unpack_from('<2I',cp,six.TABLE_FILE)!=(six.MAGIC,six.VERSION):
        raise ValueError('Custom table header/size differs')
    return [cp[six.TABLE_FILE+32+i*six.TABLE_BYTES:six.TABLE_FILE+32+(i+1)*six.TABLE_BYTES] for i in range(6)]

def identify(ap,cp):
    a=identify_ap(ap);c=firmware.sha(cp);asset=runtime()
    if a['kind']=='legacy-six':
        if code_hash(cp)!=CODE_SHA:
            if code_hash(fl23compat.transform(cp,reverse=True))!=CODE_SHA:raise ValueError('Unsupported legacy CP code identity')
        six.read_tables(cp)
    elif a.get('first_install'):
        first_source(cp,a['kind'])
    else:
        if code_hash(cp) not in (asset['cp_code_sha256'],fl23compat.runtime()['cp_code_sha256']):raise ValueError('Unsupported standalone CP code identity')
        six.read_tables(cp)
    return dict(a,layout='full7-v4' if a['kind']=='legacy-six' else 'standalone-v1',AP=firmware.sha(ap),CP=c,
        physical_first_install_tested=False if a['kind']!='legacy-six' else None)

def replace(ap,cp,replacements,*,hash_checks=True):
    identify_current=identify if hash_checks else structural
    identity=identify_current(ap,cp)
    if not replacements or any(type(s) is not int or s not in range(1,7) for s in replacements):raise ValueError('Select custom slots 1..6')
    result=bytearray(cp);spans=[];ap_result=ap;ap_spans=[]
    if identity.get('first_install'):
        result=bytearray(first_program(cp,identity['kind'],hash_checks=hash_checks))
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
    after={'appFw.so':ap_result,'cpapp-b.bin':bytes(result)};before={'appFw.so':ap,'cpapp-b.bin':cp}
    regions={'appFw.so':ap_spans,'cpapp-b.bin':spans}
    f=firmware.transition(before,after,regions)
    r=firmware.transition(after,before,regions)
    identify_current(after['appFw.so'],after['cpapp-b.bin'])
    if firmware.apply(after,r,hash_checks=hash_checks)!=before:raise ValueError('Complete table inverse differs')
    return f,r,after

def before_first_table(ap,cp,slot,*,hash_checks=True):
    """Dormant canonical data for a slot that originally used native looks."""
    identity=(identify if hash_checks else structural)(ap,cp)
    read_tables=six.read_tables if hash_checks else tables
    if not identity.get('first_install'):return read_tables(cp)[slot-1]
    return read_tables(first_program(cp,identity['kind'],hash_checks=hash_checks))[slot-1]

def deactivate(ap,cp,slot,raw,*,hash_checks=True):
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
    before={'appFw.so':ap,'cpapp-b.bin':cp};after={'appFw.so':after_ap,'cpapp-b.bin':bytes(result)}
    regions={'appFw.so':[(w['offset'],len(bytes.fromhex(w['hex']))) for w in spec['restore']],
        'cpapp-b.bin':[(at,six.TABLE_BYTES),(check,4)]}
    forward,reverse=firmware.transition(before,after,regions),firmware.transition(after,before,regions)
    identify_current(after_ap,after['cpapp-b.bin'])
    return forward,reverse,after
