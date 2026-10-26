"""First-pair development trial. Only --run opens the explicit camera session."""
import argparse
import json
from pathlib import Path
import sys
import time
from device_driver import DeviceDriver
from staging_model import ReviewRequired


def poll(driver, predicate, limit, pause):
    for _ in range(limit):
        report = driver.query()
        if predicate(report): return report
        pause(0.2)
    raise ReviewRequired('Timed out awaiting a native state; preserve this trial, do not repeat')


def run_trial(helper, core, directory, session_factory, *, prompt=input, emit=print,
              pause=time.sleep, poll_limit=600):
    driver = None
    try:
        with session_factory(expected=None) as session:
            try:
                identity = session.identity
                driver = DeviceDriver(session, directory, helper, core)
                driver.state['body_identity'] = identity
                driver._save()  # retain the same-body binding before the first upload
                driver.stage()
                driver.arm(epoch=1, generation=1)
                poll(driver, lambda r: r['arm_accepted'], poll_limit, pause)
            except BaseException:
                if driver: driver._fail()
                raise
        # Service exit precedes the prompt. Never trigger capture via USB.
        emit('准备完成。保持相机开机，不换卡、不重启；拔下 USB，手动连续拍两张 JPEG。')
        prompt('拍完后重新连接 USB，再按回车继续核对：')
        with session_factory(expected=identity) as session:
            try:
                if session.identity != identity:
                    raise ReviewRequired('Reconnected body differs from the armed body')
                driver.session = session
                report = poll(driver, lambda r: r['photo_complete'], poll_limit, pause)
                arm = driver.state['arms'][-1]
                if report['epoch'] != arm['epoch'] or report['generation'] != arm['generation']:
                    raise ReviewRequired('Completed pair differs from the armed capture identity')
                driver.disable()
                poll(driver, lambda r: driver.state['phase'] == 'DISABLED', poll_limit, pause)
            except BaseException:
                # Mark before Session.__exit__, so it cannot perform automatic rescue.
                driver._fail(); session.healthy = False; session.mutating = True
                raise
        emit('合成与媒体库核对完成：' + report['result_path'])
        emit('拔下 USB，在相机回放中检查合成图及两张原图。核心保留至 AP 进程退出。')
        return report
    except BaseException:
        if driver: driver._fail()
        raise


def camera_session(*, expected):
    # Import only after an explicit --run. Import/help/offline preparation do no USB I/O.
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root/'src/camera_runtime'))
    from transport import Session
    return Session(expected=expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', required=True, type=Path)
    parser.add_argument('--core', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run', action='store_true', help='Open service sessions and arm one experimental pair')
    args = parser.parse_args()
    if not args.run: parser.error('Use --run to explicitly start a physical trial')
    try:
        run_trial(args.helper.read_bytes(), args.core.read_bytes(), args.output, camera_session)
    except (Exception, KeyboardInterrupt) as error:
        print('实验停止；保留当前目录，不重新运行同一任务：' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
