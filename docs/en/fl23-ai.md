# FL23: AI installation and reproduction guide

[Home](../../README.md) · [简体中文](../zh-CN/fl23-ai.md) · [User installation guide](fl23.md)

Goal: install FL2/FL3 on A7C II 2.01 under Windows, with duplicate backups, writing, independent readback, cold-load, capture/playback and restoration. **Use the explicit CLI preparation route for compatibility; the retained desktop route is stock-only.** FL23 installation does not import LUTs; independent Recovery performs full rollback to the selected initial state.

## 1. Starting point

Read [AGENTS](../../AGENTS.md), [the user guide](fl23.md) and [compat.py](../../src/fl23/compat.py). Only ILCE-7CM2 is supported. The user enters 2.01 from the camera version screen; the version is not automatically queried.

Explicit FL23 preparation has no stock/repository whole-firmware provenance whitelist. Changes outside actual patch positions do not disqualify a body. Instruction conflicts at write positions still stop with an address. Preserve existing LUT slots/dispatch and merge reviewed current gamma windows where needed; already enabled current FL23 is backed up/verified without reinstalling.

The compatible CLI installation prints a provenance-risk warning. Keep duplicate actual-file backups, exact candidates/inverses and full post-write readback. Per-job integrity is distinct from stock provenance.

`Session` reads the normal USB product string, authenticates 0E8A→0336, then uses `getBackupPresetData(True)` and AP property `0x00E70003` (four bytes). Preserve the old binding with `sha256(serial.data.hex().encode('ascii'))`, not a hash of raw bytes or HASP. Match an existing expected identity before returning a usable session. Storage readiness and `getCameraInfo` are optional diagnostics, never service-entry prerequisites. Authentication/transport timeouts are not retried. This integrated change is offline-tested; user-reported success of the same service route is separate from validation of the released build.

Use 64-bit Python 3.10+ on Windows. The launcher installs dependencies, with no separate compiler operation. Normal/service USB IDs are 054C:0E8A / 054C:0336.

## 2. Existing implementation and boundaries

| Source | Role |
|---|---|
| [app.py](../../src/fl23/app.py) / [workflow.py](../../src/fl23/workflow.py) | CLI dispatch / `Job.prepare/install/verify`, backups, candidates, transactions and verification |
| [gui.py](../../src/fl23/gui.py) | Windows buttons dispatch to the same `app.py` commands |
| [core.py](../../src/fl23/core.py) | `ORIGINAL/FINAL`, fixed patches, per-body merging, guards and native report validation |
| [transport.py](../../src/fl23/transport.py) | `Session`: identity/authentication/bounded I/O, unknown-result stop, restricted staging/Backup writes |
| [assets/manifest.json](../../src/fl23/assets/manifest.json) | Exact fingerprints of compiled native assets |
| [native/installer.c](../../src/fl23/native/installer.c) | Fixed windows, retained size/inode, mode0 check/mode1 install/mode2 restore |
| [native/wbi.c](../../src/fl23/native/wbi.c) | Retained-image inspection/invalidation from the known precondition |
| [tests/test_offline.py](../../src/fl23/tests/test_offline.py) | Body isolation, occupied storage, unrelated changes, temp conflict and unknown-session checks |

Use the reviewed offsets. New preparation generates a worker for the actual files instead of using the fixed stock worker on modified files. Do not gate provenance; report instruction conflicts separately. Backups must belong to this body.

## 3. Offline startup checks

From the extracted root:

```text
.\FL23.cmd --check
.\FL23.cmd --setup-only
.\FL23.cmd check-package
```

These do not connect to the camera. Environment setup may install dependencies; incomplete existing environments are retained. Double-click `FL23.cmd` for desktop mode. Never run GUI and CLI device operations concurrently.

## 4. Complete CLI sequence

1. Select two new empty workspace/backup directories, preferably on separate disks. Retain previous workspaces.
2. Run `prepare`, requiring phase `prepared` and explicit backup/candidate/native-preflight success:

```text
.\FL23.cmd prepare --firmware-version 2.01 --workspace "D:/CameraWork-A7C2-01" --backup-copy "E:/CameraBackup-A7C2-01"
```

3. Check identity, both backups, candidates and native mode0 evidence. With actual battery at least 50% and continuous connection, install. Replace the example 82 with the real percentage:

```text
.\FL23.cmd install --workspace "D:/CameraWork-A7C2-01" --battery-percent 82
```

4. After `installed_pending_cold_start`, full readback and all I/O completion, disconnect all external power, shut down normally, wait for the access lamp and remove the battery for at least one minute. Test names, no-shutter preview, new FL2/FL3/ST captures and playback. Reconnect Mass Storage:

```text
.\FL23.cmd verify --workspace "D:/CameraWork-A7C2-01"
```

5. Check complete programs, saved parameters and AP runtime spans, keeping user observations separate. Matching readback does not prove photographic behavior or all-mode stability.

## 5. Expected work at each stage

`prepare` reads programs/body data, checks entered version and actual patch positions, merges this body's parameters, rejects occupied storage, builds candidates, verifies duplicate originals and runs native check-only. An already enabled FL23 inspection skips installer/WBI preflight and creates no new install. Temporary diagnostics execute; programs/saved recipes are not installed.

`install` requires the same body and `prepared` phase, rechecks source/settings, applies fixed program windows/full readback, merges/saves target parameters, checks unrelated-property preservation and performs guarded retained-image handling. `verify` does not reinstall; it checks post-reload files/parameters and AP spans.

Persist intent before each native invocation, verify staging, invoke once and validate magic/version/mode/length/errors and write counts. New FL23 workers use `BYTE_WINDOWS_ONLY` and complete host byte readback, with no whole-firmware hash checks. After timeout/unknown session, stop further packets including repeated cleanup. Retain `state.json`, logs, existing results and temporary files; inspect the actual outcome first.

## 6. Independent recovery

The retained stock-only FL23 restore helper is not a mixed-feature rollback entry. Use [Recovery](recovery.md) for complete rollback from the original backup2 or a new checkpoint. It does not require LUT jobs. Keep model/body binding, edited-byte checks, complete readback and unknown-result evidence; do not reintroduce whole-firmware hash gates.

Both install orders must preserve the other feature. `compat.plan` adds FL23 flags/parameters around existing LUT code; LUT's planner accepts stock or FL23 sources. FL23 verify reads current programs and checks its own activation plus live spans, allowing later LUT imports. Test both orders and selected-slot restoration after FL23 installation with real private program fixtures; offline results do not prove camera boot safety.

## 7. AI tests and handoff

Run `python -m unittest discover -s src/fl23/tests -v` and `python -m unittest discover -s dev/usb/tests -v`. The host suite includes actual CMD/PowerShell 5.1/7 forwarding, Unicode/spaced paths, exit codes and simulated USB states. These are not full camera boot, power-loss recovery or second-body validation.

Deliver commands/exit codes, backup locations, preparation/write/verify phases, complete byte readbacks, preservation/cleanup, load evidence, user capture/playback and restoration results. Do not reintroduce unnecessary hash gates. Without device access/authorization, complete offline checks and state remaining physical stages rather than inventing installation success.
