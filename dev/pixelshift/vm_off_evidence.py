"""Check the isolated-VM native OFF and two-file Backup roundtrip artifacts.

This reads artifacts only. It does not install, connect to a camera, execute
firmware, select a saved file for recovery, or establish physical boot safety.
"""
import argparse
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
import struct
import sys


@dataclass(frozen=True)
class SavedCopy:
    count: int
    value: int


def read_saved_copy(path):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src/fl23/vendor'))
    from pmca.backup import BackupFile
    raw=Path(path).read_bytes()
    backup=BackupFile(io.BytesIO(raw))
    data=backup.getProperty(0x02cf02cf).data
    if backup.revision!=4 or len(data)!=1:
        raise ValueError('Expected the native BK4 one-byte Pixel Shift setting')
    # Original backup.ko Data_GetCount/Data_SetCount use header+2C.
    return SavedCopy(struct.unpack_from('<I',raw,0x2c)[0],data[0])


def clean(raw):
    text=raw.decode('utf-8',errors='replace') if isinstance(raw,bytes) else raw
    text=text.replace('\r\n','\n')
    return re.sub(r'\[\s*\d+\.\d+\] (?:UDIF:|\[K\])[^\n]*\n','',text)


def loaded_value(log):
    text=clean(log)
    match=re.search(r'^BACKUP_DUMP id=0x2cf02cf datasize=1\nBACKUP_DUMP read=1\n00000000: ([0-9a-f]{2})\nBACKUP_DUMP_DONE shown=1$',text,re.M)
    if not match:raise ValueError('Missing complete original Backup readback')
    return int(match[1],16)


def validate(native_log,primary,secondary,reload_log,control_log):
    text=clean(native_log)
    required=[
        'LIVE_BASELINE mode=0 companion=0 enqueue=1',
        'VIRTUAL_BACKUP_INPUT write=1 read=1 value=1',
        'VIRTUAL_BACKUP_INPUT_SYNC status=0 file_byte=1',
        'LIVE_NATIVE_ON_RETURN mode=1 companion=0',
        'VIRTUAL_BACKUP_AFTER_NATIVE_ON read=1 value=1',
        'LIVE_NATIVE_OFF_RETURN mode=0 companion=0',
        'LIVE_NATIVE_OFF_LATER mode=0 companion=0',
        'VIRTUAL_BACKUP_AFTER_OFF read=1 value=1 flash_sync_tested=0',
        'VIRTUAL_EXPLICIT_OFF write=1 sync=0 read=1 value=0 file_byte=1',
        'LIVE_PROBE_DONE',
    ]
    previous=-1
    for line in required:
        matches=list(re.finditer('^'+re.escape(line)+'$',text,re.M))
        if len(matches)!=1 or matches[0].start()<=previous:
            raise ValueError('Missing native test stage: '+line.split()[0])
        previous=matches[0].start()
    if not (primary.value==1 and secondary.value==0 and primary.count<secondary.count):
        raise ValueError('Expected the retained older ON copy and newer native OFF copy')
    for name,copy in [('bin',primary),('bak',secondary)]:
        pattern=r'^FILE_STATE stage=off path=/setting/Backup\.'+name+r' .*?count='+str(copy.count)+r' ptr=\d+ value='+str(copy.value)+r'$'
        if not re.search(pattern,text,re.M):raise ValueError('Native file observations differ from exported BK4 copy: '+name)
    if loaded_value(reload_log)!=0 or loaded_value(control_log)!=1:
        raise ValueError('Fresh original loader did not distinguish OFF copy from ON control')
    for marker in ('FRESH_AP_MODE','FRESH_AP_COMPANION'):
        if not re.search(r'^'+marker+r'\nREADMEM [^\n]+ bytes=4\n[0-9a-f]{16}: 00 00 00 00$',clean(reload_log),re.M):
            raise ValueError('Fresh AP runtime OFF readback is incomplete: '+marker)
    return dict(schema='a7c2-vm-native-off-evidence/1',native_ap_on_off_returned=True,
        setting_only_left_backup_on=True,explicit_native_backup_write_and_sync_verified=True,
        primary_saved_copy=dict(count=primary.count,value=primary.value),
        secondary_saved_copy=dict(count=secondary.count,value=secondary.value),
        fresh_native_backup_loader_off_verified=True,opposite_saved_input_control_verified=True,
        fresh_ap_runtime_off_observed=True,
        saved_on_boot_failure_reproduced=False,early_boot_off_guard_implemented=False,
        native_saved_store_roundtrip_in_vm_verified=True,
        sensor_centering_or_physical_camera_recovery_verified=False,
        four_frame_scheduler_or_exposure_verified=False,camera_installer=False,
        validation_camera_io=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('native-log','primary','secondary','reload-log','control-log','output'):
        parser.add_argument('--'+arg,type=Path,required=True)
    args=parser.parse_args()
    result=validate(args.native_log.read_bytes(),read_saved_copy(args.primary),
        read_saved_copy(args.secondary),args.reload_log.read_bytes(),args.control_log.read_bytes())
    with args.output.open('x',encoding='utf-8') as handle:json.dump(result,handle,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
