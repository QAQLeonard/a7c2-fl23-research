"""Bounded Sony service transport. All device access stays in this module."""
import struct
import sys
import time
import core
import usb.core
import usb.util
import usb.backend.libusb1
import libusb_package
from pmca.usb.driver.generic import GenericUsbDriver,MscBbbDriver,GenericUsbException
from pmca.usb.driver.generic.libusb import UsbBackend
from io import BytesIO
from pmca.usb.sony import SonySenserAuthDevice,SonySenserCamera,SonyExtCmdCamera,SonyMscExtCmdDevice
from pmca.usb.sony import SonySenserDevice as PmcaSenserDevice
from pmca.usb import MscDevice

class SenserProtocolError(RuntimeError):
    """The reply cannot be associated with the current request."""


class SonySenserDevice(PmcaSenserDevice):
    """Use length-delimited reads, finishing direct CP unit reads explicitly.

    File/settings snapshots retain the field-tested v2 no-eager-read path.
    Direct CP reads finish their aligned response before the immediate WRITE41.
    Preserve any nonempty lookahead rather than discarding real data.
    """
    RESPONSE_FRAMING='length-delimited-zlp/3'
    END_PACKET_MS=1000

    def __init__(self,driver):
        super().__init__(driver)
        self._failed=False
        self._pending=bytearray()

    def _end_packet(self):
        if self._pending:return
        try:data=self.driver.read(self.SenserMinSize,timeout=self.END_PACKET_MS)
        except usb.core.USBTimeoutError:return
        except GenericUsbException as exc:
            if not isinstance(exc.__cause__ or exc.__context__,usb.core.USBTimeoutError):raise
            return
        # Some firmware omits the empty transfer. The read may have returned
        # real continuation data instead; it belongs to the next normal read.
        if data:self._pending.extend(data)

    def _read_nonempty(self,length):
        if self._pending:
            data=bytes(self._pending[:length]);del self._pending[:length]
            return data
        while True:
            data=self.driver.read(length)
            if data:return data

    def _readAll(self,length):
        chunks=[];done=0
        while done<length:
            data=self._read_nonempty(length-done)
            if len(data)>length-done:
                raise SenserProtocolError('Senser payload exceeds requested length')
            chunks.append(data);done+=len(data)
        return b''.join(chunks)

    def sendSenserPacket(self,pFunc,data,oData=None):
        if self._failed:raise SenserProtocolError('Senser channel is unusable after a failed exchange; no request sent')
        try:return self._exchange(pFunc,data,oData)
        except BaseException:
            self._failed=True
            raise

    def _exchange(self,pFunc,data,oData):
        finish_cp_read=(pFunc==SonySenserCamera.SONY_PFUNC_AdjustControl
                        and data[:4]==struct.pack('<HH',0x603,0x40))
        while data!=b'':
            header=self.SenserPacketHeader.pack(size=len(data),pFunc=pFunc,sequence=self._sequence,
                                                version=0,miconType=0,offsetType=0,response=0)
            self.driver.write(header+data[:self.SenserMaxSize])
            data=data[self.SenserMaxSize:]
        outData=BytesIO() if oData is None else oData
        minSize=0 if self.driver.getId()[1]==0x0336 else self.SenserMinSize
        while True:
            l=max(minSize-self.SenserPacketHeader.size,0)
            d=self._read_nonempty(self.SenserPacketHeader.size+l)
            if len(d)<self.SenserPacketHeader.size:
                raise SenserProtocolError('Short senser header: expected_bytes=%d actual_bytes=%d expected_sequence=%d'%(
                    self.SenserPacketHeader.size,len(d),self._sequence))
            header=self.SenserPacketHeader.unpack(d)
            if header.sequence!=self._sequence or header.pFunc!=pFunc:
                raise SenserProtocolError('Wrong senser sequence or function: expected_sequence=%d actual_sequence=%d '
                    'expected_pfunc=%#x actual_pfunc=%#x declared_bytes=%d'%(
                    self._sequence,header.sequence,pFunc,header.pFunc,header.size))
            outData.write(d[self.SenserPacketHeader.size:])
            done=l
            dataLen=min(header.size,self.SenserMaxSize)
            chunkLen=self.SenserChunkSize-minSize
            while done<dataLen:
                l=min(dataLen-done,chunkLen)
                outData.write(self._readAll(l))
                done+=l
                if finish_cp_read and not (l&(self.SenserMinSize-1)):self._end_packet()
                chunkLen=self.SenserChunkSize
            if header.size<=self.SenserMaxSize:break
        self._sequence+=1
        return header.response,outData.getvalue() if oData is None else None


class Bounded(UsbBackend):
    def __init__(self,device,budget=180):
        super().__init__(device);self.budget=budget;self.reset()
    def reset(self):self.deadline=time.monotonic()+self.budget
    def timeout(self,t=None):
        left=int((self.deadline-time.monotonic())*1000)
        if left<=0:raise TimeoutError('相機操作超出有界等待時間')
        return max(1,min(left,t or self.budget*1000))
    def read(self,ep,length,timeout=None):return super().read(ep,length,self.timeout(timeout))
    def write(self,ep,data):
        self.dev.default_timeout=self.timeout()
        try:written=self.dev.write(ep,data)
        except usb.core.USBError as exc:raise GenericUsbException('USB command write failed') from exc
        if written!=len(data):
            raise GenericUsbException('Short USB command write: expected_bytes=%d actual_bytes=%s'%(len(data),written))

def get_device(pid):
    backend=usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if backend is None:raise RuntimeError('找不到 libusb 程式庫')
    found=list(usb.core.find(find_all=True,idVendor=0x054c,idProduct=pid,backend=backend))
    if len(found)!=1:raise RuntimeError(f'需要且只能連接一台目標相機（USB {pid:04x}）；請確認大量儲存模式及驅動')
    if not list(found[0]):raise RuntimeError('無法讀取 USB 配置')
    return found[0]

# Initial USB startup fix v1: only the pre-authentication information query.
class DiagnosticUsbFailure(RuntimeError): pass
class ReadinessFailure(DiagnosticUsbFailure): pass
class SonyBusyFailure(DiagnosticUsbFailure): pass
# Optional desktop-only driver preparation between the two enumerations.
# CLI sessions leave it unset; it never retries authentication or firmware I/O.
SERVICE_DRIVER_SETUP = None
SERVICE_DRIVER_PRESENT = None
READY_WAIT=30
SONY_BUSY_WAIT=10
POLL_INTERVAL=1

class _InitialProgress:
    def event(self,kind,**values):
        if kind=='readiness' and values['attempt']==1 and values['sense']!=[0,0,0]:
            print('等待相機完成 USB 初始化。',flush=True)
        elif kind=='sony_query_status' and values['attempt']==1 and values['sense']==[9,129,129]:
            print('相機正在準備機身資訊，稍候再讀取。',flush=True)

class _InitialBackend(Bounded):
    def __init__(self,device,report):
        UsbBackend.__init__(self,device)
        self.budget=60
        self.deadline=time.monotonic()+self.budget
    def reset(self):
        return UsbBackend.reset(self)
    def read(self,ep,length,timeout=None):
        try:
            return bytes(self.dev.read(ep,length,timeout=self.timeout(timeout or 5000)))
        except usb.core.USBError as exc:
            if getattr(exc,'backend_error_code',None)==-9:
                raise GenericUsbException('Initial USB endpoint stalled') from exc
            raise
    def write(self,ep,data):
        try:
            written=self.dev.write(ep,data,timeout=self.timeout(5000))
        except usb.core.USBError as exc:
            if getattr(exc,'backend_error_code',None)==-9:
                raise GenericUsbException('Initial USB endpoint stalled') from exc
            raise
        if written!=len(data):
            raise GenericUsbException('Short initial USB command write: expected_bytes=%d actual_bytes=%s'%(len(data),written))

def _query_initial_ready(device):
    report=_InitialProgress()
    backend_type=_InitialBackend
    from pmca.usb import MscDevice
    from pmca.usb.driver.generic import MscBbbDriver
    from pmca.usb.sony import SonyExtCmdCamera, SonyMscExtCmdDevice

    class ReadyDriver(MscBbbDriver):
        def sendCommand(self, command, failOnError=False):
            if command != bytes(6):
                raise DiagnosticUsbFailure('Only TEST UNIT READY is permitted here.')
            deadline = min(self.backend.deadline, time.monotonic() + READY_WAIT)
            attempt = 0
            while True:
                if time.monotonic() >= deadline:
                    raise ReadinessFailure('Camera did not become ready; Sony query was not started.')
                attempt += 1
                sense = super().sendCommand(command, failOnError)
                report.event('readiness', attempt=attempt, sense=list(sense))
                if sense == (0, 0, 0):
                    return sense
                # Retry only explicit becoming-ready and standard attention
                # states. Missing media and unknown responses stop immediately.
                if sense not in {(2, 4, 1), (6, 0x29, 0), (6, 0x28, 0)}:
                    raise ReadinessFailure('Camera is not ready; sense=%02x/%02x/%02x. Stopped.' % sense)
                time.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))

    class BoundedInfoDevice(SonyMscExtCmdDevice):
        def sendSonyExtCommand(self, cmd, data, bufferSize):
            command = bytes([self.MSC_OC_ExtCmd]) + struct.pack('<I', cmd) + bytes(7)

            def exchange(direction):
                deadline = min(self.driver.backend.deadline, time.monotonic() + SONY_BUSY_WAIT)
                attempt = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise SonyBusyFailure('Camera remained busy after readiness passed; query stopped.')
                    attempt += 1
                    if direction == 'out':
                        sense = self.driver.sendWriteCommand(command, data)
                        result = None
                    else:
                        sense, result = self.driver.sendReadCommand(command, bufferSize)
                    report.event('sony_query_status', direction=direction, attempt=attempt, sense=list(sense))
                    if sense != self.MSC_SENSE_DeviceBusy:
                        self._checkResponse(sense)
                        return result
                    # Retry only Sony's explicit busy response. A transfer
                    # timeout or disconnect propagates without another command.
                    time.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))

            exchange('out')
            return exchange('in') if bufferSize else b''

    driver = ReadyDriver(backend_type(device, report))
    report.event('stage', name='scsi_inquiry')
    info = MscDevice(driver).getDeviceInfo()
    report.event('inquiry_ok', manufacturer=info.manufacturer.strip(), product=info.model.strip())
    if info.manufacturer.strip() != 'Sony':
        raise RuntimeError('Unexpected SCSI manufacturer; stopped before Sony extension.')
    report.event('stage', name='sony_get_camera_info')
    info = SonyExtCmdCamera(BoundedInfoDevice(driver)).getCameraInfo()
    # Do not persist info.serial, modelCode, plist, or raw transfer payloads.
    report.event('camera_info_ok', model=info.modelName)
    if info.modelName != 'ILCE-7CM2':
        raise RuntimeError('Unexpected model; this diagnostic is for ILCE-7CM2 only.')
    return info

def identity():
    dev=get_device(0x0e8a)
    try:
        info=_query_initial_ready(dev)
        if info.modelName!=core.MODEL:raise RuntimeError('只支援 '+core.MODEL)
        return {'model':info.modelName,'serial_sha256':core.sha(info.serial.encode())}
    finally:usb.util.dispose_resources(dev)

def service_identity(snapshot,model):
    """Keep the original normal-query binding without that application query."""
    if model!=core.MODEL:raise RuntimeError('只支援 '+core.MODEL)
    serial=core.backup_records(snapshot)[0].get(0x00e70003)
    if serial is None or len(serial.data)!=4:
        raise RuntimeError('服務備份缺少四位元組序列號屬性 00e70003')
    # getCameraInfo hexlifies its four serial bytes before the old tool hashes
    # the text. Hashing the raw bytes would break existing per-body backups.
    return {'model':model,'serial_sha256':core.sha(serial.data.hex().encode('ascii'))}

# Shortly after leaving service mode the camera may answer a new normal-side
# authentication by re-enumerating as 054C:0D68, then 096F, then MSC again,
# never as 0336 (field logs 28 and 30, 12-15 s after the previous exit).
SERVICE_COOLDOWN=30
SERVICE_ATTEMPTS=3
SERVICE_WAIT=120
_service_exit=None  # monotonic time the last service session ended in this process


def _cool_down():
    if _service_exit is None:return
    left=SERVICE_COOLDOWN-(time.monotonic()-_service_exit)
    if left>0:
        print('等待相机从上一次服务模式恢复（%d 秒）。'%round(left),flush=True)
        time.sleep(left)


def _sony_pids():
    backend=usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    return ['%04x'%d.idProduct for d in usb.core.find(find_all=True,idVendor=0x054c,backend=backend)]


def _wait_for(pid,seconds,seen,prepare=None):
    """Enumerate only; record every Sony identity seen while waiting."""
    started=time.monotonic()
    deadline=started+seconds
    prepared=False
    last=None
    while True:
        current=_sony_pids()
        if current!=last:
            print('USB 身份：'+(', '.join('054C:'+p.upper() for p in current) or '未出现')+
                  f'；正在等待 {pid:04X}；阶段经过 {time.monotonic()-started:.1f} 秒',flush=True)
            last=current
        for found in current:
            if found not in seen:seen.append(found)
        if prepare is not None and not prepared:
            present=SERVICE_DRIVER_PRESENT() if SERVICE_DRIVER_PRESENT is not None else False
            if present or (SERVICE_DRIVER_PRESENT is None and '%04x'%pid in current):
                if '%04x'%pid not in seen:seen.append('%04x'%pid)
                prepare();prepared=True
                # Driver installation/UAC must not consume the interface's
                # re-enumeration budget. Re-open the new device, not a stale handle.
                deadline=time.monotonic()+seconds
        try:return get_device(pid)
        except usb.core.USBError as exc:
            if getattr(exc,'backend_error_code',None)!=-4:raise
        except RuntimeError:pass
        if time.monotonic()>=deadline:return None
        time.sleep(.5)


def _rescue_service():
    """Return a body from 0336 after a read-only session lost its channel.

    The broken channel cannot carry auth.stop, so a fresh handle repeats the
    normal start/authenticate/stop exit. Only sessions that sent no write
    command use this; failures leave the camera as it was.
    """
    try:dev=get_device(0x0336)
    except Exception:return False
    try:
        if sys.platform=='darwin':
            from macos_host import claim_camera_interface
            claim_camera_interface(dev)
        auth=SonySenserAuthDevice(GenericUsbDriver(Bounded(dev,20)))
        try:auth.start();auth.authenticate()
        except Exception:pass
        auth.stop()
        print('只读通信出错后，已让相机退出服务模式（未写入相机）。',flush=True)
        return True
    except Exception as exc:
        print('相机未能自动退出服务模式（%s）；请拔 USB、取电池约 1 分钟后重开。'%exc,flush=True)
        return False
    finally:usb.util.dispose_resources(dev)


class Session:
    def __init__(self,expected=None,media_released=False):
        self.expected=expected;self.healthy=True;self.media_released=media_released
        # Any command that can change camera state disables automatic rescue.
        self.mutating=False
    def __enter__(self):
        global _service_exit
        for attempt in range(1,SERVICE_ATTEMPTS+1):
            _cool_down()
            if sys.platform=='darwin' and (attempt>1 or not self.media_released):
                # A bounce back to MSC lets macOS remount the camera storage.
                from macos_host import unmount_camera
                unmount_camera()
            dev=get_device(0x0e8a)
            try:
                if sys.platform=='darwin':
                    # MDHan's order: verify the MSC interface and claim it first.
                    from macos_host import claim_camera_interface
                    claim_camera_interface(dev,interface_class=(8,6,0x50))
                # Standard USB strings remain usable when the storage LUN and
                # DevInfoSender_GetModelInfo are busy. Neither is a service gate.
                model=usb.util.get_string(dev,dev.iProduct) if dev.iProduct else None
                if model!=core.MODEL:raise RuntimeError('只支援 '+core.MODEL+'；USB 型號不符')
                auth=SonySenserAuthDevice(GenericUsbDriver(Bounded(dev,20)))
                auth.start();auth.authenticate()
                # An authentication error is not retried or followed by stop.
            finally:usb.util.dispose_resources(dev)
            seen=[]
            self.dev=_wait_for(0x0336,SERVICE_WAIT,seen,prepare=SERVICE_DRIVER_SETUP)
            if self.dev is not None:break
            if '0336' in seen:
                raise RuntimeError('服务身份 0336 已出现，但接口无法打开；请保留驱动与 USB 日志，不重新认证。')
            # No service identity ever appeared, so no service session exists
            # and nothing was sent to the camera after authentication.
            print('认证后相机未进入服务模式（期间出现的 Sony USB 身份：%s）。'%('、'.join(seen) or '无'),flush=True)
            if attempt==SERVICE_ATTEMPTS:
                raise RuntimeError('服務身份未出現；若是第一次，請依文件安裝0336驅動（已嘗試 %d 次）'%attempt)
            if _wait_for(0x0e8a,60,seen) is None:
                raise RuntimeError('服務身份未出現，相機也未回到普通 USB；請在相機選擇「影像傳輸（MSC）」後重新連接')
            _service_exit=time.monotonic()
            print('相机已回到普通 USB，冷却后自动重试（第 %d/%d 次）。'%(attempt+1,SERVICE_ATTEMPTS),flush=True)
        time.sleep(2)
        if sys.platform=='darwin':
            from macos_host import claim_camera_interface
            claim_camera_interface(self.dev)
        self.backend=Bounded(self.dev)
        self.auth=SonySenserAuthDevice(GenericUsbDriver(self.backend))
        authenticated=False
        try:
            self.auth.start();self.auth.authenticate()
            authenticated=True
            self.channel=SonySenserDevice(self.auth.driver)
            self.camera=SonySenserCamera(self.channel)
            snapshot=self.call(self.camera.getBackupPresetData,True)
            self.identity=service_identity(snapshot,model)
            if self.expected and self.identity!=self.expected:raise RuntimeError('目前機身與備份機身不同')
        except BaseException:
            try:
                if authenticated and self.healthy:self.auth.stop();_service_exit=time.monotonic()
            finally:usb.util.dispose_resources(self.dev)
            raise
        return self
    def __exit__(self,*args):
        global _service_exit
        stopped=False
        try:
            if self.healthy:self.auth.stop();stopped=True
        finally:usb.util.dispose_resources(self.dev)
        if not self.healthy and not self.mutating:
            stopped=_rescue_service()
        if stopped and sys.platform=='darwin':
            from macos_host import wait_normal_return
            # Only enumerate here. Reading configuration opens a new handle
            # before the next session can release remounted camera storage.
            wait_normal_return(lambda:usb.core.find(idVendor=0x054c,idProduct=0x0e8a,
                backend=usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)))
        if stopped:_service_exit=time.monotonic()
    def call(self,method,*args):
        if not self.healthy:raise RuntimeError('會話結果未知，停止後續命令')
        if getattr(method,'__name__','') in ('writeBackup','saveBackup'):self.mutating=True
        self.backend.reset()
        try:return method(*args)
        except BaseException:self.healthy=False;raise
    def jiritsu(self,cmd,data=b'',missing=False):
        if cmd not in [15,16,17,18]:raise ValueError('不允許此 Jiritsu 命令')
        if cmd in (16,18):self.mutating=True
        response,out=self.call(self.channel.sendSenserPacket,0x40,struct.pack('<HH',0x1001,cmd)+data)
        if response or len(out)<4:raise RuntimeError('Jiritsu 回應格式錯誤')
        status=struct.unpack_from('<I',out)[0]
        if missing and status==0x10000006:return None
        if status:raise RuntimeError(f'Jiritsu 狀態 {status:#x}')
        return out[4:]
    def select(self,path):
        if not path.startswith('/tmp/jiritsu/') or '\0' in path or len(path)>510:raise ValueError('路徑不符')
        self.jiritsu(15,b'\0'+path.encode('ascii')+b'\0')
    def read(self,path,missing=False):self.select(path);return self.jiritsu(17,b'\0\xff\0',missing)
    def temp(self,name,data=None,remove=False):
        if name not in core.NATIVE_PATHS:raise ValueError('不是指定臨時檔')
        path='/tmp/jiritsu/'+name;self.select(path)
        if remove:self.jiritsu(18,b'\0\xff')
        elif data:
            if len(data)>65536:raise ValueError('臨時檔過大')
            self.jiritsu(16,b'\0\xff\0'+data)
        else:raise ValueError('不允許空檔寫入')
    def cp_read(self,key):
        if key not in core.CP_KEYS:raise ValueError('不允許此 CP 單元')
        return self.call(self.camera._sendAdjustControlPacket,0x603,0x40,struct.pack('<II',key,1))
    def cp_write(self,key,data):
        if key not in core.CP_KEYS or len(data)!={core.CP_KEYS[0]:8192,core.CP_KEYS[1]:28672}[key]:raise ValueError('CP 寫入目標或長度不符')
        self.mutating=True
        return self.call(self.camera._sendAdjustControlPacket,0x603,0x41,struct.pack('<II',key,1)+data)
    def ap_write(self,key,data):
        if key not in core.AP_KEYS or len(data)!=1:raise ValueError('AP 綁定目標或長度不符')
        self.mutating=True
        return self.call(self.camera.writeBackup,key,data)


class RecoverySession(Session):
    """Reattach an authenticated service endpoint for a recorded body.

    Acquisition sends no authentication/start/stop. The caller accounts for
    the previous native result and proves the live model before new writes.
    """
    def __enter__(self):
        # Reattaching to an unknown earlier outcome never sends a stop itself.
        self.mutating = True
        if not self.expected or self.expected.get('model') != core.MODEL or not self.expected.get('serial_sha256'):
            raise ValueError('Existing service recovery requires a recorded A7C II body identity')
        self.dev = get_device(0x0336)
        if sys.platform=='darwin':
            from macos_host import claim_camera_interface
            claim_camera_interface(self.dev)
        self.backend = Bounded(self.dev, 30)
        self.auth = SonySenserAuthDevice(GenericUsbDriver(self.backend))
        self.channel = SonySenserDevice(self.auth.driver)
        self.camera = SonySenserCamera(self.channel)
        try:
            snapshot = self.call(self.camera.getBackupPresetData, True)
            self.identity = service_identity(snapshot, core.MODEL)
            if self.identity != {k: self.expected[k] for k in ('model', 'serial_sha256')}:
                raise ValueError('Service endpoint belongs to a different body; no authentication or write attempted')
            self.backend.budget = 180
        except BaseException:
            self.healthy = False
            usb.util.dispose_resources(self.dev)
            raise
        return self
