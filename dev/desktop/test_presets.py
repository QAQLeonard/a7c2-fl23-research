"""Default six-pack resolution and immutable setup inputs. Never opens USB."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from desktopapp import allinone, presets
from looktool import bundle

AVAILABLE = (presets.ROOT / 'desktop-assets/presets' / presets.PACK / 'slot6.a7look').is_file()


class PresetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'A7C2_DESKTOP_DATA': str(self.root / 'app')})
        env.start(); self.addCleanup(env.stop)

    def test_custom_mode_keeps_selected_slots_without_injecting_defaults(self):
        options = dict(fl23=False, looks=[dict(slot=5, path='chosen.a7look')])
        result = presets.resolve(options)
        self.assertEqual(result, options)
        self.assertIsNot(result, options)

    def test_unknown_pack_and_ambiguous_inputs_are_rejected(self):
        for options in (dict(preset_pack='unknown'), dict(preset_pack=presets.PACK, looks=[dict(slot=1, path='chosen')])):
            with self.subTest(options=options), self.assertRaises(ValueError):presets.resolve(options)

    def test_missing_asset_stops_before_driver_or_device_actions(self):
        dispatch = Mock()
        with patch.object(presets, 'ROOT', self.root), self.assertRaisesRegex(ValueError, '尚未连接相机'):
            allinone.run(dict(workspace=str(self.root / 'setup'), firmware='2.01', power_confirmed=True,
                options=dict(preset_pack=presets.PACK)), dispatch=dispatch)
        dispatch.assert_not_called()
        self.assertFalse((self.root / 'setup/setup.private.json').exists())

    @unittest.skipUnless(AVAILABLE, 'Distribution six-pack is a separate asset')
    def test_exact_six_order_has_native_photo_and_original_profile(self):
        options = dict(preset_pack=presets.PACK)
        resolved = presets.resolve(options)
        self.assertNotIn('looks', options)
        _, rows = bundle.documents(resolved)
        self.assertEqual([r['slot'] for r in rows], list(range(1, 7)))
        self.assertEqual([r['name'] for r in rows], list(presets.NAMES))
        for row in rows:
            self.assertTrue(row['document']['native_photo'])
            self.assertTrue(row['document']['raw_profile']['dcp_base64'])

    @unittest.skipUnless(AVAILABLE, 'Distribution six-pack is a separate asset')
    def test_new_setup_copies_all_six_before_usb_and_resumes_saved_files(self):
        calls = []
        def dispatch(action, args, folder):
            calls.append((action, args))
            self.assertEqual(len(list((self.root / 'setup/inputs').glob('*.a7look'))), 6)
            if action=='voice_cleanup':
                return dict(phase='COMPLETED',voice_audio_removed=True,
                    voice_setting_locked_off=True,voice_menu_flags_verified=True)
            return dict(phase='AWAITING_RELOAD' if action == 'direct_install_all' else 'LOADED')
        args = dict(workspace=str(self.root / 'setup'), firmware='2.01', power_confirmed=True,
            options=dict(preset_pack=presets.PACK, fl23=True, sound=False, vertical=False))
        result = allinone.run(args, dispatch=dispatch)
        self.assertEqual(result['phase'], 'WAIT_RELOAD')
        original = presets.resolve(args['options'])['looks']
        for source, saved in zip(original, result['options']['looks']):
            self.assertEqual(Path(source['path']).read_bytes(), Path(saved['path']).read_bytes())
            self.assertEqual(Path(saved['path']).parent, self.root / 'setup/inputs')
        with patch.object(presets, 'resolve', side_effect=AssertionError('Do not replace saved inputs')):
            result = allinone.run(dict(args, options=dict(looks=[])), dispatch=dispatch)
        self.assertEqual(result['phase'], 'COMPLETE')
        self.assertEqual([a for a, _ in calls].count('direct_install_all'), 1)
        self.assertEqual([a for a, _ in calls].count('voice_cleanup'), 1)
        self.assertEqual(len(result['options']['looks']), 6)

    @unittest.skipUnless(AVAILABLE, 'Distribution six-pack is a separate asset')
    def test_mislabeled_asset_is_rejected(self):
        from looktool import lookfile
        real_read = lookfile.read
        def swapped(path):
            doc = real_read(path); doc['name'] = 'Wrong'; return doc
        with patch.object(lookfile, 'read', side_effect=swapped), self.assertRaisesRegex(ValueError, '名称'):
            presets.resolve(dict(preset_pack=presets.PACK))
