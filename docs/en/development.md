# Development and verification

[Home](../../README.md) · [简体中文](../zh-CN/development.md) · [Change record](changelog.md)

This guide describes the repair branch based on upstream `0bf1dbb` for Sony ILCE-7CM2 firmware 2.01. It covers host workflow repairs and the current FL23/LUT compatibility adapter. It is a development build, not a Sony update or a physically validated release. Download links in the homepages still refer to upstream releases; they do not acquire unmerged changes from this branch.

## 1. Entry points and responsibilities

| Entry | Responsibility | Device access |
|---|---|---|
| `FL23.cmd --help`, `--check`, `check-package` | Help, host environment or packaged-asset checks | None |
| `FL23.cmd prepare ...` | Version confirmation, body-bound duplicate backups, checkpoint, candidate and native preflight | USB/service access; temporary diagnostics execute |
| `FL23.cmd install ...` / `verify ...` | Install a prepared transition / verify files, settings and loaded AP spans | USB; installation writes persistently |
| `python lut.py` | Convert/import one custom look, verify reload, restore one slot | `doctor` and offline research commands do not connect; device jobs do |
| `python recovery.py` | Independent complete rollback from a checkpoint or supported legacy backup | `inspect` is offline; restore/verify connect |

The current GUI and CLI also retain the earlier `check`, `backup` and `restore` routes. The simple backup/automatic-install route is stock-only and uses the factory backup store. The legacy FL23 restore helper is not the mixed FL23/LUT rollback workflow. Use explicit `prepare` for compatibility work and independent Recovery for complete rollback. `check` authenticates to USB service mode; it is not an offline check. LUT `import` without `--write` also connects and runs preparation, although it does not install the candidate.

## 2. Source map

| Source | Role and boundary |
|---|---|
| `dev/windows/bootstrap.cmd`, `src/launcher.py` | Interpreter selection, dependency setup, argument/exit-code forwarding |
| `src/fl23/app.py`, `workflow.py` | CLI parsing and durable preparation/install/verification stages |
| `src/fl23/usbdev.py`, `transport.py` | One-device discovery, bounded service sessions, USB model/AP-serial binding |
| `src/fl23/core.py`, `backup.py`, `layout.py` | Fixed stock assets, per-body color merging, legacy backup layout and validation |
| `src/fl23/compat.py` | Plan FL23 over current bytes, preserve LUT dispatch, build per-job workers and validate candidates |
| `src/looks/looktool/device_layout.py`, `fl23compat.py` | Exact import identities, slot bitmap/table transforms and current gamma merge |
| `src/looks/looktool/devicejob.py`, `devicesettings.py` | LUT transaction, fresh settings preservation, readback and reload evidence |
| `src/looks/looktool/checkpoint*.py` | Independent archive, reverse plan, native workers and full rollback |
| `src/fl23/native/installer.c`, `src/looks/native/names.c` | Program-window and name-resource transactions; no general camera shell |
| `dev/build_lut_compat.py` | Offline reproduction of `src/looks/assets/runtime-fl23-current.json` |
| `dev/release/` | Source/standalone packaging, documentation and publication checks |

`docs/en/` and `docs/zh-CN/` are the current paired guides. Component notes under `src/fl23/docs/`, component READMEs and `docs/wb_docs/` preserve research history; their historical paths, commands and observations do not override this guide or the current code. Original attribution and licensing remain in [notices](notices.md).

## 3. Why the compatibility adapter is needed

The old LUT importer recognized FL23 CP `60a9de1a…`; current FL23 produces `442c9261…`. Admitting the latter hash alone is insufficient: the LUT bootstrap and FL23 both modify gamma routing and loaded-code metadata.

The adapter is reproduced from exact official 2.01 components. It merges eight reviewed windows, totaling 982 bytes, while retaining the LUT dispatcher and the larger loaded text extent. FL2/FL3 keep separate photo/movie rows: `(48,46)` and `(49,47)`. Custom markers 249–254 retain their ST-based routing. The immutable legacy `runtime-v1.json` remains available; the current adapter is separate.

| Starting programs | Planned behavior |
|---|---|
| Exact stock AP/CP | LUT import builds the current merged runtime without enabling FL23 menu flags |
| Exact current FL23 AP/CP | LUT import preserves current FL23 gamma and adds selected-slot behavior |
| Recognized standalone LUT | Explicit FL23 preparation retains slots and produces the same result as FL23 followed by LUT |
| Existing legacy pinned source | Existing import/update recognition remains; historical owner fixtures are still needed for the complete legacy test matrix |
| Unknown/conflicting source | Stop at the relevant identity/window guard; do not replace the expected hash to force admission |

Full-file import identities, storage integrity, body identity and edited-byte guards serve different purposes. The explicit FL23 planner uses user-confirmed version plus actual patch positions, not a whole-file provenance whitelist. LUT imports retain exact source/code identities. Slot/full recovery compare owned changes and complete bytes. None of these checks establishes boot safety.

## 4. Development environment

Use 64-bit Python 3.10+. The recorded Windows run used Python 3.14.7. Zig 0.13.0 is pinned in the device requirements; research requirements add Capstone, Keystone and Unicorn. GUI use also needs Tkinter. Dependency installation does not connect to a camera.

From the checkout root in PowerShell, create a new environment if one does not already exist:

```powershell
python -m venv .venv
$devPython = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $devPython -m pip install -r src/looks/requirements-device.txt
& $devPython -m pip install -r src/looks/requirements-research.txt
& $devPython src/fl23/app.py --help
& $devPython src/fl23/app.py check-package
& $devPython lut.py doctor --device
```

Reuse a valid existing environment; do not overwrite an incomplete one merely to retry. On macOS use a native Python environment and its interpreter path. Offline portability does not establish macOS USB support.

## 5. Official program fixtures and adapter reproduction

The [official Sony 2.01 update](https://support.d-imaging.sony.co.jp/www/cscs/firm/?area=jp&lang=jp&mdl=ILCE-7CM2) was unpacked offline using [fwtool PR #52](https://github.com/ma1co/fwtool.py/pull/52), commit `3955d7890fc38daf942bb52827599bfe35de4a14`. The downloaded container is 1,139,929,560 bytes, SHA-256 `eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`. Keep it and extracted/generated complete programs outside the Git checkout. Unpacking the file does not update the camera.

The fixture directory needs these two files:

| File | Bytes | Required original SHA-256 |
|---|---:|---|
| `appFw.so` | 99,960,744 | `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b` |
| `cpapp-b.bin` | 18,090,880 | `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428` |

Reproduce into an ignored directory first:

```powershell
$env:A7C2_STOCK_COMPONENTS = 'D:\Private\A7C2-2.01\components'
& $devPython dev/build_lut_compat.py --components $env:A7C2_STOCK_COMPONENTS --output private/generated/runtime-fl23-current.json
git diff --no-index -- src/looks/assets/runtime-fl23-current.json private/generated/runtime-fl23-current.json
```

The final command should report no differences. The builder checks both original fingerprints, reconstructs the legacy target, derives the current target, restricts changes to reviewed FL23 regions and verifies the complete merge. Do not update the asset from unmatched files. The output contains bounded patch data and fingerprints, not full firmware or body calibration.

`A7C2_RESEARCH_FIXTURES` is a different input: the author's historical three-look/six-look fixture-index JSON described in [formats](technical/formats.md). Official stock components cannot replace that history. Leave unavailable tests skipped rather than relabeling unrelated files to make them pass.

## 6. Offline verification

From the repository root, using the same interpreter:

```powershell
& $devPython -m unittest discover -s src/fl23/tests -v
& $devPython -m unittest discover -s dev/usb/tests -v
& $devPython -m unittest discover -s dev/release/tests -v
Push-Location src/looks
try { & $devPython -m unittest discover -s tests -v } finally { Pop-Location }
& $devPython dev/release/check_publication.py
git diff --check
```

Setting `A7C2_STOCK_COMPONENTS` enables 12 current-firmware integration cases. They cover both orders, exact inverse, slot undo, host preparation/install/verify, checkpoint rollback, conflicts and real AArch64 worker compilation. One case executes 512 native Thumb gamma-routing combinations. Programs are real official bytes; USB, settings/calibration and camera transactions are simulated. Tests must never discover a connected camera as a side effect.

Recorded functional results: 96 FL23, 52 host/USB and 111 LUT cases passed; 35 historical fixture cases were skipped. The 111 includes the 12 current-firmware cases. Documentation-policy tests are reported separately. Missing official components skip the additional 12 cases; that is not successful integration validation.

## 7. State, identity and preservation invariants

The compatibility route is `prepare` → `prepared` → `install` → `installed_pending_cold_start` → physical checks → `verify`. Preparation records the entered firmware version, same-body identity, two exact originals, candidate programs and an independent checkpoint containing both programs, live/saved settings and 68 name resources. It refuses nonempty or nested backup/work directories.

Installation rechecks complete current files, target settings and unrelated unsaved recipes before writing. After program writes it compares complete target bytes; selected color/settings writes are read back and stored values checked. Verification compares current FL23 activation, saved parameters and loaded AP spans so a later valid LUT import does not trigger an obsolete whole-output check.

Service entry checks the normal USB product string, authenticates once and binds the four-byte AP serial `00e70003` using its legacy hexadecimal-text digest. LUT jobs additionally retain their normal USB serial binding. Storage readiness and `getCameraInfo` are not service-entry prerequisites. HASP is not a stable body identifier.

On timeout, interruption, malformed native result or unknown write outcome, stop further packets and preserve the first evidence. Do not retry authentication or loader execution, delete unknown temporary files, or edit a phase to enable another write. Keep model/body binding, existing-byte conflicts, full readback and native report/mount checks when refactoring.

Compatible settings checks cover writable AP group `02cf` and four protected CP units. Only the two planned FL23 color units may change, within the guarded merge; other calibration remains protected. Unrelated runtime counters are backed up, not compared as configuration or written back. Unrelated unsaved recipes stop the write before a group save can persist them.

## 8. Native workers and recovery

`installer.c` supports the existing hash-checked build and a `BYTE_WINDOWS_ONLY` build for per-job compatibility/recovery. The latter checks changed bytes and requires full host byte readback; it is not an unchecked writer. `INSTALL_REQUEST`/`INSTALL_RESULT` allow Recovery's independent namespace. Both modes must compile, remain within the 65,536-byte staging limit and meet ELF/no-external-symbol checks in `nativebuild.py`.

Use `recovery.py` for complete rollback to the chosen checkpoint. Slot undo clears the selected bitmap/name/recipe and preserves other slots/FL23; dormant shared LUT code can remain. Complete Recovery removes changes relative to its chosen capture point. Retain all checkpoint/shared-store dependencies. Byte-for-byte restoration in a simulator does not prove physical recovery or power-loss recovery.

## 9. Documentation and packaging checks

`dev/release/documentation-layout.json` inventories the 15 active English/Simplified Chinese guide pairs and 17 explicitly retained historical/attribution files. Its one historical-language exception is exact-path scoped. Publication checks still scan retained documents for private markers, broken links, malformed headings and encoding; unlisted or missing documentation is rejected. Update the inventory deliberately when adding/removing documents, and keep current commands in paired guides rather than treating archived notes as installation instructions.

Build locally without publishing:

```powershell
& $devPython dev/release/build_lut.py --output dist/lut.py
& $devPython dev/release/build_lut.py --entry recovery.py --output dist/recovery.py
& $devPython dev/release/build_release.py
```

`verify_release.py` additionally requires the unchanged `dist/a7c2-dcp-profiles-2026-10-18.zip` from upstream v2.1, alongside the tools ZIP and both standalone files. Run it only with those original assets available. Do not invent substitute DCPs or report full release verification when an input is absent. Packaging checks prove bundle/source consistency, not camera behavior. Standalone launchers extract bundled source into a manifest-keyed cache; job/backup storage is separate.

## 10. Contribution and physical validation

Develop on a feature branch. Contributors without upstream write access should fork, push their branch and open a draft PR. Include the base commit, concrete before/after behavior, test commands and pass/skip counts, untouched precompiled assets, and physical limitations. Do not publish complete firmware, body backups/calibration, photos, fixture indexes, credentials or local diagnostic outputs. Do not rewrite upstream tags/releases as part of a code fix.

Before claiming a usable camera release, a separate authorized hardware run must record the exact body/version and source revision, backup/recovery locations, actual battery/connection conditions, device readback, cold-load/AP runtime evidence, no-shutter preview switching, new photos/playback, relevant video modes and real restoration. No physical USB/install/cold-boot/photo/video/recovery test has been performed for this branch. Historical one-body reports remain historical evidence; they are not acceptance of these new bytes.
