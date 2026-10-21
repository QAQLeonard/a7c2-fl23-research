"""有界的索尼服务通道。所有 USB 访问都经 usbdev，驱动差异在那里处理。"""
import struct
import time

import core
import usbdev
import usb.util
from pmca.usb.driver.generic import GenericUsbDriver, MscBbbDriver
from pmca.usb.driver.generic.libusb import UsbBackend
from pmca.usb.sony import (SonySenserAuthDevice, SonySenserDevice, SonySenserCamera,
                           SonyExtCmdCamera, SonyMscExtCmdDevice)
from pmca.usb import MscDevice


class Bounded(UsbBackend):
    """给每次读写加一个总预算，避免无限等待。"""

    def __init__(self, device, budget=180):
        super().__init__(device)
        self.budget = budget
        self.reset()

    def reset(self):
        self.deadline = time.monotonic() + self.budget

    def timeout(self, t=None):
        left = int((self.deadline - time.monotonic()) * 1000)
        if left <= 0:
            raise TimeoutError('相机操作超出有界等待时间')
        return max(1, min(left, t or self.budget * 1000))

    def read(self, ep, length, timeout=None):
        return super().read(ep, length, self.timeout(timeout))

    def write(self, ep, data):
        self.dev.default_timeout = self.timeout()
        return super().write(ep, data)


def _dispose(device):
    """释放 pyusb 资源；``None`` 或不是设备的对象都安静返回。"""
    usbdev.dispose(device)


def get_device(pid, timeout=0.0):
    """Return one device through the shared backend, or fail before any command."""
    return usbdev.require(pid, timeout=timeout)


def service_identity(snapshot, model):
    """Preserve existing body bindings without an MSC application query."""
    if model != core.MODEL:
        raise RuntimeError('只支持 ' + core.MODEL)
    serial = core.backup_records(snapshot)[0].get(0x00e70003)
    if serial is None or len(serial.data) != 4:
        raise RuntimeError('服务备份缺少四字节序列号属性 00e70003')
    # Sony's old getCameraInfo result hexlified the bytes before hashing.
    return {'model': model, 'serial_sha256': core.sha(serial.data.hex().encode('ascii'))}


def identity():
    """在 0E8A 身份上确认这是目标机型，并取出机身短码。"""
    device = usbdev.require(usbdev.PID_MSC,
                            hint='没有找到 054C:0E8A 身份的相机，请确认已开机并以 USB 海量存储模式连接')
    try:
        driver = MscBbbDriver(Bounded(device, 20))
        if MscDevice(driver).getDeviceInfo().manufacturer.strip() != 'Sony':
            raise RuntimeError('这不是 Sony 设备')
        info = SonyExtCmdCamera(SonyMscExtCmdDevice(driver)).getCameraInfo()
        if info.modelName != core.MODEL:
            raise RuntimeError('只支持 ' + core.MODEL)
        return {'model': info.modelName, 'serial_sha256': core.sha(info.serial.encode())}
    finally:
        _dispose(device)


def _matches(actual, expected):
    if not expected:
        return True
    for key, value in expected.items():
        if value is None:
            continue
        if actual.get(key) != value:
            return False
    return True


class Session:
    """一次完整的服务会话：认证 → 切到 0336 → 打开通道。"""

    def __init__(self, expected=None, service_timeout=25):
        self.expected = expected
        self.healthy = True
        self.service_timeout = service_timeout

    def __enter__(self):
        # Only local USB enumeration is retried. TUR/getCameraInfo can remain
        # busy even when service authentication is usable.
        device = get_device(usbdev.PID_MSC, timeout=15)
        try:
            model = usb.util.get_string(device, device.iProduct) if device.iProduct else None
            if model != core.MODEL:
                raise RuntimeError('USB 型号不符，只支持 ' + core.MODEL)
            auth = SonySenserAuthDevice(GenericUsbDriver(Bounded(device, 20)))
            auth.start()
            auth.authenticate()
        except BaseException:
            # No stop packet or second authentication after an unknown result.
            self.healthy = False
            raise
        finally:
            _dispose(device)
        deadline = time.monotonic() + self.service_timeout
        while True:
            probe = usbdev.find(usbdev.PID_SERVICE)
            if probe is not None:
                self.dev = probe
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('服务身份未出现，请确认 0336 驱动已安装')
            time.sleep(0.5)
        time.sleep(2)
        authenticated = False
        try:
            self.backend = Bounded(self.dev)
            self.auth = SonySenserAuthDevice(GenericUsbDriver(self.backend))
            self.auth.start()
            self.auth.authenticate()
            authenticated = True
            self.channel = SonySenserDevice(self.auth.driver)
            self.camera = SonySenserCamera(self.channel)
            snapshot = self.call(self.camera.getBackupPresetData, True)
            self.identity = service_identity(snapshot, model)
            if not _matches(self.identity, self.expected):
                raise RuntimeError('当前机身与备份的机身不同，拒绝继续')
        except BaseException:
            try:
                if authenticated and self.healthy:
                    self.auth.stop()
            finally:
                _dispose(self.dev)
            raise
        return self

    def __exit__(self, *args):
        try:
            if self.healthy:
                self.auth.stop()
        finally:
            _dispose(self.dev)

    # ---------- 基本操作 ----------
    def call(self, method, *args):
        if not self.healthy:
            raise RuntimeError('会话结果未知，停止后续命令')
        self.backend.reset()
        try:
            return method(*args)
        except BaseException:
            self.healthy = False
            raise

    def jiritsu(self, cmd, data=b'', missing=False):
        if cmd not in (15, 16, 17, 18):
            raise ValueError('不允许此 Jiritsu 命令')
        response, out = self.call(self.channel.sendSenserPacket, 0x40,
                                  struct.pack('<HH', 0x1001, cmd) + data)
        if response or len(out) < 4:
            raise RuntimeError('Jiritsu 响应格式错误')
        status = struct.unpack_from('<I', out)[0]
        if missing and status == 0x10000006:
            return None
        if status:
            raise RuntimeError(f'Jiritsu 状态 {status:#x}')
        return out[4:]

    def select(self, path):
        if not path.startswith('/tmp/jiritsu/') or '\0' in path or len(path) > 510:
            raise ValueError('路径不符')
        self.jiritsu(15, b'\0' + path.encode('ascii') + b'\0')

    def read(self, path, missing=False):
        self.select(path)
        return self.jiritsu(17, b'\0\xff\0', missing)

    def temp(self, name, data=None, remove=False):
        if name not in core.NATIVE_PATHS:
            raise ValueError('不是指定临时文件')
        self.select('/tmp/jiritsu/' + name)
        if remove:
            self.jiritsu(18, b'\0\xff')
        elif data:
            if len(data) > 65536:
                raise ValueError('临时文件过大')
            self.jiritsu(16, b'\0\xff\0' + data)
        else:
            raise ValueError('不允许空文件写入')

    # ---------- 设置读写 ----------
    def cp_read(self, key):
        if key not in core.CP_KEYS:
            raise ValueError('不允许此 CP 单元')
        return self.call(self.camera._sendAdjustControlPacket, 0x603, 0x40,
                         struct.pack('<II', key, 1))

    def cp_write(self, key, data):
        sizes = {core.CP_KEYS[0]: 8192, core.CP_KEYS[1]: 28672}
        if key not in core.CP_KEYS or len(data) != sizes[key]:
            raise ValueError('CP 写入目标或长度不符')
        return self.call(self.camera._sendAdjustControlPacket, 0x603, 0x41,
                         struct.pack('<II', key, 1) + data)

    def ap_write(self, key, data):
        if key not in core.AP_KEYS or len(data) != 1:
            raise ValueError('AP 绑定目标或长度不符')
        return self.call(self.camera.writeBackup, key, data)
