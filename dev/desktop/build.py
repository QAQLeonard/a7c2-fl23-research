"""Build on the native host; Windows output paths remain unchanged."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from profilepack import files as profile_files

ROOT = Path(__file__).resolve().parents[2]


def make_dmg(output):
    output=Path(output).resolve()
    app=output/'A7C2Tools.app'
    if not app.is_dir():raise FileNotFoundError(app)
    target=output/('A7C2Tools-macOS-'+platform.machine()+'.dmg')
    # Temporary staging prevents files from older builds leaking into the DMG.
    with tempfile.TemporaryDirectory(prefix='a7c2-dmg-',dir=output) as temporary:
        staging=Path(temporary)
        shutil.copytree(app,staging/app.name,symlinks=True)
        (staging/'Applications').symlink_to('/Applications',target_is_directory=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
        subprocess.run(['hdiutil','create','-ov','-format','UDZO','-volname',
                        'A7C II Tools','-srcfolder',str(staging),str(target)],check=True)
    subprocess.run(['hdiutil','verify',str(target)],check=True)
    return target


def make_windows_zip(output):
    output=Path(output)
    target=output/'A7C2Tools-Windows-x64.zip'
    library=profile_files()
    for relative,source in library.items():
        dest=output/'A7C2Tools/Profiles'/relative
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    shutil.copyfile(ROOT/'README.md',output/'A7C2Tools/README.md')
    shutil.copyfile(ROOT/'README.zh-CN.md',output/'A7C2Tools/README.zh-CN.md')
    shutil.copyfile(ROOT/'LICENSE',output/'A7C2Tools/LICENSE')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
        for source in sorted((output/'A7C2Tools').rglob('*')):
            relative=source.relative_to(output/'A7C2Tools')
            # Users may save diagnostic ZIPs beside the executable. Never
            # redistribute those local files in the next development bundle.
            if relative.parts[0] not in ('A7C2Tools.exe','_internal','README.md','README.zh-CN.md','LICENSE','VERSION.txt'):continue
            if relative.parts[:3]==('_internal','desktop-assets','profile-library-v1'):continue
            if source.is_file():stream.write(source,source.relative_to(output))
        for relative,source in library.items():stream.write(source,'A7C2Tools/Profiles/'+relative)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args()
    if sys.platform not in ('win32','darwin'):raise RuntimeError('Build on native Windows or macOS')
    if sys.platform=='darwin' and platform.machine()!='arm64':
        raise RuntimeError('macOS packaging supports Apple Silicon only; Intel builds are not provided')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    profile_files()
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm',
                    '--distpath',str(output),'--workpath',str(ROOT/'build/desktop'),
                    str(ROOT/'dev/desktop/desktop.spec')],cwd=ROOT,check=True)
    if sys.platform == 'darwin':
        from macos_binary import prepare_scipy
        report = prepare_scipy(output/'A7C2Tools.app')
        (output/'macos-binary-self-test.json').write_text(
            json.dumps(report,indent=2)+'\n',encoding='utf-8')
    target=make_dmg(output) if sys.platform=='darwin' else make_windows_zip(output)
    print(json.dumps(dict(artifact=str(target),bytes=target.stat().st_size,camera_io=False)))


if __name__=='__main__':main()
