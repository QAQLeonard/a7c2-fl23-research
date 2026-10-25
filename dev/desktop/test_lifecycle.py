"""Real host dispatch/discovery across repeated install and restore cycles.

The USB camera and program planner are simulated; transaction persistence,
write/readback ordering, loaded-state checks and GUI-worker routing are real.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktopapp import worker
from desktopapp.paths import data_root
from looktool import bundle, checkpointworker, direct, lookfile
from test_checkpoint import Camera, KEYS, fake_compile, values
from test_direct import SimDirect


class LifecycleTests(unittest.TestCase):
    def test_repeated_install_restore_without_photo_checkbox_or_old_job_replay(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ,A7C2_DESKTOP_DATA=temporary):
            root=data_root();work=root/'work';work.mkdir()
            camera=Camera(values());before=copy.deepcopy(camera.ram)
            compiled=root/'test.a7look'
            lookfile.write(compiled,'Test',bytes(1215),method='test fixture',attribution='test')
            def plan(current,records,mode,**kw):
                marker=0 if mode=='factory_reset' else 1
                target=dict(current);ap=bytearray(current['appFw.so']);ap[3]=marker
                target['appFw.so']=bytes(ap)
                return target,[{KEYS[0]:bytes([marker])},{}],None
            def looks(current,records,*args):return plan(current,records,'look_import')
            def job(folder,*args,**kw):return SimDirect(folder,factory=camera)
            reference=str(root/'provided-reference.json')
            def run(action,folder,**args):
                return worker.run(action,dict(workspace=str(work/folder),firmware='2.01',power_confirmed=True,
                    factory=reference,restore_voice=False,**args),root)
            def boot_and_verify(folder,number):
                camera.boot='cold-boot-'+str(number)
                return run('direct_verify',folder,accepted=False)
            with patch.object(Camera,'__call__',lambda obj,expected=None:obj), \
                    patch.object(checkpointworker,'compile_worker',side_effect=fake_compile), \
                    patch.object(direct,'plan',side_effect=plan),patch.object(bundle,'plan',side_effect=looks), \
                    patch.object(direct,'DirectJob',side_effect=job), \
                    patch('desktopapp.official.prepare_restore',return_value=({},reference,None)) as prepare, \
                    patch('desktopapp.official.load_restore',return_value={}):
                # A cold reload clears possible RAM auditions even when disk
                # bytes already match. Verification must not repeat writes.
                first=run('direct_factory_reset','original')
                self.assertEqual(first['phase'],'AWAITING_RELOAD')
                self.assertEqual(boot_and_verify('original',0)['phase'],'LOADED')
                original_bytes=(work/'original/direct.private.json').read_bytes()
                for cycle in (1,2):
                    install='install-'+str(cycle)
                    run('direct_looks_import',install,looks=[dict(slot=5,path=str(compiled))])
                    boot_and_verify(install,cycle*2)
                    restore='restore-'+str(cycle)
                    result=run('direct_factory_reset',restore,failed_workspace=str(work/'original'))
                    self.assertEqual(result['workspace'],str(work/restore))
                    self.assertEqual(result['phase'],'AWAITING_RELOAD')
                    self.assertEqual(boot_and_verify(restore,cycle*2+1)['phase'],'LOADED')
                    state=json.loads((work/restore/'direct.private.json').read_text())
                    self.assertFalse(state['physical_checks_accepted'])
                self.assertEqual((work/'original/direct.private.json').read_bytes(),original_bytes)
                self.assertEqual(camera.native_calls.count(('program',1)),4)
                self.assertEqual(camera.ram,before)
                self.assertEqual(prepare.call_count,3)
