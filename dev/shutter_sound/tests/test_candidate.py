import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import candidate
import trial


def probe(kind=3, mode='2', audio=0):
    entries = [dict(slot=i, priority=6, kind=0, first_length=0, loop_length=0, length=1216, address=0x100000) for i in range(25)]
    entries[2]['kind'] = kind
    entries[0]['kind'], entries[1]['kind'] = 1, 2
    return dict(entries=entries, image_mode=mode, audio_signals=audio, model_index=16)


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ap = bytearray(0x288549c)
        ap[:4] = b'\x7fELF'
        ap[0x286cde8:0x286cdfc] = bytes.fromhex('20af029000601391008c409100800391c0035fd6')
        ap[0x2885488:0x288549c] = bytes.fromhex('40ae02f0006013910004429100002f91c0035fd6')
        cp = bytearray(max(at+len(raw) for at,raw in candidate.CP_GUARDS)+100)
        cp[candidate.SELECTOR_TABLE:candidate.SELECTOR_TABLE+5] = candidate.TABLE_BEFORE
        for at, raw in candidate.CP_GUARDS:cp[at:at+len(raw)] = raw
        for at, old, new in candidate.WINDOWS:cp[at:at+len(old)] = old
        cp[candidate.START:candidate.START + len(candidate.CONTEXT)] = candidate.CONTEXT
        cls.ap, cls.cp = bytes(ap), bytes(cp)

    def test_only_sound_windows_change_and_inverse_preserves_later_edits(self):
        out = candidate.patch(self.ap, self.cp)
        self.assertEqual(out['appFw.so'], self.ap)
        changes = [i for i, (a, b) in enumerate(zip(self.cp, out['cpapp-b.bin'])) if a != b]
        self.assertTrue(changes)
        allowed={at+i for at,old,_ in candidate.WINDOWS for i in range(len(old))}
        self.assertTrue(set(changes)<=allowed)
        self.assertTrue(candidate.is_current(out['cpapp-b.bin']))
        later = bytearray(out['cpapp-b.bin']); later[100] = 91
        restored = candidate.patch(self.ap, bytes(later), restore=True)['cpapp-b.bin']
        expected = bytearray(self.cp); expected[100] = 91
        self.assertEqual(restored, expected)

    def test_context_conflict_rejected(self):
        cp = bytearray(self.cp); cp[candidate.START] ^= 1
        with self.assertRaisesRegex(ValueError, 'context'):
            candidate.patch(self.ap, bytes(cp))

    def test_getter_conflict_rejected(self):
        ap = bytearray(self.ap); ap[0x2885488] ^= 1
        with self.assertRaisesRegex(ValueError, 'getter'):
            candidate.patch(bytes(ap), self.cp)

    def test_live_registry_is_a_required_binding(self):
        candidate.require_registry(probe())
        with self.assertRaisesRegex(ValueError, 'kind3'):
            candidate.require_registry(probe(kind=4))
        with self.assertRaisesRegex(ValueError, 'retained'):
            candidate.require_registry(probe(mode='9'))

    def test_private_probe_binary_layout(self):
        raw = bytearray(1256)
        struct.pack_into('<8sIIqQII', raw, 0, b'A7SND001', 1, 16, 0, 0x10000000, 0, 0)
        at = 40 + 2 * 48
        raw[at + 1] = 3
        struct.pack_into('<Q', raw, at + 16, 1216)
        struct.pack_into('<Q', raw, at + 32, 0x400000)
        for i in range(2):
            at = 40 + i * 48
            raw[at + 1] = i + 1
            struct.pack_into('<Q', raw, at + 16, 128)
            struct.pack_into('<Q', raw, at + 32, 0x400000)
        raw[1240:1242] = b'2\n'
        candidate.require_registry(candidate.parse_probe(bytes(raw)))
        struct.pack_into('<q', raw, 16, -84)
        with self.assertRaisesRegex(ValueError, 'failed'):
            candidate.parse_probe(bytes(raw))

    def _workflow(self, test, *, enabled=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'job'
            cp=candidate.patch(self.ap,self.cp)['cpapp-b.bin'] if enabled else self.cp
            if enabled=='legacy':
                legacy=bytearray(self.cp)
                legacy[candidate.OFFSET:candidate.OFFSET+2]=candidate.AFTER
                cp=bytes(legacy)
            state = {'files': {'/usr/lib/appFw.so': self.ap, '/cp/cpapp-b.bin': cp},
                     'mode': '2', 'calls': [], 'audio': 0}
            class Camera:
                identity = {'model': 'ILCE-7CM2', 'serial_sha256': 'synthetic-body'}
                core = None
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self, path): return state['files'][path]
                def snapshot(self, memory): return b'unchanged settings'
                def records(self, raw): return raw
            def camera(expected=None):
                if expected is not None: self.assertEqual(expected, Camera.identity)
                return Camera()
            plans = {}
            def build(ap, cp, out, zig=None, *, restore=False):
                target = candidate.patch(ap, cp, restore=restore)
                out = Path(out); out.mkdir()
                plan = dict(native_program={'path': str(out / 'program.so'), 'windows': 1, 'sizes': [len(ap), len(cp)]})
                plans[plan['native_program']['path']] = target
                return plan, target
            def native(camera, root, job, blob, kind, mode=0, plan=None):
                state['calls'].append((kind, mode))
                if kind == 'probe': return probe(mode=state['mode'], audio=state['audio'])
                if kind == 'program' and mode:
                    for name, data in plans[str(blob)].items():
                        state['files']['/usr/lib/appFw.so' if name == 'appFw.so' else '/cp/cpapp-b.bin'] = data
                if kind == 'wbi' and mode: state['mode'] = '0'
                return {}
            with patch.object(candidate, 'build', build), patch.object(trial, 'run_native', native), \
                 patch('looktool.devicesettings.compare'):
                trial.preflight(root, Path(tmp) / 'backup2', camera_factory=camera)
                test(root, state, camera)

    def test_preflight_has_no_program_write(self):
        def check(root, state, camera):
            self.assertNotIn(('program', 1), state['calls'])
            self.assertIn(('wbi', 0), state['calls'])
            self.assertEqual(state['mode'], '2')
            self.assertEqual(state['files']['/cp/cpapp-b.bin'], self.cp)
            self.assertEqual(json.loads((root / 'job.private.json').read_text())['phase'], 'ready')
        self._workflow(check)

    def test_existing_enabled_sound_is_adopted_without_program_or_wbi_write(self):
        def check(root,state,camera):
            import zipfile
            saved=json.loads((root/'job.private.json').read_text())
            self.assertTrue(saved['adopted_existing_enabled'])
            self.assertEqual(saved['phase'],'written')
            self.assertFalse(saved['camera_firmware_written'])
            self.assertNotIn(('program',1),state['calls'])
            self.assertNotIn(('wbi',1),state['calls'])
            with zipfile.ZipFile(root/'before.private.zip') as z:
                self.assertEqual(set(z.namelist()),{'native-sound-branch.bin','ap-sound-getters.bin'})
                self.assertLess(sum(i.file_size for i in z.infolist()),100)
            trial.change(root,restore=True,camera_factory=camera)
            self.assertEqual(state['files']['/cp/cpapp-b.bin'],self.cp)
        self._workflow(check,enabled=True)

    def test_audition_adoption_never_enables_a_disabled_branch(self):
        def check(root,state,camera):
            calls=list(state['calls'])
            path=root.parent/'audition-adopt'
            with self.assertRaisesRegex(ValueError,'尚未开启'):
                trial.preflight(path,root.parent/'adopt-backup',camera_factory=camera,
                                expected=camera().identity,adopt_only=True)
            self.assertEqual(state['calls'],calls)
            self.assertEqual(state['files']['/cp/cpapp-b.bin'],self.cp)
            self.assertTrue(trial.completed_readonly_failure(json.loads((path/'job.private.json').read_text())))
        self._workflow(check)

    def test_legacy_enable_prepares_a_real_upgrade_instead_of_adopting(self):
        def check(root,state,camera):
            saved=json.loads((root/'job.private.json').read_text())
            self.assertEqual(saved['phase'],'ready')
            self.assertFalse(saved.get('adopted_existing_enabled',False))
            self.assertNotIn(('program',1),state['calls'])
            self.assertEqual(candidate.sound_state(state['files']['/cp/cpapp-b.bin']),'legacy')
            adoption=root.parent/'no-silent-rom-write'
            with self.assertRaisesRegex(ValueError,'旧版快门声音'):
                trial.preflight(adoption,root.parent/'second-backup',camera_factory=camera,adopt_only=True)
            self.assertNotIn(('program',1),state['calls'])
            trial.change(root,camera_factory=camera)
            self.assertTrue(candidate.is_current(state['files']['/cp/cpapp-b.bin']))
            self.assertTrue(json.loads((root/'job.private.json').read_text())['electronic_only_gate'])
        self._workflow(check,enabled='legacy')

    def test_apply_restore_preserve_new_unrelated_changes(self):
        def check(root, state, camera):
            trial.change(root, camera_factory=camera)
            later = bytearray(state['files']['/cp/cpapp-b.bin']); later[100] = 45
            state['files']['/cp/cpapp-b.bin'] = bytes(later)
            trial.change(root, restore=True, camera_factory=camera)
            expected = bytearray(self.cp); expected[100] = 45
            self.assertEqual(state['files']['/cp/cpapp-b.bin'], expected)
            self.assertEqual(state['calls'].count(('wbi', 1)), 1)
        self._workflow(check)

    def test_unknown_write_is_not_replayed(self):
        def check(root, state, camera):
            original = trial.run_native
            def lose(*args, **kwargs):
                if args[4:6] == ('program', 1):
                    original(*args, **kwargs)
                    raise TimeoutError('lost ACK after write')
                return original(*args, **kwargs)
            with patch.object(trial, 'run_native', lose):
                with self.assertRaises(TimeoutError): trial.change(root, camera_factory=camera)
            calls = list(state['calls'])
            with self.assertRaisesRegex(ValueError, 'known writable'):
                trial.change(root, camera_factory=camera)
            self.assertEqual(state['calls'], calls)
            self.assertTrue(candidate.is_current(state['files']['/cp/cpapp-b.bin']))
            self.assertNotIn(('wbi', 1), calls)
        self._workflow(check)

    def test_unsupported_reload_route_stops_before_firmware_write(self):
        def check(root, state, camera):
            original = trial.run_native
            def unsupported(*args, **kwargs):
                if args[4:6] == ('wbi', 0): raise ValueError('Unsupported retained image device')
                return original(*args, **kwargs)
            with patch.object(trial, 'run_native', unsupported):
                with self.assertRaisesRegex(ValueError, 'retained image'):
                    trial.change(root, camera_factory=camera)
            self.assertNotIn(('program', 1), state['calls'])
            self.assertEqual(state['files']['/cp/cpapp-b.bin'], self.cp)
        self._workflow(check)


if __name__ == '__main__': unittest.main()
