"""Authorization dispatch, cancellation and outcome forwarding; no USB writes."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from desktopapp import worker
from desktopapp.platforms import macos_authorization as macadmin
from desktopapp.paths import write_json


@pytest.mark.parametrize('action',['setup_all','direct_factory_reset','direct_verify','sound_install','connect'])
def test_camera_actions_need_mac_authorization(action):
    with patch.object(macadmin.sys,'platform','darwin'),patch.object(macadmin.os,'geteuid',return_value=501,create=True):
        assert macadmin.required(action)
    with patch.object(macadmin.sys,'platform','darwin'),patch.object(macadmin.os,'geteuid',return_value=0,create=True):
        assert not macadmin.required(action)


@pytest.mark.parametrize('action',['sound_import','compile_look','plugin_install','driver_scan'])
def test_offline_actions_do_not_request_privileges(action):
    with patch.object(macadmin.sys,'platform','darwin'),patch.object(macadmin.os,'geteuid',return_value=501,create=True):
        assert not macadmin.required(action)


def test_terminal_launcher_quoting_preserves_spaces_quotes_and_metacharacters(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'用户 data'))
    # The job folder exists on disk now; Windows test hosts forbid '"' in names.
    request=tmp_path/"quote '+$(touch should-not-run) & x;"/'request.private.json'
    request.parent.mkdir()
    prefix=['/Applications/A7 C2 "+$ app/Contents/MacOS/A7C2Tools','--worker',str(request)]
    environment={'HOME':'/Users/user name','PATH':'/usr/bin:/bin'}
    with patch('desktopapp.jobs.worker_command',return_value=list(prefix)):
        cmd=macadmin.command(request,501,20,environment)
    with patch('desktopapp.jobs.worker_command',return_value=list(prefix)):
        shell=macadmin.shell_command(request,501,20,environment)
    assert cmd[:3]==['/usr/bin/open','-a','Terminal']
    script=Path(cmd[3]).read_text(encoding='utf-8')
    assert Path(cmd[3]).parent==request.parent and 'password ' not in script
    lines=script.splitlines()
    sudo=[line for line in lines if line.startswith('/usr/bin/sudo ')]
    assert len(sudo)==1 and shlex.split(sudo[0])==['/usr/bin/sudo','/bin/sh','-c',shell]
    assert '--privileged-worker' in shell and 'A7C2_DESKTOP_DATA=' in shell and 'HOME=' in shell
    assert 'LIBUSB_DEBUG=4' in shell
    trap=shlex.split([line for line in lines if line.endswith(' HUP')][0])
    exit_file=str(request.parent/'authorization.exit')
    assert trap==['trap','echo closed > '+shlex.quote(exit_file)+'; exit 129','HUP']
    bash=shutil.which('bash')
    if bash:
        # A Windows bash shim cannot open a native Windows path. Check the
        # same script through stdin; native Mac CI also checks the real file.
        assert subprocess.run([bash,'-n'],input=script,text=True,encoding='utf-8',
                              capture_output=True,timeout=30).returncode==0


def make_request(tmp_path,monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA',str(tmp_path/'app'))
    request=tmp_path/'job/request.private.json'
    write_json(request,dict(action='direct_factory_reset',arguments={},job_dir=str(request.parent)))
    return request


def terminal(request,exit_code,status=None,stderr=''):
    """Fake `open -a Terminal`: the launcher finishes with ``exit_code``."""
    def run(*args,**kwargs):
        if status:write_json(request.parent/'status.private.json',status)
        if stderr:(request.parent/'authorization.stderr.log').write_text(stderr,encoding='utf-8')
        (request.parent/'authorization.exit').write_text(exit_code+'\n',encoding='utf-8')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    return run


def execute(request,run):
    with patch.object(macadmin.os,'getuid',return_value=501,create=True), \
         patch.object(macadmin.os,'getgid',return_value=20,create=True), \
         patch.object(macadmin.subprocess,'run',side_effect=run) as opened:
        code=macadmin.execute(request)
    return code,opened,json.loads((request.parent/'status.private.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('exit_code,stderr',[('closed',''),('1','sudo: 3 incorrect password attempts\n')])
def test_closed_terminal_or_wrong_password_never_starts_worker(tmp_path,monkeypatch,exit_code,stderr):
    request=make_request(tmp_path,monkeypatch)
    code,_,state=execute(request,terminal(request,exit_code,stderr=stderr))
    assert code==2
    assert state['error_type']=='MacAuthorizationCancelled'
    assert state['camera_io'] is False
    assert '尚未开始' in state['error']


def test_terminal_that_cannot_open_reports_not_started(tmp_path,monkeypatch):
    request=make_request(tmp_path,monkeypatch)
    code,_,state=execute(request,lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr='Unable to find application'))
    assert code==2 and state['error_type']=='MacAuthorizationError' and state['camera_io'] is False


@pytest.mark.parametrize('phase,code',[('SUCCEEDED',0),('FAILED',2)])
def test_native_worker_outcome_is_preserved_without_replay(tmp_path,monkeypatch,phase,code):
    request=make_request(tmp_path,monkeypatch)
    status=dict(phase=phase,action='direct_factory_reset',error='original camera error')
    result,opened,state=execute(request,terminal(request,str(code),status=status))
    assert result==code
    opened.assert_called_once()
    assert state['error']=='original camera error'
    assert json.loads((request.parent/'authorization.private.json').read_text())['password_stored'] is False


def test_closing_terminal_after_worker_started_waits_for_its_outcome(tmp_path,monkeypatch):
    request=make_request(tmp_path,monkeypatch)
    running=dict(phase='RUNNING',action='direct_factory_reset',pid=os.getpid())
    def finish(seconds):
        write_json(request.parent/'status.private.json',dict(phase='SUCCEEDED',action='direct_factory_reset',result={}))
    with patch.object(macadmin.time,'sleep',side_effect=finish) as sleep,patch.object(macadmin,'alive',return_value=True):
        code,_,state=execute(request,terminal(request,'closed',status=running))
    assert code==0 and state['phase']=='SUCCEEDED'
    sleep.assert_called()


def test_worker_that_ends_without_outcome_is_unknown_not_cancelled(tmp_path,monkeypatch):
    request=make_request(tmp_path,monkeypatch)
    running=dict(phase='RUNNING',action='direct_factory_reset',pid=999999)
    with patch.object(macadmin,'alive',return_value=False):
        code,_,state=execute(request,terminal(request,'closed',status=running))
    assert code==2 and state['error_type']=='MacWorkerEnded'
    assert 'camera_io' not in state and '结果未知' in state['error']


def test_dead_worker_without_terminal_exit_marker_cannot_wait_forever(tmp_path,monkeypatch):
    request=make_request(tmp_path,monkeypatch)
    def opened(*args,**kwargs):
        write_json(request.parent/'status.private.json',dict(phase='RUNNING',action='direct_factory_reset',pid=999999))
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    with patch.object(macadmin,'alive',return_value=False),patch.object(macadmin.time,'sleep',side_effect=AssertionError('Must not keep waiting')):
        code,_,state=execute(request,opened)
    assert code==2 and state['error_type']=='MacWorkerEnded'
    assert not (request.parent/'authorization.exit').exists()


def test_explicit_debug_level_is_preserved(tmp_path,monkeypatch):
    request=make_request(tmp_path,monkeypatch)
    shell=macadmin.shell_command(request,501,20,{'LIBUSB_DEBUG':'3'})
    assert 'LIBUSB_DEBUG=3' in shell


def test_dispatch_requests_authorization_before_loading_camera_backend(tmp_path,monkeypatch):
    request=make_request(tmp_path,monkeypatch)
    with patch.object(macadmin,'required',return_value=True),patch.object(macadmin,'execute',return_value=2) as authorized, \
            patch.object(worker,'run',side_effect=AssertionError('Camera must not run before authorization')):
        assert worker.execute_request(request)==2
    authorized.assert_called_once_with(request)
