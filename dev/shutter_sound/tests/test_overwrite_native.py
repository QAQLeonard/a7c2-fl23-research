"""Execute the real alternating-audio / atomic-CSV update worker offline."""
from pathlib import Path
import struct
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import boot_sound,files_worker
from verify_probe import execute

DIRECTORY='/usr/share/avsystemsound'
CSV_PATH=DIRECTORY+'/custom.txt'
TMP=[DIRECTORY+'/.a7c2-sound-audio.tmp',DIRECTORY+'/.a7c2-sound-csv.tmp']


@pytest.mark.parametrize('old_name,new_name',[
    ('custom-shutter.bin','custom-shutter-a.bin'),('custom-shutter-a.bin','custom-shutter-b.bin'),
    ('custom-shutter-b.bin','custom-shutter-a.bin')])
@pytest.mark.parametrize('fault',['none','audio_write','csv_write','csv_rename','readonly','recorded_temp','changed_temp'])
def test_atomic_sound_publication(tmp_path,old_name,new_name,fault):
    old_audio=bytes(64);audio=bytes([0,3])*64
    old_csv=boot_sound.CSV.replace(b'custom-shutter.bin',old_name.encode()).replace(b'0xEC0',b'0x40')
    csv=boot_sound.CSV.replace(b'custom-shutter.bin',new_name.encode()).replace(b'0xEC0',b'0x80')
    path=DIRECTORY+'/'+new_name;old_path=DIRECTORY+'/'+old_name
    temporary=[b'previous audio bytes',b'previous CSV bytes'] if fault in ('recorded_temp','changed_temp') else None
    worker=files_worker.build(audio,csv,tmp_path/'worker',audio_path=path,previous_csv=old_csv,temporary_files=temporary)
    files={old_path:old_audio,CSV_PATH:old_csv,DIRECTORY+'/SysSound.bin':b'unrelated'}
    if temporary is not None:
        files.update(zip(TMP,temporary))
        if fault=='changed_temp':files[TMP[0]]=b'changed after capture'
    handles={};readonly=True;events=[]
    def string(cpu,p):return bytes(cpu.mem_read(p,256)).split(b'\0',1)[0].decode()
    def syscall(cpu,no,a):
        nonlocal readonly
        allowed={path,CSV_PATH,*TMP,DIRECTORY,'/tmp/jiritsu/a7c2.install.request','/proc/mounts'}
        if no==56:
            name,flags=string(cpu,a[1]),a[2]
            if name not in allowed:return None
            if name==DIRECTORY:assert flags==0x8c000
            elif name in (path,CSV_PATH,*TMP):assert flags in (0x88000,0x880c1)
            if flags&0x40:
                if name in files:return -17
                files[name]=b''
            elif name not in files and name not in (DIRECTORY,'/tmp/jiritsu/a7c2.install.request','/proc/mounts'):return -2
            fd=max([999,*handles])+1;handles[fd]=[name,0,False];return fd
        if no==40:
            readonly=bool(a[3]&1)
            return -16 if readonly and fault=='readonly' else 0
        if no==35:
            name=string(cpu,a[1])
            if name not in TMP:return None
            files.pop(name,None);return 0
        if no==38:
            old,new=string(cpu,a[1]),string(cpu,a[3])
            if new==CSV_PATH:
                if fault=='csv_rename':return -5
                assert files[path]==audio and files[old_path]==old_audio
            files[new]=files.pop(old);events.append(('rename',new));return 0
        if not a or a[0] not in handles:return None
        name,pos,closed=handles[a[0]];assert not closed
        if no==57:handles[a[0]][2]=True;return 0
        if no==80:
            st=bytearray(128);struct.pack_into('<QQI',st,0,15,123,0o100644);struct.pack_into('<Q',st,48,len(files[name]));cpu.mem_write(a[1],bytes(st));return 0
        if no in (63,67):
            if no==67:pos=a[3]
            if name=='/tmp/jiritsu/a7c2.install.request':raw=struct.pack('<8sII',b'A7SFQ001',1,0)
            elif name=='/proc/mounts':raw=b'/dev/nflasha15 /usr ext2 '+(b'ro' if readonly else b'rw')+b',sync 0 0\n'
            else:raw=files[name]
            raw=raw[pos:pos+a[2]]
            if raw:cpu.mem_write(a[1],raw)
            if no==63:handles[a[0]][1]+=len(raw)
            return len(raw)
        if no==64:
            if (fault=='audio_write' and name==TMP[0]) or (fault=='csv_write' and name==TMP[1]):return -28
            files[name]+=bytes(cpu.mem_read(a[1],a[2]));return a[2]
        if no==82:return 0
        raise AssertionError('Unexpected sound-update syscall '+str(no))
    result=execute(worker,b'',decode=files_worker.parse,extra_syscall=syscall)
    assert all(h[2] for h in handles.values())
    assert files[old_path]==old_audio and files[DIRECTORY+'/SysSound.bin']==b'unrelated'
    if files[CSV_PATH]==csv:assert files[path]==audio
    else:assert files[CSV_PATH]==old_csv and files[old_path]==old_audio
    if fault in ('none','recorded_temp'):
        assert result['native_success'] and readonly and files[CSV_PATH]==csv
        assert events==[('rename',path),('rename',CSV_PATH)]
    else:assert not result['native_success']
