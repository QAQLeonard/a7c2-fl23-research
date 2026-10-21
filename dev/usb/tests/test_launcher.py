"""Shared launcher guards and actual Windows5.1/CMD argument forwarding. No USB."""
from contextlib import redirect_stdout,redirect_stderr
import importlib.util
import io,json,os
from pathlib import Path
import shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('a7c2_launcher',ROOT/'src/launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

class LauncherTests(unittest.TestCase):
    def test_check_is_stdlib_only_and_never_prepares_or_executes(self):
        with patch.object(launcher,'prepare') as prepare,patch.object(launcher,'execute') as execute,redirect_stdout(io.StringIO()) as out:
            self.assertEqual(launcher.main(['--check']),0)
        self.assertFalse(json.loads(out.getvalue())['PowerShell_required']);prepare.assert_not_called();execute.assert_not_called()
    def test_invalid_fl23_command_stops_before_setup(self):
        with patch.object(launcher,'prepare') as prepare,redirect_stderr(io.StringIO()):
            self.assertEqual(launcher.main(['fl23','unsafe-unknown-command']),1)
        prepare.assert_not_called()
    def test_help_and_package_check_do_not_install_dependencies(self):
        for command in ['--help','check-package']:
            with patch.object(launcher,'prepare') as prepare,patch.object(launcher,'execute',return_value=0) as execute:
                self.assertEqual(launcher.main(['fl23',command]),0)
            prepare.assert_not_called()
            self.assertEqual(execute.call_args.args[0][-1],command)
    def test_current_backup_command_is_forwarded(self):
        with patch.object(launcher,'prepare',return_value=Path(sys.executable)),patch.object(launcher,'execute',return_value=0) as execute:
            self.assertEqual(launcher.main(['fl23','backup','--workspace','chosen folder']),0)
        self.assertEqual(execute.call_args.args[0][-3:],['backup','--workspace','chosen folder'])
    def test_compatible_prepare_preserves_version_and_independent_backup(self):
        args=['fl23','prepare','--workspace','work folder','--backup-copy','backup folder','--firmware-version','2.01']
        with patch.object(launcher,'prepare',return_value=Path(sys.executable)),patch.object(launcher,'execute',return_value=0) as execute:
            self.assertEqual(launcher.main(args),0)
        self.assertEqual(execute.call_args.args[0][-7:],args[1:])
    def test_manual_device_command_executes_once_and_returns_failure(self):
        args=['fl23','install','--workspace',r'D:\space and 中文\work','--battery-percent','82']
        with patch.object(launcher,'prepare',return_value=Path(sys.executable)),patch.object(launcher,'execute',return_value=9) as run:
            self.assertEqual(launcher.main(args),9)
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.args[0][-5:],args[-5:])
    def test_looks_uses_module_path_and_passes_help_and_input_arguments(self):
        with patch.object(launcher,'prepare',return_value=Path(sys.executable)) as prepare,patch.object(launcher,'execute',return_value=0) as run:
            self.assertEqual(launcher.main(['looks','--research','inspect',r'D:\color docs\profiles\参考.dcp']),0)
        prepare.assert_called_once_with('looks',True)
        self.assertEqual(run.call_args.args[0][-2:],['inspect',r'D:\color docs\profiles\参考.dcp'])
        self.assertEqual(run.call_args.args[2],ROOT/'src/looks')
        with patch.object(launcher,'prepare',return_value=Path(sys.executable)),patch.object(launcher,'execute',return_value=0) as run:
            self.assertEqual(launcher.main(['looks','--help']),0)
        self.assertEqual(run.call_args.args[0][-1],'--help')
    def test_setup_only_never_executes_a_device_or_look_command(self):
        with patch.object(launcher,'prepare',return_value=Path(sys.executable)),patch.object(launcher,'execute') as run,redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(['fl23','--setup-only']),0)
        run.assert_not_called()
    def test_workflow_specific_checks_never_prepare_dependencies(self):
        for workflow in ['fl23','looks']:
            with patch.object(launcher,'prepare') as prepare,redirect_stdout(io.StringIO()) as out:
                self.assertEqual(launcher.main([workflow,'--check']),0)
            prepare.assert_not_called();self.assertEqual(json.loads(out.getvalue())['workflow'],workflow)
    def test_incomplete_environment_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.venv').mkdir();sentinel=root/'.venv/keep';sentinel.write_text('original')
            with patch.object(launcher,'ROOT',root),patch.object(launcher,'PYTHON',root/'.venv/Scripts/python.exe'),patch.object(launcher,'execute') as execute:
                with self.assertRaisesRegex(RuntimeError,'incomplete'):launcher.prepare('looks')
            self.assertEqual(sentinel.read_text(),'original');execute.assert_not_called()
    def test_dependency_setup_failure_cannot_start_camera(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);python=root/'.venv/Scripts/python.exe';python.parent.mkdir(parents=True);python.touch()
            with patch.object(launcher,'ROOT',root),patch.object(launcher,'PYTHON',python),patch.object(launcher,'execute',side_effect=[0,1,1]) as run,redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'Dependency installation failed'):launcher.prepare('fl23')
            self.assertEqual(run.call_count,3)
            self.assertFalse(any('app.py' in str(arg) for call in run.call_args_list for arg in call.args[0]))

@unittest.skipUnless(os.name=='nt','Windows entrypoint checks')
class WindowsEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='a7c2 entry space ');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)/'相機 tools';self.base.mkdir()
        for name in ['FL23.cmd','dev/windows/bootstrap.cmd','dev/windows/Start.ps1','src/launcher.py','src/fl23/Start.cmd','src/fl23/Start.ps1']:
            target=self.base/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
        self.env=dict(os.environ,A7C2_PYTHON=sys.executable,PYTHONUTF8='1')
    def run_cmd(self,path,*args):
        line='"'+os.environ.get('COMSPEC','cmd.exe')+'" /d /c call "'+str(path)+'" '+subprocess.list2cmdline(list(args))
        return subprocess.run(line,cwd=self.base,env=self.env,text=True,encoding='utf-8',capture_output=True,timeout=30)
    def test_exact_cmd_environment_check_in_unicode_space_path(self):
        result=self.run_cmd(self.base/'FL23.cmd','--check')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(json.loads(result.stdout)['PowerShell_required']);self.assertFalse((self.base/'.venv').exists())
    def test_windows_powershell51_wrapper_and_parser(self):
        shell=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
        result=subprocess.run([shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(self.base/'dev/windows/Start.ps1'),'--check'],cwd=self.base,env=self.env,text=True,encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(json.loads(result.stdout)['camera_io'])
        version=subprocess.run([shell,'-NoProfile','-NonInteractive','-Command','$PSVersionTable.PSVersion.ToString()'],text=True,capture_output=True,timeout=30)
        self.assertTrue(version.stdout.strip().startswith('5.1.'),version.stdout)
    def test_powershell7_wrapper_when_available(self):
        shell=shutil.which('pwsh')
        if not shell:self.skipTest('PowerShell7 is optional and not installed')
        result=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(self.base/'dev/windows/Start.ps1'),'--check'],cwd=self.base,env=self.env,text=True,encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(json.loads(result.stdout)['camera_io'])
    def test_installed_python_discovery_without_override(self):
        env=dict(self.env);env.pop('A7C2_PYTHON',None)
        command='"'+os.environ.get('COMSPEC','cmd.exe')+'" /d /c call "'+str(self.base/'FL23.cmd')+'" --check'
        result=subprocess.run(command,cwd=self.base,env=env,text=True,encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['python_bits'],64)
    def test_original_fl23_entry_preserves_workflow_and_exit_code(self):
        (self.base/'src/launcher.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\nraise SystemExit(7)\n',encoding='utf-8')
        for name,workflow in [('FL23.cmd','fl23')]:
            result=self.run_cmd(self.base/name,'--help')
            self.assertEqual(result.returncode,7,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout),[workflow,'--help'])
    def test_legacy_fl23_cmd_forwards_unicode_arguments_once(self):
        # A stub replaces only the host launcher to observe argv. No deps/USB.
        (self.base/'src/launcher.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:],ensure_ascii=True))\nraise SystemExit(7)\n',encoding='utf-8')
        result=self.run_cmd(self.base/'src/fl23/Start.cmd','verify','--workspace','D:\資料 test\工作')
        self.assertEqual(result.returncode,7,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout),['fl23','verify','--workspace','D:\資料 test\工作'])
    def test_old_powershell_wrapper_preserves_failure_and_arguments(self):
        (self.base/'src/launcher.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\nraise SystemExit(7)\n',encoding='utf-8')
        shell=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
        result=subprocess.run([shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(self.base/'src/fl23/Start.ps1'),'verify','--workspace','D:\資料 test\工作'],cwd=self.base,env=self.env,text=True,encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(result.returncode,7,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout),['fl23','verify','--workspace','D:\資料 test\工作'])

if __name__=='__main__':unittest.main()
