"""Offline compiler inputs and report checks; no USB or camera execution.

Only selected-table updates and the reviewed upload-entry migration are accepted.
This does not authorize an unknown source or install a stock-to-six build.
Generated headers contain private firmware-derived bytes; keep them private.
"""
import struct
from . import firmware, six

NAMES=('appFw.so','cpapp-b.bin')
REPORT=struct.Struct('<8sIIII7q4Q')


def prepare_table_worker(ap,cp,forward,reverse,bindings):
    if firmware.sha(ap)!=six.AP_SHA or firmware.sha(six.uploadgate.legacy_hash_source(cp))!=six.CP_SHA:
        raise ValueError('Worker preparation requires the pinned full7-v4 source')
    for manifest in [forward,reverse]:
        if manifest.get('schema')!='a7c2-private-transition/1' or set(manifest.get('files',{}))!=set(NAMES):
            raise ValueError('Expected both complete components and transition schema 1')
    plan=forward.get('slot_plan',{})
    slots=plan.get('selected_slots',[])
    if not slots or any(type(s) is not int or s not in range(1,7) for s in slots) or len(set(slots))!=len(slots):
        raise ValueError('Expected unique selected slots 1..6')
    if plan.get('model')!='ILCE-7CM2' or plan.get('firmware')!='2.01':
        raise ValueError('Slot plan model/firmware differs')
    from . import project
    project.check_bindings(plan,bindings)  # A host assertion, never live camera evidence.
    before=dict(zip(NAMES,[ap,cp]));after=firmware.apply(before,forward)
    if firmware.apply(after,reverse)!=before:
        raise ValueError('Exact complete-file inverse required')
    tables=six.read_tables(after['cpapp-b.bin'])
    expected_f,expected_r,expected_after=six.replace_tables(ap,cp,{s:tables[s-1] for s in slots})
    if after!=expected_after or forward['files']!=expected_f['files'] or reverse['files']!=expected_r['files']:
        raise ValueError('Only selected tables, their checksums and the reviewed upload entry may change')
    windows=[]
    for chip,name in enumerate(NAMES):
        windows.extend(dict(window,chip=chip) for window in forward['files'][name]['windows'])
    windows.sort(key=lambda w:(0 if w['chip']==1 else 1,0 if w['bytes']>1024 else 1,int(w['offset'],16)))
    if not windows:raise ValueError('No table changes to install')
    lines=[];rows=[]
    cbytes=lambda data:'{'+','.join(str(v) for v in data)+'}'
    for i,window in enumerate(windows):
        old,new=bytes.fromhex(window['before_hex']),bytes.fromhex(window['after_hex'])
        if not 0<len(old)==len(new)<=4096:raise ValueError('Window exceeds native buffer')
        lines.extend([f'static const u8 old_{i}[]={cbytes(old)};',f'static const u8 new_{i}[]={cbytes(new)};'])
        rows.append('{'+f"{int(window['offset'],16)}UL,{len(old)},{window['chip']},old_{i},new_{i}"+'}')
    lines.extend(['static const struct Window windows[]={'+','.join(rows)+'};',
                  f'static const u32 window_count={len(windows)};',
                  'static const u64 file_sizes[]={'+','.join(str(len(before[n]))+'UL' for n in NAMES)+'};'])
    for label,values in [('original',before),('final',after)]:
        lines.append('static const u8 '+label+'_hashes[2][32]={'+','.join(cbytes(bytes.fromhex(firmware.sha(values[n]))) for n in NAMES)+'};')
    contract={'schema':'a7c2-table-worker-contract/1','selected_slots':slots,'window_writes':len(windows),
              'sizes':{n:len(before[n]) for n in NAMES},
              'before':{n:firmware.sha(before[n]) for n in NAMES},
              'after':{n:firmware.sha(after[n]) for n in NAMES},
              'camera_io':False,'live_bindings_verified':False,
              'names_settings_reload_or_device_installer_included':False}
    return '\n'.join(lines)+'\n',contract


def validate_worker_report(raw,mode,contract):
    """Validate the existing installer.c 240-byte ABI against this exact job.

    Native evidence alone is insufficient: complete host readback, settings
    preservation, cleanup and physical acceptance remain separate checks.
    """
    if contract.get('byte_only'):
        from .checkpointworker import program_report
        return program_report(raw,mode,{'windows':contract['window_writes'],'sizes':[contract['sizes'][n] for n in NAMES]})
    if type(mode) is not int or mode not in (0,1,2) or len(raw)!=240:
        raise ValueError('Expected native mode 0/1/2 and exactly 240 report bytes')
    if contract.get('schema')!='a7c2-table-worker-contract/1':raise ValueError('Unknown worker contract')
    try:
        sizes=[contract['sizes'][n] for n in NAMES]
        before=[bytes.fromhex(contract['before'][n]) for n in NAMES]
        after=[bytes.fromhex(contract['after'][n]) for n in NAMES]
        writes=contract['window_writes']
    except (KeyError,TypeError,ValueError) as exc:raise ValueError('Invalid worker contract fields') from exc
    if any(type(n) is not int or n<=0 for n in sizes) or any(len(h)!=32 for h in before+after) or type(writes) is not int or writes<=0:
        raise ValueError('Invalid worker sizes/hashes/write count')
    values=REPORT.unpack_from(raw)
    if values[:4]!=(b'A7IRP001',1,mode,9) or any(values[i] for i in [5,6,7,8,9,10]):
        raise ValueError('Native operation did not finish cleanly; inspect without replay')
    if values[4]!=(0 if mode==0 else writes) or list(values[14:16])!=sizes or any(values[i]<=0 for i in [12,13]):
        raise ValueError('Native counts, sizes or inode evidence differs')
    actual_before=[raw[112:144],raw[144:176]];actual_after=[raw[176:208],raw[208:240]]
    if actual_before!=(after if mode==2 else before):raise ValueError('Native source hashes differ')
    if mode and actual_after!=(before if mode==2 else after):raise ValueError('Native target hashes differ')
    if mode==0 and actual_after!=[bytes(32),bytes(32)]:raise ValueError('Unexpected preflight target hashes')
    return {'mode':mode,'native_verified':True,'window_writes':values[4],
            'host_complete_readback_verified':False,'physical_test_verified':False}
