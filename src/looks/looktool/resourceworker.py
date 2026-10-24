"""Fixed resource transactions: native inventory, deletion and chunked restore."""
from hashlib import sha256
import json
from pathlib import Path
import struct
from . import nativebuild,voicelock
from .devicesession import invoke

CHUNK=1024*1024
VOICE_NAMES=tuple(language+suffix for language in ('english','french','german','italian','japanese',
    'korean','portuguese','simplifiedchinese','spanish','traditionalchinese') for suffix in ('.bin','_info.txt'))
SOUND_NAMES=('custom.txt','custom-shutter.bin','custom-shutter-a.bin','custom-shutter-b.bin',
             '.a7c2-sound-audio.tmp','.a7c2-sound-csv.tmp')
INFO=struct.Struct('<qQQ32s')
REQUEST=struct.Struct('<8sIIQII32s')


def layout(kind):
    if kind=='voice':return '/usr/share/screenreader',VOICE_NAMES
    if kind=='sound':return '/usr/share/avsystemsound',SOUND_NAMES
    raise ValueError('Unknown resource namespace')


def guards(kind,*,menu=True):
    if kind=='voice':
        result=[(at,new) for at,old,new in voicelock.WINDOWS]
        # The AP's data PT_LOAD has a 0x10000 file-to-virtual displacement.
        if menu:result.extend((at+0x10000,new) for at,old,new in voicelock.MENU_WINDOWS)
        return result
    import sys
    sys.path.insert(0,str(nativebuild.ROOT/'src/shutter_sound'))
    import boot_sound
    return [(at,old) for at,old,new in boot_sound.expected_windows()]


def parse(raw,kind,mode):
    directory,names=layout(kind);count=len(names)
    if len(raw)!=56+2*count*INFO.size:raise ValueError('Incomplete resource transaction report')
    magic,version,actual,status,readonly,cleanup,index,changed,progress=struct.unpack_from('<8sII3qIIQ',raw)
    if (magic,version,actual)!=(b'A7RSR001',1,mode) or status or readonly or cleanup:
        if kind=='voice' and mode==0 and status==-84:
            raise ValueError('语音指南关闭限制尚未按磁盘版本加载。请按提示完整断电重开，再继续资源操作；尚未删除或写回语音文件。')
        raise ValueError('资源操作未完成：status=%s，readonly=%s，cleanup=%s'%(status,readonly,cleanup))
    if index>=count:raise ValueError('Resource result index differs')
    lists=[]
    for start in (56,56+count*INFO.size):
        rows=[]
        for i,name in enumerate(names):
            state,size,allocated,digest=INFO.unpack_from(raw,start+i*INFO.size)
            if state not in (0,-2):raise ValueError('Resource stat/hash failed: '+name)
            rows.append(dict(name=name,status=state,bytes=size,allocated_bytes=allocated,sha256=digest.hex()))
        lists.append(rows)
    return dict(mode=mode,index=index,resource_kind=kind,resource_file=names[index] if mode else None,
                changed=changed,progress_bytes=progress,
                files=lists[0] if not mode else [],stages=lists[1] if not mode else [])


def build(kind,folder,*,inventory=None,targets=None,zig=None,menu=True):
    directory,names=layout(kind);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    cbytes=lambda b:'{'+','.join(map(str,b))+'}'
    quote=lambda s:json.dumps(s)
    info=lambda r:'{'+str(r['status'])+','+str(r['bytes'])+'UL,'+str(r['allocated_bytes'])+'UL,'+cbytes(bytes.fromhex(r['sha256']))+'}'
    absent=[dict(status=-2,bytes=0,allocated_bytes=0,sha256='00'*32) for _ in names]
    before=inventory or dict(files=absent,stages=absent)
    spec=guards(kind,menu=menu);lines=[f'#define FILE_COUNT {len(names)}',
        'static const char resource_directory[]='+quote(directory)+';',
        'static const char *paths[]={'+','.join(quote(directory+'/'+n) for n in names)+'};',
        'static const char *staging[]={'+','.join(quote(directory+'/.a7c2-restore-'+n+'.tmp') for n in names)+'};',
        'static const struct Info expected_files[]={'+','.join(info(r) for r in before['files'])+'};',
        'static const struct Info expected_stages[]={'+','.join(info(r) for r in before['stages'])+'};',
        'static const u8 deletable[]={'+','.join('1' if kind=='sound' or n.endswith('.bin') else '0' for n in names)+'};',
        'static const u64 target_sizes[]={'+','.join(str((targets or {}).get(n,{}).get('bytes',0))+'UL' for n in names)+'};',
        'static const u8 target_hashes[][32]={'+','.join(cbytes(bytes.fromhex((targets or {}).get(n,{}).get('sha256','00'*32))) for n in names)+'};',
        'struct Guard {u64 offset;u32 size;const u8 *bytes;};']
    for i,(at,code) in enumerate(spec):lines.append('static const u8 guard_'+str(i)+'[]='+cbytes(code)+';')
    lines+=['static const struct Guard guards[]={'+','.join('{'+str(at)+'UL,'+str(len(code))+',guard_'+str(i)+'}' for i,(at,code) in enumerate(spec))+'};',
            'static const u32 guard_count='+str(len(spec))+';']
    header=folder/'resources.private.h';header.write_text('\n'.join(lines)+'\n',encoding='ascii')
    path=folder/'resources.so'
    nativebuild.compile_worker(nativebuild.ROOT/'src/looks/native/resource_files.c',header,path,zig,fingerprints=False)
    return path


class Resources:
    def __init__(self,camera,owner,kind):
        self.camera,self.owner,self.kind=camera,owner,kind
        self.directory,self.names=layout(kind)
    def call(self,worker,mode,index=0,offset=0,count=0,prefix=None):
        self.owner.record('resource_operation',result=dict(resource_kind=self.kind,
            resource_file=self.names[index] if mode else None,index=index,mode=mode,
            requested_offset=offset,requested_bytes=count))
        return invoke(self.camera,Path(worker).read_bytes(),stage='lut-runtime-staged.so',
            request='a7c2.install.request',result='a7c2.runtime.result',
            contents=REQUEST.pack(b'A7RSQ001',mode,index,offset,count,0,prefix or bytes(32)),mode=mode,
            decode=lambda raw:parse(raw,self.kind,mode),record=self.owner.record,
            save_raw=lambda raw:self.owner.raw('resources-'+self.kind+'.bin',raw),extras=('a7c2.probe.result',))
    def inspect(self,*,menu=True):
        self.reader=build(self.kind,self.owner.root/('resources-'+self.kind)/'inspect',zig=self.owner.zig,menu=menu)
        return self.call(self.reader,0)
    def delete(self):
        before=self.inspect()
        writer=build(self.kind,self.owner.root/('resources-'+self.kind)/'delete',inventory=before,zig=self.owner.zig)
        for i,row in enumerate(before['stages']):
            if row['status']==0:
                self.owner.raw('abandoned-'+self.kind+'-'+row['name']+'.bin',
                    self.camera.read(self.directory+'/.a7c2-restore-'+row['name']+'.tmp'))
                self.call(writer,4,i)
        for i,row in enumerate(before['files']):
            if row['status']==-2 or self.kind=='voice' and not row['name'].endswith('.bin'):continue
            self.call(writer,1,i)
        after=self.call(self.reader,0)
        if any(r['status']!=-2 for r in after['files'] if self.kind=='sound' or r['name'].endswith('.bin')):
            raise ValueError('Resource deletion did not read back')
        self.owner.record('resource_files_removed',kind=self.kind,files=[r['name'] for r in before['files']
            if r['status']==0 and (self.kind=='sound' or r['name'].endswith('.bin'))])
        return after
    def restore(self,source,targets):
        # Older cleanup candidates have the four speech guards but no gray-menu
        # flags. They must still be able to restore their missing voice files.
        before=self.inspect(menu=False);source=Path(source)
        writer=build(self.kind,self.owner.root/('resources-'+self.kind)/'restore',inventory=before,targets=targets,zig=self.owner.zig,menu=False)
        for i,name in enumerate(self.names):
            target=targets[name];current=before['files'][i];stage=before['stages'][i]
            if current['status']==0 and (current['bytes'],current['sha256'])==(target['bytes'],target['sha256']):
                if stage['status']==0:
                    self.owner.raw('abandoned-voice-'+name+'.bin',self.camera.read(self.directory+'/.a7c2-restore-'+name+'.tmp'))
                    self.call(writer,4,i)
                continue
            offset=0;digest=sha256()
            with (source/name).open('rb') as stream:
                if not stage['status']:
                    prefix=stream.read(stage['bytes']);digest.update(prefix)
                    if len(prefix)==stage['bytes'] and digest.hexdigest()==stage['sha256'] and 0<stage['bytes']<=target['bytes']:
                        offset=stage['bytes']
                    else:
                        self.owner.raw('abandoned-voice-'+name+'.bin',self.camera.read(self.directory+'/.a7c2-restore-'+name+'.tmp'))
                        self.call(writer,4,i);stream.seek(0);digest=sha256()
                while data:=stream.read(CHUNK):
                    self.camera.temp_write('resource.chunk',data)
                    if self.camera.temp_read('resource.chunk')!=data:raise ValueError('Voice chunk staging differs')
                    result=self.call(writer,2,i,offset,len(data),digest.digest())
                    if result['progress_bytes']!=offset+len(data):raise ValueError('Voice chunk progress differs')
                    self.camera.temp_remove('resource.chunk');digest.update(data);offset+=len(data)
                    print('语音文件写回：%s %.1f / %.1f MiB'%(name,offset/1048576,target['bytes']/1048576),flush=True)
                if offset!=target['bytes'] or digest.hexdigest()!=target['sha256']:raise ValueError('Voice source changed during restore')
            self.call(writer,3,i)
            actual=self.camera.read(self.directory+'/'+name)
            if len(actual)!=target['bytes'] or sha256(actual).hexdigest()!=target['sha256']:raise ValueError('Voice full readback differs: '+name)
        self.owner.record('voice_resources_complete_readback_verified',files=list(self.names))


def restore_voice(camera,owner,source):
    from desktopapp import screenreader
    from . import checkpoint
    manifest=screenreader.load(source)
    if manifest.get('identity'):checkpoint.same_body(manifest['identity'],camera.identity)
    Resources(camera,owner,'voice').restore(source,manifest['files'])
