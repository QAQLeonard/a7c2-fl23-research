"""Compressed shared foundations and small per-snapshot deltas. No device I/O.

Objects are immutable. Deltas reference raw foundation chunks, never other
deltas, so a snapshot does not depend on earlier slot/job directories.
"""
import hashlib,json,os,re,time,uuid,zlib
from pathlib import Path
from .devicelock import DeviceLock

CHUNK=1024*1024
MAX_FILE=256*1024*1024

def sha(raw):return hashlib.sha256(raw).hexdigest()

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
    with temporary.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,sort_keys=True,separators=(',',':'));stream.write('\n');stream.flush();os.fsync(stream.fileno())
    for attempt in range(6):
        try:
            os.replace(temporary,path)
            return
        except PermissionError:
            if attempt==5:raise
            time.sleep(.05*2**attempt)

def body_key(identity):
    serial=identity.get('usb_serial_sha256') or identity.get('serial_sha256')
    if identity.get('model')!='ILCE-7CM2' or not isinstance(serial,str) or not serial:
        raise ValueError('Body-bound backup storage requires a verified camera identity')
    return sha(('ILCE-7CM2\0'+serial).encode('utf-8'))

class Store:
    def __init__(self,root,body,*,hash_checks=True):
        if not re.fullmatch('[a-f0-9]{64}',body):raise ValueError('Invalid backup body key')
        self.root=Path(root).resolve()/body;self.new_bytes=0;self.new_objects=0;self.hash_checks=hash_checks
    def _path(self,digest):
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Invalid backup object reference')
        return self.root/'objects'/(digest+'.z')
    def _read(self,digest,size):
        if type(size) is not int or not 0<=size<=CHUNK:raise ValueError('Invalid backup chunk size')
        packed=self._path(digest).read_bytes()
        if len(packed)>CHUNK+65536:raise ValueError('Oversized compressed backup object')
        decoder=zlib.decompressobj()
        try:raw=decoder.decompress(packed,size+1)
        except zlib.error as exc:raise ValueError('Compressed backup object is damaged') from exc
        if len(raw)!=size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or (self.hash_checks and sha(raw)!=digest):
            raise ValueError('Compressed backup object is damaged')
        return raw
    def _put(self,raw):
        digest=sha(raw);path=self._path(digest)
        if path.exists():
            if self._read(digest,len(raw))!=raw:raise ValueError('Existing backup object differs')
            return digest
        path.parent.mkdir(parents=True,exist_ok=True);packed=zlib.compress(raw,9)
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
        with temporary.open('xb') as stream:stream.write(packed);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        if self._read(digest,len(raw))!=raw:raise ValueError('Backup object write verification failed')
        self.new_bytes+=len(packed);self.new_objects+=1
        return digest
    def put(self,name,raw):
        if not isinstance(raw,bytes) or len(raw)>MAX_FILE:raise ValueError('Invalid backup file')
        self.root.mkdir(parents=True,exist_ok=True)
        with DeviceLock(self.root/'store.lock'):
            index=self.root/'foundation.private.json'
            anchors=json.loads(index.read_text(encoding='utf-8')) if index.exists() else {}
            anchor=anchors.get(name);chunks=[];foundation=[]
            for n,at in enumerate(range(0,len(raw),CHUNK)):
                block=raw[at:at+CHUNK];digest=sha(block);base=None
                if anchor and n<len(anchor):
                    base=self._read(anchor[n]['sha256'],anchor[n]['bytes'])
                    base=base[:len(block)].ljust(len(block),b'\0')
                if base is None:
                    self._put(block);entry={'sha256':digest,'bytes':len(block)}
                elif block==base and anchor[n]['bytes']==len(block):entry={'sha256':digest,'bytes':len(block)}
                else:
                    delta=bytes(a^b for a,b in zip(block,base))
                    entry={'sha256':digest,'bytes':len(block),'base':anchor[n]['sha256'],'base_bytes':anchor[n]['bytes'],'delta':self._put(delta)}
                chunks.append(entry);foundation.append({'sha256':digest,'bytes':len(block)})
            if anchor is None:
                anchors[name]=foundation;write_json(index,anchors)
            spec={'bytes':len(raw),'sha256':sha(raw),'chunks':chunks}
            if self.read(spec)!=raw:raise ValueError('Backup reconstruction differs')
            return spec
    def read(self,spec):
        size=spec['bytes']
        if type(size) is not int or not 0<=size<=MAX_FILE or len(spec['chunks'])!=(size+CHUNK-1)//CHUNK:
            raise ValueError('Invalid backup file dimensions')
        output=bytearray()
        for n,entry in enumerate(spec['chunks']):
            expected=min(CHUNK,size-n*CHUNK)
            if entry['bytes']!=expected:raise ValueError('Invalid backup chunk dimensions')
            if 'delta' in entry:
                base=self._read(entry['base'],entry['base_bytes'])[:expected].ljust(expected,b'\0');delta=self._read(entry['delta'],expected)
                block=bytes(a^b for a,b in zip(base,delta))
                if self.hash_checks and sha(block)!=entry['sha256']:raise ValueError('Backup delta reconstruction differs')
            else:block=self._read(entry['sha256'],expected)
            output.extend(block)
        raw=bytes(output)
        if len(raw)!=size or (self.hash_checks and sha(raw)!=spec['sha256']):raise ValueError('Backup file reconstruction differs')
        return raw
