"""Execute the compiled resource worker with a synthetic filesystem and faults."""
from hashlib import sha256
from pathlib import Path
import struct
import sys
import pytest
from looktool import resourceworker,voicelock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'dev/shutter_sound'))
from verify_probe import execute


class Disk:
    def __init__(self,kind='voice'):
        self.kind=kind;self.directory,self.names=resourceworker.layout(kind)
        self.data={self.directory+'/'+n:(n+' original').encode() for n in self.names}
        self.data[self.directory+'/unrelated.bin']=b'untouched'
        self.readonly=True;self.events=[];self.fault=None
    def run(self,worker,mode=0,index=0,offset=0,payload=None,prefix=None,loaded=True):
        request=resourceworker.REQUEST.pack(b'A7RSQ001',mode,index,offset,len(payload or b''),0,prefix or bytes(32))
        chunk='/tmp/jiritsu/resource.chunk'
        if payload is not None:self.data[chunk]=payload
        handles={};injected=set()
        def string(cpu,at):return bytes(cpu.mem_read(at,256)).split(b'\0',1)[0].decode()
        def syscall(cpu,no,a):
            if no==56:
                path,flags=string(cpu,a[1]),a[2]
                if not (path.startswith(self.directory+'/') or path in (self.directory,'/tmp/jiritsu/a7c2.install.request',chunk,'/proc/mounts')):return None
                if flags==0x200c1:
                    assert not self.readonly
                    if path in self.data:return -17
                    self.data[path]=b'';self.events.append(('create',path))
                elif path not in self.data and path not in (self.directory,'/tmp/jiritsu/a7c2.install.request','/proc/mounts'):return -2
                fd=1000+len(handles);handles[fd]=[path,0,False,flags];return fd
            if no==40:
                assert string(cpu,a[1])=='/usr'
                ro=bool(a[3]&1);self.events.append(('mount',ro))
                if self.fault=='remount_ro' and ro:return -5
                self.readonly=ro;return 0
            if no==43:
                fs=bytearray(128);struct.pack_into('<7Q',fs,0,0xef53,1024,900000,800000,
                    0 if self.fault=='space' else 800000,1000,900);cpu.mem_write(a[1],bytes(fs));return 0
            if no==35:
                path=string(cpu,a[1])
                if not path.startswith(self.directory+'/'):return None
                assert not self.readonly
                if path not in self.data:return -2
                self.events.append(('unlink',path));del self.data[path];return 0
            if no==38:
                old,new=string(cpu,a[1]),string(cpu,a[3]);assert not self.readonly
                if self.fault=='rename':return -5
                self.events.append(('rename',old,new));self.data[new]=self.data.pop(old);return 0
            if not a or a[0] not in handles:return None
            path,pos,closed,flags=handles[a[0]];assert not closed
            if no==57:handles[a[0]][2]=True;return 0
            if no==80:
                st=bytearray(128);struct.pack_into('<QQII',st,0,15,99,0o100644,1)
                struct.pack_into('<q',st,48,len(self.data[path]));struct.pack_into('<Q',st,64,8)
                cpu.mem_write(a[1],bytes(st));return 0
            if no in (63,67):
                value=(request if path=='/tmp/jiritsu/a7c2.install.request' else
                    b'/dev/nflasha15 /usr ext2 '+(b'ro' if self.readonly else b'rw')+b',sync 0 0\n'
                    if path=='/proc/mounts' else self.data[path])
                at=a[3] if no==67 else pos;value=value[at:at+a[2]]
                if no==63:handles[a[0]][1]+=len(value)
                cpu.mem_write(a[1],value);return len(value)
            if no==68:
                assert not self.readonly and '/.a7c2-restore-' in path
                if self.fault=='short_write' and 'write' in injected:return -5
                count=a[2]//2 if self.fault=='short_write' else a[2];injected.add('write')
                value=bytes(cpu.mem_read(a[1],count));at=a[3]
                self.data[path]=self.data[path][:at]+value+self.data[path][at+count:]
                self.events.append(('write',path,at,count));return count
            if no==82:
                if self.fault=='fsync' and '/.a7c2-restore-' in path:return -5
                return 0
            raise AssertionError((no,path))
        headers={at:code if loaded else bytes(len(code)) for at,code in resourceworker.guards(self.kind)}
        raw=execute(worker,b'',extra_headers=headers,extra_syscall=syscall,
            extra_outputs={'/tmp/jiritsu/a7c2.runtime.result':0x241},
            result_path='/tmp/jiritsu/a7c2.runtime.result',decode=lambda raw:raw)
        assert all(v[2] for v in handles.values())
        assert self.data[self.directory+'/unrelated.bin']==b'untouched'
        return resourceworker.parse(raw,self.kind,mode)


def workers(tmp_path,disk,targets=None):
    reader=resourceworker.build(disk.kind,tmp_path/'inspect')
    before=disk.run(reader)
    writer=resourceworker.build(disk.kind,tmp_path/'writer',inventory=before,targets=targets)
    return reader,writer,before


def test_delete_audio_preserves_all_indices_and_unrelated_files(tmp_path):
    disk=Disk();reader,writer,before=workers(tmp_path,disk)
    for i,name in enumerate(disk.names):
        if name.endswith('.bin'):disk.run(writer,1,i)
    result=disk.run(reader)
    assert all(r['status']==(-2 if r['name'].endswith('.bin') else 0) for r in result['files'])
    assert disk.readonly


def test_loaded_disable_guard_is_mandatory_before_deletion(tmp_path):
    disk=Disk();_,writer,_=workers(tmp_path,disk);before=dict(disk.data)
    with pytest.raises(ValueError,match='status=-84'):disk.run(writer,1,loaded=False)
    assert disk.data==before and not disk.events


def test_changed_file_is_not_deleted_after_preflight(tmp_path):
    disk=Disk();_,writer,_=workers(tmp_path,disk)
    path=disk.directory+'/'+disk.names[0];disk.data[path]=b'changed after snapshot'
    with pytest.raises(ValueError,match='status=-116'):disk.run(writer,1)
    assert disk.data[path]==b'changed after snapshot' and not disk.events


def test_chunk_restore_publishes_only_complete_hash_verified_file(tmp_path):
    disk=Disk();name=disk.names[0];path=disk.directory+'/'+name;original=disk.data.pop(path)
    target=b'new audio '*17;targets={name:dict(bytes=len(target),sha256=sha256(target).hexdigest())}
    _,writer,_=workers(tmp_path,disk,targets)
    first=target[:73];disk.run(writer,2,payload=first)
    assert path not in disk.data
    with pytest.raises(ValueError,match='status=-84'):disk.run(writer,3)
    assert path not in disk.data
    disk.run(writer,2,offset=len(first),payload=target[len(first):],prefix=sha256(first).digest())
    assert path not in disk.data
    disk.run(writer,3)
    assert disk.data[path]==target and disk.readonly


@pytest.mark.parametrize('fault',['short_write','space','fsync','rename','remount_ro'])
def test_faults_never_publish_incomplete_voice_audio(tmp_path,fault):
    disk=Disk();name=disk.names[0];path=disk.directory+'/'+name;old=disk.data[path]
    target=b'replacement'*10;targets={name:dict(bytes=len(target),sha256=sha256(target).hexdigest())}
    _,writer,_=workers(tmp_path,disk,targets);disk.fault=fault
    if fault=='rename':
        disk.fault=None;disk.run(writer,2,payload=target);disk.fault='rename'
        with pytest.raises(ValueError):disk.run(writer,3)
    else:
        with pytest.raises(ValueError):disk.run(writer,2,payload=target)
    assert disk.data[path]==old
    if fault!='remount_ro':assert disk.readonly


def test_wrong_prefix_cannot_append_to_a_stale_stage(tmp_path):
    disk=Disk();name=disk.names[0];target=b'abcdefgh';targets={name:dict(bytes=8,sha256=sha256(target).hexdigest())}
    _,writer,_=workers(tmp_path,disk,targets);disk.run(writer,2,payload=target[:4])
    with pytest.raises(ValueError):disk.run(writer,2,offset=4,payload=target[4:],prefix=bytes(32))
    assert disk.data[disk.directory+'/.a7c2-restore-'+name+'.tmp']==target[:4]


def test_abandoned_stage_cleanup_checks_its_captured_hash(tmp_path):
    disk=Disk();stage=disk.directory+'/.a7c2-restore-'+disk.names[0]+'.tmp'
    disk.data[stage]=b'old staged bytes';_,writer,_=workers(tmp_path,disk)
    disk.data[stage]=b'changed staged bytes'
    with pytest.raises(ValueError,match='status=-116'):disk.run(writer,4)
    assert disk.data[stage]==b'changed staged bytes'


def test_offset_overflow_is_rejected_without_creating_a_stage(tmp_path):
    disk=Disk();name=disk.names[0];targets={name:dict(bytes=8,sha256=sha256(b'12345678').hexdigest())}
    _,writer,_=workers(tmp_path,disk,targets)
    with pytest.raises(ValueError,match='status=-22'):disk.run(writer,2,offset=(1<<64)-1,payload=b'12')
    assert disk.directory+'/.a7c2-restore-'+name+'.tmp' not in disk.data


def test_one_mib_chunk_uses_bounded_native_writes_without_publishing(tmp_path):
    disk=Disk();name=disk.names[0];path=disk.directory+'/'+name;old=disk.data[path]
    payload=bytes(range(256))*4096
    target=payload+b'end';targets={name:dict(bytes=len(target),sha256=sha256(target).hexdigest())}
    _,writer,_=workers(tmp_path,disk,targets)
    result=disk.run(writer,2,payload=payload)
    assert result['progress_bytes']==1024*1024 and disk.data[path]==old
    assert disk.data[disk.directory+'/.a7c2-restore-'+name+'.tmp']==payload
    assert max(event[3] for event in disk.events if event[0]=='write')<=65536


def test_only_resource_chunk_mailbox_accepts_one_mib():
    from unittest.mock import Mock
    from looktool.devicesession import Camera
    camera=Camera();camera.programs_pinned=True;camera.service_only=False;camera.link=Mock()
    camera.temp_write('resource.chunk',bytes(1024*1024))
    with pytest.raises(ValueError):camera.temp_write('resource.chunk',bytes(1024*1024+1))
    with pytest.raises(ValueError):camera.temp_write('libJit.so',bytes(65537))
