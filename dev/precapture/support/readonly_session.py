"""Constrain a reviewed transport to existing-file/settings reads.

No USB module is imported or opened here. The private operator supplies the
pinned transport and the common device lock. Normal entry/healthy exit use
its authentication protocol, but an unknown exchange never triggers rescue,
reauthentication, temporary-file cleanup or upload from this wrapper.
An explicit optional scope permits one fixed eight-byte vendor policy read;
the default session continues to reject direct CP property packets.
"""
import struct

REVIEWED_FRAMINGS = frozenset({'length-delimited-zlp/1', 'length-delimited-zlp/3'})


def exit_without_rescue(transport, session):
    """Close only a known healthy session; never reauthenticate an unknown one."""
    try:
        if session.healthy:
            try:
                session.auth.stop()
            except BaseException:
                session.healthy = False
                raise
            transport._service_exit = transport.time.monotonic()
    finally:
        transport.usb.util.dispose_resources(session.dev)


def session_class(transport, *, policy_scalar=False):
    if type(policy_scalar) is not bool:
        raise ValueError('Explicit policy-scalar read scope required')
    if getattr(transport.SonySenserDevice, 'RESPONSE_FRAMING', None) not in REVIEWED_FRAMINGS:
        raise ValueError('Reviewed length-delimited reply transport required')

    class ReadOnlySession(transport.Session):
        def __init__(self, paths, expected=None):
            paths = frozenset(paths)
            if not paths or any(not isinstance(p, str) or not p.startswith('/tmp/jiritsu/')
                                or '\0' in p or len(p) > 510 or not p.isascii() for p in paths):
                raise ValueError('Explicit existing-file path allowlist required')
            self.allowed_paths = paths
            self._selected = None
            self._policy_scalar_available = policy_scalar
            super().__init__(expected)

        def call(self, method, *args):
            owner = getattr(method, '__self__', None)
            name = getattr(method, '__name__', '')
            camera = getattr(self, 'camera', None)
            channel = getattr(self, 'channel', None)
            if owner is camera and camera is not None and name == 'getBackupPresetData':
                if len(args) != 1 or type(args[0]) is not bool:
                    raise ValueError('Only a live/saved settings snapshot is permitted')
            elif owner is camera and camera is not None and name == '_sendAdjustControlPacket' and policy_scalar:
                if args != (0x603, 0x40, struct.pack('<II', 0xfa0182, 1)) or not self._policy_scalar_available:
                    raise ValueError('Outside the single fixed policy-scalar read')
                self._policy_scalar_available = False
            elif owner is channel and channel is not None and name == 'sendSenserPacket':
                if len(args) != 2 or args[0] != 0x40 or not isinstance(args[1], bytes):
                    raise ValueError('Not a read-only file packet')
                packet = args[1]
                selections = {struct.pack('<HH', 0x1001, 15)+b'\0'+p.encode('ascii')+b'\0'
                              for p in self.allowed_paths}
                if packet not in selections:
                    if (packet != struct.pack('<HH', 0x1001, 17)+b'\0\xff\0'
                            or self._selected not in self.allowed_paths):
                        raise ValueError('File operation is outside the read-only allowlist')
            else:
                raise ValueError('No parameter writes, native calls, capture or arbitrary packets')
            return super().call(method, *args)

        def read_cp_policy_value(self):
            raw = self.call(self.camera._sendAdjustControlPacket,
                0x603, 0x40, struct.pack('<II', 0xfa0182, 1))
            if not isinstance(raw, bytes) or len(raw) != 8:
                raise ValueError('Incomplete fixed policy-scalar reply; do not replay')
            return raw

        def select(self, path):
            if path not in self.allowed_paths:
                raise ValueError('File path is outside the read-only allowlist')
            self._selected = None
            super().select(path)
            self._selected = path

        def jiritsu(self, cmd, data=b'', missing=False):
            if cmd not in (15, 17):
                raise ValueError('File upload, deletion and execution are forbidden')
            return super().jiritsu(cmd, data, missing)

        def __exit__(self, *args):
            # Intentionally do not call Session.__exit__: current main can
            # reauthenticate a broken read-only channel as automatic rescue.
            # This research session preserves unknown outcomes instead.
            exit_without_rescue(transport, self)

    return ReadOnlySession
