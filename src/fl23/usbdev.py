"""USB 设备层：后端选择、驱动识别、模式切换。所有设备访问都留在这个模块里。

相机有两个 USB 身份：

* ``054C:0E8A`` 海量存储身份（插上就出现）
* ``054C:0336`` SonyUSBDevice 服务身份（主机在 0E8A 上完成认证后由相机切过去）

两个身份都要装好驱动，libusb 才能打开。这里同时接受 **WinUSB** 与
**libusbK**（以及 libusb-win32 的 libusb0）—— 三种驱动对 libusb 都可见，
pyusb 的 libusb1 后端都能打开，所以检查只要求是其中之一，不强制某一种。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

VID = 0x054C
PID_MSC = 0x0E8A          # 海量存储 / 常规身份
PID_SERVICE = 0x0336      # SonyUSBDevice / 服务身份

# libusb 能打开的驱动服务名（不区分大小写）
ACCEPTED_SERVICES = ('winusb', 'libusbk', 'libusb0')
SERVICE_LABELS = {'winusb': 'WinUSB', 'libusbk': 'libusbK', 'libusb0': 'libusb-win32'}

# 读取驱动服务名用的脚本宿主：先用系统自带的 Windows PowerShell，
# 找不到才退回另一个；两者都不要求额外安装。
SHELL_CANDIDATES = ('powershell.exe', 'pwsh.exe')

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'vendor'))

_PS_SCRIPT = r'''
$ErrorActionPreference = 'SilentlyContinue'
$out = @()
$ids = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_054C&PID_(0E8A|0336)' } |
       Select-Object -ExpandProperty InstanceId
foreach ($id in $ids) {
  $svc = (Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_Service').Data
  $out += [pscustomobject]@{ InstanceId = $id; Service = $svc }
}
$out | ConvertTo-Json -Compress
'''


class DriverError(RuntimeError):
    """驱动缺失或不是可接受的驱动。"""


def backend():
    """返回可用的 libusb1 后端；找不到就抛错。"""
    import usb.backend.libusb1
    import libusb_package
    be = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if be is None:
        raise RuntimeError('找不到 libusb 运行库，请重新运行 Start.cmd 安装依赖')
    return be


def find(pid, timeout=0.0):
    """等待并取出唯一一台目标设备；等不到就返回 ``None``。

    返回的是单个 ``usb.core.Device``，不是列表。找到两台以上会抛错，
    因为后面的流程无法判断该操作哪一台。
    """
    import usb.core
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        found = list(usb.core.find(find_all=True, idVendor=VID, idProduct=pid, backend=backend()))
        if found:
            break
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.4)
    if len(found) != 1:
        raise RuntimeError(f'需要且只能连接一台目标相机（USB {pid:04x}），现在检测到 {len(found)} 台')
    return found[0]


def require(pid, timeout=0.0, hint=''):
    """与 :func:`find` 相同，但等不到时抛一条能直接显示给用户的错误。"""
    device = find(pid, timeout)
    if device is None:
        raise RuntimeError(hint or f'没有找到 USB {pid:04x} 设备，请确认相机已开机并以 USB 连接')
    return device


def dispose(device):
    """释放 pyusb 资源；传 ``None``、列表或不是设备的对象都安静返回。

    ``usb.util.dispose_resources()`` 只接受单个 Device，传列表会得到
    ``'list' object has no attribute '_ctx'``，所以这里统一做防御。
    """
    if device is None or isinstance(device, (list, tuple, set)):
        return
    if not hasattr(device, '_ctx'):
        return
    try:
        import usb.util
        usb.util.dispose_resources(device)
    except Exception:
        pass


def _windows_services():
    """读出两个身份各自绑定的驱动服务名。失败时返回 None。

    优先用系统自带的 Windows PowerShell（5.1，Windows 一定会有），
    找不到才退回 pwsh；也就是说不需要额外安装任何新版脚本宿主。
    """
    if sys.platform != 'win32':
        return None
    for exe in SHELL_CANDIDATES:
        try:
            done = subprocess.run(
                [exe, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', _PS_SCRIPT],
                capture_output=True, text=True, errors='replace', timeout=60)
        except Exception:
            continue
        if done.returncode != 0:
            continue
        parsed = _parse_services(done.stdout)
        return [] if parsed is None else parsed
    return None


def _parse_services(text):
    """把脚本输出的 JSON 解析成 [(InstanceId, Service)]。"""
    text = (text or '').strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        return None
    if isinstance(data, dict):
        data = [data]
    return [(str(row.get('InstanceId', '')), row.get('Service')) for row in data]


def _accept(service):
    if not service:
        return False
    return str(service).strip().lower() in ACCEPTED_SERVICES


def driver_report():
    """两个身份的在线情况与驱动状态。

    返回 ``{'0e8a': {...}, '0336': {...}, 'platform': ..., 'ok': bool}``。
    ``reachable`` 表示 libusb 能打开；``service`` 是驱动服务名。
    """
    rows = _windows_services()
    report = {'platform': sys.platform, 'checked': [], 'ok': False}
    for pid, key in ((PID_MSC, '0e8a'), (PID_SERVICE, '0336')):
        item = {'pid': f'{pid:04x}', 'present': False, 'service': None,
                'driver_ok': False, 'reachable': False, 'detail': ''}
        if rows is not None:
            needle = f'PID_{pid:04X}'.upper()
            matched = [s for i, s in rows if needle in i.upper()]
            if matched:
                item['present'] = True
                item['service'] = matched[0]
                item['driver_ok'] = _accept(matched[0])
                if not item['driver_ok']:
                    item['detail'] = f'当前驱动 “{matched[0]}” 不是 WinUSB / libusbK'
            else:
                item['detail'] = '未在系统里找到此身份（相机可能未以该模式连接）'
        if item['present'] and item['driver_ok']:
            try:
                dev = find(pid)
                item['reachable'] = dev is not None
                dispose(dev)
                if not item['reachable']:
                    item['detail'] = '驱动已装但读不到 USB 配置，请重新插拔'
            except Exception as exc:
                item['detail'] = str(exc)
        elif rows is None:
            # 读不到系统信息时，退回“能不能打开”作为唯一判据
            try:
                dev = find(pid)
                item['present'] = dev is not None
                item['reachable'] = dev is not None
                item['driver_ok'] = item['reachable']
                if dev is None:
                    item['detail'] = '没有找到此身份（相机可能未开机，或未处于该模式）'
                dispose(dev)
            except ModuleNotFoundError as exc:
                if getattr(exc, 'name', '') == 'usb':
                    item['detail'] = '缺少 pyusb 依赖，请重新运行 Start.cmd 安装'
                else:
                    item['detail'] = str(exc)
            except Exception as exc:
                item['detail'] = str(exc)
        report[key] = item
        report['checked'].append(key)
    report['ok'] = all(report[k]['driver_ok'] and report[k]['reachable'] for k in ('0e8a', '0336'))
    return report


def request_service_mode():
    """在 0E8A 上完成认证，让相机切到 SonyUSBDevice（0336）身份。

    返回 ``{'switched': bool, 'waited': float, 'detail': str}``。
    """
    # 先确认设备存在再导入 pmca：没有相机时不必依赖 vendor，也不会走到
    # ``finally`` 里释放资源（旧版正因为在这里 finally 里 dispose 一个 list 而崩，
    # 而 finally 抛出的异常不会被外层的 except 接住）。
    dev = find(PID_MSC)
    if dev is None:
        return {'switched': False, 'waited': 0.0,
                'detail': '没有找到 054C:0E8A 身份，请确认相机已开机并以 USB 海量存储模式连接'}

    from pmca.usb.driver.generic import GenericUsbDriver
    from pmca.usb.sony import SonySenserAuthDevice
    from transport import Bounded

    auth = None
    try:
        auth = SonySenserAuthDevice(GenericUsbDriver(Bounded(dev, 20)))
        auth.start()
        auth.authenticate()
    finally:
        # Authentication may have switched USB identities. Do not send a stop
        # through the old handle, particularly after an ambiguous failure.
        dispose(dev)

    deadline = time.monotonic() + 20
    started = time.monotonic()
    while True:
        probe = find(PID_SERVICE)
        dispose(probe)
        if probe is not None:
            return {'switched': True, 'waited': round(time.monotonic() - started, 1), 'detail': ''}
        if time.monotonic() >= deadline:
            return {'switched': False, 'waited': round(time.monotonic() - started, 1),
                    'detail': '20 秒内没有出现 0336 服务身份，请确认相机已开机、USB 连接正常'}
        time.sleep(0.5)


def preflight():
    """检查按钮要做的整件事：先看驱动，再切模式，再验第二个驱动。"""
    first = driver_report()
    steps = [{'step': '驱动预检（0E8A）', **_brief(first['0e8a'])}]
    if not first['0e8a']['driver_ok'] or not first['0e8a']['reachable']:
        return {'ok': False, 'steps': steps,
                'message': '054C:0E8A 身份的驱动不可用，请先安装 WinUSB 或 libusbK 驱动再检查'}
    switch = request_service_mode()
    steps.append({'step': '切换到 SonyUSBDevice（0336）', 'ok': switch['switched'],
                  'detail': switch['detail'] or f"等待 {switch['waited']} 秒"})
    if not switch['switched']:
        return {'ok': False, 'steps': steps, 'message': '无法进入服务模式，请确认相机处于 USB 海量存储模式'}
    time.sleep(2)
    second = driver_report()
    steps.append({'step': '驱动复检（0336）', **_brief(second['0336'])})
    ok = second['0336']['driver_ok'] and second['0336']['reachable']
    return {'ok': ok, 'steps': steps,
            'message': '两个 USB 身份的驱动都已就绪' if ok else '0336 身份的驱动不可用，请补装后重新检查',
            'first': first, 'second': second}


def _brief(item):
    return {'ok': bool(item['driver_ok'] and item['reachable']),
            'detail': item['detail'] or (SERVICE_LABELS.get(str(item['service']).lower(),
                                                            item['service'] or '已就绪'))}
