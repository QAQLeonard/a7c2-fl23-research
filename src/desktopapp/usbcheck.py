"""Read-only USB soak test over the camera's program files; never stages native workers.

The two program files are the same large reads a real write performs during its
full readback. Every round re-reads both and must match the first round byte for
byte. The clock starts once the service connection is ready, so connection and
authentication time never counts towards the minimum duration. A completed read
slower than MIN_MB_PER_SECOND indicates a degraded link (USB 1.1, hub or poor
cable); a read that hangs is stopped by the transport's own timeout and fails.
"""
import time
from pathlib import Path
from .paths import write_json

PATHS=('/usr/lib/appFw.so','/cp/cpapp-b.bin')
MIN_SECONDS=120
MIN_ROUNDS=5
MAX_ROUNDS=60
MIN_MB_PER_SECOND=2.0
MIN_BYTES,MAX_BYTES=1024*1024,256*1024*1024
NOTE='通过只说明这段时间内连续只读传输稳定；不保证刷写期间一定不掉线，也不代表线材认证。'


class Incomplete(RuntimeError):
    """The round cap was reached before the minimum duration; not a pass."""


def run(job,*,factory=None,clock=time.monotonic,min_seconds=MIN_SECONDS,min_rounds=MIN_ROUNDS,
        max_rounds=MAX_ROUNDS,min_rate=MIN_MB_PER_SECOND):
    if factory is None:
        from looktool.devicesession import Camera
        factory=Camera
    job=Path(job);job.mkdir(parents=True,exist_ok=True)
    report=dict(schema='a7c2-usb-stability/3',phase='CONNECTING',paths=list(PATHS),rounds=[],
                minimum_seconds=min_seconds,minimum_rounds=min_rounds,maximum_rounds=max_rounds,
                minimum_mb_per_second=min_rate,camera_firmware_written=False,camera_settings_written=False,
                native_worker_executed=False,note=NOTE)
    def save():write_json(job/'usb-stability.private.json',report)
    save();connect_begin=clock();start=None;number=0;reading_path=None
    def elapsed():return 0.0 if start is None else clock()-start
    try:
        with factory() as camera:
            start=clock();report.update(phase='READING',connect_seconds=round(start-connect_begin,3));save()
            baseline={}
            while number<min_rounds or elapsed()<min_seconds:
                if number>=max_rounds:
                    raise Incomplete('已读 %d 轮，达到轮数上限，但连续读取只持续 %.0f 秒，未满 %d 秒；本次不算通过'%
                                     (number,elapsed(),min_seconds))
                number+=1
                print('USB 稳定性检测：第 %d 轮只读读取程序文件（至少 %d 轮、连续 %d 秒），不写固件或设置。'%
                      (number,min_rounds,min_seconds),flush=True)
                reads=[]
                for path in PATHS:
                    reading_path=path
                    begin=clock()
                    try:
                        raw=camera.read(path)
                        seconds=clock()-begin
                        if raw is None or not MIN_BYTES<=len(raw)<=MAX_BYTES:
                            raise ValueError('程序文件未完整读回：'+path)
                        if path in baseline and raw!=baseline[path]:
                            raise ValueError('重复读回的字节不一致：'+path)
                        rate=len(raw)/1048576/seconds if seconds>0 else None
                        if rate is not None and rate<min_rate:
                            raise ValueError('读取 %s 只有 %.2f MB/s，低于 %.1f MB/s；连接可能经过 USB 1.1、扩展坞或线材质量较差'%
                                             (path,rate,min_rate))
                    except BaseException as exc:
                        # A decoded negative reply accounts for this read;
                        # transport timeouts/disconnects still have unknown outcomes.
                        if getattr(exc,'jiritsu_status',None) is None:
                            mark=getattr(camera,'mark_unknown',None)
                            if mark:mark()
                        raise
                    baseline.setdefault(path,raw)
                    reads.append(dict(path=path,bytes=len(raw),seconds=round(seconds,3),
                                      mb_per_second=round(rate,2) if rate is not None else None))
                report['rounds'].append(dict(round=number,bytes=sum(r['bytes'] for r in reads),reads=reads,passed=True))
                save()
            seconds=elapsed()
        speeds=[r['mb_per_second'] for row in report['rounds'] for r in row['reads'] if r['mb_per_second']]
        report.update(phase='PASSED',total_bytes=sum(r['bytes'] for r in report['rounds']),
                      seconds=round(seconds,3),camera_io_ended=True,
                      slowest_mb_per_second=min(speeds) if speeds else None,
                      fastest_mb_per_second=max(speeds) if speeds else None)
        save()
        print('%d 轮只读传输均完成，共 %.1f MB，连续读取 %.0f 秒，逐轮字节一致。%s'%
              (len(report['rounds']),report['total_bytes']/1048576,report['seconds'],NOTE),flush=True)
        return report
    except BaseException as exc:
        incomplete=isinstance(exc,Incomplete)
        connected=start is not None
        report.update(phase='INCOMPLETE' if incomplete else 'FAILED',
                      failed_stage='reading' if connected else 'connecting',
                      failed_round=number if connected and not incomplete else None,
                      failed_path=reading_path,
                      error_type=type(exc).__name__,error=str(exc),camera_io_ended=True,seconds=round(elapsed(),3))
        status=getattr(exc,'jiritsu_status',None)
        if status is not None:
            command=exc.command
            mode=exc.request_mode
            report.update(failure_kind='camera-file-command',jiritsu_status=hex(status),
                          jiritsu_command=command,jiritsu_mode=mode)
            if command==17 and mode==0 and status==0x10000004:
                report['failure_kind']='camera-staging-mount'
                advice='相机端 /tmp/jiritsu 暂存目录挂载准备失败，尚未读取目标文件；需要核查机身端挂载环境，不能据此判定线材故障。'
            else:
                advice='相机端文件命令已返回失败；请保留诊断记录，按状态码检查文件访问，不能据此判定线材故障。'
        else:
            advice='请换线或直连电脑 USB 接口后重测；'
        save()
        if incomplete:
            raise RuntimeError('USB 稳定性检测未完成：%s。本次没有固件或设置写入。'%str(exc)) from exc
        raise RuntimeError('USB 稳定性检测未通过（%s）：%s。%s本次没有固件或设置写入。'%
                           ('第 %d 轮'%number if connected else '连接阶段',str(exc),advice)) from exc
