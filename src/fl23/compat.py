"""Version-scoped FL23 planning without a firmware-provenance whitelist.

Only edited bytes have conflict guards; full readback compares bytes.
"""
from pathlib import Path
import sys
import core

WARNING='不驗證韌體來源。非本倉庫修改的韌體可能與 FL23 衝突，造成相機無法正常啟動；請保留備份。'
LEGACY_CONVERTER=bytes.fromhex('e1000035002800511f1400718800005400e4031140000039c0035fd63f2c007188020054800000100048613840000039c0035fd600030201100f1112050d13141f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d5')


def modules():
    sys.path.insert(0,str(core.BASE.parent/'looks'))
    try:
        from looktool import device_layout,firmware,nativebuild,worker
    except ImportError as exc:
        raise ValueError('LUT 相容模式缺少依賴，請更新完整工具並重新開啟 FL23.cmd。') from exc
    return device_layout,firmware,nativebuild,worker


def plan(ap,cp,version=core.VERSION,*,transitions=True):
    if version!=core.VERSION:raise ValueError('FL23 只適用於 ILCE-7CM2 2.01；請依相機版本頁填寫')
    layout,firmware,_,_=modules()
    before=dict(zip(core.PROGRAMS,[ap,cp]))
    # These are instruction-boundary checks, not file-source fingerprints.
    # A LUT converter already handles native FL2/FL3 and must not be replaced.
    template=ap[0x35287f0:0x3528874].hex();templates=layout.runtime()['ap_templates']
    lut=template in templates or ap[0x3528804:0x3528874]==LEGACY_CONVERTER
    mask=templates.index(template) if template in templates else None
    manifest=core.read_json(core.BASE/'assets/patches.json')
    if lut:
        for at,expected in [(0x138814,bytes.fromhex('3720e7e7')),(0x13882e,bytes.fromhex('3820dae7'))]:
            if cp[at:at+len(expected)]!=expected:raise ValueError(f'CP FL23 呼叫位置衝突：{at:#x}；沒有寫入')
    after={};regions={};changed=False
    for chip,name in enumerate(core.PROGRAMS):
        source=before[name];result=bytearray(source);spans=[]
        if lut and chip==1:
            from looktool import fl23compat,checkpointworker
            protected=fl23compat.preserve_lut_dispatch(source)
            result=fl23compat.transform(source)
            for w in manifest[chip]['writes']:
                at=int(w['file_offset'],16);new=bytes.fromhex(w['after_hex'])
                if at not in protected and result[at:at+len(new)]!=new:
                    raise ValueError(f'CP FL23/LUT 位置衝突：{at:#x}；沒有寫入')
            spans=[(at,len(old)) for at,old,new in checkpointworker.differences(source,result)]
            after[name]=result;regions[name]=spans;changed|=result!=source
            continue
        for w in manifest[chip]['writes']:
            at=int(w['file_offset'],16);old,new=bytes.fromhex(w['before_hex']),bytes.fromhex(w['after_hex'])
            if lut and at==0x3528804:continue
            if len(old)!=len(new) or at+len(old)>len(source):raise ValueError(f'補丁位置越界：{name} {at:#x}')
            current=source[at:at+len(old)]
            if current==new:continue
            if current!=old:raise ValueError(f'補丁位置衝突：{name} {at:#x}；沒有寫入')
            result[at:at+len(new)]=new;changed=True
            for offset in range(0,len(new),4096):spans.append((at+offset,min(4096,len(new)-offset)))
        after[name]=bytes(result);regions[name]=spans
    identity={'kind':'lut' if lut else 'version-2.01','mask':mask,'provenance_checked':False,'firmware_version':version,'version_source':'user-camera-version-screen'}
    if not changed:return identity,True,before,None,None
    if not transitions:return identity,False,after,None,None
    forward=firmware.transition(before,after,regions)
    reverse=firmware.transition(after,before,regions)
    if firmware.apply(firmware.apply(before,forward),reverse)!=before:
        raise ValueError('完整還原候選不符')
    return identity,False,after,forward,reverse


def prepare(root,ap,cp,version=core.VERSION):
    identity,enabled,after,_,_=plan(ap,cp,version,transitions=False)
    result={'identity':identity,'already_enabled':enabled}
    if not enabled:
        from looktool.checkpointworker import build_programs
        result['byte_builds']=build_programs(dict(zip(core.PROGRAMS,[ap,cp])),after,root/'compat-worker',checkpoint_namespace=False)
    for n,data in after.items():(root/'candidate'/n).write_bytes(data)
    return result


def validate(root,state):
    spec=state['compatibility']
    ap,cp=[(root/'original'/(n+'.bin')).read_bytes() for n in core.PROGRAMS]
    identity,enabled,after,_,_=plan(ap,cp,state.get('version',core.VERSION),transitions=False)
    if spec['identity']!=identity or spec['already_enabled']!=enabled:
        raise ValueError('相容任務來源或目標已變')
    for n,data in after.items():
        if (root/'candidate'/n).read_bytes()!=data:raise ValueError('相容候選已變')


def validate_enabled_colors(a,b):
    # Undo only the exact FL23 colour records, then re-merge. This proves
    # ownership without clearing calibration, user recipes or LUT tables.
    x,y=bytearray(a),bytearray(b)
    if len(x)!=8192 or len(y)!=28672:raise ValueError('色彩單元長度不符')
    for row in core.read_json(core.BASE/'assets/colors.json'):
        p,s=row['parameter'],row['slot'];x[0x1200+p]=0;y[0x196+p]=0
        x[0x1250+s*64:0x1250+(s+1)*64]=bytes(64)
        y[0x1e0+s*768:0x1e0+s*768+576]=bytes(576)
    if core.merge_colors(bytes(x),bytes(y))!=(a,b):raise ValueError('既有 FL23 色彩資料不完整；拒絕重寫')
