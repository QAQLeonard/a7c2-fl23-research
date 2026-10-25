# Development guide

[Home](../../README.md) · [简体中文](../zh-CN/development.md)

One overview for maintainers and AI agents. Read [AGENTS.md](../../AGENTS.md) first: it holds the rules that must not be broken. This page explains how the code fits together; for details, read the code it points to.

## Scope

- Camera: Sony ILCE-7CM2, firmware 2.01 only.
- Product: the 3.0 desktop app (`desktop.py`), on Windows 10/11 x64 and macOS 14+ Apple Silicon. Windows and macOS share the GUI, planners, camera writes and recovery. Only USB drivers, privilege elevation and media handling differ per host.
- Legacy command-line tools (`FL23.cmd`, `lut.py`, `recovery.py`, `shutter.py`, `vertical.py`, `a7look_*.py`, `raw_*.py`) remain for advanced use. Their backup-based workflows are separate from the desktop's backup-free direct operations.

## External A7CR port: research boundary

The downstream [agent-neutral A7CR workflow](https://github.com/littleben/a7cr-creative-look-tools)
extends the previously listed injectiver research source. It does not change
this app's ILCE-7CM2-only contract or provide permission to substitute an A7CR PID.
The A7CR adapter uses separate exact-source guards and model-specific offsets:

| A7CR 2.01 location | File offset / role |
| --- | --- |
| AP converter and bounded title helper | `0x3528cd8..0x3528d5c` |
| AP title-getter entry | `0x1b5ce5c` |
| AP native look map | `0x4c7d4cc` |
| CP native controller entry | `0x1354d8`; native continuations differ from the A7C II reference |

These are file offsets, not live process addresses. The downstream code audits
ownership, incoming branches, loaded extents, data/BSS and the loader/bootstrap
before building a candidate. It separately saves and synchronizes native ST,
using the A7CR menu call chain and re-probing all 18 bases after each slot. It
binds loaded/native reports by PID, base and kernel boot ID. Its increment keeps
slot 1 CC while adding slots 2/3, with an exact inverse to the preceding CC state.

Reported physical coverage is one A7CR 2.01 on Apple Silicon macOS: full program
and 68-resource readback, new-boot AP-span checks, saved/native bases, and new
JPEGs with custom markers 249/250/251 plus an ST control. New portrait-look
samples were still life; skin-tone fidelity and complete physical restoration
remain unverified. A completed-write/ordinary-USB-exit timeout was resolved by
preserved binary evidence and a later cold-start read-only verification, without
replaying installation. No firmware, body backup, calibration, DCP or photo is
included in this documentation contribution.

## Repository map

| Path | Responsibility |
| --- | --- |
| `desktop.py` | Entry point: GUI, `--worker`, `--privileged-worker` (macOS), `--raw-profile-worker` (Lightroom), `--offline-self-test` |
| `src/desktopapp/` | GUI (`window.py`, `lookeditor.py`; colors and states in `theme.py`), jobs (`jobs.py`), worker dispatch (`worker.py`), one-click coordinator (`allinone.py`), dialog texts (`reloadguide.py`, `connectionguide.py`, `lookguide.py`, `completion.py`) |
| `src/desktopapp/actions/` | `catalog.py`: which actions touch the camera or need power confirmation. `look_compiler.py` and `sound.py`: adapters for offline conversion and the sound runtime |
| `src/desktopapp/platforms/` | Host-specific code: `usb_drivers.py` (Windows WinUSB via libwdi, UAC, uninstall), `windows_pnp.py`, `macos_authorization.py` (Terminal + sudo), `macos_media.py`. `drivers.py`/`macadmin.py` are compatibility aliases |
| `src/looks/looktool/` | Core engines: `direct.py` (backup-free transactions), `bundle.py` (combined plan), `factoryrecover.py`, `compilelook.py` (DCP/CUBE → `.a7look`), `rawauto.py`/`rawidentity.py` (Lightroom), plus legacy checkpoint/job modules |
| `src/camera_runtime/` | USB service session (`transport.py`), FL23 planner/assets, macOS host helpers (`macos_host.py`), vendored Sony-PMCA-RE |
| `src/shutter_sound/` | Sound conversion/volume, audition, persistent install; `native/` holds the AArch64 camera workers |
| `src/vertical/` | Vertical Display workers and portrait resources (**being rewritten**) |
| `src/fl23/` | Standalone legacy FL23 installer; its `native/` workers are reused by the engines |
| `plugins/A7LookAuto.lrplugin/` | Lightroom Classic auto-profile plugin |
| `calibration/` | Virtual 2.01 response model used by the compiler |
| `dev/desktop/` | Packaging (`build.py`, `desktop.spec`, `prepare_assets.py`, `prepare_presets.py`, `profilepack.py`) and the desktop test suite |
| `dev/shutter_sound/`, `dev/vertical/`, `dev/usb/` | Tests, emulators and research tools |
| `dev/release/` | Historical v2.x CLI release scripts and `check_publication.py` |
| `desktop-assets/` (ignored) | Distribution-only inputs: six default looks, paired profile library, Windows/macOS helpers |
| `build/`, `dist/` (ignored) | Caches, private evidence and build outputs |

## How a button becomes a camera write

1. **GUI** (`window.launch`). Write actions show a power/model confirmation; the request then carries `power_confirmed=True`. The UI thread never calls camera, driver or native-worker code.
2. **Job** (`jobs.new_job`). Creates `<data root>/runs/<UTC time>-<action>-<id>/` with `request.private.json` (schema `a7c2-desktop-job/1`) and `status.private.json`.
3. **Worker** (`desktop.py --worker`). A fresh child process for every job. On macOS, camera actions first re-run the same worker as root through a per-job Terminal sudo script. The worker writes `worker.log` and sets the status to `RUNNING`, then `SUCCEEDED` with `result`, or `FAILED` with `error`, `error_type` and the full traceback.
4. **Dispatch** (`worker.run`). Routes the action to an engine (see the table below).
5. **GUI completion** (`window.finished`). Reads the status and `result.phase`, then shows the matching dialog: cold reload, resource reload, sound notice or completion.

`SUCCEEDED` only means the worker returned. The phase says what happens next:

| Phase | Meaning |
| --- | --- |
| `AWAITING_RELOAD` / one-click `WAIT_RELOAD` | Written and fully read back; the user must cold-reload |
| `AWAITING_RESOURCE_RELOAD` / `WAIT_RESOURCE_RELOAD` | Names written, programs not yet; cold-reload, then continue |
| `LOADED` / `COMPLETE` | Verified after a new boot (`COMPLETE` also records the owner's physical check) |
| `NEEDS_REVIEW` | Stopped. Keep the evidence; never replay an unknown write |

Data root: `%LOCALAPPDATA%\A7C2Tools` on Windows, `~/Library/Application Support/A7C2Tools` on macOS. Override it with `A7C2_DESKTOP_DATA`. GUI settings are stored in `desktop.json`.

## Action catalog

| Action | Engine | Notes |
| --- | --- | --- |
| `setup_all` | `allinone.run` | One-click install/continue; calls the other actions in-process |
| `driver_scan`, `usb_prepare`, `driver_install`, `driver_uninstall`, `mac_unmount` | `platforms.usb_drivers` | Only `054C:0E8A` and `054C:0336`; existing WinUSB/libusbK/libusb0 bindings are kept |
| `connect`, `usb_stability` | `devicesession.Camera`, `usbcheck` | Read-only |
| `direct_factory_reset` (→ `direct_resume_factory` / `direct_verify`) | `looktool.direct` | Built-in factory reference; the GUI resolves pending transactions first |
| `direct_fl23_enable`, `direct_fl23_disable` | `looktool.direct` | |
| `direct_looks_import` (→ `direct_resume_looks`) | `lookbatch` + `looktool.direct` (`install_all`) | `operations`: `slot`, `action=write/restore`, `path`, optional `name` |
| `vertical_enable`, `vertical_disable` | `looktool.direct` (persistent) | Being rewritten |
| `sound_on`, `sound_off` | `looktool.direct` (`sound_enable/disable`) | |
| `sound_import`, `sound_volume` | `actions.sound` → `shutter_sound.sound_cli` | Computer only, no camera access |
| `sound_audition`, `sound_install`, `sound_verify`, `sound_restore_sound` | `actions.sound` | Camera actions |
| `compile_look` | `actions.look_compiler` → `looktool.compilelook` | Offline |
| `plugin_install` | `desktopapp.plugins` | Optional Lightroom plugin; bundles ExifTool |
| `fl23_*`, `look_*`, `restore*` | Legacy engines | Older backup-based flows, kept for history and CLI parity |

A replacement frontend only needs `jobs.new_job(action, arguments)` plus `jobs.worker_command(...)`, and must interpret phases as above. Keep the argument names used by `Window.common()` and the catalog.

## Core flows

**Direct transaction** (`looktool/direct.py`, `DirectJob`):
1. `plan()` is pure. It turns the camera's current bytes into target bytes and wanted settings, and changes only the regions each mode declares. `bundle.plan()` stacks several modes (FL23, looks, ST resets, sound, vertical) into one plan.
2. `run_direct()` order: capture current state → plan → save `PLANNED` → native preflight → names first, then program windows → full program readback → name resources → settings → WBI → `AWAITING_RELOAD`. Every step is journaled in `direct.private.json`.
3. If the read-only remount returns EBUSY after names are written, the job stops at `AWAITING_RESOURCE_RELOAD`. Programs are written in a fresh transaction after a verified new boot.
4. `verify_direct()` re-plans from current bytes and must find nothing left to change. It then checks RAM and saved settings, requires a changed `boot_id` (proof of a cold reload), and checks that loaded program spans match the disk. Factory reset also requires `/usr` to be mounted read-only.

**One-click install** (`allinone.py`, state in `setup.private.json`):
`READY → DRIVERS → PREPARED → INSTALLING → WAIT_RELOAD → (verify) → FINALIZING → COMPLETE`, with a `WAIT_RESOURCE_RELOAD` branch.
- `FINALIZING` adopts sound, installs the plugin and RAW mapping, and checks the persisted Vertical Display.
- After a failure, a child that failed before any write gets a fresh `install-retry-*` plan. Unknown results stop with their evidence intact.

**Factory restore:** the built-in reference `src/looks/assets/factory-regions-2.01.json` holds generic stock bytes only for the regions this project changes. It contains no full firmware and no body data. Bytes outside those regions, and body calibration, are preserved. Interrupted restores continue from current bytes (`factoryrecover.pending`).

**USB service entry** (`camera_runtime/transport.Session`):
1. Check the normal USB product string.
2. Authenticate.
3. Wait for `0336`.
4. Authenticate again.
5. Bind the body by property `00e70003` (hex-text serial digest).

If `0336` never appears and the camera returns to `0E8A`, the session cools down for 30 s and retries, up to 3 attempts. Nothing is sent to the camera after an authentication that never reached `0336`.

**Sound** (`src/shutter_sound/`): `media.py`/`native_codec.py` convert audio on the computer. `sound_cli.py` drives the workflow for both the desktop and `shutter.py`. `candidate.py`/`boot_sound.py`/`files_worker.py` build the fixed native changes. Audition and confirmation records are optional and never gate saving.

**Look conversion:** `compilelook.py` parses DCP LookTable/tone curves, or ST/sRGB CUBEs, and fits them to the native table with `calibration/a7c2-2.01.virtual.npz`. No Lightroom is needed. See [LUT formats](lut-formats.md) for supported inputs.

## Build and test

Use native 64-bit Python 3.11.

```text
python -m pip install --no-build-isolation -r desktop-requirements.txt pyinstaller==6.16.0 pytest==8.3.5
python -m pytest dev/desktop dev/shutter_sound/tests dev/vertical -q
python desktop.py
```

The root `conftest.py` blocks physical USB enumeration in every test. Other suites: `python -m unittest discover -s src/looks/tests`, `src/fl23/tests`, `src/camera_runtime/tests`, `dev/usb/tests`. Private fixtures (`A7C2_RESEARCH_FIXTURES`) are optional; without them those tests skip.

**Packaging:**
1. Prepare the ignored distribution assets: `python dev/desktop/prepare_assets.py`. Use `--preset-archive <zip>` to import the six defaults and the paired library from an exported pack or a Windows build; use `--export-presets <zip>` to create such a pack.
2. Build: `python dev/desktop/build.py`.

Outputs:
- **Windows:** `dist/A7C2Tools-Windows-x64.zip`. It contains `A7C2Tools.exe`, `_internal/`, `Profiles/` (paired library), both READMEs and `LICENSE`.
- **macOS (Apple Silicon only):** `dist/A7C2Tools-macOS-arm64.dmg`. The paired library lives inside the app (`desktop-assets/profile-library-v1`).
- `profilepack.py` refuses to package unless all 11 Fujifilm and 4 Ricoh color pairs are present. Monochrome pairs are allowed only if they meet the independent error limits (MAE ≤3/255, P95 ≤12/255).

CI: `.github/workflows/desktop-preview.yml` builds on native Windows and `macos-15` runners and uploads artifacts without publishing a Release. Updating `dev/desktop/native-build-request.json` triggers an Apple Silicon build. Keystone/Unicorn build from source on ARM64 (Xcode CLT, CMake 3.31.6); Zig is 0.13.0.

Packages have no Developer ID signature. Offline tests, packaged self-tests and byte readback do not prove camera boot safety, colors or sound. Physical acceptance is recorded separately in the [changelog](changelog.md).

## Documentation policy

Keep the documentation small:

| File | Audience |
| --- | --- |
| `README.md` / `README.zh-CN.md` | Users: download, step-by-step guide, troubleshooting |
| `docs/*/lut-formats.md` | Users: supported LUT/DCP inputs |
| `docs/*/changelog.md` | Everyone: version history and test records |
| `docs/*/notices.md` | Everyone: sources and licenses |
| `docs/*/development.md` | Maintainers and AI: this page |
| `AGENTS.md` | AI: rules that must not be broken |

Every English page has a Simplified Chinese counterpart at the same path; keep them in sync. Don't add per-feature guides or research notes. Read the code, and record decisions in the changelog or commit messages instead. Historical documents remain in git history.
