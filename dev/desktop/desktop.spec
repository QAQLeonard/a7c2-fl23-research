from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parents[1]
sys.path.insert(0,str(root/'dev/desktop'))
from profilepack import files as profile_files
version = {}
exec((root / 'src/desktopapp/__init__.py').read_text(encoding='utf-8'), version)
for slot in range(1, 7):
    path = root / 'desktop-assets/presets/default-six-v1' / ('slot%d.a7look' % slot)
    if not path.is_file():
        raise FileNotFoundError('Prepare the six-look distribution pack first: ' + str(path))
datas, binaries, hidden = [], [], ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
                                 'tarfile', 'lzma', 'bz2', 'zlib', 'urllib.request', 'wave', 'plistlib', 'backports.tarfile', 'zipfile', 'filecmp']
if sys.platform=='darwin':hidden.append('pwd')
for package in ('numpy', 'scipy', 'PIL', 'tifffile', 'yaml', 'elftools', 'usb',
                'libusb_package', 'Cryptodome', 'imageio_ffmpeg', 'ziglang', 'keystone', 'capstone', 'unicorn'):
    d, b, h = collect_all(package)
    datas.extend(d)
    binaries.extend(b)
    hidden.extend(h)

# Source keeps original __file__-relative native headers and asset paths.
for folder in ('src/desktopapp', 'src/camera_runtime', 'src/looks/looktool',
               'src/looks/assets', 'src/looks/native', 'src/fl23/native', 'src/fl23/assets',
               'src/fl23/vendor', 'src/fl23/licenses',
               'src/vertical', 'src/shutter_sound', 'plugins', 'desktop-assets'):
    for source in (root / folder).rglob('*'):
        relative = source.relative_to(root)
        if relative.parts[:2]==('desktop-assets','profile-library-v1'):continue
        if not source.is_file() or any(p in ('__pycache__', 'tests') for p in relative.parts):
            continue
        if sys.platform == 'darwin' and (relative.parts[:2] == ('desktop-assets', 'windows') or source.suffix.lower() in ('.exe', '.dll', '.pyd', '.bat', '.cmd')):
            continue
        if source.suffix.lower()=='.dcp' and relative.parts[:2]!=('desktop-assets','profile-library-v1'):
            continue
        if '.private.' in source.name or source.suffix.lower() in ('.arw', '.hif', '.jpg', '.cube', '.pyc'):
            continue
        datas.append((str(source), str(relative.parent)))
for relative,source in profile_files().items():
    datas.append((str(source),str(Path('desktop-assets/profile-library-v1')/Path(relative).parent)))
for name in ('desktop.py', 'LICENSE', 'README.md', 'README.zh-CN.md', 'desktop-requirements.txt',
             'dev/desktop/offline_smoke.py', 'docs/en/lut-formats.md', 'docs/zh-CN/lut-formats.md',
             'docs/en/notices.md', 'docs/zh-CN/notices.md', 'docs/licenses/a7c2-fl23-macos-MIT.txt',
             'docs/licenses/project-legacy-MIT.txt',
             'calibration/a7c2-2.01.virtual.npz'):
    datas.append((str(root / name), str(Path(name).parent)))

entry = root / 'dev/desktop/frozen_entry.py'
if os.environ.get('A7C2_BUILD_PREVIEW_GATE_TRIAL') == '1':
    datas.append((str(entry), 'dev/desktop'))
    entry = root / 'dev/desktop/preview_gate_entry.py'
a = Analysis([str(entry)], pathex=[],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['tkinter', 'matplotlib', 'pandas', 'IPython', 'pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='A7C2Tools',
          console=False, disable_windowed_traceback=False)
collection = COLLECT(exe, a.binaries, a.datas, name='A7C2Tools')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='A7C2Tools.app', bundle_identifier='io.github.QAQLeonard.A7C2Tools',
                 info_plist={'CFBundleShortVersionString': version['VERSION'],
                             'CFBundleVersion': version['VERSION'].rsplit('.', 1)[-1],
                             'LSMinimumSystemVersion': '14.0',
                             'NSHighResolutionCapable': True,
                             'NSUSBUsageDescription': 'Access your Sony A7C II for requested camera operations.'})
