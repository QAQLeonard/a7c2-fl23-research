"""RAW slot -> dated source-DCP registry -> mergeable XMP, without USB.

Only the project's explicit 249..254 markers identify custom slots. A slot
number alone cannot identify a look after that slot has been replaced.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

SCHEMA='a7c2-raw-profile-registry/1'
CRS='http://ns.adobe.com/camera-raw-settings/1.0/'
RDF='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
X='adobe:ns:meta/'
for prefix,uri in (('x',X),('rdf',RDF),('crs',CRS)):ET.register_namespace(prefix,uri)


def dcp_info(path):
    """Read the two identity strings, without evaluating color or file hashes."""
    raw=bytes(path) if isinstance(path,(bytes,bytearray)) else Path(path).read_bytes()
    if raw[:2] not in (b'II',b'MM') or len(raw)<8:raise ValueError('Not a classic TIFF DCP')
    order='<' if raw[:2]==b'II' else '>'
    magic,start=struct.unpack_from(order+'HI',raw,2)
    if magic not in (42,0x4352) or start+2>len(raw):raise ValueError('Unsupported DCP header')
    count=struct.unpack_from(order+'H',raw,start)[0];values={}
    if start+2+12*count+4>len(raw):raise ValueError('Truncated DCP directory')
    for index in range(count):
        at=start+2+12*index;tag,kind,size,offset=struct.unpack_from(order+'HHII',raw,at)
        if tag not in (50708,50936,50942):continue
        if kind!=2:raise ValueError('Invalid DCP identity string')
        pointer=at+8 if size<=4 else offset
        if pointer+size>len(raw):raise ValueError('DCP string outside file')
        values[tag]=raw[pointer:pointer+size].rstrip(b'\0').decode('utf-8')
    if values.get(50708)!='Sony ILCE-7CM2':raise ValueError('Select a Sony ILCE-7CM2 DCP')
    if not values.get(50936):raise ValueError('DCP has no profile name')
    return dict(model=values[50708],profile=values[50936],copyright=values.get(50942,''))


def camera_time(value, subseconds=None):
    text=str(value).strip()
    if len(text)>=10 and text[4]==':' and text[7]==':':text=text[:10].replace(':','-')+text[10:]
    text=text.replace('T',' ')
    if '.' not in text and subseconds is not None:
        fraction=str(subseconds)
        if isinstance(subseconds,int):fraction=fraction.zfill(3)
        text+='.'+fraction
    result=datetime.fromisoformat(text)
    if result.tzinfo is not None:raise ValueError('Use camera-local time without a timezone offset')
    return result


def slot_number(marker):
    try:number=int(marker)
    except (ValueError,TypeError):return None
    return number-248 if 249<=number<=254 else None


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
        temporary=Path(stream.name)
        stream.write((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


class Registry:
    def __init__(self,root):self.root=Path(root);self.path=self.root/'registry.json'

    def read(self):
        if not self.path.exists():return dict(schema=SCHEMA,entries=[])
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('schema')!=SCHEMA:raise ValueError('Unknown RAW profile registry')
        return data

    def bind(self,slot,dcp,since,until=None,look=None):
        if slot not in range(1,7):raise ValueError('Custom slot must be1..6')
        beginning=camera_time(since);ending=camera_time(until) if until else None
        if ending and ending<=beginning:raise ValueError('Until must follow since')
        info=dcp_info(dcp);data=self.read();raw=Path(dcp).read_bytes();retained=None
        for entry in data['entries']:
            if entry.get('profile')==info['profile'] and entry.get('dcp'):
                if (self.root/entry['dcp']).read_bytes()!=raw:
                    raise ValueError('Different DCP versions share this profile name; give them distinct DCP profile names before registering')
                retained=Path(entry['dcp'])
            if entry['slot']==slot and camera_time(entry['since'])==beginning:
                if entry.get('profile')==info['profile'] and entry.get('until')==(ending.isoformat() if ending else None):return entry
                raise ValueError('This slot already has a different binding at the same camera time')
        event=uuid.uuid4().hex[:12];stored=retained or Path('profiles')/(event+'.dcp')
        (self.root/'profiles').mkdir(parents=True,exist_ok=True)
        if retained is None:shutil.copyfile(dcp,self.root/stored)
        row=dict(id=event,slot=slot,since=beginning.isoformat(),until=ending.isoformat() if ending else None,
            state='profile',profile=info['profile'],dcp=stored.as_posix(),source_filename=Path(dcp).name,
            look_name=look,copyright=info['copyright'])
        data['entries'].append(row);data['entries'].sort(key=lambda e:(e['slot'],e['since']))
        write_json(self.path,data)
        return row

    def suspend(self,slot,since,reason='Temporary measurement parameters'):
        if slot not in range(1,7):raise ValueError('Custom slot must be1..6')
        beginning=camera_time(since);data=self.read()
        if any(e['slot']==slot and camera_time(e['since'])==beginning for e in data['entries']):
            raise ValueError('A binding already exists at that camera time')
        data['entries'].append(dict(id=uuid.uuid4().hex[:12],slot=slot,since=beginning.isoformat(),
            until=None,state='suspended',reason=reason))
        self.root.mkdir(parents=True,exist_ok=True);write_json(self.path,data)

    def match(self,slot,shot):
        candidates=[row for row in self.read()['entries'] if row['slot']==slot and camera_time(row['since'])<=shot]
        if not candidates:return None
        row=max(candidates,key=lambda e:camera_time(e['since']))
        if row.get('state')!='profile' or (row.get('until') and shot>=camera_time(row['until'])):return None
        return row


def metadata(files,exiftool):
    """Read only the fields needed for routing; never write a RAW."""
    paths=[]
    for file in files:
        source=str(file)
        path=str(Path(source).absolute())
        # -@ is a line-based argument file, not an escaped filename list.
        # Validate the whole batch before launch; absolute paths also prevent
        # leading '-' or '#' from becoming options or comments.
        if any(char in value for value in (source,path) for char in ('\r','\n','\0')):
            raise ValueError('ExifTool input paths cannot contain CR, LF or NUL characters')
        paths.append(path)
    if not paths:return []
    command=[str(exiftool),'-j','-n','-charset','filename=UTF8','-Model','-DateTimeOriginal',
             '-SubSecTimeOriginal','-Sony:CreativeStyle','-@','-']
    result=subprocess.run(command,input='\n'.join(paths)+'\n',stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError('ExifTool could not read RAW metadata: '+result.stderr.strip())
    return json.loads(result.stdout)


def plan(files,registry,exiftool):
    rows=[]
    for item in metadata(files,exiftool):
        path=Path(item['SourceFile']);marker=item.get('CreativeStyle');slot=slot_number(marker)
        row=dict(file=str(path.resolve()),marker=marker,slot=slot)
        if item.get('Model')!='ILCE-7CM2':row.update(action='skip',reason='different_camera')
        elif slot is None:row.update(action='native',reason='native_style_unchanged')
        elif not item.get('DateTimeOriginal'):row.update(action='skip',reason='capture_time_missing')
        else:
            shot=camera_time(item['DateTimeOriginal'],item.get('SubSecTimeOriginal'));entry=registry.match(slot,shot)
            row['camera_time']=shot.isoformat()
            if entry is None:row.update(action='skip',reason='no_binding_for_capture_time')
            else:row.update(action='profile',profile=entry['profile'],binding_id=entry['id'],
                            look_id=entry.get('look_id'),
                            dcp=str((registry.root/entry['dcp']).resolve()))
        rows.append(row)
    return rows


def merge_xmp(raw,profile,replace_profile=False):
    """Change only the profile; retain existing exposure/crop/rating/keywords."""
    raw=Path(raw);sidecar=raw.with_suffix('.xmp')
    if not sidecar.exists() and raw.with_suffix('.XMP').exists():sidecar=raw.with_suffix('.XMP')
    old=sidecar.read_bytes() if sidecar.exists() else None
    if old is None:
        root=ET.Element('{'+X+'}xmpmeta');rdf=ET.SubElement(root,'{'+RDF+'}RDF')
        description=ET.SubElement(rdf,'{'+RDF+'}Description',{'{'+RDF+'}about':''})
        description.set('{'+CRS+'}Version','18.5.1');description.set('{'+CRS+'}ProcessVersion','15.4')
        description.set('{'+CRS+'}WhiteBalance','As Shot')
    else:
        root=ET.fromstring(old)
        descriptions=list(root.iter('{'+RDF+'}Description'))
        if not descriptions:raise ValueError('Existing XMP has no RDF description: '+str(sidecar))
        description=next((node for node in descriptions if '{'+CRS+'}CameraProfile' in node.attrib),descriptions[0])
        previous=description.get('{'+CRS+'}CameraProfile')
        child=description.find('{'+CRS+'}CameraProfile')
        if previous is None and child is not None:previous=child.text
        if previous and previous!=profile and not replace_profile:
            return dict(status='profile_conflict',file=str(sidecar),existing_profile=previous)
        if previous==profile and description.get('{'+CRS+'}HasSettings','').lower()=='true':
            return dict(status='already_prepared',file=str(sidecar))
        for node in descriptions:
            node.attrib.pop('{'+CRS+'}CameraProfileDigest',None)
            for tag in ('CameraProfile','CameraProfileDigest'):
                for child in list(node.findall('{'+CRS+'}'+tag)):node.remove(child)
            if node is not description:node.attrib.pop('{'+CRS+'}CameraProfile',None)
    description.set('{'+CRS+'}CameraProfile',profile)
    description.set('{'+CRS+'}HasSettings','True')
    description.set('{'+CRS+'}AlreadyApplied','False')
    description.set('{'+CRS+'}RawFileName',raw.name)
    data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    backup=None
    if old is not None:
        backup=sidecar.with_name(sidecar.name+'.before-a7look')
        if not backup.exists():
            with backup.open('xb') as stream:stream.write(old)
    with tempfile.NamedTemporaryFile(dir=sidecar.parent,prefix=sidecar.name+'.',suffix='.tmp',delete=False) as stream:
        temporary=Path(stream.name);stream.write(data)
    try:os.replace(temporary,sidecar)
    finally:temporary.unlink(missing_ok=True)
    return dict(status='prepared',file=str(sidecar),backup=str(backup) if backup else None)


def adobe_profile_directory():
    if sys.platform=='win32':return Path(os.environ.get('APPDATA',Path.home()/'AppData/Roaming'))/'Adobe/CameraRaw/CameraProfiles'
    if sys.platform=='darwin':return Path.home()/'Library/Application Support/Adobe/CameraRaw/CameraProfiles'
    return Path.home()/'.config/Adobe/CameraRaw/CameraProfiles'


def install_profiles(rows,destination=None):
    root=Path(destination) if destination else adobe_profile_directory()
    wanted={row['profile']:Path(row['dcp']) for row in rows if row['action']=='profile'}
    if not wanted:return []
    installed={}
    for path in root.rglob('*.dcp') if root.exists() else []:
        try:info=dcp_info(path)
        except (ValueError,OSError):continue
        if info['profile'] in wanted:installed.setdefault(info['profile'],[]).append(path)
    reports=[]
    for name,source in wanted.items():
        content=source.read_bytes();existing=installed.get(name,[])
        if any(path.read_bytes()==content for path in existing):
            reports.append(dict(profile=name,status='already_installed'));continue
        if existing:raise ValueError('Adobe already has a different DCP with this profile name: '+name)
        destination=root/'A7Look-Imported'/(uuid.uuid4().hex+'.dcp');destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        reports.append(dict(profile=name,status='installed',restart_may_be_needed=True))
    return reports


def exported_profile(path):
    header=b'http://ns.adobe.com/xap/1.0/\0'
    with Path(path).open('rb') as stream:
        if stream.read(2)!=b'\xff\xd8':raise ValueError('Expected a JPEG verification export')
        while True:
            marker=stream.read(2)
            if len(marker)!=2 or marker[0]!=255 or marker[1] in (0xda,0xd9):break
            length=struct.unpack('>H',stream.read(2))[0];payload=stream.read(length-2)
            if marker==b'\xff\xe1' and payload.startswith(header):
                root=ET.fromstring(payload[len(header):])
                for element in root.iter():
                    if '{'+CRS+'}CameraProfile' in element.attrib:return element.attrib['{'+CRS+'}CameraProfile']
                    if element.tag=='{'+CRS+'}CameraProfile':return element.text
    raise ValueError('Adobe export does not identify its applied camera profile')
