"""Automatically apply a captured custom-slot's source DCP when importing RAW."""
import argparse
import json
from pathlib import Path
import shutil
import uuid
from . import rawprofiles


def files_at(path):
    path=Path(path)
    if path.is_file():
        if path.suffix.lower()!='.arw':raise ValueError('Select an ARW or a folder of ARWs')
        return [path.resolve()]
    return sorted(file.resolve() for file in path.rglob('*') if file.is_file() and file.suffix.lower()=='.arw')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry',type=Path)
    parser.add_argument('--config',type=Path)
    commands=parser.add_subparsers(dest='command',required=True)
    bind=commands.add_parser('bind',help='Record the DCP actually installed in a slot, in camera-local time')
    bind.add_argument('--slot',type=int,required=True);bind.add_argument('--dcp',type=Path,required=True)
    bind.add_argument('--since',required=True);bind.add_argument('--until');bind.add_argument('--look-name')
    suspend=commands.add_parser('suspend',help='Record a temporary measurement/non-DCP period')
    suspend.add_argument('--slot',type=int,required=True);suspend.add_argument('--since',required=True)
    commands.add_parser('list',help='Show dated bindings')
    for name in ('plan','prepare','import'):
        command=commands.add_parser(name)
        command.add_argument('source',type=Path)
        command.add_argument('--exiftool',type=Path)
        command.add_argument('--replace-profile',action='store_true',help='Replace an existing XMP profile, preserving other edits and an XMP backup')
        command.add_argument('--report',type=Path)
        if name=='import':command.add_argument('--verify',action='store_true',help='Export small proof JPEGs to verify the profile Adobe actually applied')
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parents[3]
    config_file=args.config or root/'raw-import.local.json'
    config=json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
    registry_path=args.registry or Path(config.get('registry',Path.home()/'.a7look/raw-profiles'))
    if not args.registry and not registry_path.is_absolute():registry_path=config_file.parent/registry_path
    registry=rawprofiles.Registry(registry_path)
    if args.command=='bind':
        print(json.dumps(registry.bind(args.slot,args.dcp,args.since,args.until,args.look_name),ensure_ascii=False,indent=2));return 0
    if args.command=='suspend':registry.suspend(args.slot,args.since);print('Recorded temporary measurement period.');return 0
    if args.command=='list':print(json.dumps(registry.read(),ensure_ascii=False,indent=2));return 0
    exiftool=args.exiftool or config.get('exiftool') or shutil.which('exiftool')
    if not exiftool:parser.error('Install ExifTool or set its path with --exiftool')
    photos=files_at(args.source)
    if not photos:parser.error('No ARW files found')
    rows=rawprofiles.plan(photos,registry,exiftool)
    if args.command=='plan':print(json.dumps(dict(camera_io=False,photos=rows),ensure_ascii=False,indent=2));return 0
    job=registry.root/'jobs'/uuid.uuid4().hex[:12];job.mkdir(parents=True)
    report=dict(camera_io=False,RAW_pixels_modified=False,mode=args.command,photos=[],
        profile_installation=rawprofiles.install_profiles(rows))
    bridge=None
    try:
        if args.command=='import':
            from .renderbridge import Lightroom
            command=config.get('renderer_command')
            if not command:parser.error('Configure renderer_command for the Lightroom bridge, or use prepare followed by normal Lightroom import')
            command=[str((config_file.parent/value).resolve()) if i>0 and value.endswith('.js') and not Path(value).is_absolute()
                     else value for i,value in enumerate(command)]
            bridge=Lightroom(command,job/'lightroom.log')
        for row in rows:
            current=dict(row);path=Path(row['file'])
            if row['action']=='skip':current['status']='skipped'
            else:
                existing=False
                if bridge:
                    try:bridge.call('get_photo_metadata',photo_id=str(path));existing=True
                    except RuntimeError as exc:
                        if not any(word in str(exc).lower() for word in ('not found','no photo','could not find')):raise
                if existing:current.update(status='already_in_catalog',note='Existing Lightroom edits unchanged; use prepare and Read Metadata only if desired')
                else:
                    if row['action']=='profile':
                        current['sidecar']=rawprofiles.merge_xmp(path,row['profile'],args.replace_profile)
                        if current['sidecar']['status']=='profile_conflict':
                            current['status']='profile_conflict';report['photos'].append(current)
                            rawprofiles.write_json(job/'report.json',report);continue
                    if bridge:
                        bridge.call('import_photos',source_path=str(path))
                        current['status']='imported_requested_DCP' if row['action']=='profile' else 'imported_native'
                        if row['action']=='profile' and args.verify:
                            destination=job/'verification';destination.mkdir(exist_ok=True)
                            bridge.call('export_photos',photo_ids=[str(path)],destination=str(destination.resolve()),
                                format='jpeg',quality=80,width=512,height=512,on_existing='skip')
                            jpeg=destination/(path.stem+'.jpg')
                            applied=rawprofiles.exported_profile(jpeg)
                            current.update(actual_Adobe_profile=applied,profile_application_verified=applied==row['profile'])
                            if applied!=row['profile']:
                                current.update(status='profile_not_applied',note='Restart Lightroom after adding a new DCP, or check import presets')
                            else:current['status']='imported_DCP_verified'
                    else:current['status']='prepared' if row['action']=='profile' else 'native_unchanged'
            report['photos'].append(current);rawprofiles.write_json(job/'report.json',report)
            print(path.name+': '+current['status']+((' -> '+row['profile']) if row.get('profile') else ''),flush=True)
    finally:
        if bridge:bridge.close()
        rawprofiles.write_json(job/'report.json',report)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);rawprofiles.write_json(args.report,report)
    print('Report: '+str((job/'report.json').resolve()),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
