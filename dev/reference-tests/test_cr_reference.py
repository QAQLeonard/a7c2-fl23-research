"""Offline reference-collection tests. Never enumerate or access USB devices."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

SOURCE = Path(__file__).resolve().parents[1]/'pixelshift'
sys.path.insert(0, str(SOURCE))
from collect_cr_reference import initialize, check, pack
from cr_usb_readonly import ReadOnlyChannel, read_snapshots, collect, CP_UNITS, Connection


def raw(*, shot=0, count=0, group=0, model=b'ILCE-7CR\0', iso=100):
    data = bytearray(512)
    data[:8] = b'II'+struct.pack('<HI', 42, 8)
    def ifd(at, entries):
        struct.pack_into('<H', data, at, len(entries))
        for n, entry in enumerate(entries):
            struct.pack_into('<HHII', data, at+2+12*n, *entry)
    data[48:48+len(model)] = model
    ifd(8, [(272, 2, len(model), 48), (34665, 4, 1, 80)])
    ifd(80, [(33434, 5, 1, 160), (33437, 5, 1, 168),
             (34855, 3, 1, iso), (37500, 7, 128, 200)])
    struct.pack_into('<IIII', data, 160, 1, 125, 56, 10)
    ifd(200, [(0x202f, 7, 6, 300)])
    struct.pack_into('<IBB', data, 300, group, shot, count)
    return bytes(data)


def complete(root):
    initialize(root, firmware='2.01', lens='Manual reference lens')
    (root/'before/BASE.ARW').write_bytes(raw())
    (root/'after/BASE.ARW').write_bytes(raw())
    for n in range(1, 5):
        (root/('four-shot/%d.ARW' % n)).write_bytes(raw(shot=n, count=4, group=9))


class ReferenceFiles(unittest.TestCase):
    def test_pack_preserves_originals_and_uses_only_relative_selected_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reference'
            complete(root)
            (root/'evidence/cycle.MP4').write_bytes(b'phone video')
            (root/'unrequested-firmware.bin').write_bytes(b'not selected')
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*.ARW')}
            report, archive = pack(root)
            self.assertEqual(report['status'], 'READY')
            self.assertFalse(report['physical_shift_verified'])
            with zipfile.ZipFile(archive) as packed:
                self.assertNotIn('unrequested-firmware.bin', packed.namelist())
                self.assertIn('evidence/cycle.MP4', packed.namelist())
                self.assertNotIn(str(root), packed.read('validation.json').decode())
                for name, data in before.items():
                    self.assertEqual(packed.read(name), data)
                    self.assertEqual((root/name).read_bytes(), data)
            with self.assertRaises(FileExistsError):
                pack(root)

    def test_ordinary_burst_and_wrong_model_are_not_accepted_as_reference_group(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reference'
            complete(root)
            (root/'four-shot/2.ARW').write_bytes(raw())
            report, _ = check(root)
            self.assertEqual(report['status'], 'INCOMPLETE')
            with self.assertRaises(ValueError):
                pack(root)
            (root/'four-shot/2.ARW').write_bytes(raw(shot=2, count=4, group=9, model=b'ILCE-7CM2\0'))
            self.assertTrue(any('expected ILCE-7CR' in error for error in check(root)[0]['errors']))

    def test_partial_archive_records_missing_data_and_mismatched_exposure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reference'
            complete(root)
            (root/'after/BASE.ARW').write_bytes(raw(iso=200))
            report, output = pack(root, allow_partial=True)
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertTrue(any('differs' in error for error in report['errors']))
            self.assertTrue(output.is_file())

    def test_external_file_alias_is_not_collected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reference'
            complete(root)
            target = Path(folder)/'outside.jpg'
            target.write_bytes(b'private unrelated photo')
            try:
                (root/'evidence/outside.jpg').symlink_to(target)
            except OSError:
                self.skipTest('This host does not permit symlink creation')
            with self.assertRaisesRegex(ValueError, 'outside'):
                check(root)


class RecordingChannel:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at
    def sendSenserPacket(self, function, data):
        self.calls.append((function, data))
        if len(self.calls) == self.fail_at:
            raise OSError('simulated interrupted read')
        return 0, b'read-only data'
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class ReadOnlyProtocol(unittest.TestCase):
    def test_only_exact_read_packets_reach_wire(self):
        wire = RecordingChannel()
        gate = ReadOnlyChannel(wire, cp_shadows=True)
        forbidden = [
            (0x40, struct.pack('<HHI', 0x603, 2, 0x02cf02cf)+b'\0'),  # writeBackup
            (0x40, struct.pack('<HHH', 0x603, 3, 0x02cf)),            # saveBackup
            (0x40, struct.pack('<HH', 0x603, 4)+b'backup'),           # setBackupPresetData
            (0x40, struct.pack('<HH', 0x603, 0x41)+b'unit'),          # CP write
            (0x40, struct.pack('<HH', 0x1001, 16)+b'payload'),        # Jiritsu file write
            (0xff01, b'file write'), (0xff03, b'memory access'),
            (0x20, b'firmware update'),
            (0x40, struct.pack('<HHB', 0x603, 5, 2)),
            (0x40, struct.pack('<HHII', 0x603, 0x40, 0x02a4ffff, 1)),
        ]
        for function, data in forbidden:
            with self.assertRaises(ValueError):
                gate.sendSenserPacket(function, data)
        self.assertEqual(wire.calls, [])
        output = {}
        result = read_snapshots(wire, output.__setitem__, cp_shadows=True)
        self.assertEqual(len(wire.calls), 2+len(CP_UNITS))
        self.assertEqual(len(output), 21)
        self.assertTrue(result.healthy)
        self.assertEqual(wire.calls[0], (0x40, struct.pack('<HHB', 0x603, 5, 1)))

    def test_unknown_result_stops_without_retry_or_followup(self):
        wire = RecordingChannel(fail_at=1)
        gate = ReadOnlyChannel(wire)
        packet = struct.pack('<HHB', 0x603, 5, 1)
        with self.assertRaises(OSError):
            gate.sendSenserPacket(0x40, packet)
        with self.assertRaises(RuntimeError):
            gate.sendSenserPacket(0x40, packet)
        self.assertEqual(len(wire.calls), 1)

    def test_collector_preserves_partial_session_and_reports_failed_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reference'
            initialize(root, firmware='2.01')
            wire = RecordingChannel(fail_at=2)
            with self.assertRaises(RuntimeError):
                collect(root, label='off-before', connector=lambda: wire)
            output = next((root/'runtime').iterdir())
            report = json.loads((output/'snapshot.json').read_text())
            self.assertFalse(report['complete'])
            self.assertEqual(report['current_read'], 'settings-saved.bin')
            self.assertEqual((output/'settings-ram.bin').read_bytes(), b'read-only data')
            self.assertEqual(len(wire.calls), 2)

    def test_complete_usb_snapshot_is_packaged_without_claiming_cp_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reference'
            complete(root)
            collect(root, label='off-before', connector=RecordingChannel)
            report, output = pack(root)
            self.assertEqual(report['runtime_snapshots'][0]['settings_ram_captured'], True)
            self.assertFalse(report['runtime_snapshots'][0]['cp_execution_ram_captured'])
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(sum(name.endswith('.bin') for name in archive.namelist()), 2)

    def test_teardown_error_is_preserved_without_reporting_complete(self):
        class FailedExit(RecordingChannel):
            def __exit__(self, *args):
                raise OSError('simulated service teardown error')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'reference'
            initialize(root, firmware='2.01')
            with self.assertRaises(RuntimeError):
                collect(root, label='off-after', connector=FailedExit)
            report = json.loads(next((root/'runtime').glob('*/snapshot.json')).read_text())
            self.assertFalse(report['complete'])
            self.assertEqual(report['stage'], 'service-exit')
            self.assertEqual(len(report['files']), 2)


class UsbConnection(unittest.TestCase):
    def environment(self, products):
        events = []
        class Device:
            iProduct = 1
            def __init__(self, name, pid=0x9999):
                self.product = name
                self.idProduct = pid
            def get_active_configuration(self):
                return {(0, 0): types.SimpleNamespace(bInterfaceClass=8)}
        devices = [Device(name, pid) for name, pid in products]
        service = Device('Sony USB Device', 0x0336)
        modules = {name: types.ModuleType(name) for name in (
            'usb', 'usb.core', 'usb.util', 'usb.backend', 'usb.backend.libusb1', 'libusb_package')}
        modules['usb'].core = modules['usb.core']
        modules['usb'].util = modules['usb.util']
        modules['usb'].backend = modules['usb.backend']
        modules['usb.backend'].libusb1 = modules['usb.backend.libusb1']
        modules['usb.core'].find = lambda **args: [service] if args.get('idProduct') == 0x0336 else devices
        modules['usb.util'].get_string = lambda dev, key: dev.product
        modules['usb.util'].dispose_resources = lambda dev: events.append(('dispose', dev.product))
        modules['usb.backend.libusb1'].get_backend = lambda **args: object()
        modules['libusb_package'].find_library = lambda *args: 'offline-fake'
        class Backend:
            def __init__(self, device):
                self.dev = device
        class Driver:
            def __init__(self, backend):
                self.backend = backend
            def vendorRequestOut(self, *args):
                events.append(('stop', self.backend.dev.product))
        class Auth:
            SONY_VendorRequest_StopSenser = (1, 0xc800, 0x2855)
            def __init__(self, driver):
                self.driver = driver
            def start(self):
                events.append(('start', self.driver.backend.dev.product))
            def authenticate(self):
                events.append(('authenticate', self.driver.backend.dev.product))
        sony = types.SimpleNamespace(SonySenserAuthDevice=Auth, SonySenserDevice=lambda driver: RecordingChannel())
        vendors = sony, types.SimpleNamespace(GenericUsbDriver=Driver), types.SimpleNamespace(UsbBackend=Backend)
        return modules, vendors, events

    def test_wrong_model_or_multiple_bodies_stop_before_authentication(self):
        for products in ([('ILCE-7CM2', 0x0e8a)], [('ILCE-7CR', 1), ('ILCE-7CR', 2)],
                         [('ILCE-7CR', 1), ('Sony USB Device', 0x0336)]):
            modules, vendors, events = self.environment(products)
            with patch.dict(sys.modules, modules), patch('cr_usb_readonly.vendor_modules', return_value=vendors):
                with self.assertRaises(RuntimeError):
                    with Connection():
                        self.fail('Unexpected connection')
            self.assertFalse(any(event[0] in ('start', 'authenticate', 'stop') for event in events))

    def test_service_session_authenticates_once_per_identity_and_exits_once(self):
        modules, vendors, events = self.environment([('ILCE-7CR', 0x1234)])
        with patch.dict(sys.modules, modules), patch('cr_usb_readonly.vendor_modules', return_value=vendors), \
                patch('cr_usb_readonly.time.sleep'):
            with Connection() as connection:
                self.assertEqual(connection.normal_product_id, 0x1234)
                read_snapshots(connection, lambda name, data: None)
        self.assertEqual([event for event in events if event[0] == 'authenticate'],
                         [('authenticate', 'ILCE-7CR'), ('authenticate', 'Sony USB Device')])
        self.assertEqual([event for event in events if event[0] == 'stop'], [('stop', 'Sony USB Device')])

    def test_ambiguous_session_failure_does_not_send_teardown(self):
        modules, vendors, events = self.environment([('ILCE-7CR', 0x1234)])
        with patch.dict(sys.modules, modules), patch('cr_usb_readonly.vendor_modules', return_value=vendors), \
                patch('cr_usb_readonly.time.sleep'):
            with self.assertRaises(OSError):
                with Connection():
                    raise OSError('unknown transfer result')
        self.assertFalse(any(event[0] == 'stop' for event in events))


if __name__ == '__main__':
    unittest.main()
