"""Check public links, publication privacy, UTF-8 and Python syntax."""
import ast,base64,hashlib,json,re,zipfile
from pathlib import Path
from urllib.parse import unquote
ROOT=Path(__file__).resolve().parents[2]
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    # Inspect intentional publication roots only, never local firmware/backups.
    files=[p for p in ROOT.iterdir() if p.is_file() and p.name!='.git' and p.suffix!='.zip']
    for folder in ['src','dev','docs']:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    errors=[];links=0
    for p in files:
        data=p.read_bytes()
        if p.parent==ROOT/'src/fl23/assets' and p.suffix=='.so':
            # Exact workers already shipped in the historical public ZIP.
            # Retain their tested bytes and manifest; their DWARF contains
            # a project build path, not body backups or credentials.
            manifest=json.loads((p.parent/'manifest.json').read_text(encoding='utf-8'))
            if sha(data)!=manifest['files'].get(p.name):errors.append('Native worker fingerprint differs: '+p.name)
            continue
        if re.search(rb'[A-Z]:[\\/](?:Users|LeoClaw|a7c2-fl23)[\\/]',data,re.I) or re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----[\r\n]',data):errors.append('Private marker: '+str(p.relative_to(ROOT)))
        if p.suffix=='.md':
            text=data.decode('utf-8')
            if re.search(r'^#{1,6}(?!#)[^\s#]',text,re.M):errors.append('Malformed heading: '+str(p.relative_to(ROOT)))
            for url in re.findall(r'\]\(([^)\s]+)(?:\s+"[^"]*")?\)',text):
                if url.startswith(('https:','http:','mailto:','#')):continue
                target=(p.parent/unquote(url.split('#')[0])).resolve();links+=1
                if not target.exists():errors.append('Missing link '+url+' in '+str(p.relative_to(ROOT)))
        elif p.suffix=='.py':ast.parse(data.decode('utf-8'),filename=str(p))
    for p in ROOT.glob('*.zip'):errors.append('Download binary belongs in Releases: '+p.name)
    for p in ROOT.glob('*USB*.cmd'):errors.append('Separate repair download remains: '+p.name)
    if not (ROOT/'lut.py').is_file():errors.append('Missing LUT Python entry')
    if {p.name for p in ROOT.glob('*.cmd')}!={'FL23.cmd'}:errors.append('Expected original FL23 CMD only')
    if any(p.suffix.lower() in ['.cmd','.ps1'] or p.name=='gui.py' for p in (ROOT/'src/looks').rglob('*') if p.is_file()):errors.append('Retired LUT launcher or GUI remains')
    english={p.relative_to(ROOT/'docs/en').as_posix() for p in (ROOT/'docs/en').rglob('*.md')}
    chinese={p.relative_to(ROOT/'docs/zh-CN').as_posix() for p in (ROOT/'docs/zh-CN').rglob('*.md')}
    if english!=chinese or len(english)!=17:errors.append('Expected 17 matching English/Simplified Chinese guide pairs')
    expected_markdown={'README.md','README.zh-CN.md','AGENTS.md','src/looks/AGENTS.md'}
    expected_markdown|={'docs/'+lang+'/'+name for lang in ['en','zh-CN'] for name in english}
    actual_markdown={p.relative_to(ROOT).as_posix() for p in files if p.suffix=='.md'}
    if actual_markdown!=expected_markdown:errors.append('Markdown outside the documented bilingual structure')
    for p in files:
        if p.suffix=='.md' and ('zh-TW' in p.name or '(鑻辨枃)' in p.read_text(encoding='utf-8') or '锛堣嫳鏂囷級' in p.read_text(encoding='utf-8')):errors.append('Retired language reference: '+str(p.relative_to(ROOT)))
    manifest=json.loads((ROOT/'docs/profiles/manifest.json').read_text(encoding='utf-8'))
    if len(manifest['profiles'])!=18:errors.append('Expected all18 DCP references')
    if errors:raise ValueError('\n'.join(errors))
    print(json.dumps({'public_files_checked':len(files),'local_markdown_links_checked':links,'bilingual_guide_pairs':len(english),'UTF8_and_Python_syntax_verified':True,'DCP_manifest_count':18,'camera_io':False},indent=2))
if __name__=='__main__':main()
