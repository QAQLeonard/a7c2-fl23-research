"""Private job files, complete exception logs and support-bundle export."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import platform
import sys
import uuid
import zipfile
from .paths import data_root, write_json
from . import VERSION

from .actions.catalog import CAMERA_ACTIONS, POWER_ACTIONS, DIRECT_ACTIONS


def new_job(action, arguments):
    root = data_root() / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                                 + '-' + action + '-' + uuid.uuid4().hex[:6])
    root.mkdir(parents=True)
    request = {'schema': 'a7c2-desktop-job/1', 'action': action, 'arguments': arguments,
               'job_dir': str(root), 'version': VERSION}
    write_json(root / 'request.private.json', request)
    write_json(root / 'status.private.json', {'phase': 'QUEUED', 'action': action})
    return root


def worker_command(request):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--worker', str(request)]
    from .paths import ROOT
    return [sys.executable, '-u', str(ROOT / 'desktop.py'), '--worker', str(request)]


def sound_summary(root):
    """Which sound operation is unresolved, without audio or camera buffers."""
    path=root/'sound.private.json'
    if not path.is_file():return {}
    state=json.loads(path.read_text(encoding='utf-8'))
    def plain(values):
        return {k:v for k,v in values.items() if v is None or isinstance(v,(bool,int,float))
                or (isinstance(v,str) and len(v)<=600)}
    summary=plain(state)
    summary.update(pending=state.get('pending'),history=[plain(h) for h in state.get('history',[])[-10:]])
    jobs={}
    for key in ('pending_job','audio_job','native_job','boot_job'):
        folder=(state.get('pending') or {}).get('job') if key=='pending_job' else state.get(key)
        record=Path(folder or '','job.private.json')
        if not folder or not record.is_file():continue
        value=json.loads(record.read_text(encoding='utf-8'))
        row=plain(value)
        events=value.get('journal') or value.get('events') or []
        row['events']=[e.get('event') for e in events[-30:] if isinstance(e,dict)]
        row['files']=sorted(p.name for p in Path(folder).iterdir())[:50]
        jobs[key]=row
    summary['jobs']=jobs
    return {'sound-summary.json':summary}


def transaction_summaries(job):
    """Include original failure stages, never program/settings snapshots."""
    request_path=Path(job)/'request.private.json'
    if not request_path.is_file():return {}
    request=json.loads(request_path.read_text(encoding='utf-8'))
    folder=request.get('arguments',{}).get('workspace')
    if not folder:return {}
    if request.get('action','').startswith('sound_'):
        return sound_summary(Path(folder))
    root=Path(folder);result={};children=[root]
    pointer=Path(job)/'backend-workspace.private.json'
    if pointer.is_file():
        children=[Path(json.loads(pointer.read_text(encoding='utf-8'))['workspace'])]
    elif request.get('action') in ('vertical_enable','vertical_disable') and not (root/'direct.private.json').is_file():
        # Persistent vertical actions use a fresh child below the page's root.
        # Include the actual child; the old export omitted its native result.
        children=[p.parent for p in sorted(root.glob('persistent-*/direct.private.json'),key=lambda p:p.stat().st_mtime_ns)[-3:]]
    fields=('schema','phase','mode','failed_during','error','error_type','completed_steps',
            'install_workspace','failed_install_workspaces','names_cleanup_pending',
            'readonly_after_reload_verified','physical_checks_accepted','private_sound_files_removed','native_portrait','restore_voice')
    setup=root/'setup.private.json'
    if setup.is_file():
        state=json.loads(setup.read_text(encoding='utf-8'))
        result['setup-summary.json']={k:state[k] for k in fields if k in state}
        children=[Path(state.get('install_workspace') or root/'install')]
        children.extend(Path(p) for p in state.get('failed_install_workspaces',[])[-5:])
    for i,child in enumerate(dict.fromkeys(children)):
        path=child/'direct.private.json'
        if not path.is_file():continue
        state=json.loads(path.read_text(encoding='utf-8'))
        summary={k:state[k] for k in fields if k in state}
        summary['journal']=[]
        for event in state.get('journal',[]):
            row={k:event[k] for k in ('event','stage','mode') if k in event}
            if isinstance(event.get('result'),dict):
                row['result']={k:event['result'][k] for k in ('phase','status','windows','mode',
                    'staged','linked','committed','restored','rollback','remount','readonly','cleanup',
                    'failure_group','failure_step','progress_bytes','available_bytes','required_bytes',
                    'created','removed','source_sizes',
                    'resource_kind','resource_file','index','requested_offset','requested_bytes',
                    'program','expected_bytes','actual_bytes','first_difference') if k in event['result']}
                # These are public look indices/values, not program or sensor
                # bytes. Keep the binding report that older exports discarded.
                native=event['result']
                targets=native.get('targets')
                if isinstance(targets,list) and targets and all(isinstance(t,dict)
                        and t.get('key') in {*(0x02cf0cd0+2*i for i in range(6)),0x02cf1287,0x02cf1289}
                        and type(t.get('index')) is int and t['index'] in range(10,18)
                        and type(t.get('value')) is int and t['value'] in range(12) for t in targets):
                    row['result']['targets']=[{k:t[k] for k in ('key','index','value')} for t in targets]
                    for key in ('before','after'):
                        value=native.get(key)
                        if isinstance(value,list) and len(value)==18 and all(type(v) is int and 0<=v<=0xffffffff for v in value):
                            row['result'][key]=value
                    for key in ('current','changed_mask'):
                        if type(native.get(key)) is int:row['result'][key]=native[key]
            summary['journal'].append(row)
        result['direct-summary-%d.json'%i]=summary
    return result


def export_support(job, destination):
    """Export diagnostic text only; never programs, sensor calibration or photos."""
    job = Path(job)
    summary = {'app_version': VERSION, 'platform': platform.platform(),
               'python': sys.version, 'camera_binaries_included': False,
               'contains_local_paths': True}
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('environment.json', json.dumps(summary, indent=2))
        for name in ['request.private.json', 'status.private.json', 'worker.log',
                     'process.log', 'result.private.json', 'driver-report.private.json',
                     'authorization.private.json','authorization.stdout.log','authorization.stderr.log',
                     'privilege.private.json','usb-stability.private.json','backend-workspace.private.json']:
            path = job / name
            if path.is_file():
                archive.write(path, 'diagnostics/' + name)
        try:
            for name,value in transaction_summaries(job).items():
                archive.writestr('diagnostics/transactions/'+name,json.dumps(value,ensure_ascii=False,indent=2))
        except (OSError,ValueError,TypeError) as exc:
            archive.writestr('diagnostics/transactions/read-error.txt',str(exc))
        # SetupAPI is particularly useful for driver installation failures.
        setupapi = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'INF/setupapi.dev.log'
        if sys.platform == 'win32' and setupapi.exists():
            with setupapi.open('rb') as stream:
                stream.seek(max(0, setupapi.stat().st_size - 512000))
                archive.writestr('diagnostics/setupapi-tail.log', stream.read())
    return str(destination)
