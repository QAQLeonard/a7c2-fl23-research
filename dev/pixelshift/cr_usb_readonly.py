"""Explicit A7CR service collection: settings RAM, saved settings, optional shadows.

No native payload, memory-address reads, firmware/file/settings writes, saves,
capture commands, terminal enabling or shell execution. Authentication changes
temporary USB identity. Settings RAM is NOT CP execution RAM or a motion trace.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys
import time

MODEL = 'ILCE-7CR'
CP_UNITS = tuple(range(0x02a40000, 0x02a40013))
SERVICE_PID = 0x0336
USB_SELECTION_PID = 0x096f  # Observed on the contributing A7CR after StopSenser.


def physical_port(device):
    ports = getattr(device, 'port_numbers', None)
    bus = getattr(device, 'bus', None)
    return (bus, tuple(ports)) if bus is not None and ports else None


def release_linux_storage(device, interface):
    """Detach only the selected interface, never unload a host-wide driver."""
    if sys.platform.startswith('linux') and device.is_kernel_driver_active(interface):
        device.detach_kernel_driver(interface)
        return True
    return False


def wait_normal_identity(usb, backend, *, port, normal_pid, timeout=15):
    """Observe a matching normal identity after releasing the service handle.

    Disappearance alone is insufficient. No second StopSenser, authentication,
    capture, settings request or reconnect command is sent here.
    """
    deadline = time.monotonic()+timeout
    while True:
        matches, service_present = [], False
        for dev in usb.core.find(find_all=True, idVendor=0x054c, backend=backend):
            try:
                same_port = port is not None and physical_port(dev) == port
                if port is not None and not same_port:
                    continue
                if dev.idProduct == SERVICE_PID:
                    service_present = True
                    continue
                if same_port and dev.idProduct in (normal_pid, USB_SELECTION_PID):
                    matches.append(dict(product_id='0x%04x' % dev.idProduct,
                        matched_by='physical-port', usb_selection_required=dev.idProduct == USB_SELECTION_PID))
                elif port is None and dev.idProduct == normal_pid:
                    name = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ''
                    if name == MODEL:
                        matches.append(dict(product_id='0x%04x' % dev.idProduct,
                            matched_by='model-and-product', usb_selection_required=False))
            finally:
                usb.util.dispose_resources(dev)
        if not service_present and len(matches) == 1:
            return dict(normal_identity_observed=True, **matches[0])
        if time.monotonic() >= deadline:
            raise RuntimeError('Service exit not confirmed: matching normal USB identity did not reappear; do not retry StopSenser')
        time.sleep(0.25)


class ReadOnlyChannel:
    """Filter exact read requests before the vendor implementation sees them."""
    def __init__(self, channel, *, cp_shadows=False):
        self.channel = channel
        self.cp_shadows = cp_shadows
        self.healthy = True
        self.operations = []

    def sendSenserPacket(self, function, data, out=None):
        allowed = function == 0x40 and data in (struct.pack('<HHB', 0x603, 5, 0),
                                               struct.pack('<HHB', 0x603, 5, 1))
        if self.cp_shadows:
            allowed = allowed or (function == 0x40 and len(data) == 12
                and struct.unpack_from('<HH', data) == (0x603, 0x40)
                and struct.unpack_from('<II', data, 4) in [(key, 1) for key in CP_UNITS])
        if not allowed or out is not None:
            raise ValueError('Collector permits only settings snapshot reads and selected CP shadow reads')
        if not self.healthy:
            raise RuntimeError('Previous USB result is unknown; no further requests will be sent')
        try:
            response, payload = self.channel.sendSenserPacket(function, data)
            if response != 0:
                raise RuntimeError('Sony read request returned status '+str(response))
        except BaseException:
            self.healthy = False
            raise
        self.operations.append(data.hex())
        return response, payload


def read_snapshots(channel, save, *, cp_shadows=False, event=None):
    """Protocol-only core, exercised with a recording fake in offline tests."""
    gate = ReadOnlyChannel(channel, cp_shadows=cp_shadows)
    for name, memory in (('settings-ram.bin', 1), ('settings-saved.bin', 0)):
        if event:
            event(name)
        _, data = gate.sendSenserPacket(0x40, struct.pack('<HHB', 0x603, 5, memory))
        if not data:
            gate.healthy = False
            raise RuntimeError('Camera returned an empty settings snapshot')
        save(name, data)
    if cp_shadows:
        for key in CP_UNITS:
            if event:
                event('cp-shadow-%08x.bin' % key)
            _, data = gate.sendSenserPacket(0x40, struct.pack('<HHII', 0x603, 0x40, key, 1))
            if not data:
                gate.healthy = False
                raise RuntimeError('Camera returned an empty CP shadow unit')
            save('cp-shadow-%08x.bin' % key, data)
    return gate


def vendor_modules():
    import importlib
    here = Path(__file__).resolve().parent
    vendor = here/'vendor'
    if not vendor.is_dir():
        vendor = here.parents[1]/'src/fl23/vendor'
    sys.path.insert(0, str(vendor))
    return importlib.import_module('pmca.usb.sony'), importlib.import_module('pmca.usb.driver.generic'), importlib.import_module('pmca.usb.driver.generic.libusb')


class Connection:
    """A single bounded service session; no TUR or camera-info precondition."""
    def __enter__(self):
        import usb.core
        import usb.util
        import usb.backend.libusb1
        import libusb_package
        sony, generic, libusb = vendor_modules()
        self.usb = usb
        self.sony = sony
        self.device = None
        self.auth = None
        self.healthy = False
        self.exit_observation = None
        self.kernel_driver_detached = False
        backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
        if backend is None:
            raise RuntimeError('libusb is unavailable; install the optional USB requirements')

        class Bounded(libusb.UsbBackend):
            def __init__(self, device):
                super().__init__(device)
                self.deadline = time.monotonic()+45
            def remaining(self):
                value = int((self.deadline-time.monotonic())*1000)
                if value <= 0:
                    raise TimeoutError('Bounded USB operation timed out')
                return min(value, 5000)
            def read(self, ep, size, timeout=None):
                return super().read(ep, size, self.remaining())
            def write(self, ep, data):
                self.dev.default_timeout = self.remaining()
                return super().write(ep, data)
            def vendorRequestOut(self, *args):
                self.dev.default_timeout = self.remaining()
                return super().vendorRequestOut(*args)

        class Auth(sony.SonySenserAuthDevice):
            def stop(self):
                # Do not turn an unknown USB teardown result into reported success.
                self.driver.vendorRequestOut(*self.SONY_VendorRequest_StopSenser)

        matches = []
        for dev in usb.core.find(find_all=True, idVendor=0x054c, backend=backend):
            if dev.idProduct == 0x0336:
                for previous in matches:
                    usb.util.dispose_resources(previous)
                usb.util.dispose_resources(dev)
                raise RuntimeError('A Sony service device is already connected; end that session before starting a fresh collection')
            try:
                name = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ''
                if name == MODEL:
                    matches.append(dev)
                else:
                    usb.util.dispose_resources(dev)
            except BaseException:
                usb.util.dispose_resources(dev)
                raise
        if len(matches) != 1:
            for dev in matches:
                usb.util.dispose_resources(dev)
            raise RuntimeError('Connect exactly one ILCE-7CR in Mass Storage mode; no camera was authenticated')
        normal = matches[0]
        self.normal_port = physical_port(normal)
        self.enumeration_backend = backend
        detached_interface = None
        switched = False
        try:
            interface = normal.get_active_configuration()[(0, 0)]
            if interface.bInterfaceClass != 8:
                raise RuntimeError('Choose Mass Storage mode on the A7CR')
            self.normal_product_id = normal.idProduct
            number = interface.bInterfaceNumber
            if release_linux_storage(normal, number):
                detached_interface = number
                self.kernel_driver_detached = True
            auth = Auth(generic.GenericUsbDriver(Bounded(normal)))
            auth.start()
            auth.authenticate()
            switched = True
        finally:
            usb.util.dispose_resources(normal)
            if detached_interface is not None and not switched:
                # A failed authentication can leave the original identity alive.
                # Reattach its interface if possible; re-enumerated devices bind
                # their kernel drivers independently.
                try:
                    normal.attach_kernel_driver(detached_interface)
                except Exception:
                    pass
                finally:
                    usb.util.dispose_resources(normal)
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            devices = list(usb.core.find(find_all=True, idVendor=0x054c, idProduct=0x0336, backend=backend))
            if len(devices) > 1:
                for dev in devices:
                    usb.util.dispose_resources(dev)
                raise RuntimeError('More than one Sony service device appeared; stopped')
            if devices:
                self.device = devices[0]
                break
            time.sleep(0.25)
        if self.device is None:
            raise RuntimeError('Service USB identity did not appear; no read or retry was performed')
        try:
            # Native service initialization needs a short enumeration boundary.
            time.sleep(2)
            self.backend = Bounded(self.device)
            interface = self.device.get_active_configuration()[(0, 0)]
            if release_linux_storage(self.device, interface.bInterfaceNumber):
                self.kernel_driver_detached = True
            self.auth = Auth(generic.GenericUsbDriver(self.backend))
            self.auth.start()
            self.auth.authenticate()
            self.channel = sony.SonySenserDevice(self.auth.driver)
            self.healthy = True
            return self
        except BaseException:
            usb.util.dispose_resources(self.device)
            raise

    def sendSenserPacket(self, function, data):
        self.backend.deadline = time.monotonic()+45
        try:
            return self.channel.sendSenserPacket(function, data)
        except BaseException:
            self.healthy = False
            raise

    def __exit__(self, kind, value, traceback):
        stop_error = None
        try:
            if kind is None and self.healthy:
                try:
                    self.auth.stop()
                except Exception as exc:
                    # Some bodies disconnect before the host receives the
                    # final control-transfer status. Observe the next identity
                    # instead of suppressing an arbitrary transport failure.
                    stop_error = exc
        finally:
            self.usb.util.dispose_resources(self.device)
        if kind is None and self.healthy:
            self.exit_observation = dict(normal_identity_observed=False,
                stop_request_error_type=type(stop_error).__name__ if stop_error else None)
            if stop_error:
                self.exit_observation['stop_request_error'] = str(stop_error)
            self.exit_observation.update(wait_normal_identity(self.usb, self.enumeration_backend,
                port=self.normal_port, normal_pid=self.normal_product_id))


def collect(root, *, label, cp_shadows=False, connector=Connection):
    root = Path(root).resolve()
    session = json.loads((root/'session.json').read_text(encoding='utf-8'))
    if session.get('schema') != 'a7cr-reference-session/1' or session.get('model') != MODEL:
        raise ValueError('Initialize an A7CR reference session first')
    if label not in ('off-before', 'four-selected', 'off-after'):
        raise ValueError('Unknown collection label')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = root/'runtime'/(label+'-'+stamp)
    folder.mkdir(parents=True, exist_ok=False)
    report = dict(schema='a7cr-readonly-settings/1', model_from_usb=None,
        firmware_user_reported=session.get('firmware_user_reported'), label=label,
        files=[], complete=False, data_complete=False, settings_ram_captured=False, cp_execution_ram_captured=False,
        camera_io=True, service_exit_confirmed=False, cp_shadows_requested=cp_shadows,
        firmware_writes=False, camera_file_writes=False, settings_writes=False,
        save_commands=False, memory_patches=False, native_payload_uploaded=False,
        capture_commands=False, temporary_usb_identity_change=True,
        stage='connecting',
        usb_observation_limit='Mass Storage/service connection can change the observed state; not an in-exposure trace',
        cp_shadow_limit='Backup-shadow units are not CP execution memory; calibration semantics are not assumed')

    def record():
        (folder/'snapshot.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')

    def save(name, data):
        with (folder/name).open('xb') as handle:
            handle.write(data)
        report['files'].append(name)
        if name == 'settings-ram.bin':
            report['settings_ram_captured'] = True
        record()

    def event(name):
        report['stage'] = 'reading'
        report['current_read'] = name
        record()

    record()
    connection = None
    try:
        print('Reading native A7CR settings only. Keep USB connected until this command finishes.', flush=True)
        with connector() as connection:
            report['model_from_usb'] = MODEL
            gate = read_snapshots(connection, save, cp_shadows=cp_shadows, event=event)
            report['read_operations'] = gate.operations
            report['data_complete'] = True
            report['kernel_driver_detached'] = getattr(connection, 'kernel_driver_detached', False)
            report['stage'] = 'service-exit'
            report.pop('current_read', None)
            record()
        report['service_exit'] = getattr(connection, 'exit_observation', None)
        report['service_exit_confirmed'] = bool(report['service_exit'] and
            report['service_exit']['normal_identity_observed'])
        if not report['service_exit_confirmed']:
            raise RuntimeError('Collector connector did not confirm normal USB identity')
        report['complete'] = True
        report['stage'] = 'finished'
        record()
    except BaseException as exc:
        # Preserve partial bytes and the failed session; no automatic retry.
        report['error_type'] = type(exc).__name__
        report['error'] = str(exc)
        report['service_exit'] = getattr(connection, 'exit_observation', None)
        record()
        raise RuntimeError('Read-only collection stopped. Preserve runtime/'+folder.name+
                           '/snapshot.json; do not run another command blindly. '+str(exc)) from exc
    return dict(complete=True, folder=folder.name, files=len(report['files']),
        settings_ram_captured=True, cp_execution_ram_captured=False,
        camera_io_finished=True, originals_modified=False,
        message='USB reads have ended. The camera may ask you to choose Mass Storage again. Disconnect USB before changing camera menu settings.')
