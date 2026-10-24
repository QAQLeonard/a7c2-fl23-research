"""Check the actual packaged privileged worker on Mac CI, without USB."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))


def run(app):
    if sys.platform!='darwin':raise RuntimeError('Run on an Apple Silicon Mac')
    from desktopapp import jobs
    from desktopapp.platforms import macos_authorization as macadmin
    uid,gid=os.getuid(),os.getgid()
    if uid==0:raise RuntimeError('Start the smoke check as the normal login user')
    app=Path(app).resolve()
    with tempfile.TemporaryDirectory(prefix='a7c2-authorize-') as temporary:
        root=Path(temporary).resolve()
        data=root/'user data "+$';job=root/'user job';job.mkdir()
        request=job/'request.private.json'
        request.write_text(json.dumps(dict(action='mac_authorization_self_test',
            arguments=dict(workspace=str(root/'workspace')),job_dir=str(job))),encoding='utf-8')
        previous=os.environ.get('A7C2_DESKTOP_DATA')
        original=jobs.worker_command
        os.environ['A7C2_DESKTOP_DATA']=str(data)
        jobs.worker_command=lambda path:[str(app),'--worker',str(path)]
        try:
            command=macadmin.command(request,uid,gid,os.environ)
            assert command[:3]==['/usr/bin/open','-a','Terminal']
            subprocess.run(['/bin/bash','-n',command[3]],check=True)
            shell=macadmin.shell_command(request,uid,gid,os.environ)
            # CI has passwordless sudo and no Terminal session. Run exactly the
            # command the Terminal launcher passes to sudo, without a prompt.
            done=subprocess.run(['/usr/bin/sudo','-n','/bin/sh','-c',shell],timeout=90)
            if done.returncode:
                for name in ('authorization.stderr.log','worker.log'):
                    path=job/name
                    if path.exists():print(path.read_text(encoding='utf-8',errors='replace'))
                raise RuntimeError('Packaged authorized worker failed: '+str(done.returncode))
            status=json.loads((job/'status.private.json').read_text())
            result=status['result']
            assert status['phase']=='SUCCEEDED' and result['euid']==0 and result['camera_io'] is False
            assert Path(result['home']).resolve()==Path.home().resolve()
            assert Path(result['data_root'])==data
            for path in [*job.rglob('*'),*data.rglob('*')]:
                if path.is_file():assert path.stat().st_uid==uid,str(path)
            assert (data/'authorization-self-test.private.json').stat().st_uid==uid
            return dict(camera_io=False,terminal_launcher_parses=True,privileged_euid=0,
                user_home_preserved=True,ownership_returned=True)
        finally:
            jobs.worker_command=original
            if previous is None:os.environ.pop('A7C2_DESKTOP_DATA',None)
            else:os.environ['A7C2_DESKTOP_DATA']=previous


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,default=ROOT/'dist/A7C2Tools.app/Contents/MacOS/A7C2Tools')
    parser.add_argument('--report',type=Path,default=ROOT/'dist/mac-authorization-self-test.json')
    args=parser.parse_args();result=run(args.app)
    args.report.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
