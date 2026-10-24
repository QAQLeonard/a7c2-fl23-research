"""Combined persistent vertical setup, actual host ordering, simulated device."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from desktopapp.worker import setup_runtime
from desktopapp import worker
setup_runtime()
from looktool import bundle, checkpointworker, direct, verticalpersist
from test_checkpoint import Camera, Prop, values, fake_compile
from test_direct import SimDirect
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/vertical'))
from verticaltool import device


class PersistentVerticalTests(unittest.TestCase):
    def test_native_bank_disable_removes_full_or_partial_banks_only_after_off(self):
        from verticaltool import nativeportrait
        from looktool import resourceworker
        for mask in (7,1):
            with self.subTest(mask=mask):
                targets=[b'managed-'+bytes([i]) for i in range(3)]
                actual=[value if mask&(1<<i) else None for i,value in enumerate(targets)]
                self.camera.primary=0
                for records in (self.camera.ram,self.camera.saved):records[0][verticalpersist.SETTING]=Prop(b'\0',64)
                read=self.camera.read
                def current(path,missing=False):
                    return actual[device.ALIASES.index(path)] if path in device.ALIASES else read(path,missing)
                def remove(worker):
                    self.assertEqual(self.camera.primary,1)
                    self.assertEqual(self.camera.saved[0][verticalpersist.SETTING].data,b'\1')
                    actual[:]=[None]*3
                with patch.object(self.camera,'read',side_effect=current), \
                     patch.object(nativeportrait,'owned',side_effect=lambda value:bool(value and value.startswith(b'managed-'))), \
                     patch.object(nativeportrait,'targets',return_value=targets), \
                     patch.object(resourceworker.Resources,'delete',remove), \
                     patch.object(direct,'plan',side_effect=lambda c,r,m,**kw:self.plan(c,r,False)):
                    result=SimDirect(self.root/('native-off-'+str(mask)),factory=self.camera).run_direct(
                        'vertical_disable',version='2.01',power_confirmed=True)
                self.assertEqual(result['phase'],'AWAITING_RELOAD')
                self.assertEqual(actual,[None]*3)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.camera = Camera(values())
        self.camera.ram[0][verticalpersist.SETTING] = Prop(b'\1', 64)
        self.camera.saved = copy.deepcopy(self.camera.ram)
        self.camera.primary = 1
        self.camera.alias_mask = 0
        self.events = []
        self.fail_aliases = False
        self.bad_alias = False
        self.mount_busy = False
        self.originals = [bytes([i+65])*12 for i in range(3)]
        self.factory_patch = patch.object(Camera, '__call__', lambda obj, expected=None: obj)
        self.factory_patch.start(); self.addCleanup(self.factory_patch.stop)
        compile_patch = patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile)
        compile_patch.start(); self.addCleanup(compile_patch.stop)
        worker_patch = patch.object(device, 'Workers', side_effect=self.workers)
        worker_patch.start(); self.addCleanup(worker_patch.stop)
        original_read = self.camera.read
        def read(path, missing=False):
            if path in device.SOURCES:return self.originals[device.SOURCES.index(path)]
            if path in device.ALIASES:
                i = device.ALIASES.index(path)
                return (b'wrong' if self.bad_alias else self.originals[i]) if self.camera.alias_mask & (1<<i) else None
            return original_read(path, missing)
        self.camera.read = read
        original_save = self.camera.save_group
        def save(group):
            self.events.append(('save', self.camera.ram[0][verticalpersist.SETTING].data))
            original_save(group)
        self.camera.link.camera.saveBackup = save

    def workers(self, camera, journal):
        fixture = self
        class Workers:
            def probe(self):return dict(value=camera.primary, status=0)
            def ram(self, value):
                fixture.events.append(('primary', value)); camera.primary=value
                return dict(status=0)
            def aliases(self, mode):
                fixture.events.append(('aliases',mode))
                prior=camera.alias_mask
                if mode==1:
                    if fixture.fail_aliases:raise OSError('alias commit failed')
                    camera.alias_mask=7
                elif mode==2:camera.alias_mask=0
                return dict(status=0,readonly=0,source_ok=7,phase=1 if mode==0 else 5,mode=mode,
                    prior=prior,source_sizes=list(map(len,fixture.originals))) if not fixture.mount_busy else dict(
                    status=-16 if mode else 0,readonly=-16,source_ok=7,phase=1 if mode==0 else 5,mode=mode,
                    prior=prior,created=0,removed=prior if mode==2 else 0,rollback=0,source_sizes=list(map(len,fixture.originals)))
        return Workers()

    def plan(self, current, records, enabled):
        return dict(current), [{verticalpersist.SETTING: b'\0' if enabled else b'\1'},{}], None

    def test_combined_write_saves_on_before_reload_without_session_enable(self):
        job=SimDirect(self.root/'install',factory=self.camera)
        with patch.object(bundle,'plan',side_effect=lambda c,r,*a:self.plan(c,r,True)):
            result=job.run_direct('install_all',version='2.01',power_confirmed=True,
                bundle_options=dict(looks=[],fl23=False,sound=False,vertical_persistent=True))
            self.assertEqual(result['phase'],'AWAITING_RELOAD')
            self.assertEqual(self.camera.saved[0][verticalpersist.SETTING].data,b'\0')
            self.assertLess(self.events.index(('aliases',1)),self.events.index(('save',b'\0')))
            self.assertFalse(any(e[0]=='primary' for e in self.events))
            self.assertEqual(self.camera.primary,1) # No fake RAM-only success.
            self.camera.boot='new-cold-boot'
            with self.assertRaisesRegex(ValueError,'RAM'):job.verify_direct()
            self.camera.primary=0 # Model the native cold-load from saved ON.
            events=list(self.events)
            verified=job.verify_direct()
            self.assertEqual(verified['phase'],'LOADED')
            self.assertTrue(verified['vertical_result']['loaded_verified'])
            self.assertEqual([e for e in self.events[len(events):] if e!=('aliases',0)],[])

    def test_alias_failure_prevents_saved_enable_and_program_writes(self):
        self.fail_aliases=True
        job=SimDirect(self.root/'failed',factory=self.camera)
        with patch.object(bundle,'plan',side_effect=lambda c,r,*a:self.plan(c,r,True)),self.assertRaises(OSError):
            job.run_direct('install_all',version='2.01',power_confirmed=True,
                bundle_options=dict(looks=[],fl23=False,sound=False,vertical_persistent=True))
        self.assertEqual(self.camera.saved[0][verticalpersist.SETTING].data,b'\1')
        self.assertFalse(self.camera.saves)
        self.assertFalse(any(kind=='program' and mode==1 for kind,mode in self.camera.native_calls))

    def test_disable_saves_off_then_disables_running_before_resource_removal(self):
        self.camera.primary=0; self.camera.alias_mask=7
        for values_ in (self.camera.saved,self.camera.ram):values_[0][verticalpersist.SETTING]=Prop(b'\0',64)
        job=SimDirect(self.root/'off',factory=self.camera)
        with patch.object(direct,'plan',side_effect=lambda c,r,*a,**kw:self.plan(c,r,False)):
            result=job.run_direct('vertical_disable',version='2.01',power_confirmed=True)
        self.assertLess(self.events.index(('save',b'\1')),self.events.index(('primary',1)))
        self.assertLess(self.events.index(('primary',1)),self.events.index(('aliases',2)))
        self.assertEqual((self.camera.primary,self.camera.alias_mask),(1,0))
        self.assertEqual(result['phase'],'AWAITING_RELOAD')

    def test_unselected_unsaved_settings_are_not_accidentally_saved(self):
        key=0x02cf9999
        self.camera.ram[0][key]=Prop(b'new',64);self.camera.saved[0][key]=Prop(b'old',64)
        job=SimDirect(self.root/'unsaved',factory=self.camera)
        with patch.object(bundle,'plan',side_effect=lambda c,r,*a:self.plan(c,r,True)),self.assertRaisesRegex(ValueError,'Unselected unsaved'):
            job.run_direct('install_all',version='2.01',power_confirmed=True,
                bundle_options=dict(looks=[],fl23=False,sound=False,vertical_persistent=True))
        self.assertFalse(self.events);self.assertFalse(self.camera.saves)

    def test_partial_or_wrong_aliases_stop_before_saving(self):
        for mask,bad in ((3,False),(7,True)):
            self.camera.alias_mask=mask;self.bad_alias=bad
            job=SimDirect(self.root/str(mask),factory=self.camera)
            with patch.object(bundle,'plan',side_effect=lambda c,r,*a:self.plan(c,r,True)),self.assertRaises(ValueError):
                job.run_direct('install_all',version='2.01',power_confirmed=True,
                    bundle_options=dict(looks=[],fl23=False,sound=False,vertical_persistent=True))
            self.assertFalse(self.camera.saves)

    def test_gui_vertical_button_uses_saved_direct_job_not_legacy_session_toggle(self):
        from desktopapp import vertical_native
        from desktopapp.platforms import usb_drivers
        response=dict(phase='AWAITING_RELOAD',mode='vertical_enable',
            vertical_result=dict(saved='ON',running='OFF',persistent=True,loaded_verified=False))
        with patch.object(vertical_native,'run',return_value=response) as run, \
                patch.object(usb_drivers,'prepare',return_value={}), \
                patch.object(device,'execute',side_effect=AssertionError('no session toggle')):
            result=worker.run('vertical_enable',dict(workspace=str(self.root/'gui'),firmware='2.01',power_confirmed=True),self.root)
        self.assertEqual(run.call_args.args[0]['firmware'],'2.01')
        self.assertTrue(run.call_args.args[0]['power_confirmed'])
        self.assertEqual(result['phase'],'AWAITING_RELOAD')
        self.assertTrue(result['vertical_result']['persistent'])

    def test_disable_recovers_known_busy_mount_but_cannot_claim_loaded_until_readonly(self):
        self.camera.primary=0;self.camera.alias_mask=7;self.mount_busy=True
        for props in (self.camera.saved,self.camera.ram):props[0][verticalpersist.SETTING]=Prop(b'\0',64)
        job=SimDirect(self.root/'busy-off',factory=self.camera)
        with patch.object(direct,'plan',side_effect=lambda c,r,*a,**kw:self.plan(c,r,False)):
            result=job.run_direct('vertical_disable',version='2.01',power_confirmed=True)
            self.assertEqual(result['phase'],'AWAITING_RELOAD')
            self.assertTrue(result['readonly_deferred_busy'])
            self.assertEqual((self.camera.primary,self.camera.alias_mask),(1,0))
            self.camera.boot='new-boot'
            with self.assertRaisesRegex(ValueError,'只读'):job.verify_direct()
            self.mount_busy=False
            self.assertEqual(job.verify_direct()['phase'],'LOADED')
