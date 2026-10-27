"""Independent custom speaker audio through the existing native CSV loader.

The reader indexes only native kinds 1..3, within its original instruction
extent. Kind1 plays the mechanical clip, kind2 a silent closing segment, and
kind3 the electronic clip. Unselected descriptors and files remain unchanged.
No USB access occurs on import or while building a plan.
"""
from pathlib import Path
import re
import struct

import boot_sound

TARGETS=('electronic','mechanical','both')
ROOT='/usr/share/avsystemsound/'
FILES=tuple('custom-shutter'+suffix+'.bin' for suffix in ('','-a','-b'))
EXTRA=(
    (0x275a290,bytes.fromhex('3f630071'),bytes.fromhex('9f0f0071')),
    (0x275a298,bytes.fromhex('b50b01b0'),boot_sound.branch(0x275a298,0x2759bc8)),
    (0x275a324,bytes.fromhex('00168052a2e34139207f209b6103008b626b203800b00091a27340b96003008b'),
     bytes.fromhex('9907005100168052207f209b6103008ba2e3413922000039a27340b920b00091')),
)


def target(value):
    if value not in TARGETS:raise ValueError('选择只修改机械、只修改电子或两者都修改')
    return value


def boot_bytes():
    # Use the table base; the bounded kind index selects the original row.
    raw=next(new for at,old,new in boot_sound.expected_windows() if at==boot_sound.BOOT)
    return raw[:4]+bytes.fromhex('00000091')+raw[8:]


def sparse(ap):
    return (ap[boot_sound.BOOT:boot_sound.BOOT+16]==boot_bytes() or
            any(ap[at:at+len(new)]==new for at,old,new in EXTRA))


def windows(ap):
    result=[]
    for at,old,new in boot_sound.expected_windows():
        actual=ap[at:at+len(old)]
        allowed=(old,new,boot_bytes()) if at==boot_sound.BOOT else (old,new)
        if actual not in allowed:raise ValueError('Custom sound instruction conflict at '+hex(at))
        result.append((at,old,boot_bytes() if at==boot_sound.BOOT else new))
    for at,old,new in EXTRA:
        if ap[at:at+len(old)] not in (old,new):
            raise ValueError('Custom sound reader instruction conflict at '+hex(at))
    # Reader prerequisites precede the boot call. Never introduce a code cave.
    return result[:-1]+list(EXTRA)+result[-1:]


def row(kind,name,size,offset=0):
    return ('CUSTOM,0x%04X,APP,%s,0x%X,0x%X,AA_RT,6,%d,0,0,0\n'%
            (kind,name,size,offset,kind)).encode('ascii')


def encode(rows):
    return (b'\n/* START */\n'+ROOT.encode()+b'\n'+
            b''.join(row(k,**v) for k,v in sorted(rows.items()))+b'/* END */\n')


def decode(csv):
    if not csv:return {}
    rows={}
    for match in re.finditer(rb'CUSTOM,0x000([123]),APP,(custom-shutter(?:-[ab])?\.bin),(0x[0-9A-F]+),(0x[0-9A-F]+),AA_RT,6,([123]),0,0,0\n',csv):
        kind=int(match[1]);size=int(match[3],16);offset=int(match[4],16)
        if kind in rows or int(match[5])!=kind or not 0<size<=51200 or size%64 or offset%64:
            raise ValueError('Custom sound row dimensions differ')
        if offset+size>51200:raise ValueError('Custom sound row exceeds audio bounds')
        rows[kind]=dict(name=match[2].decode(),size=size,offset=offset)
    if not rows or encode(rows)!=csv:raise ValueError('Unrecognized custom sound configuration; preserve diagnostics')
    if (1 in rows)!=(2 in rows):raise ValueError('Incomplete mechanical sound pair')
    if 1 in rows and (rows[2]['name']!=rows[1]['name'] or rows[2]['size']!=64 or
                      rows[2]['offset']!=rows[1]['size'] or rows[1]['offset']):
        raise ValueError('Mechanical closing segment must be bounded silence')
    if 3 in rows and rows[3]['offset']:raise ValueError('Electronic sound offset differs')
    return rows


def configuration(csv,payload,selection,*,installed=False,reserved_names=()):
    """Build one inactive file and a merged CSV; preserve the other selection."""
    target(selection)
    if not payload or len(payload)>51136 or len(payload)%64 or any(payload[n]>8 for n in range(0,len(payload),32)):
        raise ValueError('Convert a complete native audio clip within the sound size limit')
    rows=decode(csv) if csv else {}
    if installed and not rows:raise ValueError('Installed sound hook lacks its configuration')
    # Legacy hooks start at kind3 and cannot safely consume a mechanical CSV.
    # Caller verifies hook revision before publishing the merged configuration.
    used={v['name'] for v in rows.values()}|set(reserved_names)
    filename=next((name for name in FILES if name not in used),None)
    if filename is None:raise ValueError('相机仍加载着旧声音，暂无空闲音频位置；请先按上次写入提示断电重开并核对，不覆盖在用文件。')
    audio=payload+(bytes(64) if selection in ('mechanical','both') else b'')
    if selection in ('mechanical','both'):
        rows[1]=dict(name=filename,size=len(payload),offset=0)
        rows[2]=dict(name=filename,size=64,offset=len(payload))
    if selection in ('electronic','both'):rows[3]=dict(name=filename,size=len(payload),offset=0)
    result=encode(rows);decode(result)
    return audio,result,filename,rows


def program_plan(ap,cp,selection):
    import candidate
    switches=candidate.switches(cp)
    changed=candidate.patch(ap,cp,mechanical=True if selection in ('mechanical','both') else switches['mechanical'],
                            electronic=True if selection in ('electronic','both') else switches['electronic'])
    edits=[]
    for at,old,new in windows(ap):
        actual=ap[at:at+len(old)]
        if actual!=new:edits.append((at,actual,new))
    result=bytearray(ap)
    for at,old,new in edits:result[at:at+len(old)]=new
    changed['appFw.so']=bytes(result)
    return changed,edits


def install_connected(camera,root,state,payload,selection,backup_copy,zig=None):
    import boot_trial,candidate,files_worker,trial
    from looktool import nativebuild
    before=trial.capture(camera)
    ap,cp=before['appFw.so'],before['cpapp-b.bin']
    candidate.guard(ap,cp,installed=candidate.is_enabled(cp))
    target_programs,edits=program_plan(ap,cp,selection)
    old_csv=camera.read(ROOT+'custom.txt',True) or b''
    installed=boot_sound.installed(ap)
    if not installed and old_csv:
        # A partially prepared known configuration is admissible only after
        # validating it, not by discarding it and replacing other selections.
        decode(old_csv)
    prior=decode(old_csv) if old_csv else {}
    if not sparse(ap) and set(prior)-{3}:raise ValueError('Legacy hook has incompatible mechanical rows')
    retained={}
    for value in prior.values():
        raw=camera.read(ROOT+value['name'])
        retained[value['name']]=raw
        if len(raw)<value['offset']+value['size']:raise ValueError('Existing custom audio is incomplete')
        if value.get('offset') and any(raw[value['offset']:value['offset']+value['size']]):
            raise ValueError('Mechanical closing segment is not silent')
    state.update(identity=camera.identity,sound_target=selection,
                 phase='preparing',camera_firmware_written=False,audio_resources_written=False)
    state['backup_copy']=trial.backup(root,backup_copy,dict(before,**{'custom.txt':old_csv}))
    trial.save(root,state);camera.programs_pinned=True
    probe=boot_trial.current_probe(ap,root/'probe',zig)
    header=Path(probe).with_name('current-probe.private.h')
    wbi=root/'wbi.so'
    nativebuild.compile_worker(candidate.ROOT/'src/fl23/native/wbi.c',header,wbi,zig,fingerprints=False)
    runtime=boot_trial.probe(camera,root,state,dict(probe=str(probe),wbi=str(wbi)))
    reserved={Path(row['filename']).name for row in runtime['entries'][:3]
              if row.get('filename','').startswith(ROOT) and Path(row['filename']).name in FILES}
    audio,csv,filename,rows=configuration(old_csv,payload,selection,installed=installed,reserved_names=reserved)
    state['custom_rows']=rows
    disarm=None;source=ap
    legacy_boot=next((old,new) for at,old,new in boot_sound.expected_windows() if at==boot_sound.BOOT)
    if installed and not sparse(ap):
        # Remove the old offset-based call before a multi-row CSV can be
        # published. A power loss between batches then has no custom call.
        source=boot_sound.patch(ap,[(boot_sound.BOOT,legacy_boot[1],legacy_boot[0])])
        disarm=boot_trial.program_worker(ap,cp,[(boot_sound.BOOT,legacy_boot[1],legacy_boot[0])],root/'disarm',zig)
        target_programs,edits=program_plan(source,cp,selection)
    cp_edits=[(at,cp[at:at+len(old)],target_programs['cpapp-b.bin'][at:at+len(old)])
              for at,old,new in candidate.WINDOWS if cp[at:at+len(old)]!=target_programs['cpapp-b.bin'][at:at+len(old)]]
    program=boot_trial.program_worker(source,cp,edits,root/'program',zig,cp_edits=cp_edits)
    temporary=[camera.read(ROOT+name,True) for name in ('.a7c2-sound-audio.tmp','.a7c2-sound-csv.tmp')]
    files=files_worker.build(audio,csv,root/'files',zig,audio_path=ROOT+filename,
                             previous_csv=old_csv,temporary_files=temporary)
    state['components']=dict(paths=[ROOT+filename,ROOT+'custom.txt'],custom_rows=rows)
    trial.save(root,state)
    if disarm:trial.run_native(camera,root,state,disarm['path'],'program',0,disarm)
    # Program mode0 for the second batch must wait until the disarm's complete
    # readback, since its pinned BOOT window then has different current bytes.
    boot_trial.invoke_files(camera,root,state,files,0)
    if disarm:
        state['phase']='disabling_legacy_call';trial.save(root,state)
        trial.run_native(camera,root,state,disarm['path'],'program',1,disarm)
        state['camera_firmware_written']=True;trial.save(root,state)
        if camera.read('/usr/lib/appFw.so')!=source:raise ValueError('Legacy boot-call removal readback differs')
    trial.run_native(camera,root,state,program['path'],'program',0,program)
    state['phase']='publishing_custom_audio';trial.save(root,state)
    boot_trial.invoke_files(camera,root,state,files,1)
    state['audio_resources_written']=True;trial.save(root,state)
    if camera.read(ROOT+filename)!=audio or camera.read(ROOT+'custom.txt')!=csv:
        raise ValueError('Complete sound resource readback differs; new hook not written')
    state['phase']='installing_custom_audio_hook';trial.save(root,state)
    trial.run_native(camera,root,state,program['path'],'program',1,program)
    state['camera_firmware_written']=True;trial.save(root,state)
    for name,path in (('appFw.so','/usr/lib/appFw.so'),('cpapp-b.bin','/cp/cpapp-b.bin')):
        if camera.read(path)!=target_programs[name]:raise ValueError('Complete custom sound program readback differs')
    # Also re-read every retained row/file, including the unselected side.
    for value in rows.values():
        raw=camera.read(ROOT+value['name'])
        if len(raw)<value['offset']+value['size']:raise ValueError('Retained custom audio became incomplete')
    for name,raw in retained.items():
        if camera.read(ROOT+name)!=raw:raise ValueError('Unselected/previous custom audio changed')
    boot_trial.check_settings(camera,before)
    if runtime['image_mode']=='2':trial.run_native(camera,root,state,str(wbi),'wbi',1)
    state.update(phase='installed_cold_test_pending',complete_readback_and_settings_verified=True,
                 reload_required=True,physical_audio_verified=False)
    trial.save(root,state)
    return state


def run(args):
    """Explicit desktop Save only; conversion and selection checks precede USB."""
    import sound_cli,trial
    from replacement import command_lock,CurrentRequest
    from looktool.power import require_power
    selection=target(args.get('sound_target','electronic'))
    if args.get('firmware')!='2.01':raise ValueError('Custom shutter sound supports ILCE-7CM2 2.01 only')
    require_power(confirmed=args.get('power_confirmed',False))
    root=Path(args['workspace']).resolve()
    with command_lock(root):
        backup=args.get('backup')
        if not backup and not (root/'sound.private.json').is_file():backup=str(root)+'-backup'
        root,state=sound_cli.workspace(root,True,backup)
        sound_cli.require_idle(state,root)
        conversion=sound_cli.selected_conversion(root,state)
        if not conversion:return sound_cli.installation_step('sound_conversion_required','import')
        payload=(Path(conversion)/'custom-native.private.bin').read_bytes()
        configuration(b'',payload,selection)  # validate before device access
        job=sound_cli.new_path(root,'custom-'+selection);job.mkdir(parents=True)
        current=dict(schema='a7c2-targeted-sound-job/1',phase='preparing',journal=[],sound_target=selection)
        trial.save(job,current)
        def execute():
            try:
                with trial.factory() as camera:
                    return install_connected(camera,job,current,payload,selection,Path(state['backup_root'])/job.name)
            except BaseException as exc:
                current.update(failed_during=current['phase'],phase='needs_review',error_type=type(exc).__name__,error=str(exc))
                trial.save(job,current)
                raise
        # Validate the previous intent before entering this context. Prepare
        # the current session before operate() publishes the NEW intent, so
        # inert audition reports can be archived without retiring that intent.
        with CurrentRequest(root,state,'install',refresh=False):
            result=sound_cli.operate(root,state,'install',job,execute)
        return dict(result,workspace=str(job),command='install')
