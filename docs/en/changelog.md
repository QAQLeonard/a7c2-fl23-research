# Changelog

[Home](../../README.md) · [简体中文](../zh-CN/changelog.md)

## Unreleased — host workflow and current FL23/LUT repairs

Based on upstream `0bf1dbb` for ILCE-7CM2 2.01. This branch is for review and has no physical camera acceptance. The historical Release links below do not contain these changes.

- Restore direct service authentication with USB-model and AP-serial binding; remove LUT dependencies on deleted transport interfaces. Unknown authentication, interrupted I/O and malformed native results stop without replay or cleanup packets.
- Preserve an explicitly selected FL23 backup and its color units, including an empty default store or stale workspace. Restore launcher argument/exit-code forwarding and use the recorded workspace/backup for reload verification.
- Add a reproducible current-FL23/LUT adapter. Official Sony 2.01 AP/CP components match the repository's original fingerprints. Eight reviewed windows (982 bytes) merge current gamma data/helper behavior while retaining LUT dispatch and the larger loaded extent. Both install orders produce identical complete programs; exact inverse, slot undo and full checkpoint rollback are covered offline.
- Restore explicit compatibility `prepare`, per-body candidate/native workers, independent checkpoints, complete byte readback and verification after a later LUT import. Preserve writable look settings and protected CP units; reject unrelated unsaved recipes before writes and do not misclassify runtime counters as configuration changes.
- Restore byte-only worker compilation and independent checkpoint request/result names alongside the hash-checked importer. Existing precompiled FL23 assets and the legacy runtime table are unchanged.
- Document module boundaries, command variants, fixture acquisition, adapter reproduction, test commands, state/preservation invariants, packaging inputs and hardware acceptance. Inventory retained historical documents explicitly; keep privacy/link checks for them and reject unlisted documents.

**Validation:** 96 FL23, 52 USB/launcher and 111 LUT cases passed; 35 historical fixture cases skipped. The LUT result includes 12 official-component integration cases and 512 native Thumb routing replays. Real AArch64 import/recovery workers compiled. Six publication-policy tests and the publication check passed. The adapter reproduces byte for byte from official components, and standalone bundles were checked against source. No camera was connected, authenticated or written.

**Remaining acceptance:** real USB, install, cold boot, photo/video, long-term behavior and physical/power-loss recovery remain untested. Historical three-look/six-look owner files are still required for the skipped matrix. Full release verification also needs the unchanged upstream original-DCP attachment; no new Release or rewritten tag is part of this change.

See the [development guide](development.md) for reproducible commands and [historical validation](technical/validation.md) for earlier build evidence. Complete firmware and generated program images remain outside the public repository.

## v2.2-preview.1 — updated 2026-10-20

- **Independent Recovery:** restore the selected complete checkpoint or original FL23 backup2 without the original workspace or any LUT job. The tool saves a compressed copy of the current state, restores programs, project names/settings, and fully reads back the result. [Recovery instructions](recovery.md).
- **Separate responsibilities:** FL23 installs/verifies; LUT imports/restores individual slots; Recovery performs complete rollback. FL23's restore command and desktop button have been removed.
- **Both installation orders:** FL23 → LUT and LUT → FL23 preserve each other's changes. Verification accepts the expected later changes.
- **Smaller LUT backups:** share a compressed foundation and record the selected slot's pre-write state. Later imports retain changed data instead of repeated complete copies. Keep the shared storage directories with the jobs/backups.
- **Single-slot restoration:** restore its previous table, title and recipe, including undoing first activation, while preserving other slots and FL23. No firmware or backup-file hash admission checks; edited-byte checks and full readback remain.
- **FL23 admission:** check the camera model and user-entered firmware version 2.01, without a firmware-provenance hash whitelist. Warn about other projects' modifications; retain actual patch-position conflict checks.
- **USB connection:** authenticate directly instead of blocking on storage `02/04/01` or application-query Busy. Confirm the USB model and bind the service backup's four-byte AP serial (`0x00E70003`) using the original hex-text digest, retaining existing backups. No separate USB-fix tool is required; Windows device drivers are still required.
- **Failure explanations:** integrated LUT job diagnostics explain native-name transaction failures from saved evidence without reopening USB or blindly repeating a write.

**Validation:** offline suites passed: 131 LUT cases (35 skipped without private fixtures), 22 FL23 cases and 46 host/USB cases, including nine service-first connection/failure cases. Historical real backup data reproduces its original body binding. Separately, 7 real-file order/slot cases and 44 native-name syscall/failure cases passed. This release update did not operate a camera; the user's reported service-route installation is separate evidence. Physical complete Recovery and Mac USB remain untested. [Evidence and limits](technical/validation.md).

These fixes are included in `main` and the updated v2.2-preview.1 commit/release, as authorized by the owner. Existing v2.1/v1.0 releases remain available. ZIP and single-file tools are in the [preview release](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.2-preview.1).

## v2.1

Published FL23 and the independent LUT/DCP CLI, with single-camera Windows slot-update observations, original DCP attachments and film comparisons. [Release notes](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1).

## v1.0

FL23-only tool. [Release notes](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v1.0).
