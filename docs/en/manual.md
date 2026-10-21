# Windows / macOS setup

[Home](../../README.md) · [简体中文](../zh-CN/manual.md)

FL23 keeps its existing Windows CLI and desktop entry: [FL23 instructions](fl23.md). The commands below are for the independent LUT importer.

## Python and dependencies

Install architecture-matching 64-bit Python 3.10+. The packaged Zig dependency requires macOS 12+ (Intel or Apple Silicon). For a source checkout:

| Windows terminal | macOS terminal |
|---|---|
| `python -m venv .venv-lut` | `python3 -m venv .venv-lut` |
| `.venv-lut\Scripts\python.exe -m pip install -r src/looks/requirements-device.txt` | `.venv-lut/bin/python -m pip install -r src/looks/requirements-device.txt` |
| `.venv-lut\Scripts\python.exe lut.py doctor --device` | `.venv-lut/bin/python lut.py doctor --device` |

Use that interpreter instead of `python` in the [eight-step guide](custom-lut.md). No environment activation, PowerShell script, policy change or AI service is needed. Use native arm64/universal2 Python on Apple Silicon; do not copy a Windows environment.

With the standalone `lut.py` download, install dependencies using the same interpreter:

```text
python -m pip install "numpy>=1.24,<3" "scipy>=1.10,<2" pyusb==1.3.1 libusb-package==1.0.30.0 pycryptodomex==3.24.1 PyYAML==6.0.3 "pyelftools>=0.31,<1" ziglang==0.13.0
python lut.py doctor --device
```

On Mac replace `python` with `python3`. The standalone file extracts its bundled source/native assets under `~/.a7c2-tools/runtime`; jobs/backups are separate and survive tool updates. Pip dependencies are not bundled or automatically installed. `doctor` never opens the camera.

## Camera connection

Connect one supported A7C II by a data-capable USB cable, choose Mass Storage, use a charged battery and close other camera tools. On Windows prepare the normal/service USB drivers using [the existing USB instructions](fl23.md#3-connect-the-camera-and-prepare-usb-drivers). LUT reuses this transport without running the FL23 installer.

If the first libusbK replacement leads to a connection countdown/disconnect or “Check the connected device,” see [two-stage driver troubleshooting](fl23.md#first-driver-replacement-disconnects--check-the-connected-device). LUT users should run `import` without `--write` after preparing both drivers. Do not install FL23 just to prepare drivers or repeat an import after an unknown write outcome.

Mac uses libusb rather than Zadig. If the camera is busy, close Photos/Image Capture and eject mounted camera volumes before device access. If macOS refuses interface access, stop at preparation and retain the error; do not retry a write or change system security settings. **Mac hardware/USB installation has not been tested.**

Names/paths with spaces need quotes. Unsupported firmware, missing dependencies, a changed backup or an unknown transaction stops the command. Errors are not instructions to reinstall drivers.

## Main commands

| Command | Action |
|---|---|
| `import FILE --name NAME --slot N` | Capture backups, convert, compile and preflight |
| Same command plus `--write --battery-percent N` | Also install and fully read back |
| `install JOB --battery-percent N` | Install a prepared job |
| `verify JOB --accept-photos` | Check reload and record completed physical acceptance |
| `diagnose-job JOB` | Explain recorded failures/name reports offline, with no camera access |
| `restore-slot JOB --battery-percent N` | Restore one slot, including first activation; preserve other slots and FL23 |
| `recover JOB` | Recover existing evidence without loader execution |
| `resume JOB --battery-percent N` | Continue a proven interrupted phase |
| `configure --calibration MODEL --backup-root DIR` | Optional persistent color-model/backup preferences |

All examples have the prefix `python lut.py`. Offline research commands remain available in `--help`; ordinary users do not need them.

## Independent Recovery

Complete rollback uses `python recovery.py restore BACKUP --firmware-version 2.01 --battery-percent N`. Its own [guide](recovery.md) covers original backup2 folders and new archives, reload and verification. Recovery uses the same Python/device dependencies and works without LUT jobs. On Mac use `python3`. For mixed-feature work, use the explicit FL23 prepare/install/verify route; its retained legacy stock restore helper is not a substitute for Recovery.
