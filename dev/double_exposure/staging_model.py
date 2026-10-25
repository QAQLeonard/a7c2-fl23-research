"""Offline-only model of a bounded, journaled core transfer; no device transport.

All methods require one serialized caller. A reopened transaction verifies every
acknowledged byte. An unfinished intent requires review, never write replay.
READY describes verified file contents, not a loadable ELF or SDK readiness.
Windows fsync here is not a claim about power-loss durability on camera storage.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

CHUNK_BYTES = 48 * 1024
MAX_BYTES = 8 * 1024 * 1024


class ReviewRequired(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ReviewRequired('Expected a regular owned file: ' + path.name)
    return info


@dataclass(frozen=True)
class Plan:
    size: int
    sha256: str
    chunks: tuple

    def __post_init__(self):
        if type(self.size) is not int or not 0 < self.size <= MAX_BYTES:
            raise ValueError('Invalid core size')
        if type(self.chunks) is not tuple or len(self.chunks) != (self.size + CHUNK_BYTES - 1) // CHUNK_BYTES:
            raise ValueError('Invalid chunk count')
        for value in (self.sha256, *self.chunks):
            if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Invalid SHA-256')

    @classmethod
    def from_bytes(cls, data):
        return cls(len(data), digest(data), tuple(digest(data[i:i + CHUNK_BYTES])
                                                for i in range(0, len(data), CHUNK_BYTES)))

    def document(self):
        return {'size': self.size, 'sha256': self.sha256, 'chunk_bytes': CHUNK_BYTES,
                'chunks': list(self.chunks)}

    def chunk_size(self, index):
        if type(index) is not int or not 0 <= index < len(self.chunks):
            raise ValueError('Invalid chunk index')
        return min(CHUNK_BYTES, self.size - index * CHUNK_BYTES)


class LocalStage:
    """Local filesystem stand-in, deliberately not connected to Session/USB.

    No deletion, overwrite of core/chunks, automatic loading or cleanup. Hashes
    detect transfer mismatch; they are not signatures or authorship checks.
    """
    def __init__(self, root, plan, state):
        self.root, self.plan, self.state = Path(root), plan, state

    @classmethod
    def create(cls, root, plan):
        root = Path(root)
        root.mkdir()  # create-new directory is the ownership boundary
        stage = cls(root, plan, {'schema': 1, 'plan': plan.document(),
                                'phase': 'RECEIVING', 'completed': 0, 'intent': None})
        stage._save()
        return stage

    @classmethod
    def reopen(cls, root, plan):
        root = Path(root)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ReviewRequired('Transaction directory is not owned local storage')
        try:
            regular(root / 'state.json')
            state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
            expected = {'schema', 'plan', 'phase', 'completed', 'intent'}
            if set(state) != expected or state['schema'] != 1 or state['plan'] != plan.document():
                raise ReviewRequired('Transaction plan differs')
            stage = cls(root, plan, state)
            stage.verify()
            return stage
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ReviewRequired('Cannot verify existing transaction') from error

    def _save(self):
        try:
            self._save_state()
        except BaseException:
            self.state['phase'] = 'REVIEW'
            raise

    def _save_state(self):
        temporary = self.root / ('.journal-' + uuid.uuid4().hex)
        with temporary.open('xb') as stream:
            stream.write((json.dumps(self.state, sort_keys=True) + '\n').encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.root / 'state.json')
        if os.name != 'nt':
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _chunk(self, index):
        return self.root / f'{index:04d}.chunk'

    def _read_chunk(self, index):
        path = self._chunk(index)
        if regular(path).st_size != self.plan.chunk_size(index):
            raise ReviewRequired('Chunk size differs')
        data = path.read_bytes()
        if digest(data) != self.plan.chunks[index]:
            raise ReviewRequired('Chunk digest differs')
        return data

    def verify(self):
        state = self.state
        count = state['completed']
        if state['intent'] is not None or state['phase'] not in ('RECEIVING', 'READY'):
            raise ReviewRequired('Unfinished intent; preserve files without replay')
        if type(count) is not int or not 0 <= count <= len(self.plan.chunks):
            raise ReviewRequired('Invalid completed count')
        expected = {'state.json'} | {self._chunk(i).name for i in range(count)}
        for i in range(count):
            self._read_chunk(i)
        if state['phase'] == 'READY':
            if count != len(self.plan.chunks):
                raise ReviewRequired('Incomplete READY transaction')
            expected.add('core.so')
            path = self.root / 'core.so'
            if regular(path).st_size != self.plan.size or digest(path.read_bytes()) != self.plan.sha256:
                raise ReviewRequired('Assembled core differs')
        if {p.name for p in self.root.iterdir()} != expected:
            raise ReviewRequired('Unacknowledged files; preserve transaction')

    def receive(self, index, data):
        self.verify()
        size = self.plan.chunk_size(index)
        if self.state['phase'] != 'RECEIVING' or index != self.state['completed']:
            raise ValueError('Only the next unacknowledged chunk can be sent')
        if len(data) != size or digest(data) != self.plan.chunks[index]:
            raise ValueError('Chunk does not match the plan')
        self.state['intent'] = {'operation': 'WRITE_CHUNK', 'index': index}
        self._save()  # persist before the first data side effect
        with self._chunk(index).open('xb') as stream:
            written = stream.write(data)
            if written != len(data):
                raise ReviewRequired('Short chunk write')
            stream.flush()
            os.fsync(stream.fileno())
        self._read_chunk(index)
        self.state['completed'] += 1
        self.state['intent'] = None
        self._save()

    def assemble(self):
        self.verify()
        if self.state['phase'] != 'RECEIVING' or self.state['completed'] != len(self.plan.chunks):
            raise ValueError('Assembly requires every acknowledged chunk')
        self.state['intent'] = {'operation': 'ASSEMBLE'}
        self._save()
        temporary = self.root / 'assembling.tmp'
        total, checksum = 0, hashlib.sha256()
        with temporary.open('xb') as stream:
            for index in range(len(self.plan.chunks)):
                data = self._read_chunk(index)
                if stream.write(data) != len(data):
                    raise ReviewRequired('Short assembly write')
                checksum.update(data)
                total += len(data)
            stream.flush()
            os.fsync(stream.fileno())
        if total != self.plan.size or checksum.hexdigest() != self.plan.sha256:
            raise ReviewRequired('Whole-core digest differs')
        # Local no-replace publication. This is not a camera Fsys_Move claim.
        os.link(temporary, self.root / 'core.so')
        temporary.unlink()
        self.state['phase'], self.state['intent'] = 'READY', None
        self._save()
        self.verify()
        return self.root / 'core.so'
