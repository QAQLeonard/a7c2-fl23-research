"""Native-stage slot isolation and actual-byte admission, without USB."""
import copy
import struct
import unittest
from unittest.mock import patch
import builtins
import importlib.util
from looktool import photoio,photobasis,photobuild,device_layout


class PhotoIOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_photoformat import curve
        from looktool import photoformat
        cp=bytearray(0x1101fa0)
        for hook in photoio.template()['hooks']:
            at,raw=hook['offset'],bytes.fromhex(hook['before']);cp[at:at+len(raw)]=raw
        for row in range(50):
            pointers=[0x180000+row*0x2000+column*0x400 for column in range(7)]
            struct.pack_into('<7I',cp,0x1209480-0x108000+row*28,*pointers)
            for pointer in pointers:cp[pointer-0x108000:pointer-0x108000+576]=curve()
        struct.pack_into('<3I',cp,0x20124,0,0xb27fb0-0x20000,0x128000)
        struct.pack_into('<3I',cp,0x2013c,0x1101ae0-0x20000,1216,0x1209ae0)
        spec=next(row for row in device_layout.runtime()['cp_sources'] if row['kind']=='fl23')
        for window in spec['windows']:
            if window['offset'] in (0xb27490,0xb27f10):
                raw=bytes.fromhex(window['after']);cp[window['offset']:window['offset']+len(raw)]=raw
        cls.source=bytes(cp);cls.bank=photoformat.PhotoBank(curve(),curve(),bytes(576),bytes(64))
        cls.delta=photobasis.pack(cls.bank,tone=[32,0,0],
            matrices=[[1,-1,2,-2,1,-1] for _ in range(3)])[1]

    def install(self,source,changes):return photoio.update(source,changes,self.bank,allocation_proved=True)

    def test_first_install_and_reconstruction_keep_native_segments(self):
        target=self.install(self.source,{4:self.delta})
        self.assertEqual(photoio.inspect(target)['mask'],8)
        self.assertEqual(target[0x20124:0x20154],self.source[0x20124:0x20154])
        self.assertEqual(photoio.slot_delta(target,4,self.bank),self.delta)

    def test_replacing_then_clearing_one_slot_keeps_the_other_stage_bytes(self):
        one=self.install(self.source,{4:self.delta})
        two=self.install(one,{5:self.delta})
        original=photoio.slot_bytes(two,5)
        three=self.install(two,{4:None})
        self.assertIsNone(photoio.slot_bytes(three,4))
        self.assertEqual(photoio.slot_bytes(three,5),original)
        self.assertEqual(photoio.inspect(three)['mask'],16)

    def test_magic_word_does_not_admit_modified_runtime_code(self):
        target=bytearray(self.install(self.source,{1:self.delta}))
        target[photobuild.CODE_FILE+20]^=1
        with self.assertRaisesRegex(ValueError,'runtime bytes conflict'):photoio.inspect(bytes(target))

    def test_fl23_refresh_updates_active_native_rows_and_preserves_custom_slots(self):
        installed=self.install(self.source,{1:self.delta,6:self.delta})
        changed=bytearray(installed)
        original=0x1209480-photobuild.BASE
        # An independent FL23 write changes the original rows while hooks
        # still read the table copied when the custom looks were installed.
        for row,pointer in ((46,0x1208dc0),(47,0x1209240),(48,0x1208b80),(49,0x1209000)):
            struct.pack_into('<7I',changed,original+row*28,*([pointer]*7))
        with self.assertRaisesRegex(ValueError,'runtime bytes conflict'):
            photoio.inspect(bytes(changed))
        refreshed=photoio.refresh_gamma_table(bytes(changed))
        self.assertEqual(photoio.inspect(refreshed)['mask'],33)
        expected=bytearray(changed)
        expected[photobuild.TABLE_FILE:photobuild.TABLE_FILE+50*28]=changed[original:original+50*28]
        self.assertEqual(refreshed,bytes(expected))
        for slot in (1,6):
            self.assertEqual(photoio.slot_bytes(refreshed,slot),photoio.slot_bytes(installed,slot))
        self.assertEqual(photoio.refresh_gamma_table(refreshed),refreshed)

    def test_fl23_refresh_does_not_accept_an_unrelated_code_change(self):
        changed=bytearray(self.install(self.source,{1:self.delta}))
        changed[photobuild.CODE_FILE+20]^=1
        with self.assertRaisesRegex(ValueError,'runtime bytes conflict'):
            photoio.refresh_gamma_table(bytes(changed))

    def test_empty_storage_without_reviewed_allocation_is_not_accepted(self):
        source=bytearray(self.source);source[0xb27490]^=1
        with self.assertRaisesRegex(ValueError,'allocation conflicts'):
            self.install(bytes(source),{1:self.delta})

    def test_containing_segments_with_wrong_file_to_virtual_mapping_are_rejected(self):
        # Both containment checks still pass, but the loader would place our
        # bytes at different addresses than the compiled hooks/table pointers.
        for header in (0x20124,0x2013c):
            for field in ('file','virtual'):
                with self.subTest(header=hex(header),field=field):
                    source=bytearray(self.source)
                    offset,size,va=struct.unpack_from('<3I',source,header)
                    if field=='file':
                        delta=4 if header==0x20124 else -4
                        offset+=delta;size-=delta
                    else:
                        va-=4;size+=4
                    struct.pack_into('<3I',source,header,offset,size,va)
                    with self.assertRaisesRegex(ValueError,'file/virtual mapping'):
                        self.install(bytes(source),{1:self.delta})

    def test_field_payload_must_match_its_declared_integer_basis(self):
        delta=copy.deepcopy(self.delta);delta['matrix_coefficient_delta'][0][1][0]+=1
        with self.assertRaisesRegex(ValueError,'Full photo fields differ'):
            self.install(self.source,{1:delta})

    def test_new_native_delta_requires_fresh_body_records(self):
        with self.assertRaisesRegex(ValueError,'Fresh body ST records'):
            photoio.update(self.source,{1:self.delta},allocation_proved=True)

    def test_writer_needs_neither_keystone_nor_capstone(self):
        original_import=builtins.__import__
        def without_assembler(name,*args,**kwargs):
            if name.split('.')[0] in ('keystone','capstone'):raise ImportError('Optional assembler deliberately absent')
            return original_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=without_assembler):
            target=self.install(self.source,{4:self.delta})
            self.assertEqual(photoio.inspect(target)['mask'],8)

    def test_later_other_slot_data_is_accepted_but_selected_or_code_changes_are_not(self):
        from looktool import six
        source=bytearray(self.source);payload=six.prefix([bytes(1215) for _ in range(6)])
        source[six.TABLE_FILE:six.TABLE_FILE+len(payload)]=payload
        one=self.install(bytes(source),{1:self.delta})
        two=self.install(one,{2:self.delta})
        expected={'appFw.so':b'AP','cpapp-b.bin':one}
        actual={'appFw.so':b'AP','cpapp-b.bin':two}
        self.assertTrue(device_layout.same_selected_programs(expected,actual,1))
        self.assertFalse(device_layout.same_selected_programs(expected,actual,2))
        changed=bytearray(two);changed[0x400000]^=1
        self.assertFalse(device_layout.same_selected_programs(expected,dict(actual,**{'cpapp-b.bin':bytes(changed)}),1))
        self.assertFalse(device_layout.same_selected_programs(expected,dict(actual,**{'appFw.so':b'changed AP'}),1))

    @unittest.skipUnless(importlib.util.find_spec('keystone') and importlib.util.find_spec('capstone'),'Research assembler unavailable')
    def test_template_matches_research_assembler_byte_for_byte(self):
        for mask in (0,1,63):
            knobs=[dict(tone=[16,0,0]) for _ in range(6)]
            expected,_=photobuild.build(self.source,self.bank,knobs,active_mask=mask)
            actual,_=photoio.build(self.source,self.bank,knobs,active_mask=mask)
            self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main()
