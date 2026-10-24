"""Optional original-firmware planning checks. No camera or driver access."""
import copy
import json
import os
from pathlib import Path
import tempfile
import importlib.util
import unittest
from unittest.mock import patch

from desktopapp import official
from desktopapp.worker import setup_runtime
setup_runtime()
from looktool import direct, photoformat, photobasis, photoio, lookfile, device_layout, nameworker
from test_checkpoint import stock_names
from looktool.devicesession import modules


@unittest.skipUnless(os.environ.get('A7C2_ORIGINAL_REFERENCE') and os.environ.get('A7C2_RESEARCH_FIXTURES'),
                     'Needs private reference and known program fixtures; never a camera')
class ReferencePlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = official.load(os.environ['A7C2_ORIGINAL_REFERENCE'])
        cls.core = modules()[1]
        index = json.loads(Path(os.environ['A7C2_RESEARCH_FIXTURES']).read_text())
        cls.ap = Path(index['six_ap']).read_bytes()
        cls.cp = Path(index['v4_cp']).read_bytes()
        cls.records = cls.core.backup_records(cls.stock['CX89700_ALLLANG.bin'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = {'appFw.so': self.ap, 'cpapp-b.bin': self.cp,
            **{'resources/' + n: stock_names() for n in nameworker.filenames()}}
        self.props = copy.deepcopy(self.records)
        for key, at in ((0x02a40001, 0x100), (0x02a4000d, 0x80)):
            raw = bytearray(self.props[1][key].data)
            raw[at:at + 8] = b'BODYDATA'
            self.props[1][key] = self.props[1][key]._replace(data=bytes(raw))

    def apply(self, mode, **kwargs):
        target, wanted, _ = direct.plan(self.current, self.props, mode, **kwargs)
        for chip in (0, 1):
            for key, value in wanted[chip].items():
                self.props[chip][key] = self.props[chip][key]._replace(data=value)
        self.current = target
        return target, wanted

    def test_fl23_remove_and_enable_preserves_every_lut_program_byte(self):
        enabled, _ = self.apply('fl23_enable')
        removed, _ = self.apply('fl23_disable')
        self.assertEqual(removed['cpapp-b.bin'], enabled['cpapp-b.bin'])
        expected = bytearray(enabled['appFw.so'])
        for at in direct.MENU_FLAGS:
            expected[at:at + 2] = b'\0\0'
        self.assertEqual(removed['appFw.so'], bytes(expected))
        restored, _ = self.apply('fl23_enable')
        self.assertEqual(restored, enabled)

    def test_native_vertical_saved_switch_composes_with_looks_and_factory_reset(self):
        from looktool import verticalpersist, bundle
        before=copy.deepcopy(self.props)
        options=dict(looks=[],fl23=False,sound=False,vertical_persistent=True)
        target,wanted,_=bundle.plan(self.current,self.props,options,[])
        self.assertEqual(target,self.current) # No speculative program hook.
        self.assertEqual(wanted,[{verticalpersist.SETTING:b'\0'},{}])
        self.props[0][verticalpersist.SETTING]=self.props[0][verticalpersist.SETTING]._replace(data=b'\0')
        _,off,_=direct.plan(target,self.props,'factory_reset',factory=official.builtin())
        self.assertEqual(off[0][verticalpersist.SETTING],b'\1')
        self.assertEqual(self.props[1],before[1])

    def test_stock_recovery_resets_project_regions_but_keeps_body_calibration(self):
        self.apply('fl23_enable')
        before = copy.deepcopy(self.props)
        result, wanted = self.apply('factory_reset', factory=self.stock)
        self.assertEqual(result['appFw.so'], self.stock['appFw.so'])
        self.assertEqual(result['cpapp-b.bin'], self.stock['cpapp-b.bin'])
        for key, spans in direct.color_regions().items():
            a, b = before[1][key].data, wanted[1][key]
            expected = bytearray(a)
            for at, size in spans:
                expected[at:at + size] = self.records[1][key].data[at:at + size]
            self.assertEqual(b, bytes(expected))
        self.assertEqual(self.props[1][0x02a40001].data[0x100:0x108], b'BODYDATA')
        self.assertEqual(self.props[1][0x02a4000d].data[0x80:0x88], b'BODYDATA')
        for key, prop in before[0].items():
            if key not in wanted[0]:
                self.assertEqual(self.props[0][key], prop)

    def test_builtin_original_regions_remove_all_known_legacy_program_changes(self):
        self.apply('fl23_enable')
        restored, wanted = self.apply('factory_reset', factory=official.builtin())
        self.assertEqual(restored['appFw.so'], self.stock['appFw.so'])
        self.assertEqual(restored['cpapp-b.bin'], self.stock['cpapp-b.bin'])

    def test_builtin_reference_reverses_both_evf_pending_trials(self):
        from looktool import uploadpending, uploadgate
        for _, at, before, _ in uploadpending.WINDOWS:
            if any(offset == at for offset, _ in uploadpending.factory_windows()):
                raw = bytes.fromhex(before)
                self.assertEqual(self.stock['cpapp-b.bin'][at:at + len(raw)], raw)
        underlay = uploadgate.restore(self.cp)
        previous = bytearray(underlay)
        for _, at, _, after in uploadpending.TRIAL2_WINDOWS:
            raw = bytes.fromhex(after)
            previous[at:at + len(raw)] = raw
        for trial in (bytes(previous), uploadpending.install(self.cp)):
            self.current['appFw.so'] = self.ap
            self.current['cpapp-b.bin'] = trial
            restored, _ = self.apply('factory_reset', factory=official.builtin())
            self.assertEqual(restored['appFw.so'], self.stock['appFw.so'])
            self.assertEqual(restored['cpapp-b.bin'], self.stock['cpapp-b.bin'])

    def test_normal_desktop_import_uses_and_preserves_the_tested_evf_layout(self):
        from looktool import uploadpending
        look = self.make_look(1, 24)
        self.apply('look_import', slot=1, look=look)
        installed = dict(self.current)
        self.assertTrue(uploadpending.active(installed['cpapp-b.bin']))
        for _, at, _, after in uploadpending.WINDOWS:
            raw = bytes.fromhex(after)
            self.assertEqual(installed['cpapp-b.bin'][at:at + len(raw)], raw)
        self.apply('look_import', slot=1, look=look)
        self.assertEqual(self.current, installed)
        self.apply('look_import', slot=2, look=self.make_look(2, -24))
        self.assertTrue(uploadpending.active(self.current['cpapp-b.bin']))
        self.apply('slot_default', slot=2)
        self.assertTrue(uploadpending.active(self.current['cpapp-b.bin']))

    def test_builtin_reference_preserves_unrelated_program_regions(self):
        for name in ('appFw.so', 'cpapp-b.bin'):
            changed = bytearray(self.current[name])
            changed[0x70000] ^= 1
            self.current[name] = bytes(changed)
        restored, _ = self.apply('factory_reset', factory=official.builtin())
        for name in ('appFw.so', 'cpapp-b.bin'):
            self.assertEqual(restored[name][0x70000], self.stock[name][0x70000] ^ 1)

    @unittest.skipUnless(importlib.util.find_spec('keystone'), 'Optional sound assembler')
    def test_builtin_reference_reverses_the_real_sound_hook_and_reader_changes(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'dev/shutter_sound'))
        import boot_sound
        modified = boot_sound.patch(self.stock['appFw.so'], boot_sound.windows(self.stock['appFw.so']))
        self.current['appFw.so'] = modified
        restored, _ = self.apply('factory_reset', factory=official.builtin())
        self.assertEqual(restored['appFw.so'], self.stock['appFw.so'])

    def make_look(self, slot, amount):
        cp = self.current['cpapp-b.bin']
        if device_layout.structural(self.current['appFw.so'], cp).get('first_install'):
            cp = device_layout.replace(self.current['appFw.so'], cp, {slot: bytes(1215)},
                hash_checks=False, transitions=False)[2]['cpapp-b.bin']
        bank = photoformat.extract_bank(cp,
            self.props[1][0x02a40001].data, self.props[1][0x02a4000d].data,
            gamma_table_va=0x1209480, regular_row=0, still_row=10, color_parameter=0)[0]
        delta = photobasis.pack(bank, tone=[amount, 0, 0])[1]
        path = self.root / ('look-' + str(slot) + '.a7look')
        return lookfile.write(path, 'Look ' + str(slot), bytes([slot]) * 1215,
            method='offline fixture', attribution='test', native_photo=delta)

    def test_reset_one_native_slot_retains_other_native_slot_exactly(self):
        self.apply('look_import', slot=5, look=self.make_look(5, 32))
        self.apply('look_import', slot=6, look=self.make_look(6, -32))
        before_cp = self.current['cpapp-b.bin']
        before_table = device_layout.tables(before_cp)[5]
        before_state = photoio.inspect(before_cp)
        before_settings = copy.deepcopy(self.props)
        self.apply('slot_default', slot=5)
        self.assertEqual(device_layout.tables(self.current['cpapp-b.bin'])[5], before_table)
        state = photoio.inspect(self.current['cpapp-b.bin'])
        self.assertEqual(state['knobs'][5], before_state['knobs'][5])
        self.assertEqual(state['mask'] & 16, 0)
        self.assertEqual(state['mask'] & 32, 32)
        changed_keys = direct.recipe_defaults(self.ap, [5])
        for key, value in before_settings[0].items():
            if key not in changed_keys:
                self.assertEqual(self.props[0][key], value)
        self.assertEqual(self.props[1], before_settings[1])

    def test_each_of_six_slots_can_be_imported_reimported_and_reset_independently(self):
        for slot in range(1, 7):
            with self.subTest(slot=slot):
                self.current = {'appFw.so': self.stock['appFw.so'], 'cpapp-b.bin': self.stock['cpapp-b.bin'],
                    **{'resources/' + n: stock_names() for n in nameworker.filenames()}}
                self.props = copy.deepcopy(self.records)
                before = copy.deepcopy(self.props)
                look = self.make_look(slot, 12 + slot)
                self.apply('look_import', slot=slot, look=look)
                installed = dict(self.current)
                self.assertEqual(device_layout.structural(installed['appFw.so'], installed['cpapp-b.bin'])['mask'], 1 << (slot - 1))
                self.apply('look_import', slot=slot, look=look)
                self.assertTrue(self.current == installed, 're-import/verification must not append names or drift tables')
                self.apply('slot_default', slot=slot)
                self.assertEqual(device_layout.structural(self.current['appFw.so'], self.current['cpapp-b.bin'])['mask'], 0)
                selected = direct.recipe_defaults(installed['appFw.so'], [slot])
                for key, value in before[0].items():
                    if key not in selected:self.assertEqual(self.props[0][key], value)
                self.assertEqual(self.props[1], before[1])

    def test_mixed_slot_pairs_reset_only_the_requested_slot(self):
        base_current, base_props = dict(self.current), copy.deepcopy(self.props)
        for first, second in ((1, 6), (2, 4), (3, 5)):
            with self.subTest(first=first, second=second):
                self.current, self.props = dict(base_current), copy.deepcopy(base_props)
                self.apply('look_import', slot=first, look=self.make_look(first, 18))
                self.apply('look_import', slot=second, look=self.make_look(second, -24))
                before = device_layout.tables(self.current['cpapp-b.bin'])
                recipe_before = copy.deepcopy(self.props)
                self.apply('slot_default', slot=first)
                after = device_layout.tables(self.current['cpapp-b.bin'])
                self.assertEqual(after[second - 1], before[second - 1])
                changed = direct.recipe_defaults(self.current['appFw.so'], [first])
                for key, value in recipe_before[0].items():
                    if key not in changed:self.assertEqual(self.props[0][key], value)
                self.assertEqual(self.props[1], recipe_before[1])

    def test_bundle_composes_fl23_sound_and_multiple_slots_without_name_growth(self):
        from looktool import bundle, resources
        self.current['appFw.so'] = self.stock['appFw.so']
        self.current['cpapp-b.bin'] = self.stock['cpapp-b.bin']
        before = dict(self.current)
        selected = [dict(slot=s, name='Look ' + str(s), document=self.make_look(s, 10+s)) for s in (2, 5)]
        options = dict(fl23=True, sound=True)
        target, wanted, _ = bundle.plan(self.current, self.props, options, selected)
        for chip in (0, 1):
            for key, data in wanted[chip].items():self.props[chip][key] = self.props[chip][key]._replace(data=data)
        self.assertEqual(device_layout.structural(target['appFw.so'], target['cpapp-b.bin'])['mask'], 18)
        import candidate
        self.assertTrue(candidate.is_current(target['cpapp-b.bin']))
        for filename in nameworker.filenames():
            key = 'resources/' + filename
            ids = device_layout.structural(target['appFw.so'], target['cpapp-b.bin'])['label_ids']
            self.assertEqual(target[key], resources.rename(before[key], {2: 'Look 2', 5: 'Look 5'}, ids)[0])
        repeated, _, _ = bundle.plan(target, self.props, options, selected)
        self.assertTrue(repeated == target, 'repeated bundle plan must be byte-identical')

    def test_builtin_reset_removes_native_photo_code_and_all_tables(self):
        self.apply('look_import', slot=5, look=self.make_look(5, 32))
        restored, _ = self.apply('factory_reset', factory=official.builtin())
        self.assertEqual(restored['appFw.so'], self.stock['appFw.so'])
        self.assertEqual(restored['cpapp-b.bin'], self.stock['cpapp-b.bin'])

    def test_bundled_six_from_stock_preserves_calibration_and_is_repeatable(self):
        from desktopapp import presets
        from looktool import bundle, resources
        options, rows = bundle.documents(presets.resolve(dict(preset_pack=presets.PACK, fl23=True, sound=True)))
        self.current.update({k: self.stock[k] for k in ('appFw.so', 'cpapp-b.bin')})
        before = copy.deepcopy(self.props)
        target, wanted, titles = bundle.plan(self.current, self.props, options, rows)
        layout = device_layout.structural(target['appFw.so'], target['cpapp-b.bin'])
        self.assertEqual(layout['mask'], 63)
        self.assertEqual(titles[0], dict(enumerate(presets.NAMES, 1)))
        self.assertEqual(device_layout.tables(target['cpapp-b.bin']),
            [lookfile.writer_document(r['document']) for r in rows])
        import candidate
        self.assertTrue(candidate.is_current(target['cpapp-b.bin']))
        for at in direct.MENU_FLAGS:self.assertEqual(target['appFw.so'][at:at+2], b'\1\0')
        for filename in nameworker.filenames():
            entries = resources.decode(target['resources/' + filename])['entries']
            for slot, name in enumerate(presets.NAMES, 1):
                self.assertEqual(entries[layout['label_ids'][slot-1]]['text'], name)
        for chip in (0, 1):
            for key, data in wanted[chip].items():self.props[chip][key] = self.props[chip][key]._replace(data=data)
        self.assertEqual(self.props[1][0x02a40001].data[0x100:0x108], b'BODYDATA')
        self.assertEqual(self.props[1][0x02a4000d].data[0x80:0x88], b'BODYDATA')
        for chip in (0, 1):
            for key in before[chip]:
                if key not in wanted[chip]:self.assertEqual(self.props[chip][key], before[chip][key])
        repeated, _, _ = bundle.plan(target, self.props, options, rows)
        self.assertEqual(repeated, target)

    def test_stock_first_import_and_default_return_need_no_original_job(self):
        self.current['appFw.so'] = self.stock['appFw.so']
        self.current['cpapp-b.bin'] = self.stock['cpapp-b.bin']
        self.apply('fl23_enable')
        self.apply('look_import', slot=2, look=self.make_look(2, 20))
        imported = device_layout.structural(self.current['appFw.so'], self.current['cpapp-b.bin'])
        self.assertEqual(imported['mask'], 2)
        self.apply('slot_default', slot=2)
        self.assertEqual(device_layout.structural(self.current['appFw.so'], self.current['cpapp-b.bin'])['mask'], 0)
        restored, _ = self.apply('factory_reset', factory=official.builtin())
        self.assertEqual(restored['appFw.so'], self.stock['appFw.so'])
        self.assertEqual(restored['cpapp-b.bin'], self.stock['cpapp-b.bin'])

    def test_look_only_batch_from_stock_does_not_enable_fl23_or_sound(self):
        from desktopapp import lookbatch, presets
        from looktool import bundle
        self.current.update({k:self.stock[k] for k in ('appFw.so','cpapp-b.bin')})
        options,rows=bundle.documents(lookbatch.options(presets.catalog()))
        before=copy.deepcopy(self.props)
        target,wanted,_=bundle.plan(self.current,self.props,options,rows)
        self.assertEqual(device_layout.structural(target['appFw.so'],target['cpapp-b.bin'])['mask'],63)
        for at in direct.MENU_FLAGS:self.assertEqual(target['appFw.so'][at:at+2],self.stock['appFw.so'][at:at+2])
        self.assertEqual(target['cpapp-b.bin'][0x3935ca:0x3935cc],self.stock['cpapp-b.bin'][0x3935ca:0x3935cc])
        self.assertEqual(wanted[1],{})
        for key,value in before[0].items():
            if key not in direct.recipe_defaults(target['appFw.so'],range(1,7)):
                self.assertNotIn(key,wanted[0])

    def test_sparse_batch_replaces_selected_slots_and_keeps_other_tables_names_and_recipes(self):
        from desktopapp import presets,lookbatch
        from looktool import bundle,resources
        # Begin with six installed looks, then replace only 2 and 5 together.
        options,rows=bundle.documents(lookbatch.options(presets.catalog()))
        target,wanted,_=bundle.plan(self.current,self.props,options,rows)
        for chip in (0,1):
            for key,data in wanted[chip].items():self.props[chip][key]=self.props[chip][key]._replace(data=data)
        before=copy.deepcopy(self.props)
        chosen=[dict(slot=s,name='Batch '+str(s),document=self.make_look(s,20+s)) for s in (2,5)]
        result,fields,_=bundle.plan(target,self.props,dict(fl23=False,sound=False),chosen)
        a,b=device_layout.tables(target['cpapp-b.bin']),device_layout.tables(result['cpapp-b.bin'])
        old,new=photoio.inspect(target['cpapp-b.bin']),photoio.inspect(result['cpapp-b.bin'])
        ids=device_layout.structural(result['appFw.so'],result['cpapp-b.bin'])['label_ids']
        for slot in (1,3,4,6):
            self.assertEqual(a[slot-1],b[slot-1]);self.assertEqual(old['knobs'][slot-1],new['knobs'][slot-1])
            for name in nameworker.filenames():
                key='resources/'+name
                self.assertEqual(resources.decode(target[key])['entries'][ids[slot-1]],resources.decode(result[key])['entries'][ids[slot-1]])
        selected=direct.recipe_defaults(result['appFw.so'],[2,5])
        self.assertTrue(set(fields[0])<=set(selected));self.assertEqual(fields[1],{})
        for at in direct.MENU_FLAGS:self.assertEqual(result['appFw.so'][at:at+2],target['appFw.so'][at:at+2])
        self.assertEqual(result['cpapp-b.bin'][0x3935ca:0x3935cc],target['cpapp-b.bin'][0x3935ca:0x3935cc])

    def test_direct_default_reset_has_no_firmware_sha_gate_or_scan(self):
        with patch('looktool.firmware.sha', side_effect=AssertionError('No firmware SHA in direct operations')):
            self.apply('slot_default', slot=4)
            self.apply('fl23_disable')
            self.apply('factory_reset', factory=official.builtin())

    def test_mixed_restore_and_write_preserves_unselected_slots_and_native_features(self):
        from desktopapp import presets,lookbatch
        from looktool import bundle,resources
        self.current.update({k:self.stock[k] for k in ('appFw.so','cpapp-b.bin')})
        initial,rows=bundle.documents(dict(looks=presets.catalog(),fl23=True,sound=True))
        self.current,fields,_=bundle.plan(self.current,self.props,initial,rows)
        for chip in (0,1):
            for key,data in fields[chip].items():self.props[chip][key]=self.props[chip][key]._replace(data=data)
        before=dict(self.current);settings=copy.deepcopy(self.props)
        operations=[dict(slot=4,action='restore')]
        for slot in (2,6):
            self.make_look(slot,20+slot)
            operations.append(dict(slot=slot,action='write',path=str(self.root/('look-%d.a7look'%slot)),name='Mixed '+str(slot)))
        options,rows=bundle.documents(lookbatch.options(operations))
        target,wanted,titles=bundle.plan(before,self.props,options,rows)
        old_tables=device_layout.tables(before['cpapp-b.bin']);new_tables=device_layout.tables(target['cpapp-b.bin'])
        old_photo=photoio.inspect(before['cpapp-b.bin']);new_photo=photoio.inspect(target['cpapp-b.bin'])
        layout=device_layout.structural(target['appFw.so'],target['cpapp-b.bin'])
        self.assertEqual(layout['mask'],63 & ~(1<<3))
        self.assertEqual(titles[0],{2:'Mixed 2',6:'Mixed 6'})
        for slot in (1,3,5):
            self.assertEqual(new_tables[slot-1],old_tables[slot-1])
            self.assertEqual(new_photo['knobs'][slot-1],old_photo['knobs'][slot-1])
        for row in rows:self.assertEqual(new_tables[row['slot']-1],lookfile.writer_document(row['document']))
        for at in direct.MENU_FLAGS:self.assertEqual(target['appFw.so'][at:at+2],before['appFw.so'][at:at+2])
        self.assertEqual(target['cpapp-b.bin'][0x3935ca:0x3935cc],before['cpapp-b.bin'][0x3935ca:0x3935cc])
        for filename in nameworker.filenames():
            key='resources/'+filename
            # The merged plan appends both selected titles in one rename pass.
            self.assertEqual(target[key],resources.rename(before[key],titles[0],titles[1])[0])
        allowed=direct.recipe_defaults(target['appFw.so'],[2,4,6])
        self.assertTrue(set(wanted[0])<=set(allowed));self.assertEqual(wanted[1],{})
        for chip in (0,1):
            for key,data in wanted[chip].items():self.props[chip][key]=self.props[chip][key]._replace(data=data)
            for key,record in settings[chip].items():
                if key not in wanted[chip]:self.assertEqual(self.props[chip][key],record)
        again,second_fields,_=bundle.plan(target,self.props,options,rows)
        self.assertEqual(again,target)
        self.assertEqual(second_fields,wanted)

    def test_restore_only_batch_deactivates_exact_requested_mask_bits_without_program_drift(self):
        from desktopapp import presets,lookbatch
        from looktool import bundle
        self.current.update({k:self.stock[k] for k in ('appFw.so','cpapp-b.bin')})
        options,rows=bundle.documents(lookbatch.options(presets.catalog()))
        before,fields,_=bundle.plan(self.current,self.props,options,rows)
        for chip in (0,1):
            for key,data in fields[chip].items():self.props[chip][key]=self.props[chip][key]._replace(data=data)
        resets,empty=bundle.documents(lookbatch.options([dict(slot=s,action='restore') for s in (1,4,6)]))
        target,wanted,_=bundle.plan(before,self.props,resets,empty)
        self.assertEqual(device_layout.structural(target['appFw.so'],target['cpapp-b.bin'])['mask'],22)
        old=device_layout.tables(before['cpapp-b.bin']);new=device_layout.tables(target['cpapp-b.bin'])
        for slot in (2,3,5):self.assertEqual(old[slot-1],new[slot-1])
        self.assertEqual(wanted[1],{})
        for chip in (0,1):
            for key,data in wanted[chip].items():self.props[chip][key]=self.props[chip][key]._replace(data=data)
        repeated,_,_=bundle.plan(target,self.props,resets,empty)
        self.assertEqual(repeated,target)

    def test_legacy_six_mixed_reset_uses_zero_table_and_merges_st_title_with_import(self):
        from desktopapp import lookbatch
        from looktool import bundle,resources
        self.assertEqual(device_layout.structural(self.ap,self.cp)['kind'],'legacy-six')
        self.make_look(2,22)
        options,rows=bundle.documents(lookbatch.options([dict(slot=4,action='restore'),
            dict(slot=2,action='write',path=str(self.root/'look-2.a7look'),name='Legacy 2')]))
        target,wanted,titles=bundle.plan(self.current,self.props,options,rows)
        self.assertEqual(titles[0],{4:'ST',2:'Legacy 2'})
        tables=device_layout.tables(target['cpapp-b.bin'])
        self.assertEqual(tables[3],bytes(1215))
        self.assertEqual(tables[1],lookfile.writer_document(rows[0]['document']))
        old=device_layout.tables(self.cp)
        for slot in (1,3,5,6):self.assertEqual(tables[slot-1],old[slot-1])
        for filename in nameworker.filenames():
            key='resources/'+filename
            self.assertEqual(target[key],resources.rename(self.current[key],titles[0],titles[1])[0])
        for chip in (0,1):
            for key,data in wanted[chip].items():self.props[chip][key]=self.props[chip][key]._replace(data=data)
        repeated,_,_=bundle.plan(target,self.props,options,rows)
        self.assertEqual(repeated,target)

    def test_pr6_upgrades_previous_native_curves_and_preserves_custom_runtime(self):
        from looktool import device_layout
        for label in ('stock','six-custom'):
            with self.subTest(source=label):
                self.current={'appFw.so':self.stock['appFw.so'] if label=='stock' else self.ap,
                    'cpapp-b.bin':self.stock['cpapp-b.bin'] if label=='stock' else self.cp,
                    **{'resources/'+n:stock_names() for n in nameworker.filenames()}}
                self.props=copy.deepcopy(self.records)
                self.apply('fl23_enable')
                previous=bytearray(self.current['cpapp-b.bin'])
                for at,old,new,legacy in device_layout.fl23_native_windows():
                    variants=device_layout.fl23_previous_values(at)
                    if variants:previous[at:at+len(variants[0])]=variants[0]
                self.current['cpapp-b.bin']=bytes(previous)
                before=dict(self.current)
                upgraded,_=self.apply('fl23_enable')
                expected=bytearray(before['cpapp-b.bin'])
                for at,old,new,legacy in device_layout.fl23_native_windows():expected[at:at+len(new)]=new
                self.assertEqual(upgraded['cpapp-b.bin'],bytes(expected))
                self.assertEqual(upgraded['appFw.so'],before['appFw.so'])
                if label=='six-custom':
                    self.assertEqual(device_layout.tables(before['cpapp-b.bin']),device_layout.tables(upgraded['cpapp-b.bin']))
                again,_=self.apply('fl23_enable');self.assertEqual(again,upgraded)


if __name__ == '__main__':
    unittest.main()
