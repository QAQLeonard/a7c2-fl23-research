import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
from unittest.mock import patch
import unittest
from device_driver import DeviceDriver
from staging_model import ReviewRequired


def elf(size):
    data = bytearray(size); data[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<HH', data, 16, 3, 183)
    return bytes(data)


class FakeSession:
    def __init__(self, fault=None):
        self.healthy, self.mutating = True, False
        self.files, self.calls, self.fault = {}, [], fault
        self.operation, self.request_id, self.phase, self.active = 0, 0, 0, 0

    def read(self, path, missing=False):
        name = path.rsplit('/', 1)[1]
        self.calls.append(('read', name))
        if missing: return self.files.get(name)
        return self.files[name]

    def temp(self, name, data=None, remove=False):
        self.calls.append(('remove' if remove else 'write', name, len(data) if data is not None else 0))
        if remove: del self.files[name]; return
        self.files[name] = data
        if name != 'libJit.so': return
        if self.fault == 'timeout': raise TimeoutError('native outcome unknown')
        wire = self.files['a7c2.dex.request']
        header = bytearray(64); header[:8] = b'A7ENT001'; struct.pack_into('<I', header, 8, 1)
        header[32:64] = hashlib.sha256(wire).digest()
        if wire[:8] == b'A7STG001':
            op, index = struct.unpack_from('<II', wire, 8)
            payload = bytearray(112); struct.pack_into('<IIII', payload, 0, 1, op, 2 if op == 3 else 1,
                                                      index + 1 if op == 2 else 0)
            kind, status = 1, 0
        else:
            op = struct.unpack_from('<I', wire, 8)[0]
            if op != 3:
                self.operation, self.request_id = op, struct.unpack_from('<Q', wire, 16)[0]
                self.active = 1
            elif self.operation == 1: self.phase = 7
            elif self.operation == 4: self.active = 0
            payload = bytearray(2832)
            struct.pack_into('<IIIIQ', payload, 0, 1, self.operation, int(op != 3), 0, self.request_id)
            struct.pack_into('<I', payload, 44, self.active)
            struct.pack_into('<I', payload, 80, self.phase)
            kind, status = 2, 0
            if self.fault == 'busy' and op == 3:
                status = -16004; struct.pack_into('<I', payload, 8, 1)
        struct.pack_into('<I', header, 12, kind)
        raw = bytes(header) + struct.pack('<iI', status, len(payload)) + payload
        raw += hashlib.sha256(raw).digest() + b'A7DONE01'
        if self.fault == 'corrupt': raw = raw[:-1]
        self.files['a7c2.dex.result'] = raw


class DeviceTransport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a7c2-driver-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'job'

    def driver(self, session):
        return DeviceDriver(session, self.root, elf(4096), elf(180001), identity=b'INSTANCE-0000001')

    def test_construction_never_uses_session(self):
        session = FakeSession(); driver = self.driver(session)
        self.assertEqual(session.calls, [])
        self.assertEqual(driver.state['phase'], 'PREPARED')

    def test_bounded_stage_arm_query_and_disable(self):
        session = FakeSession(); driver = self.driver(session)
        driver.stage(); self.assertEqual(driver.state['phase'], 'CORE_READY')
        self.assertFalse(session.files)
        driver.arm(epoch=1, generation=1, nonce=123)
        self.assertEqual(driver.state['phase'], 'ARMED')
        self.assertTrue(driver.query()['photo_complete'])
        self.assertEqual(driver.state['phase'], 'COMPLETE')
        driver.disable(); self.assertEqual(driver.state['phase'], 'DISABLING')
        driver.query(); self.assertEqual(driver.state['phase'], 'DISABLED')
        driver.arm(epoch=2, generation=1)
        self.assertEqual(len({row['nonce'] for row in driver.state['arms']}), 2)
        self.assertTrue(list(self.root.glob('*.request.private.bin')))
        writes = [row for row in session.calls if row[0] == 'write']
        self.assertTrue(all(row[2] <= 65536 for row in writes))
        self.assertTrue(list(self.root.glob('*.receipt.private.bin')))
        removals = [row[1] for row in session.calls if row[0] == 'remove']
        self.assertEqual(removals[-1], 'a7c2.dex.result')

    def test_existing_file_is_not_overwritten_or_removed(self):
        session = FakeSession(); session.files['a7c2.dex.payload'] = b'user file'
        driver = self.driver(session)
        with self.assertRaises(ReviewRequired): driver.stage()
        self.assertEqual(session.files['a7c2.dex.payload'], b'user file')
        self.assertFalse(any(row[0] in ('write', 'remove') for row in session.calls))

    def test_unknown_native_outcome_keeps_files_and_never_replays(self):
        session = FakeSession('timeout'); driver = self.driver(session)
        with self.assertRaises(TimeoutError): driver.stage()
        self.assertEqual(driver.state['phase'], 'REVIEW')
        self.assertFalse(session.healthy); self.assertTrue(session.mutating)
        count = len(session.calls)
        with self.assertRaises(ReviewRequired): driver.stage()
        self.assertEqual(len(session.calls), count)
        self.assertIn('libJit.so', session.files)
        self.assertFalse(any(row[0] == 'remove' for row in session.calls))

    def test_incomplete_receipt_is_preserved_and_not_cleanup_permission(self):
        session = FakeSession('corrupt'); driver = self.driver(session)
        with self.assertRaises(ValueError): driver.stage()
        self.assertEqual(driver.state['phase'], 'REVIEW')
        self.assertIn('a7c2.dex.result', session.files)
        self.assertFalse(any(row[0] == 'remove' for row in session.calls))

    def test_busy_query_keeps_running_state(self):
        session = FakeSession(); driver = self.driver(session); driver.stage()
        driver.arm(epoch=1, generation=1)
        session.fault = 'busy'
        self.assertEqual(driver.query()['status'], -16004)
        self.assertEqual(driver.state['phase'], 'ARMED')
        self.assertTrue(session.healthy)

    def test_final_host_state_failure_stops_every_operation_without_replay(self):
        cases = (('stage', 'CORE_READY'), ('arm', 'ARMED'),
                 ('query', 'COMPLETE'), ('disable', 'DISABLING'))
        for operation, phase in cases:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                session = FakeSession()
                driver = DeviceDriver(session, Path(directory)/'job', elf(4096), elf(180001))
                if operation != 'stage': driver.stage()
                if operation in ('query', 'disable'): driver.arm(epoch=1, generation=1)
                save = driver._save
                def unavailable():
                    if driver.state['phase'] == phase:
                        raise OSError('host journal unavailable after native return')
                    save()
                with patch.object(driver, '_save', side_effect=unavailable):
                    with self.assertRaisesRegex(OSError, 'host journal unavailable'):
                        if operation == 'arm': driver.arm(epoch=1, generation=1)
                        else: getattr(driver, operation)()
                self.assertEqual(driver.state['phase'], 'REVIEW')
                self.assertFalse(session.healthy)
                self.assertTrue(session.mutating)
                self.assertTrue(list(driver.root.glob('*.receipt.private.bin')))
                calls = list(session.calls)
                for method in (driver.stage, driver.query, driver.disable,
                               lambda: driver.arm(epoch=2, generation=1)):
                    with self.assertRaises(ReviewRequired): method()
                self.assertEqual(session.calls, calls)
                self.assertEqual(json.loads((driver.root/'state.private.json').read_text())['phase'], 'REVIEW')

    def test_concurrent_command_is_rejected_without_touching_running_session(self):
        session = FakeSession(); driver = self.driver(session); driver.stage()
        entered, release = threading.Event(), threading.Event()
        temp = session.temp
        failures = []
        def blocked(name, data=None, remove=False):
            if name == 'libJit.so' and not remove and not entered.is_set():
                entered.set()
                if not release.wait(5): raise TimeoutError('test barrier expired')
            return temp(name, data, remove)
        def stage():
            try: driver.arm(epoch=1, generation=1)
            except BaseException as error: failures.append(error)
        with patch.object(session, 'temp', side_effect=blocked):
            worker = threading.Thread(target=stage)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                calls = list(session.calls)
                with self.assertRaisesRegex(ReviewRequired, 'operation is running'):
                    driver.query()
                self.assertEqual(session.calls, calls)
                self.assertEqual(driver.state['phase'], 'CORE_READY')
                self.assertTrue(session.healthy)
            finally:
                release.set(); worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
        self.assertEqual(driver.state['phase'], 'ARMED')

    def test_invalid_arm_parameters_leave_ready_transaction_usable(self):
        session = FakeSession(); driver = self.driver(session); driver.stage()
        calls = list(session.calls)
        with self.assertRaises(ValueError): driver.arm(epoch=0, generation=1)
        self.assertEqual(driver.state['phase'], 'CORE_READY')
        self.assertEqual(session.calls, calls)
        self.assertTrue(session.healthy)
        driver.arm(epoch=1, generation=1)
        self.assertEqual(driver.state['phase'], 'ARMED')
