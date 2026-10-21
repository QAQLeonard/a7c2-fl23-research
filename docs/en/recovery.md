# Recovery: independent complete rollback

[Home](../../README.md) · [简体中文](../zh-CN/recovery.md)

Recovery performs full rollback. FL23 only installs/verifies; LUT imports/restores individual slots. This page covers v2.2-preview.1; the v2.1 download does not include Recovery. [Python/driver setup](manual.md) uses shared dependencies, but Recovery does not call the LUT entry or require a LUT job.

Download [standalone recovery.py](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.2-preview.1/recovery.py) or the [complete tools ZIP](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.2-preview.1/a7c2-tools-2.2-preview.1.zip). [Changelog](changelog.md).

Run the source entry from the complete checkout root, or use the packaged self-contained `recovery.py` on its own. The packaged file embeds its support code; Python/device dependencies still need installation.

## Choose a backup

Use a new `checkpoint.private.zip`, its containing backup directory, or an original raw FL23 backup2 folder. Legacy backup2 works directly: body identity comes from the backup itself, and original titles are reconstructed from current native records. No original workspace or first LUT job is required.

The selected capture point supplies programs, Creative Look names/recipes and FL23 parameters. Features present at that time remain; unrelated shooting settings and counters are preserved. Keep private body backups with their original camera.

Inspect offline first:

```text
python recovery.py inspect "E:/CameraBackup-A7C2-01"
```

## Restore with complete readback

Reconnect in Mass Storage mode and use the actual battery percentage. Choose a fresh `RecoveryWork` directory:

```text
python recovery.py restore "E:/CameraBackup-A7C2-01" --work-dir "D:/RecoveryWork" --firmware-version 2.01 --battery-percent 90
```

Recovery reads the current state, saves a compressed copy, plans the reverse transition, writes and reads back complete files. Later FL23/LUT installations do not require reverse-order uninstallation or firmware-provenance hashes. Original backups are retained.

## Reload and verify

After `RESTORED_AWAITING_RELOAD` and the end of all I/O, disconnect USB/other power, shut down normally, wait for the access lamp, and remove the battery for at least one minute. Restart and check live view, names, new captures and playback. Reconnect and run:

```text
python recovery.py verify "D:/RecoveryWork" --accept-photos
```

`--accept-photos` records observations you actually completed. Complete readback, AP runtime spans and photographic behavior are separate checks. This development workflow is accepted on offline tests; no new physical rollback test is claimed.

## AI implementation notes

The entry is [recovery.py](../../recovery.py), sharing [checkpoint.py](../../src/looks/looktool/checkpoint.py), [checkpointjob.py](../../src/looks/looktool/checkpointjob.py) and [checkpointworker.py](../../src/looks/looktool/checkpointworker.py). Do not route mixed-feature rollback through the retained stock-only FL23 restore helper or require LUT jobs.

Legacy AP property `00e70003` contains the camera serial used for normal Sony identity binding, not firmware admission. `resources.before_custom()` locates the aligned end of the last of 2860 native indices and reverses this project's six appended title indices/strings. Exact reconstruction covers all 68 original resources. This handles project append-only edits, not arbitrary third-party resource replacement.

Legacy backups recorded live settings without a separate flash snapshot; use the recorded values and retain that limitation in metadata. New checkpoints include both snapshots and complete names. Restore project fields while preserving body calibration; preserve evidence and stop on unknown writes. Invalidate retained images only when the observed mode is 2.

Run `test_checkpoint`, `test_install_order`, entry and native-worker regressions offline. Report software checks, device readback, loaded state and physical behavior separately. [Validation record](technical/validation.md).
