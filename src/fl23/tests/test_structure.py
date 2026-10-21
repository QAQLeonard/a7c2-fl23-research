"""0.6.0 重构后的结构测试：目录约定、备份校验、驱动识别。

全程离线，不接触相机；机身设置用替身，程序文件用合成内容。
覆盖的是「备份必须原厂、未打 FL2／FL3 补丁」这条判据本身。
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup as backup_mod
import core
import layout
import usbdev
import workflow

FAKE_APP = b'APPFW-ORIGINAL-FACTORY'
FAKE_CP = b'CPAPP-ORIGINAL-FACTORY'
ZERO_01 = bytes(8192)
ZERO_0D = bytes(28672)


def property_dict(cp, ap):
    return [dict((k, SimpleNamespace(data=v, attr=0)) for k, v in ap.items()),
            dict((k, SimpleNamespace(data=v, attr=0)) for k, v in cp.items())]


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved = (layout.WORKDIR, layout.BACKUP)
        layout.WORKDIR = self.base / 'workdir'
        layout.BACKUP = self.base / 'backup'

    def tearDown(self):
        layout.WORKDIR, layout.BACKUP = self.saved
        self.tmp.cleanup()

    def test_session_dir_is_created_under_workdir(self):
        path = layout.session_path('abc12345deadbeef')
        self.assertEqual(path.parent, layout.WORKDIR)
        for sub in ('original', 'candidate', 'readback', 'evidence'):
            self.assertTrue((path / sub).is_dir(), sub)
        self.assertIn('abc12345', path.name)

    def test_two_sessions_never_collide(self):
        first = layout.session_path('abc12345deadbeef', stamp='20261020-140000')
        second = layout.session_path('abc12345deadbeef', stamp='20261020-140000')
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir() and second.is_dir())

    def test_backup_dir_is_per_body(self):
        path = layout.backup_path('0123456789abcdef')
        self.assertEqual(path.parent, layout.BACKUP)
        self.assertEqual(path.name, '01234567')
        self.assertTrue(path.is_dir())

    def test_list_and_find(self):
        self.assertEqual(layout.list_backups(), [])
        target = layout.backup_path('aaaabbbbccccdddd')
        (target / layout.BACKUP_MANIFEST).write_text(
            '{"format":2,"serial_sha256":"aaaabbbbccccdddd"}', encoding='utf-8')
        found = layout.list_backups()
        self.assertEqual(len(found), 1)
        self.assertEqual(layout.find_backup('aaaabbbbccccdddd'), target)
        self.assertIsNone(layout.find_backup('9999999999999999'))


class BackupVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved_original = list(core.ORIGINAL)
        self.saved_records = core.backup_records
        self.saved_backup_root = layout.BACKUP
        layout.BACKUP = self.base / 'backup'
        core.ORIGINAL = [core.sha(FAKE_APP), core.sha(FAKE_CP)]
        self.ap = {k: b'\0' for k in core.AP_KEYS}
        self.cp = {k: (ZERO_01 if i == 0 else ZERO_0D) for i, k in enumerate(core.CP_KEYS)}
        core.backup_records = lambda raw: property_dict(self.cp, self.ap)
        self.store = backup_mod.Backup(layout.backup_path('1111222233334444'))

    def tearDown(self):
        core.ORIGINAL = self.saved_original
        core.backup_records = self.saved_records
        layout.BACKUP = self.saved_backup_root
        self.tmp.cleanup()

    def files(self):
        return {layout.PROGRAM_FILES['appFw.so']: FAKE_APP,
                layout.PROGRAM_FILES['cpapp-b.bin']: FAKE_CP,
                layout.UNIT_FILES[core.CP_KEYS[0]]: ZERO_01,
                layout.UNIT_FILES[core.CP_KEYS[1]]: ZERO_0D,
                layout.SETTINGS_FILE: b'RAW'}

    def test_clean_factory_backup_passes(self):
        report = self.store.write(self.files(), {'model': core.MODEL,
                                                 'serial_sha256': '1111222233334444'})
        self.assertTrue(report['ok'], report['problems'])
        names = {c['name'] for c in report['checks']}
        self.assertIn('原厂程序 appFw.so.bin', names)
        self.assertIn('FL2／FL3 参数映射为空', names)

    def test_tampered_file_is_rejected(self):
        self.store.write(self.files(), {'serial_sha256': '1111222233334444'})
        (self.store.path / layout.PROGRAM_FILES['appFw.so']).write_bytes(b'TAMPERED')
        report = self.store.verify()
        self.assertFalse(report['ok'])
        self.assertTrue(any('杂凑不符' in p for p in report['problems']))

    def test_missing_file_is_rejected(self):
        self.store.write(self.files(), {'serial_sha256': '1111222233334444'})
        (self.store.path / layout.SETTINGS_FILE).unlink()
        report = self.store.verify()
        self.assertFalse(report['ok'])
        self.assertTrue(any('缺少' in p for p in report['problems']))

    def test_patched_program_is_not_factory(self):
        files = self.files()
        files[layout.PROGRAM_FILES['cpapp-b.bin']] = b'PATCHED-WITH-FL23'
        report = self.store.write(files, {'serial_sha256': '1111222233334444'})
        self.assertFalse(report['ok'])
        self.assertTrue(any('不是未打补丁的原厂程序' in p for p in report['problems']))

    def test_existing_fl23_binding_is_rejected(self):
        self.store.write(self.files(), {'serial_sha256': '1111222233334444'})
        self.ap[core.AP_KEYS[0]] = b'\x0a'
        report = self.store.verify()
        self.assertFalse(report['ok'])
        self.assertTrue(any('FL2／FL3 绑定' in p for p in report['problems']))

    def test_occupied_colour_slot_is_rejected(self):
        """机身里已经写过 FL2／FL3 的色彩单元，不能当成原厂备份。"""
        self.store.write(self.files(), {'serial_sha256': '1111222233334444'})
        unit01 = bytearray(ZERO_01)
        parameter, slot = core.COLOUR_SLOTS[0]
        unit01[0x1200 + parameter] = slot
        unit01[0x1250 + slot * 64] = 1
        (self.store.path / layout.UNIT_FILES[core.CP_KEYS[0]]).write_bytes(bytes(unit01))
        # 同步清单杂凑，这样只剩「不是原厂未打补丁状态」这一条会失败
        manifest = self.store.manifest()
        manifest['files'][layout.UNIT_FILES[core.CP_KEYS[0]]] = core.sha(bytes(unit01))
        self.store.manifest_path.write_text(
            __import__('json').dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        report = self.store.verify()
        self.assertFalse(report['ok'], report['checks'])
        self.assertTrue(any('映射已占用' in p for p in report['problems']), report['problems'])

    def test_verified_backup_lookup(self):
        self.store.write(self.files(), {'serial_sha256': '1111222233334444'})
        found = backup_mod.verified_backup('1111222233334444')
        self.assertIsNotNone(found)
        self.assertEqual(found['backup'].path, self.store.path)
        self.assertIsNone(backup_mod.verified_backup('9999999999999999'))


class DriverTests(unittest.TestCase):
    def test_accepts_winusband_libusbk(self):
        for service in ('WinUSB', 'winusb', 'libusbK', 'libusb0', ' libusbk '):
            self.assertTrue(usbdev._accept(service), service)

    def test_rejects_other_drivers(self):
        for service in ('', None, 'USBSTOR', 'WUDFRd', 'usbccgp'):
            self.assertFalse(usbdev._accept(service), service)

    def test_report_shape_without_devices(self):
        with patch.object(usbdev,'_windows_services',return_value=None),patch.object(usbdev,'find',return_value=None):
            report = usbdev.driver_report()
        self.assertEqual(set(['0e8a', '0336']) <= set(report), True)
        self.assertIn('ok', report)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved = (layout.WORKDIR, layout.BACKUP)
        layout.WORKDIR = self.base / 'workdir'
        layout.BACKUP = self.base / 'backup'

    def tearDown(self):
        layout.WORKDIR, layout.BACKUP = self.saved
        self.tmp.cleanup()

    def test_job_creates_its_own_session_dir(self):
        job = workflow.Job()
        self.assertEqual(job.root.parent, layout.WORKDIR)
        self.assertTrue((job.root / 'evidence').is_dir())

    def test_job_honours_explicit_workspace(self):
        target = self.base / 'manual'
        job = workflow.Job(target)
        self.assertEqual(job.root, target.resolve())

    def test_restore_without_backup_is_refused(self):
        job = workflow.Job()
        with self.assertRaises(ValueError) as caught:
            job.restore(80)
        self.assertIn('没有通过校验的备份', str(caught.exception))

    def test_restore_requires_battery(self):
        job = workflow.Job()
        with self.assertRaises(ValueError) as caught:
            job.restore(10)
        self.assertIn('电量', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
