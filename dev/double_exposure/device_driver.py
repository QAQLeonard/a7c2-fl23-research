"""Development driver using an explicitly supplied, already-open session.

Import/construction never discovers, authenticates or connects to a camera.
stage/arm/query/disable are explicit device operations. Offline tests supply a
fake session. The desktop does not expose/package this experimental driver.
"""
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import struct
import uuid
import threading
from entry_protocol import device_request, receipt
from staging_model import CHUNK_BYTES, Plan, ReviewRequired
from staging_protocol import CREATE, PUT, ASSEMBLE, request


def sha(data):
    return hashlib.sha256(data).hexdigest()


def arm64_shared(data):
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (3, 183):
        raise ValueError('Expected a little-endian AArch64 shared library')


def operation(method):
    """Serialize the whole operation, including host journal transitions."""
    @wraps(method)
    def run(self, *args, **kwargs):
        if not self._operation_lock.acquire(blocking=False):
            raise ReviewRequired('Another driver operation is running')
        self._operation_started = False
        try:
            if self.state['phase'] == 'REVIEW' or not self.session.healthy:
                raise ReviewRequired('Previous result needs review; no replay')
            return method(self, *args, **kwargs)
        except BaseException:
            if self._operation_started: self._fail()
            raise
        finally:
            self._operation_started = False
            self._operation_lock.release()
    return run


class DeviceDriver:
    def __init__(self, session, directory, helper, core, *, identity=None):
        arm64_shared(helper)
        arm64_shared(core)
        if len(helper) > 65536:
            raise ValueError('One-shot entry exceeds transport limit')
        self.plan = Plan.from_bytes(core)
        self.identity = identity if identity is not None else uuid.uuid4().bytes
        # Validate the common identity/encoding before creating host files.
        device_request(self.identity, 3, 1)
        self.session, self.helper, self.core = session, bytes(helper), bytes(core)
        self._operation_lock = threading.Lock()
        self._operation_started = False
        self.root = Path(directory)
        self.root.mkdir()  # new host evidence directory, no historical replay
        self.state = {'schema': 1, 'identity': self.identity.hex(), 'phase': 'PREPARED',
                      'helper_sha256': sha(self.helper), 'core_sha256': sha(self.core),
                      'command': 0, 'request_id': 0, 'journal': []}
        self._save()

    def _save(self):
        target = self.root/'state.private.json'
        temporary = self.root/('state-' + uuid.uuid4().hex + '.tmp')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(self.state, stream, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)

    def _fail(self):
        self.state['phase'] = 'REVIEW'
        self.session.healthy = False
        self.session.mutating = True  # prevent automatic service recovery
        try: self._save()
        except BaseException: pass  # retain the original error and archived evidence

    def _exchange(self, wire, payload=None):
        if self.state['phase'] == 'REVIEW' or not self.session.healthy:
            raise ReviewRequired('Previous result needs review; no replay')
        names = ('a7c2.dex.request', 'a7c2.dex.payload', 'libJit.so', 'a7c2.dex.result')
        owned = {}
        for name in names:
            if self.session.read('/tmp/jiritsu/' + name, True) is not None:
                raise ReviewRequired('Existing temporary file: ' + name)
        self.state['command'] += 1
        self.state['journal'].append({'command': self.state['command'], 'intent': True,
                                       'request_sha256': sha(wire)})
        self._save()
        archived_request = self.root / f"{self.state['command']:06d}.request.private.bin"
        with archived_request.open('xb') as stream:
            stream.write(wire); stream.flush(); os.fsync(stream.fileno())
        for name, data in (('a7c2.dex.request', wire), ('a7c2.dex.payload', payload)):
            if data is None: continue
            if not data or len(data) > 65536: raise ValueError('Invalid temporary payload')
            owned[name] = bytes(data)
            self.session.temp(name, data)
            if self.session.read('/tmp/jiritsu/' + name) != data:
                raise ReviewRequired('Temporary input readback differs')
        self.state['journal'][-1]['native_about_to_run'] = True
        self._save()
        owned['libJit.so'] = self.helper
        self.session.temp('libJit.so', self.helper)
        raw = self.session.read('/tmp/jiritsu/a7c2.dex.result')
        archive = self.root / f"{self.state['command']:06d}.receipt.private.bin"
        with archive.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        parsed = receipt(raw, wire)
        self.state['journal'][-1].update(intent=False, result=parsed)
        self._save()
        if parsed['status'] != 0 and not (parsed['status'] == -16004 and parsed.get('intent') and
                                         wire[:8] == b'A7DEX001' and struct.unpack_from('<I', wire, 8)[0] == 3):
            raise ReviewRequired('Native request stopped: ' + str(parsed['status']))
        if parsed.get('review'):
            raise ReviewRequired('Native pipeline retained an uncertain result')
        owned['a7c2.dex.result'] = raw
        for name, data in owned.items():
            if self.session.read('/tmp/jiritsu/' + name) != data:
                raise ReviewRequired('Temporary file changed before cleanup: ' + name)
        for name in ('libJit.so', 'a7c2.dex.payload', 'a7c2.dex.request', 'a7c2.dex.result'):
            if name not in owned: continue
            if self.session.read('/tmp/jiritsu/' + name) != owned[name]:
                raise ReviewRequired('Temporary file changed before cleanup: ' + name)
            self.session.temp(name, remove=True)
            if self.session.read('/tmp/jiritsu/' + name, True) is not None:
                raise ReviewRequired('Temporary cleanup incomplete: ' + name)
        return parsed

    @operation
    def stage(self):
        if self.state['phase'] != 'PREPARED':
            raise ReviewRequired('Staging requires a fresh prepared transaction')
        self._operation_started = True
        self.state['phase'] = 'STAGING'; self._save()
        self._exchange(request(self.plan, self.identity, CREATE))
        for index, offset in enumerate(range(0, len(self.core), CHUNK_BYTES)):
            report = self._exchange(request(self.plan, self.identity, PUT, index), self.core[offset:offset + CHUNK_BYTES])
            if report.get('completed_chunks') != index + 1:
                self.state['phase'] = 'REVIEW'; self._save()
                raise ReviewRequired('Receiver did not confirm the next chunk')
        report = self._exchange(request(self.plan, self.identity, ASSEMBLE))
        if report.get('phase') != 2:
            self.state['phase'] = 'REVIEW'; self._save()
            raise ReviewRequired('Receiver did not confirm a complete core')
        self.state['phase'] = 'CORE_READY'; self._save()
        return report

    def _control(self, operation, **kwargs):
        if self.state['phase'] not in ('CORE_READY', 'ARMING', 'ARMED', 'COMPLETE', 'DISABLING', 'DISABLED'):
            raise ReviewRequired('A verified staged core is required')
        self._operation_started = True
        self.state['request_id'] += 1; self._save()
        report = self._exchange(device_request(self.identity, operation, self.state['request_id'], **kwargs))
        if report.get('review'):
            self.state['phase'] = 'REVIEW'; self._save()
            raise ReviewRequired('Native pipeline retained an uncertain result')
        if not report.get('intent') and report.get('operation') == 4 and not report.get('active'):
            self.state['phase'] = 'DISABLED'
        elif report.get('photo_complete'): self.state['phase'] = 'COMPLETE'
        elif report.get('arm_accepted'):
            arm = self.state['arms'][-1]
            if (report['request_id'] != arm['request_id'] or report['epoch'] != arm['epoch'] or
                report['generation'] != arm['generation'] or
                (arm['media'] is not None and arm['media'] != 0xffffffff and report['media'] != arm['media'])):
                raise ReviewRequired('Accepted pair differs from the requested capture identity')
            self.state['phase'] = 'ARMED'
        self._save()
        return report

    @operation
    def arm(self, *, epoch, generation, media=None, nonce=None):
        if self.state['phase'] not in ('CORE_READY', 'DISABLED'):
            raise ReviewRequired('A new pair cannot replace the current operation')
        arms = self.state.setdefault('arms', [])
        if arms and epoch <= max(row['epoch'] for row in arms):
            raise ValueError('Capture epochs must increase')
        used = {row['nonce'] for row in arms}
        if nonce is None:
            nonce = uuid.uuid4().int & 0xffffff
            while nonce in used: nonce = uuid.uuid4().int & 0xffffff
        if nonce in used: raise ValueError('Output nonce already used in this host transaction')
        device_request(self.identity, 1, self.state['request_id'] + 1, epoch=epoch,
                       generation=generation, media=media, nonce=nonce)
        self._operation_started = True
        arms.append({'epoch': epoch, 'generation': generation, 'media': media, 'nonce': nonce,
                     'request_id': self.state['request_id'] + 1})
        self._save()
        report = self._control(1, epoch=epoch, generation=generation, media=media, nonce=nonce)
        self.state['phase'] = 'ARMING'; self._save()
        return report

    @operation
    def query(self):
        return self._control(3)

    @operation
    def disable(self):
        report = self._control(4)
        if self.state['phase'] != 'DISABLED': self.state['phase'] = 'DISABLING'
        self._save()
        return report
