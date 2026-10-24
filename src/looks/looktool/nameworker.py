"""Prepare and verify the separate, atomic, job-pinned name transaction."""
import json,re
from pathlib import Path
from . import firmware,resources
from .nativebuild import ROOT,compile_worker
from .jobdiagnostics import NAME_REPORT,name_failure_text

REPORT=NAME_REPORT

def filenames():
    names=json.loads((ROOT/'src/looks/assets/resource-files.json').read_text(encoding='utf-8'))
    if len(names)!=68 or len(set(names))!=68 or any(not re.fullmatch(r'string_[a-z]+_(horizontal|vertical)\.uxc',n) for n in names):raise ValueError('Resource allowlist differs')
    return names

def prepare(sources,names,ap,job_id,out,zig=None,*,target_ap=None,label_ids=resources.LABEL_IDS,byte_only=False):
    if set(sources)!=set(filenames()):raise ValueError('All 68 complete resource sources are required')
    if not re.fullmatch(r'[a-f0-9]{16}',job_id):raise ValueError('Invalid resource transaction ID')
    out=Path(out);out.mkdir(parents=True,exist_ok=True);target={};specs=[];pointers=[]
    q=lambda s:json.dumps(s,ensure_ascii=True)
    cbytes=lambda b:'{'+','.join(map(str,b))+'}'
    unchanged=True
    for filename in filenames():
        raw=sources[filename];parsed=resources.decode(raw)
        if parsed['count'] not in [2860,2866] or parsed['group']!=5:raise ValueError('Unsupported resource source layout')
        changed,plan=resources.rename(raw,names,label_ids)
        unchanged=unchanged and all(parsed['entries'].get(label_ids[slot-1],{}).get('text')==name for slot,name in names.items())
        if resources.inverse(changed,plan)!=raw:raise ValueError('Resource inverse differs')
        target[filename]=changed;pointers.append([parsed['entries'].get(rid,{}).get('pointer',65535) for rid in label_ids])
        specs.append({'file':filename,'before_bytes':len(raw),'after_bytes':len(changed),'before_sha256':'00'*32 if byte_only else firmware.sha(raw),'after_sha256':'00'*32 if byte_only else firmware.sha(changed),'inverse':plan})
    if unchanged:
        for spec in specs:
            spec['after_bytes']=spec['before_bytes'];spec['after_sha256']=spec['before_sha256']
            spec['inverse'].update(after_bytes=spec['before_bytes'],changes=[])
        return dict(sources),{'unchanged':True,'AP':None if byte_only else firmware.sha(ap),
            'target_AP':None if byte_only else firmware.sha(target_ap if target_ap is not None else ap),
            'count':len(specs),'files':specs,'job_id':job_id,'byte_only':byte_only}
    lines=['static const struct Asset assets[]={'+','.join('{'+q(s['file'])+','+str(s['before_bytes'])+','+cbytes(bytes.fromhex(s['before_sha256']))+','+cbytes(bytes.fromhex(s['after_sha256']))+'}' for s in specs)+'};',
        'static const u32 asset_count='+str(len(specs))+';',
        'static const u32 after_sizes[]={'+','.join(str(s['after_bytes']) for s in specs)+'};',
        'static const u32 old_counts[]={'+','.join(str(s['inverse']['before_count']) for s in specs)+'};',
        'static const u32 label_ids[]={'+','.join(str(rid)+'U' for rid in label_ids)+'};',
        'static const unsigned short old_pointers[68][6]={'+','.join('{'+','.join(map(str,row))+'}' for row in pointers)+'};',
        'static const u8 names[6][64]={'+','.join(cbytes(names.get(slot,'ST').encode('utf-8')+b'\0') for slot in range(1,7))+'};',
        'static const u32 selected_mask='+str(sum(1<<(slot-1) for slot in names))+';',
        'static const char backup_prefix[]='+q('/usr/share/app/.a7c2-lut-'+job_id+'-')+';',
        # Pinned official 2.01 filesystem ownership, retained by prior atomic
        # installers. Root is the worker's euid, not the files' owner.
        'static const u32 original_uid=57285,original_gid=1000;',
        'static const u64 ap_size='+str(len(ap))+'UL;',
        'static const u8 ap_plain_hash[32]='+cbytes(bytes(32) if byte_only else bytes.fromhex(firmware.sha(ap)))+';',
        'static const u8 ap_named_hash[32]='+cbytes(bytes(32) if byte_only else bytes.fromhex(firmware.sha(target_ap if target_ap is not None else ap)))+';']
    if byte_only:lines[:0]=['#define CHECKPOINT_BYTES 1','#define BYTE_NAME_UPDATES 1',
        '#define BYTE_NAME_STREAM_INSTALL 1','#define CHECKPOINT_STREAM_RESTORE 1']
    header=out/'names.private.h';header.write_text('\n'.join(lines)+'\n',encoding='ascii',newline='\n')
    destination=out/'names.so';build=compile_worker(ROOT/'src/looks/native/names.c',header,destination,zig,fingerprints=not byte_only)
    build.update(path=str(destination),AP=None if byte_only else firmware.sha(ap),target_AP=None if byte_only else firmware.sha(target_ap if target_ap is not None else ap),count=len(specs),files=specs,job_id=job_id,byte_only=byte_only,stream_install=byte_only)
    return target,build

def completed_mount_busy(raw,mode,build):
    if len(raw)!=REPORT.size or mode!=1 or not build.get('byte_only') or not build.get('stream_install'):return False
    v=REPORT.unpack(raw);count=build['count']
    return (v[:5]==(b'A7NMR001',1,1,9,count) and 1<=count<=68 and len(build['files'])==count
        and v[5]==v[8]==-16 and all(v[i]==0 for i in (6,7,9,10,13,15,16,17))
        and v[11]>0 and v[12]==v[14]==count)


def validate(raw,mode,build,*,allow_completed_busy=False):
    if len(raw)!=REPORT.size or mode not in (0,1,2,3):raise ValueError('Invalid name result ABI')
    values=REPORT.unpack(raw)
    count=build['count']
    if not 1<=count<=68 or len(build['files'])!=count:raise ValueError('Invalid pinned resource count')
    if allow_completed_busy and completed_mount_busy(raw,mode,build):
        return {'native_verified':True,'mode':mode,'files':count,'restored':0,'readonly_deferred_busy':True}
    expected_ap=build.get('target_AP',build['AP']) if mode==3 else build['AP']
    if values[:5]!=(b'A7NMR001',1,mode,9,count) or any(values[i] for i in [5,6,7,8,9,10,17]) or (not build.get('byte_only') and values[18].hex()!=expected_ap):
        raise ValueError(name_failure_text(raw,mode,build))
    if values[11]<=0 or any(n>count for n in values[12:17]):raise ValueError('Native name PID/count bounds differ')
    if mode==0 and any(values[12:17]):raise ValueError('Read-only name preflight reported a write')
    if mode==1 and (values[12:15]!=(count,0 if build.get('stream_install') else count,count) or any(values[15:17])):raise ValueError('Native name commit counts differ')
    if mode==2 and any(values[13:15]):raise ValueError('Name restoration reported a forward commit')
    if mode==3 and any(values[12:16]):raise ValueError('Name cleanup reported resource writes')
    return {'native_verified':True,'mode':mode,'files':count,'restored':values[15]}

def prepare_cleanup(build,header,current,out,zig=None):
    """Retain the original job's backup paths; target proved later resources."""
    if not build.get('byte_only') or build.get('unchanged'):raise ValueError('Byte-based existing name transaction required')
    if set(current)!={spec['file'] for spec in build['files']}:raise ValueError('Complete current name resources required')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    text=Path(header).read_text(encoding='ascii')
    sizes=','.join(str(len(current[spec['file']])) for spec in build['files'])
    text,count=re.subn(r'static const u32 after_sizes\[\]=\{[^}]*\};','static const u32 after_sizes[]={'+sizes+'};',text)
    if count!=1:raise ValueError('Original name manifest sizes unavailable')
    target=out/'names.private.h';target.write_text(text,encoding='ascii',newline='\n')
    result=json.loads(json.dumps(build));result.update(compile_worker(ROOT/'src/looks/native/names.c',target,out/'names.so',zig,fingerprints=False))
    result['path']=str(out/'names.so')
    for spec in result['files']:spec['after_bytes']=len(current[spec['file']])
    return result
