"""Local factory transaction discovery and accounted temporary-state cleanup.

No device access at import/discovery. Recovery re-plans from current bytes;
it never replays a request with an unknown outcome.
"""
import json
import os
from pathlib import Path
import re
from . import checkpointworker, nameworker, nativebuild, worker

FINISHED = {'AWAITING_RELOAD', 'LOADED', 'COMPLETE'}


# Retained import for historical explicit recovery callers and diagnostics.
from .requestcleanup import supersede_temporary


def prewrite_temporary_conflict(state):
    """A fresh restore stopped on shared names before any changing worker."""
    if (state.get('mode')!='factory_reset' or state.get('phase')!='NEEDS_REVIEW'
            or state.get('failed_during') not in ('READING','PLANNED','PREFLIGHT_VERIFIED')
            or state.get('resume_from')):
        return False
    if state.get('error') not in {
        'Existing temporary state needs recovery: '+name for name in
        ('lut-names-staged.so','a7c2.names.request','a7c2.names.result')
    } | {'相机执行插件仍存在，不能在执行期间覆盖；本次尚未恢复写入，请结束连接后完整断电再重试'}:return False
    outstanding=set()
    for event in state.get('journal',[]):
        kind=event.get('event','')
        if kind.endswith('native_intent') and event.get('mode')!=0:return False
        if kind.endswith('native_stage_intent'):
            if event.get('mode')!=0:return False
            outstanding.add((kind[:-len('stage_intent')],event.get('stage')))
        elif kind.endswith('native_cleanup_verified'):
            outstanding.discard((kind[:-len('cleanup_verified')],event.get('stage')))
    return not outstanding


def connection_failed_before_restore(state):
    return (state.get('mode')=='factory_reset' and state.get('phase')=='NEEDS_REVIEW'
            and state.get('failed_during')=='READING' and state.get('journal')==[]
            and not state.get('identity') and not state.get('resume_from'))


def chain(folder):
    result, seen = [], set()
    while folder:
        root = Path(folder).resolve()
        if root in seen:
            raise ValueError('Recovery transaction ancestry contains a loop')
        seen.add(root)
        state = json.loads((root / 'direct.private.json').read_text(encoding='utf-8'))
        if state.get('mode') != 'factory_reset':
            raise ValueError('Not a factory recovery transaction')
        result.append((root, state))
        folder = state.get('resume_from')
    return list(reversed(result))


def pending(work_root, preferred=None):
    """Find the latest meaningful transaction per body, ignoring read-only failures.

    Old records are evidence for a restore, never a precondition: one that
    cannot be read or attributed is skipped (and kept), so the restore button
    re-plans from the connected camera instead of stopping on stale state.
    """
    paths = set(Path(work_root).glob('*/direct.private.json'))
    if preferred and Path(preferred, 'direct.private.json').is_file():
        paths.add(Path(preferred, 'direct.private.json'))
    rows = []
    for path in paths:
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            print('本地记录无法读取，未用于自动续接（记录保留）：' + str(path), flush=True)
            continue
        if not isinstance(state, dict):
            continue
        if state.get('mode') != 'factory_reset' or not state.get('identity'):
            continue
        journal = state.get('journal', [])
        stages = [i for i, r in enumerate(journal) if r.get('event') == 'native_stage_intent']
        unfinished_native = bool(stages) and not any(r.get('event') == 'native_cleanup_verified' for r in journal[stages[-1] + 1:])
        meaningful = (state.get('phase') in FINISHED or bool(state.get('resume_from')) or
                      unfinished_native or any(r.get('event') == 'native_intent' and r.get('mode') in (1, 2) for r in journal))
        if not meaningful:
            continue
        identity = state['identity']
        key = (identity.get('model'), identity.get('serial_sha256') or identity.get('usb_serial_sha256'))
        if not all(key):
            print('恢复记录缺少机身身份，未用于自动续接（记录保留）：' + str(path), flush=True)
            continue
        rows.append((path.stat().st_mtime_ns, str(path), key, path.parent.resolve(), state))
    latest = {}
    for row in sorted(rows):
        latest[row[2]] = row
    # LOADED + verified RO is already a completed device recovery. Physical
    # photo acceptance remains separate; it must not keep hijacking future
    # Restore clicks after the owner installs other features again.
    active = [r for r in latest.values() if not (
        r[4].get('phase') == 'COMPLETE' or
        (r[4].get('phase') == 'LOADED' and r[4].get('readonly_after_reload_verified') is True))]
    if preferred:
        selected = Path(preferred).resolve()
        for row in active:
            try:
                ancestry = [root for root, _ in chain(row[3])]
            except (OSError, ValueError):
                ancestry = [row[3]]
            if selected in ancestry:
                return row[3], row[4]
    if len(active) > 1:
        # Which body is connected is unknown until USB opens; a fresh restore
        # binds to the connected body and re-plans from its current bytes.
        print('有多台机身的未完成恢复记录（均保留）；本次按当前连接的相机重新生成恢复计划：' +
              '; '.join(str(r[3]) for r in active), flush=True)
        return None
    return (active[0][3], active[0][4]) if active else None


def known_programs(current, history):
    """Every previously attempted window must be exactly old or target bytes."""
    for root, state in history:
        for build in state.get('program_builds', []):
            path = Path(build['path'])
            if path.parent.resolve() != (root / 'worker').resolve():
                raise ValueError('Program evidence is outside its transaction')
            text = path.with_suffix('.private.h').read_text(encoding='ascii')
            arrays = {(kind, int(i)): bytes(map(int, values.split(','))) for kind, i, values in
                      re.findall(r'static const u8 (old|new)_(\d+)\[\]=\{([\d,]+)\};', text)}
            rows = re.findall(r'\{(\d+)UL,(\d+),([01]),old_(\d+),new_(\d+)\}', text)
            if len(rows) != build['windows']:
                raise ValueError('Incomplete recovery window evidence')
            for at, size, chip, old, new in rows:
                a, b = arrays['old', int(old)], arrays['new', int(new)]
                image = current[worker.NAMES[int(chip)]]
                if len(image) != build['sizes'][int(chip)] or len(a) != int(size) or len(b) != int(size):
                    raise ValueError('Recovery program layout differs')
                if image[int(at):int(at) + int(size)] not in (a, b):
                    raise ValueError('程序窗口包含未确认的字节；保留记录，不能自动重放写入')


def outcome(raw, result, mode, state, camera, *, allow_completed_name_mount_busy=False):
    """Require a complete native report with successful cleanup/remount.

    An operation may have failed; re-planning handles its actual current bytes.
    Cleanup/remount failures and incomplete reports require inspection.
    """
    if result == 'checkpoint.program.result':
        if len(raw) != 240:
            raise ValueError('Incomplete native program result')
        v = worker.REPORT.unpack_from(raw)
        sizes = [b['sizes'] for b in state.get('program_builds', [])]
        if (v[:3] != (b'A7IRP001', 1, mode) or not 1 <= v[3] <= 9
                or any(v[i] for i in (6, 7, 8, 9, 10)) or v[11] <= 0
                or list(v[14:16]) not in sizes):
            raise ValueError('Native program did not establish a clean completed outcome')
    elif result == 'checkpoint.names.result' and mode == 5:
        # Backup cleanup only deletes stale project backups; any complete
        # report that restored the read-only mount is accounted for.
        if len(raw) != nameworker.REPORT.size:
            raise ValueError('Incomplete backup cleanup result')
        v = nameworker.REPORT.unpack(raw)
        if v[:3] != (b'A7NMR001', 1, 5) or not 1 <= v[3] <= 9 or any(v[i] for i in (6, 7, 8, 9, 10)) or v[11] <= 0:
            raise ValueError('Backup cleanup remount is unconfirmed')
    elif result == 'checkpoint.names.result':
        if len(raw) != nameworker.REPORT.size:
            raise ValueError('Incomplete native name result')
        v = nameworker.REPORT.unpack(raw)
        build = state.get('inverse_name_build') or {}
        if allow_completed_name_mount_busy and checkpointworker.names_completed_mount_busy(raw, mode, build):
            return {'readonly_deferred_busy': True}
        if (v[:3] != (b'A7NMR001', 1, mode) or not 1 <= v[3] <= 9 or v[4] != build.get('count')
                or any(v[i] for i in (6, 7, 8, 9, 10, 13, 14, 17)) or v[11] <= 0
                or any(n > v[4] for n in v[12:17])):
            raise ValueError('Native name cleanup/remount is unconfirmed')
    elif result == 'a7c2.runtime.result':
        camera.core.parse_native('runtime', raw)
    elif result == 'a7c2.wbi.result':
        camera.core.parse_native('wbi', raw, mode)
    else:
        raise ValueError('Unsupported outstanding native operation: ' + str(result))
    return {}


def completion_evidence(camera, history, root, state, intent, later):
    """An empty /tmp alone does not establish that execution has finished."""
    if any(r.get('event') == 'native_result_verified' for r in later):
        return 'recorded-native-completion'
    for _, entry in history:
        for event in entry.get('journal', []):
            if (event.get('event') in ('pending_temporary_cleanup_verified', 'failed_name_temporary_cleanup_verified')
                    and event.get('previous_workspace', event.get('failed_workspace')) == str(root)):
                return 'recorded-temporary-cleanup'
    # Names/runtime/WBI modes run at most once per direct transaction.
    # Program batches share one result name, so an older batch report cannot
    # prove completion of the most recent program invocation.
    if intent['result'] != 'checkpoint.program.result':
        matching = set()
        for path in (root / 'evidence').glob('*.bin'):
            raw = path.read_bytes()
            try:
                outcome(raw, intent['result'], intent['mode'], state, camera)
            except (ValueError, KeyError, IndexError):
                continue
            matching.add(raw)
        if len(matching) == 1:
            return 'complete-saved-native-report'
    old_boot = state.get('source_boot_id', '').strip()
    if old_boot:
        raw = camera.read('/proc/sys/kernel/random/boot_id', True)
        boot = raw.decode('ascii', errors='replace').strip() if raw else ''
        if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', boot) and boot != old_boot:
            return 'new-camera-boot'
    raise ValueError('临时文件和结果均缺失，尚无执行完成或新开机证据；不会重新写入，请保留事务记录')


def cleanup(camera, history, record, save_raw, *, allow_completed_name_mount_busy=False):
    """Account for the most recent invocation before removing exact owned /tmp files."""
    outstanding = None
    for root, state in history:
        journal = state.get('journal', [])
        stages = [i for i, r in enumerate(journal) if r.get('event') == 'native_stage_intent']
        if stages:
            index = stages[-1]
            later = journal[index + 1:]
            outstanding = None if any(r.get('event') == 'native_cleanup_verified' for r in later) else (root, state, journal[index], later)
    if outstanding is None:
        return
    root, state, intent, later = outstanding
    stage, request, result = intent['stage'], intent.get('request'), intent['result']
    if stage != 'checkpoint.staged.so' or request not in (None, 'checkpoint.program.request', 'checkpoint.names.request', 'a7c2.wbi.request'):
        raise ValueError('Unsupported outstanding recovery namespace')
    if result == 'checkpoint.program.result':
        blobs = [Path(b['path']).read_bytes() for b in state.get('program_builds', [])]
    elif result == 'checkpoint.names.result' and intent.get('mode') == 5:
        blobs = [Path(state['purge_build']['path']).read_bytes()]
    elif result == 'checkpoint.names.result':
        blobs = [Path(state['inverse_name_build']['path']).read_bytes()]
    else:
        asset = 'runtime.so' if result == 'a7c2.runtime.result' else 'wbi.so'
        blobs = [(nativebuild.ROOT / 'src/fl23/assets' / asset).read_bytes()]
    names = [stage, *([request] if request else []), 'libJit.so', result]
    if result == 'a7c2.runtime.result':
        names.append('a7c2.probe.result')
    actual = {n: camera.temp_read(n, True) for n in names}
    if actual['libJit.so'] is not None:
        raise ValueError('执行插件仍存在，不能确认相机端已结束；不会删除或重试')
    if actual[stage] is not None and actual[stage] not in blobs:
        raise ValueError('Temporary worker bytes do not match the recorded transaction')
    if request and actual[request] not in (None, bytes.fromhex(intent['contents_hex'])):
        raise ValueError('Temporary request differs from the recorded transaction')
    executed = any(r.get('event') == 'native_intent' for r in later)
    raw = actual[result]
    metadata = {}
    if executed:
        if raw is None:
            if any(value is not None for value in actual.values()):
                raise ValueError('相机端结果报告缺失，暂时不能确认执行结果；保留临时文件，未重新写入')
            proof = completion_evidence(camera, history, root, state, intent, later)
            record('previous_temporary_namespace_empty', previous_workspace=str(root), completion_evidence=proof)
            return
        save_raw('recovered-' + result, raw)
        metadata=outcome(raw, result, intent['mode'], state, camera,
                         allow_completed_name_mount_busy=allow_completed_name_mount_busy)
        if result == 'a7c2.runtime.result' and actual['a7c2.probe.result'] is not None:
            camera.core.parse_native('probe', actual['a7c2.probe.result'])
    elif raw is not None:
        raise ValueError('Unexpected result exists before recorded execution intent')
    if camera.read('/etc/ld.so.preload', True):
        raise ValueError('Existing preload requires inspection')
    record('pending_native_outcome_accounted', previous_workspace=str(root), result=result, executed=executed, **metadata)
    # Keep the result until last: interruption during cleanup can still be
    # accounted for from that complete report on the next manual run.
    for name in [n for n in names if n != result] + [result]:
        # Recheck exact captured bytes immediately before removal.
        if camera.temp_read(name, True) != actual[name]:
            raise ValueError('Temporary state changed during recovery; no retry')
        if actual[name] is not None:
            camera.temp_remove(name)
        if camera.temp_read(name, True) is not None:
            raise ValueError('Temporary cleanup incomplete: ' + name)
    record('pending_temporary_cleanup_verified', previous_workspace=str(root))
    return metadata
