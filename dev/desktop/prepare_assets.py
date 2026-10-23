"""Download build-time driver/metadata helpers, without running either."""
import argparse
from pathlib import Path
import urllib.request
import urllib.error
import zipfile
import io
import re
import os
import sys
from profilepack import files as profile_files,archive_values

ROOT = Path(__file__).resolve().parents[2]
DRIVER = 'https://github.com/Timocop/libwdi-wdi-releases/releases/download/v1.0/x64.zip'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'A7C2Tools-Build'})
    if re.fullmatch(r'https://api\.github\.com/repos/QAQLeonard/a7c2-fl23-research/releases/assets/[0-9]+', url):
        request.add_header('Accept','application/octet-stream')
        token=os.environ.get('GH_TOKEN')
        if token:request.add_unredirected_header('Authorization','Bearer '+token)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError('Build asset download failed: HTTP %s; %s' % (exc.code,exc.read().decode('utf-8',errors='replace'))) from None


PRESET_NAMES = tuple('slot%d.a7look' % slot for slot in range(1,7)) + (
    'credits.json','NOTICE.txt')
OPTIONAL_PRESET_NAMES = ('CC-BY-NC-SA-4.0.txt',)


def import_presets(archive, root=ROOT):
    """Import defaults and accepted profile pairs; never executable build inputs."""
    target=Path(root)/'desktop-assets/presets/default-six-v1'
    with zipfile.ZipFile(archive) as source:
        candidates=[n for n in source.namelist() if n.endswith('/default-six-v1/slot1.a7look')
                    or n=='slot1.a7look' or n=='default-six-v1/slot1.a7look']
        if len(candidates)!=1:raise ValueError('Archive must contain one default-six-v1 pack')
        prefix=candidates[0][:-len('slot1.a7look')]
        # Read all required files before replacing an existing local pack.
        values={name:source.read(prefix+name) for name in PRESET_NAMES}
        values.update({name:source.read(prefix+name) for name in OPTIONAL_PRESET_NAMES
                       if prefix+name in source.namelist()})
        library=archive_values(source)
    target.mkdir(parents=True,exist_ok=True)
    for name,value in values.items():(target/name).write_bytes(value)
    library_root=Path(root)/'desktop-assets/profile-library-v1'
    for name,value in library.items():
        path=library_root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
    return target


def export_presets(destination, root=ROOT):
    folder=Path(root)/'desktop-assets/presets/default-six-v1'
    values={name:(folder/name).read_bytes() for name in PRESET_NAMES}
    values.update({name:(folder/name).read_bytes() for name in OPTIONAL_PRESET_NAMES
                   if (folder/name).is_file()})
    library=profile_files(root)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as output:
        for name,value in values.items():output.writestr('default-six-v1/'+name,value)
        for name,path in library.items():output.write(path,'profile-library-v1/'+name)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exiftool-archive', type=Path,
                        help='Optional official Windows ExifTool ZIP to bundle')
    parser.add_argument('--preset-archive',type=Path,help='Exported defaults/profile library or existing desktop ZIP')
    parser.add_argument('--presets-url',default=os.environ.get('A7C2_PRESET_ARCHIVE_URL'),
                        help='Download the same six-look pack for native CI builds')
    parser.add_argument('--export-presets',type=Path,help='Export default six and accepted DCP/A7Look pairs for CI')
    args = parser.parse_args()
    if not args.presets_url and not args.preset_archive:
        request_file=ROOT/'dev/desktop/native-build-request.json'
        if request_file.is_file() and not all((ROOT/'desktop-assets/presets/default-six-v1'/('slot%d.a7look'%slot)).is_file() for slot in range(1,7)):args.presets_url=__import__('json').loads(request_file.read_text(encoding='utf-8'))['preset_archive_url']
    if args.export_presets:
        print(export_presets(args.export_presets));return
    if args.preset_archive:import_presets(args.preset_archive)
    elif args.presets_url:import_presets(io.BytesIO(fetch(args.presets_url)))
    if sys.platform == 'win32':
        dest = ROOT / 'desktop-assets/windows'
        dest.mkdir(parents=True, exist_ok=True)
        exe = dest / 'wdi-simple.exe'
        if not exe.exists():
            with zipfile.ZipFile(io.BytesIO(fetch(DRIVER))) as archive:
                item = next(n for n in archive.namelist() if Path(n).name.lower() == 'wdi-simple.exe')
                exe.write_bytes(archive.read(item))
        (dest / 'SOURCE.txt').write_text(
            'libwdi wdi-simple driver helper, https://github.com/pbatard/libwdi\n'
            'Prebuilt distributor: ' + DRIVER + '\n'
            'GNU LGPL v3 or later; source and license: https://github.com/pbatard/libwdi/blob/master/COPYING\n', encoding='utf-8')
        license_file = dest / 'COPYING.txt'
        if not license_file.exists():
            license_file.write_bytes(fetch('https://raw.githubusercontent.com/pbatard/libwdi/master/COPYING'))
    sys.path.insert(0,str(ROOT/'src'))
    from desktopapp.exiftool import install,executable
    dest=ROOT/'desktop-assets/exiftool'
    if args.exiftool_archive:
        install(dest,archive=args.exiftool_archive)
    elif not executable(dest).is_file():
        request_file=ROOT/'dev/desktop/native-build-request.json'
        urls=__import__('json').loads(request_file.read_text(encoding='utf-8')).get('exiftool_archives',{}) if request_file.is_file() else {}
        if sys.platform in urls:
            import tempfile
            try:
                with tempfile.TemporaryDirectory(prefix='a7c2-exiftool-input-') as temporary:
                    path=Path(temporary)/('helper.zip' if sys.platform=='win32' else 'helper.tar.gz')
                    path.write_bytes(fetch(urls[sys.platform]))
                    install(dest,archive=path)
            except RuntimeError as exc:
                # A pinned draft asset can disappear; the official release is the same tool.
                print('Pinned ExifTool archive unavailable ('+str(exc)[:120]+'); using the official download.',flush=True)
                install(dest)
        else:install(dest)
    print('Build helpers prepared. No driver installed; no camera connected.')


if __name__ == '__main__':
    main()
