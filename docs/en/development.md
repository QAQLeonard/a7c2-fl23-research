# Development guide

[Home](../../README.md) · [简体中文](../zh-CN/development.md)

One overview for maintainers and AI agents. Read [AGENTS.md](../../AGENTS.md) first: it holds the rules that must not be broken. This page explains how the code fits together; for details, read the code it points to.

## Scope

- Integration branch: `dev` (renamed from `develop`). Release history remains on `main`.
- Camera: Sony ILCE-7CM2, firmware 2.01 only.
- Product: the 3.0 desktop app (`desktop.py`), on Windows 10/11 x64 and macOS 14+ Apple Silicon. Windows and macOS share the GUI, planners, camera writes and recovery. Only USB drivers, privilege elevation and media handling differ per host.
- Legacy command-line tools (`FL23.cmd`, `lut.py`, `recovery.py`, `shutter.py`, `vertical.py`, `a7look_*.py`, `raw_*.py`) remain for advanced use. Their backup-based workflows are separate from the desktop's backup-free direct operations.

## Repository map

| Path | Responsibility |
| --- | --- |
| `desktop.py` | Entry point: GUI, `--worker`, `--privileged-worker` (macOS), `--raw-profile-worker` (Lightroom), `--offline-self-test` |
| `src/desktopapp/` | GUI (`window.py`, `lookeditor.py`; colors and states in `theme.py`), jobs (`jobs.py`), worker dispatch (`worker.py`), one-click coordinator (`allinone.py`), dialog texts (`reloadguide.py`, `connectionguide.py`, `lookguide.py`, `completion.py`) |
| `src/desktopapp/actions/` | `catalog.py`: which actions touch the camera or need power confirmation. `look_compiler.py` and `sound.py`: adapters for offline conversion and the sound runtime |
| `src/desktopapp/platforms/` | Host-specific code: `usb_drivers.py` (Windows WinUSB via libwdi, UAC, uninstall), `windows_pnp.py`, `macos_authorization.py` (Terminal + sudo), `macos_media.py` |
| `src/looks/looktool/` | Core engines: `direct.py` (backup-free transactions), `bundle.py` (combined plan), `requestcleanup.py`, `compilelook.py` (DCP/CUBE → `.a7look`), `rawauto.py`/`rawidentity.py` (Lightroom), plus legacy checkpoint/job modules |
| `src/camera_runtime/` | USB service session (`transport.py`), FL23 planner/assets, macOS host helpers (`macos_host.py`), shared Sony-PMCA-RE under `src/fl23/vendor` |
| `src/shutter_sound/` | Sound conversion/volume, audition, persistent install; `native/` holds the AArch64 camera workers |
| `src/vertical/` | Vertical Display workers and portrait resources (**being rewritten**) |
| `src/double_exposure/native/` | Experimental mean/stream core, file request entry, SDK event forwarding, background pipeline, DCF publication and SIDB registration; offline candidate with physical acceptance pending |
| `src/fl23/` | Standalone legacy FL23 installer; its `native/` workers are reused by the engines |
| `plugins/A7LookAuto.lrplugin/` | Lightroom Classic auto-profile plugin |
| `calibration/` | Virtual 2.01 response model used by the compiler |
| `dev/desktop/` | Packaging (`build.py`, `desktop.spec`, `prepare_assets.py`, `prepare_presets.py`, `profilepack.py`) and the desktop test suite |
| `dev/shutter_sound/`, `dev/vertical/`, `dev/usb/` | Tests, emulators and research tools |
| `dev/release/` | Historical v2.x CLI release scripts and `check_publication.py` |
| `desktop-assets/` (ignored) | Distribution-only inputs: six default looks, paired profile library, Windows/macOS helpers |
| `build/`, `dist/` (ignored) | Caches, private evidence and build outputs |

Not every retained source file is a desktop feature. The independent CLI still uses `devicejob.py`, `devicecli.py` and the legacy FL23 modules. `fl23_color.py` rebuilds and checks donor color assets; `standalone.py` and `photobuild.build()` reproduce the bundled instruction templates for offline validation. Native worker sources have one canonical location under `src/fl23/native`. An import without a local variable use may be a public re-export (`jobs` action categories, macOS media helpers) or required path initialization (`files_worker` importing `candidate`). Check those roles before deleting it.

## How a button becomes a camera write

1. **GUI** (`window.launch`). Write actions show a power/model confirmation; the request then carries `power_confirmed=True`. The UI thread never calls camera, driver or native-worker code.
2. **Job** (`jobs.new_job`). Creates `<data root>/runs/<UTC time>-<action>-<id>/` with `request.private.json` (schema `a7c2-desktop-job/1`) and `status.private.json`.
3. **Worker** (`desktop.py --worker`). A fresh child process for every job. On macOS, camera actions first re-run the same worker as root through a per-job Terminal sudo script. The worker writes `worker.log` and sets the status to `RUNNING`, then `SUCCEEDED` with `result`, or `FAILED` with `error`, `error_type` and the full traceback.
4. **Dispatch** (`worker.run`). Routes the action to an engine (see the table below). Power confirmation is recorded by the executing backend; the desktop does not measure or print a battery percentage.
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
| `direct_factory_reset` / `direct_verify` | `looktool.direct` | User-provided recovery source; one primary button starts and finishes recovery |
| `direct_fl23_enable`, `direct_fl23_disable` | `looktool.direct` | |
| `direct_looks_import` (→ `direct_resume_looks`) | `lookbatch` + `looktool.direct` (`install_all`) | `operations`: `slot`, `action=write/restore`, `path`, optional `name` |
| `vertical_enable`, `vertical_disable` | `looktool.direct` (persistent) | Being rewritten |
| `sound_on`, `sound_off` | `looktool.direct` (`sound_enable/disable`) | |
| `sound_mechanical_on`, `sound_mechanical_off` | `looktool.direct` (`sound_mechanical_enable/disable`) | Native speaker segments; preserve the electronic switch and shutter settings |
| `sound_import`, `sound_volume` | `actions.sound` → `shutter_sound.sound_cli` | Computer only, no camera access |
| `sound_audition`, `sound_install`, `sound_verify`, `sound_restore_sound` | `actions.sound` | Camera actions |
| `compile_look` | `actions.look_compiler` → `looktool.compilelook` | Offline |
| `plugin_install` | `desktopapp.plugins` | Optional Lightroom plugin; bundles ExifTool |
| `restore`, `restore_auto`, `restore_verify` | `checkpointjob.Rollback` | Optional restoration from a selected or discovered complete backup |
| `backup_current` | `desktopapp.backup` | Optional read-only current project checkpoint; voice resources can be saved in a separate ZIP |

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

**Factory restore:** `src/looks/assets/factory-layout-2.01.json` contains only offsets, lengths and original-content digests. `official.prepare_restore` obtains actual recovery bytes from a user-supplied official 2.01 file or a usable original same-body backup before USB opens. A local private reference supports the post-reload check; it is not a distribution asset. The same primary button starts recovery and then continues its final verification. Optional voice restoration is recorded in the transaction; skipping it retains the disable guard. Unrelated bytes/calibration are preserved.

**Optional current backup:** the recovery page can create an existing-format `checkpoint.private.zip` containing current AP/CP programs, live/saved settings and the 68 name resources. Its provenance is `current-project-backup`: it can be selected for rollback but is excluded from automatic earliest-original discovery. The optional `voice-resources.private.zip` contains the twenty captured voice-guide files; it supplies voice data when a selected rollback needs to remove the voice disable guard. Installation does not require a backup; factory recovery requires an explicit official/original source. Official voice resources can instead be prepared locally from the user's own 2.01 update with `desktopapp.screenreader`; the application does not bundle them. Voice restoration uses 1 MiB chunks into fixed staging names, checks the complete file digest and atomically publishes each file before removing the disable guard.

**Voice space:** `voicelock.py` changes four existing instruction windows (20 bytes total): the native support leaf and three ordinary setting writers. Five native menu records also change thirteen mode flags each from 1 to 2 (130 data bytes): the original nonzero visibility check still passes, but the exactly-1 selectability check fails. The native setting and trigger are saved OFF. New one-click installs always call `voice_cleanup` before other feature writes. It first installs this disable plan and requests a cold reload; only a later request whose loaded guards match may delete the ten language audio BINs. Index files stay. `resource_files.c` admits only its compiled fixed paths and sizes/digests from the fresh inventory, remounts `/usr` read-only after each operation and publishes a restored file only after its full hash matches. Native emulation uses a synthetic filesystem and does not prove filesystem behavior under physical power loss or camera boot safety. Factory reset selects mechanical shutter, disables silent mode, restores the original sound path and requires the reload check before private sound-file cleanup and completion. AF audio settings are preserved.

**USB service entry** (`camera_runtime/transport.Session`):
1. Check the normal USB product string.
2. Authenticate.
3. Wait for `0336`.
4. Authenticate again.
5. Bind the body by property `00e70003` (hex-text serial digest).

If `0336` never appears and the camera returns to `0E8A`, the session cools down for 30 s and retries, up to 3 attempts. Nothing is sent to the camera after an authentication that never reached `0336`.

**Sound** (`src/shutter_sound/`): `media.py`/`native_codec.py` convert audio on the computer. `sound_cli.py` drives the workflow for both the desktop and `shutter.py`. `candidate.py`/`boot_sound.py`/`files_worker.py` build the fixed native changes. Audition and confirmation records are optional and never gate saving.

**Native portrait candidate:** `desktopapp.vertical_native` first retires legacy portrait edits through the existing inverse and asks for a cold reload. `verticaltool.nativeportrait` then builds independent `_23` image banks at the original IDs, using current body images and the existing drawn portrait shapes; it leaves `_32` horizontal banks and AP drawing code original. `resourceworker` admits only the three fixed bank paths and checks loaded original AP windows before copying; its native worker also requires the runtime display switch OFF for mutations. `verticalpersist.Stage` recognizes complete or partial managed files for disabling/restoration. Factory recovery releases these files before restoring voice audio, so the reclaimed voice space is available again. One-click setup pauses before its program/LUT phase if legacy migration needs a cold reload. This is an offline-tested candidate; it has not been physically accepted.

**Look conversion:** `compilelook.py` parses DCP LookTable/tone curves, or ST/sRGB CUBEs, and fits them to the native table with `calibration/a7c2-2.01.virtual.npz`. No Lightroom is needed. See [LUT formats](lut-formats.md) for supported inputs.

## Build and test

Use native 64-bit Python 3.11.

```text
python -m pip install --no-build-isolation -r desktop-requirements.txt pyinstaller==6.16.0 pytest==8.3.5
python -m pytest dev/desktop dev/shutter_sound/tests dev/vertical -q
python desktop.py
```

The root `conftest.py` blocks physical USB enumeration in every test. Other suites: `python -m unittest discover -s src/looks/tests`, `src/fl23/tests`, `src/camera_runtime/tests`, `dev/usb/tests`. Private fixtures (`A7C2_RESEARCH_FIXTURES`) are optional; without them those tests skip.

**Double-exposure development:** `dev/double_exposure/build_jpeg.py` builds a static
ARM64 Linux processor from a local, unmodified libjpeg-turbo 3.1.2 source tree,
using Zig, CMake and Ninja. Pass `--source`, `--output`, `--zig`, `--cmake` and
`--ninja`; `--target host` builds the same C pipeline for local tests. Build
tools are listed in `dev/double_exposure/requirements.txt`. The output directory
includes codec notices and licenses. This helper takes two completed baseline
8-bit sRGB/untagged JPEGs with matching dimensions/orientation and saves a new
quality-95 JPEG using scanline RGB means. Run `python -m unittest discover -s
dev/double_exposure -v`; set `A7C2_ZIG` for the kernel tests and
`A7C2_JPEG_COMMAND` to a JSON argv list for the built processor or its runner.
The helper is not included in the desktop installer or connected to a camera
menu/capture hook yet; file processing does not register the result in the
camera's media database.

`capture_pair.c` is a separate freestanding coordinator: the adapter must supply
correlated capture-start/completion events, resolved JPEG paths and media
generations, and persist the session state. It does no I/O or firmware calls.
Its capture-result decoder reads reservation identity only. Set the optional
`A7C2_CAPTURE_AP` to an original 2.01 `appFw.so` to compare directory/file
decoding against the native auto-review reader under emulation; that check
intercepts model/string helpers and does not execute camera hardware.
The coordinator accepts native Fsys or POSIX paths for sources, staging and
catalog entries. The executing adapter must establish output ownership;
a proposed staging path is not a reservation. Native Fsys paths cannot be
passed directly to the standalone Linux processor's POSIX file interface.

`jpeg_stream.c` performs the same mean through caller-owned I/O callbacks.
`mpr_stream.c` adapts the existing AP's synchronous MPR file functions and
Fsys flush function; the caller supplies function pointers and stays in the
initialized AP process. Read-open uses native flag 1 and retains its native
path/handle lifetime through close. Writer attachment requires an already-owned
temporary handle; it never opens/truncates a destination. The core does not
flush, close, publish or register output. These remain the caller's transaction.
The runtime binder is implemented, but has not been invoked against a live SDK.

Build `--component stream` into a separate output directory for a host library
or the ARM64 shared library targeting glibc 2.25. The camera build checks ELF
dependencies and required libc symbol versions. Set `A7C2_STREAM_LIBRARY` to a
host DLL/SO for callback/adapter tests. Camera `--harness` additionally builds a
test-only synthetic MPR runner; `A7C2_STREAM_COMMAND` is its JSON runner argv.
That runner validates the shared-library ABI under QEMU, not actual camera I/O.
Embedded codec symbols are local to the shared module; the native harness
exports an incompatible host codec symbol to verify that it is never called.

`ap_runtime.c` binds only already-loaded SDK modules (`RTLD_NOLOAD`), qualifies
symbol ownership and pins its own module. `BOUND` means exports resolved, not
camera/SDK readiness. Keep job leases through I/O and handle reconciliation;
keep callback leases through unregistration and native rundown. Retirement
refuses active leases and returns a module reference for the caller to close
outside the core. No SDK init/file I/O or callback installation occurs on bind.
`--harness` also builds a loader runner and synthetic SDK libraries under
`test-sdk/`. They are test fixtures, never device assets. Set
`A7C2_BINDING_COMMAND` to that runner's JSON argv for ARM64 loader tests.

`output_reservation.c` separates pure planning/intents from directory creation
and temporary-file opening. Persist each intent before its SDK step. It uses
a newly-created private directory under the selected DCF photo folder;
write|create flag 6 alone does not establish exclusive ownership. Existing or
uncertain state is retained, with no automatic retry/delete. The integrated
pipeline below supplies publication, media registration and module loading;
all current executing SDK tests use local synthetic backends.

`bootstrap.c` is a separate small explicit-call control helper. It resolves and
qualifies the core's ABI/start/query/retire exports, retains a temporary module
reference during control calls, and closes a transferred self-pin only after
the core returns. Query/retire use `RTLD_NOLOAD`; a failed close stops without
retry. The outer caller must serialize requests, persist dispatch intent and
retain unknown results. `dev/double_exposure/build_bootstrap.py --output <dir>
--harness` builds the ARM64 helper (limited to 64 KiB) and a test-only loader
runner. It has no libJit `_init` dispatch entry or device transport. Loading a
verified core can execute its ELF startup code; verification/ownership must
precede the call. The helper report contains no transferable loader handles.

`dev/double_exposure/staging_model.py` models an offline local transaction:
48 KiB immutable chunks, per-chunk and whole-core SHA-256, create-new directory
ownership, journaled intents and no-replace local publication. Reopening checks
all acknowledged bytes; unfinished intents retain evidence and stop. Only a
verified acknowledged prefix can resume. It does not implement a camera upload
or prove camera filesystem/power-loss behavior. `READY` means verified bytes,
not ELF/SDK readiness. Set `A7C2_ZIG` for nine loader fault-injection tests;
`A7C2_BOOTSTRAP_COMMAND` (JSON runner argv ending in helper path and synthetic
SDK directory) and `A7C2_STAGE_CORE` enable five actual ARM64 loader tests,
including chunking/reassembling the core before a full load/retire cycle.

`staging.c/.h` implements the native Linux POSIX receiver behind the model.
Its 80-byte little-endian request identifies the transaction, core size/hash,
operation and chunk index; CREATE appends the chunk hashes. CREATE owns a new
directory, PUT accepts only the next chunk, ASSEMBLE checks the independent
whole-core hash and publishes without replacing an existing file, and QUERY
rechecks the immutable plan, intent/data/confirmation records and file contents.
An unfinished intent stops without replay. A lost reply can be reconciled by
QUERY when durable confirmation and matching bytes exist; duplicate PUT and
ASSEMBLE requests still fail. Directory `flock` serializes cooperating callers.
Descriptor-relative no-follow/exclusive opens preserve foreign files; only a
successfully published assembly's temporary link is removed. The report is
112 bytes; `pending_fd` is diagnostic evidence, never a request to retry close.

Build `build_bootstrap.py --component staging --output <dir> --harness` for the
separate small ARM64 receiver and local test runners. Set
`A7C2_STAGING_COMMAND` to the native runner JSON argv and
`A7C2_STAGING_FAULT_COMMAND` to the separate test-only fault runner. Twenty-nine
ARM64 tests cover SHA-256 padding boundaries, concurrent requests, corruption,
partial/zero writes, readback/flush/close errors, process interruption and
publication collisions. One test receives the actual core through this C
receiver, then loads/retires it against synthetic SDK libraries. Two host
protocol tests check wire encoding. This receiver itself has no SDK/photo I/O;
the file entry and integrated pipeline below connect its verified output.

`file_entry.c` is the small one-shot libJit request entry. Its constructor reads
only fixed `/tmp/jiritsu/a7c2.dex.{request,payload}` inputs, creates an exclusive
result intent before executing, and appends a checked result/commit marker.
Stage requests use the 80-byte protocol; control uses the 64-byte `A7DEX001`
ARM/WORK/QUERY/DISABLE protocol. ARM requires verified complete core staging;
QUERY/DISABLE use `RTLD_NOLOAD`. A complete command receipt is not a completed
photo. Build `build_bootstrap.py --component entry --output <dir> --harness`;
the entry file stays within 64 KiB. Large staging buffers are heap/module-owned,
not placed on the AP request thread's stack. The explicit-call test runner
disables automatic constructor execution and uses local fixture directories.
An additional loader runner opens the actual production helper without calling
its entry export. `A7C2_FILE_ENTRY_CONSTRUCTOR_COMMAND` is a JSON argv list
using `dev/double_exposure/file_entry_namespace.py` with explicit `--qemu`,
`--sysroot`, `--runner` and `--helper` paths. Linux user/mount namespaces hide
host `/tmp` and bind the owned fixture at `/tmp/jiritsu`; keep all input paths
and TMPDIR outside `/tmp`. Six ARM64 cases cover full staging, query/disable,
missing SDK, retained handles and unload/reload. Holding an entry handle avoids
constructor reexecution; the one-shot loader must release it between requests.
That requirement concerns the small entry, not the permanently pinned core.
These loader tests do not validate the camera service's actual loader lifecycle.

`device_request.c`, `pipeline.c`, `native_session.c` and `resident_entry.c`
connect requests, callback queues, JPEG means, publication, SIDB transactions
and independent confirmation. One worker has a 512 KiB stack. Callback paths
only copy bounded events and wake it; file/codec/catalog calls run on that
worker. Intents/results are append-only checked records in a separate owned
POSIX run directory. Unknown outcomes retain source/result paths, pending
handles, native errors and UID results; they cannot be replayed. DISABLE can
queue behind running work and completes only after context rundown. Instance
identity and increasing request IDs prevent an old request from starting a new
job. Reports are pointer-free: pipeline 2,800 bytes, device 2,832 bytes.
ARM's media ID can be explicit or `UINT32_MAX` (the driver's default): choose
the first eligible SDK begin media, then bind both photos to that native ID.
Arm from an idle capture state and poll acceptance before taking the two shots.

`sony_sdk.c` qualifies exports from already-loaded Sony libraries and checks
the mapped 2.01 AP/DCF profile. `sony_begin.c` forwards the SDK countdown and
write-finished events with their original pointers. The SDK's 88-byte payload
retains the JPEG UID before AP marshaling; its UID is resolved by fresh SIDB
Select on the worker. Native AP delegate registration/unregistration stays
under its original owner. Detaching drains sink/context users, while forwarding
code, SDK references and AP code remain pinned until AP process exit because
SDK pointer dispatch has no proven unload rundown. A disabled pair therefore
does not permit hot retirement/replacement of the resident core. The separate
`capture_delegate.c` seam requires ownership of the delegate owner's lifetime;
production uses SDK forwarding. No sensor/firmware/settings patch is
installed by these adapters.

`dcf_publish.c` selects a free numeric DCF folder, reserves/confirms that entry
and its native file-number bitmap under the numbering mutex, creates a new owned folder and publishes
`A7AV0001.JPG`. It re-enumerates numeric aliases, compares staging readback
with the encoded write-stream digest, and verifies the destination hash after
moving. Native folder-cache updates use native string construction
and assignment. This prototype uses one new result folder per pair (the DCF
100..999 ceiling applies). `media_catalog.c` uses native record clear/Select,
IssueUniqueId, Update and Flush; source time is retained, a fresh UID is issued
once, and a new Select must confirm path/size/time before COMPLETE.

`dev/double_exposure/device_driver.py` accepts an explicitly supplied open
session; import/construction never enumerates/authenticates/connects USB. Its
explicit stage/arm/query/disable operations use bounded uploads, durable host
intents and matching archived receipts. All owned temporary contents are checked
before deletion and results are removed last; uncertainty preserves evidence
and disables further commands. A nonblocking per-driver lock covers each entire
operation, including host state changes. Once an operation begins, any failure
(including a final host journal save after the native return) marks the driver
REVIEW and the session unhealthy/mutating; no subsequent command is sent.
Invalid ARM arguments detected before starting leave the transaction usable.
The caller still owns session-wide exclusivity across driver instances.
Only its three fixed temporary names were added
to the existing transport allowlists. ARM submission leaves the host ARMING;
only a fresh native report with matching request/epoch/media generation and an
active attached collector makes it ARMED. Photo completion additionally checks
pipeline/catalog status, UID validity, matching result/publication paths and
matching nonzero output/publication sizes.

`dev/double_exposure/experiment.py --helper <entry.so> --core <core.so>
--output <new-directory> --run` is the explicit first-pair operator entry.
Only --run creates service sessions. It stages/arms and polls acceptance, exits
the service session, then prompts for USB removal and two manual JPEG shots.
Reconnect to the same body without restarting/changing cards; it polls the
result, preserves the result path and disables/drains processing before service
exit. Failure/timeout preserves evidence and stops without automatic rearming,
disabling or replay. The first trial uses matching baseline sRGB JPEG settings
and a fixed physical card generation; changing cards is outside that trial.
The small loader's original 2.01 SET_FILE2 implementation uses RTLD_LAZY then
dlclose; loader reference handling was also checked against local original
instructions. These are development trial tools, not a desktop feature.

Use `A7C2_PIPELINE_LIBRARY` for integrated host tests,
`A7C2_PIPELINE_COMMAND` for the ARM64 asynchronous pipeline runner, and
`A7C2_FILE_ENTRY_COMMAND` for the ARM64 file entry runner (JSON argv lists).
The command variables are JSON argv lists. `A7C2_NATIVE_MPR` optionally points
to a local original 2.01 library for replaying its numeric bitmap helper in
synthetic RAM; the original library is never distributed. The tests use
synthetic SDK/AP providers and local files; they exercise the
actual compiled codec/controller and failure/rundown contracts, not a live
Sony SDK. Physical capture/preview/playback, media insertion/removal, camera
filesystem/cache behavior, AP restart and power-loss acceptance remain pending.
The caller supplies the selected media generation; no physical acceptance is
inferred from that logical identifier or from successful symbol binding.

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
