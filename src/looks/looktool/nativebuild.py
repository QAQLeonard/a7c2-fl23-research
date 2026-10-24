"""Compile job-pinned native workers from fresh verified inputs, offline."""
import importlib.util,os,shutil,subprocess,sys
from pathlib import Path
from . import firmware
from .worker import NAMES

ROOT=Path(__file__).resolve().parents[3]

def zig_command(explicit=None):
    if explicit:return [str(Path(explicit).resolve())]
    found=shutil.which('zig')
    if found:return [found]
    spec=importlib.util.find_spec('ziglang')
    if spec is not None:
        # Local/portable runtimes may add this package to sys.path only.
        # Its executable works directly; a fresh `python -m` loses that path.
        for folder in spec.submodule_search_locations or []:
            binary=Path(folder)/('zig.exe' if os.name=='nt' else 'zig')
            if binary.is_file():return [str(binary.resolve())]
        return [sys.executable,'-m','ziglang']
    raise ValueError('Device preparation needs Zig: install requirements-device.txt or supply --zig')

def compile_worker(source,header,destination,zig=None,*,fingerprints=True):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    if sys.platform=='darwin' and getattr(sys,'frozen',False):
        # Child compiler must use the system loader, not frozen Python dylibs.
        for key in ('DYLD_LIBRARY_PATH','DYLD_FRAMEWORK_PATH'):
            original=env.pop(key+'_ORIG',None)
            env.pop(key,None)
            if original:env[key]=original
    cache=Path(os.environ.get('A7C2_ZIG_CACHE',Path.home()/'.cache/a7c2-lut/zig')).resolve()
    env['ZIG_GLOBAL_CACHE_DIR']=str(cache/'global');env['ZIG_LOCAL_CACHE_DIR']=str(cache/'local')
    command=zig_command(zig)+['cc','-target','aarch64-linux-gnu','-shared','-fPIC','-O2',
        '-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
        '-nostdlib','-g0','-Wl,--strip-debug','-Wl,--no-undefined','-Wl,-Bsymbolic','-Wl,-z,noexecstack',
        '-I',str(ROOT/'src/fl23/native'),'-I',str(Path(header).parent),
        '-DPATCH_MANIFEST="'+Path(header).resolve().as_posix()+'"','-o',str(destination),str(source)]
    result=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,
        creationflags=0x08000000 if os.name=='nt' else 0)
    if result.returncode:raise ValueError('Native compilation failed: '+result.stderr[-4000:])
    blob=destination.read_bytes()
    if len(blob)>65536:raise ValueError('Native worker exceeds current staging limit')
    from elftools.elf.elffile import ELFFile
    with destination.open('rb') as stream:
        elf=ELFFile(stream)
        if elf['e_machine']!='EM_AARCH64' or elf['e_type']!='ET_DYN':raise ValueError('Wrong native ELF architecture/type')
        tags=list(elf.get_section_by_name('.dynamic').iter_tags())
        if not any(t.entry.d_tag=='DT_INIT' for t in tags) or any(t.entry.d_tag=='DT_NEEDED' for t in tags):raise ValueError('Invalid native ELF initialization/dependencies')
        if any(s.name and s['st_shndx']=='SHN_UNDEF' for s in elf.get_section_by_name('.dynsym').iter_symbols()):raise ValueError('External native symbols')
        for section in elf.iter_sections():
            if section['sh_type']=='SHT_RELA' and any(r['r_info_type']!=1027 or r['r_info_sym']!=0 for r in section.iter_relocations()):raise ValueError('Unsupported native relocation')
    if not fingerprints:return {'bytes':len(blob)}
    return {'sha256':firmware.sha(blob),'bytes':len(blob),'native_source_sha256':firmware.sha(Path(source).read_bytes()),'manifest_sha256':firmware.sha(Path(header).read_bytes())}

def program_header(before,forward,reverse,*,byte_only=False,window_priority=None):
    after=firmware.apply(before,forward,hash_checks=not byte_only)
    if firmware.apply(after,reverse,hash_checks=not byte_only)!=before:raise ValueError('Complete program inverse required')
    rows=[];lines=[];windows=[]
    for chip,name in enumerate(NAMES):
        windows.extend(dict(w,chip=chip) for w in forward['files'][name]['windows'])
    windows.sort(key=window_priority or (lambda w:(0 if w['chip']==1 else 1,0 if w['bytes']>1024 else 1,int(w['offset'],16))))
    cbytes=lambda b:'{'+','.join(map(str,b))+'}'
    for i,w in enumerate(windows):
        old,new=bytes.fromhex(w['before_hex']),bytes.fromhex(w['after_hex'])
        if not 0<len(old)==len(new)<=4096:raise ValueError('Invalid native program window')
        lines.extend([f'static const u8 old_{i}[]={cbytes(old)};',f'static const u8 new_{i}[]={cbytes(new)};'])
        rows.append('{'+f"{int(w['offset'],16)}UL,{len(old)},{w['chip']},old_{i},new_{i}"+'}')
    if not rows:return None,None
    lines.extend(['static const struct Window windows[]={'+','.join(rows)+'};',
        f'static const u32 window_count={len(windows)};',
        'static const u64 file_sizes[]={'+','.join(str(len(before[n]))+'UL' for n in NAMES)+'};'])
    if byte_only:lines.insert(0,'#define BYTE_WINDOWS_ONLY 1')
    else:
        for label,images in [('original',before),('final',after)]:
            lines.append('static const u8 '+label+'_hashes[2][32]={'+','.join(cbytes(bytes.fromhex(firmware.sha(images[n]))) for n in NAMES)+'};')
    contract={'schema':'a7c2-table-worker-contract/1','sizes':{n:len(before[n]) for n in NAMES},
        'window_writes':len(windows),'byte_only':byte_only}
    if not byte_only:contract.update(before={n:firmware.sha(before[n]) for n in NAMES},after={n:firmware.sha(after[n]) for n in NAMES})
    return '\n'.join(lines)+'\n',contract

def build_program(before,forward,reverse,out,zig=None,*,byte_only=False,window_priority=None):
    header,contract=program_header(before,forward,reverse,byte_only=byte_only,window_priority=window_priority)
    if header is None:return {'unchanged':True,'contract':None}
    out=Path(out);out.mkdir(parents=True,exist_ok=True);h=out/'manifest.private.h';h.write_text(header,encoding='ascii',newline='\n')
    source=ROOT/'src/fl23/native/installer.c';destination=out/'program.so'
    build=compile_worker(source,h,destination,zig,fingerprints=not byte_only)
    build.update(path=str(destination),contract=contract,unchanged=False)
    return build
