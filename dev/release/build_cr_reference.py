"""Build a standalone collector ZIP containing code/guides, never camera data."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def build(output):
    sources = ROOT/'dev/pixelshift'
    members = {name: (sources/name).read_bytes() for name in (
        'collect_cr_reference.py', 'cr_usb_readonly.py', 'raw_group.py', 'cr-reference-usb-requirements.txt')}
    vendor = ROOT/'src/fl23/vendor'
    for name in ('__init__.py', 'util/__init__.py', 'usb/__init__.py', 'usb/sony.py',
                 'usb/constants.py', 'usb/crypto.py', 'usb/driver/__init__.py',
                 'usb/driver/generic/__init__.py', 'usb/driver/generic/libusb.py'):
        members['vendor/pmca/'+name] = (vendor/'pmca'/name).read_bytes()
    members['LICENSE.txt'] = (ROOT/'src/fl23/LICENSE').read_bytes()
    members['Sony-PMCA-RE-MIT.txt'] = (ROOT/'src/fl23/licenses/Sony-PMCA-RE-MIT.txt').read_bytes()
    members['AGENTS.md'] = (
        '# A7CR reference collection task\n\n'
        'Read README.zh-CN.md or README.en.md first. The owner authorizes local preparation, '
        'dependency installation, explicit read-only collector USB commands, file inspection and private packaging. '
        'Run collect_cr_reference.py --help before execution. Verify the actual model and ask for the actual firmware version. '
        'Use only the provided collector for camera access. Do not upload native code, patch memory/firmware, '
        'save/write settings, initialize/reset, or invoke firmware modification/recovery tools. '
        'Do not automatically install/change USB drivers; explain the exact device first if driver work is needed. '
        'Do not control the shutter through USB. Ask the owner only for physical menu/shutter/cable operations '
        'and confirmations that cannot be obtained from files. Finish each USB command before any physical step. '
        'Keep a timestamped evidence/operations.txt with command exit status, source filenames and owner-reported actions; '
        'never describe owner reports as directly observed. Do not request video. Preserve partial results on failure '
        'and stop rather than retry blindly. Keep originals unchanged and data private; do not upload automatically. '
        'Settings snapshots are not CP execution RAM or per-exposure motion traces. '
        'Report completed/missing stages and validation limits honestly.\n'
    ).encode('utf-8')
    for language in ('en', 'zh-CN'):
        text = (ROOT/'docs'/language/'cr-reference.md').read_text(encoding='utf-8')
        text = text.replace('(pixel-shift.md)', '(https://github.com/QAQLeonard/a7c2-fl23-research/blob/feature/pixel-shift/docs/'+language+'/pixel-shift.md)')
        text = text.replace('(../en/cr-reference.md)', '(README.en.md)').replace('(../zh-CN/cr-reference.md)', '(README.zh-CN.md)')
        members['README.'+language+'.md'] = text.encode('utf-8')
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return list(members)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print('Built collector: '+str(args.output)+' ('+str(len(build(args.output)))+' files; no camera data)')


if __name__ == '__main__':
    main()
