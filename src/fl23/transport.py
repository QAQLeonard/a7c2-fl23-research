"""有界的索尼服务通道。所有 USB 访问都经 usbdev，驱动差异在那里处理。"""
import struct
import time

import core
import usbdev
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
        self.identity = identity()
        if not _matches(self.identity, self.expected):
            raise RuntimeError('当前机身与备份的机身不同，拒绝继续')
        device = usbdev.require(usbdev.PID_MSC,
                                hint='没有找到 054C:0E8A 身份的相机，请确认已开机并以 USB 海量存储模式连接')
        auth = None
        try:
            auth = SonySenserAuthDevice(GenericUsbDriver(Bounded(device, 20)))
            auth.start()
            auth.authenticate()
        except BaseException:
            if auth is not None:
                try:
                    auth.stop()
                except Exception:
                    pass
            raise
        finally:
            _dispose(device)
        deadline = time.monotonic() + self.service_timeout
        while True:
            probe = None
            try:
                probe = usbdev.find(usbdev.PID_SERVICE)
            except RuntimeError as exc:
                if '需要且只能连接一台' in str(exc):
                    raise
            if probe is not None:
                self.dev = probe          # 找到就保留，不要在这里 dispose
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('服务身份未出现，请确认 0336 驱动已安装')
            time.sleep(0.5)
        time.sleep(2)
        self.backend = Bounded(self.dev)
        self.auth = SonySenserAuthDevice(GenericUsbDriver(self.backend))
        try:
            self.auth.start()
            self.auth.authenticate()
            self.channel = SonySenserDevice(self.auth.driver)
            self.camera = SonySenserCamera(self.channel)
            if len(self.camera.readHasp()) != 88:
                raise RuntimeError('ProductInfo 响应不符')
        except BaseException:
            try:
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
        except Exception:
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
