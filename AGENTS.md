# Repository rules for AI agents

Read [docs/en/development.md](docs/en/development.md) for how the code fits together,
then read the code itself. These rules override anything else in the repository;
the user's explicit instructions override these rules.

No Claude or additional agents without explicit user authorization.

## Shared project knowledge and existing chats

- Before starting or resuming work, after context compaction, and before changing
  an existing feature, re-read the current-state section of the development guide
  and inspect the actual branch, HEAD and working-tree changes. Do not rely only
  on a previous chat summary or a version label shared by different builds.
- In the owner's multi-checkout workspace, also read the local shared knowledge
  index at `../../knowledge/INDEX.md` when present (relative to this checkout).
  Search its `entries/` for the current topic. This is local context, not a
  publication asset or authority to access a device.
- Each chat may and should extend that knowledge base under its template:
  use a separate dated entry for its task, cite source/transaction/test evidence,
  distinguish implementation, package, commit/push and physical acceptance, and
  record failures and next steps before finishing. Re-read before updating;
  preserve other chats' changes and superseded evidence.
- Keep reusable public decisions in the existing bilingual development guide
  and changelog. Never copy the private workspace index or its local paths into
  the public repository or packages. Existing chats need an explicit context
  refresh; do not claim that editing an instruction file updates their context.
- Voice-audio cleanup and its disable/menu guards already exist. Read the guide
  before proposing their implementation or restoration; a cleanup policy in
  source is not evidence that a particular body has completed deletion.

## Branches and releases

- The owner approved merging the Recovery/slot-restoration fixes and the
  service-first USB fix into `main` on October 20, 2026, and updating the existing
  v2.2-preview.1 commit/release. Develop future changes on feature branches;
  further release rewrites need authorization.
- Version 3.0 is the desktop app (`desktop.py`). On October 23 the owner accepted
  the cp-restore.6 test build and authorized integration into `main` and release
  packaging. Record physical test coverage separately from offline/CI checks.

## Desktop direct operations

- Owner exception (October 21): `desktop.py` uses `looktool.direct` for FL23
  enable/menu removal, A7Look import, selected-slot ST defaults and factory-function
  reset without mandatory complete body backups. Keep transaction evidence and
  exact byte readback. Do not reintroduce backup directories or old-recipe
  requirements into these GUI actions; ST reset does not recover former recipes.
- Historical backup restoration and the existing CLI behavior remain separate,
  optional paths with their own contracts.
- Factory recovery sources come from the user's official 2.01 firmware or a
  usable same-body original backup. Ship only the region layout/digests, not
  original recovery bytes. New one-click installs always include voice cleanup;
  only the full recovery flow offers optional voice restoration.
- Preserve current calibration, unselected slots and their titles, and unrelated
  settings. Every imported slot uses ST in saved and runtime bindings; the base
  picker stays editable, so never claim a hard lock.

## Camera safety

- Never repeat a write with an unknown outcome. Recover from existing transaction
  results; retry only known read-only readiness/busy states. An unknown result,
  timeout or disconnect stops.
- Only explicit device actions open USB; doctor/offline commands and app startup
  never do. Run offline validation before camera interaction. One service session
  at a time.
- Service entry checks the normal USB product string, authenticates, then binds AP
  property `00e70003` using the legacy hex-text serial digest. Do not make TUR
  readiness or getCameraInfo prerequisites, or substitute a HASP hash.
- FL23 admits model/user-confirmed version 2.01 without a firmware fingerprint
  whitelist. New FL23 and checkpoint workers use edited-byte checks and full host
  byte readback, without firmware SHA gates or repeated package SHA scans. Keep
  actual patch-position conflict guards and body-bound backups.
- Existing LUT import adapters keep their source fingerprints. Single-slot
  restoration uses byte checks without firmware/backup/worker hash gates.
  Checkpoint rollback is independent of job order and output fingerprints.
- After writing: full readback; size/inode/mount/cleanup checks; check that saved
  and runtime settings are preserved; inspect retained images. A kernel boot is
  not proof of direct CP RAM state.
- Never treat zero-filled storage as proof of ownership. Check exact mapped and
  loaded extents, references, lifetime and BSS boundaries. Audit the ABI and
  every entry boundary.
- Do not reuse the failed display/segment/icon approach or the withdrawn
  `0xff2f04` notification change. Retired `bootstrap6` is prohibited.
- Keep FL/FL2/FL3 working. Names, preview, photo output and metadata are separate
  paths.

## Legacy CLI contracts (`lut.py`, `recovery.py`, `FL23.cmd`)

- `FL23.cmd` only prepares/installs/verifies; `lut.py` imports and restores one
  slot; complete rollback belongs to `recovery.py`. Both install orders must work.
- CLI writes need fresh source identity/settings, two independently
  reconstructable verified backups (shared compressed store plus per-slot
  checkpoints), a tested inverse, native preflight and adequate power. No automatic
  deletion of either store; do not reintroduce repeated raw program/readback copies.
- Settings checks cover writable AP group `02cf` and four protected CP units.
  Unrelated runtime groups and the known `02cf0b6e` diagnostic value are not
  install gates or write targets.
- Use exact adapter source identities. `device_layout` supports pinned stock/FL23,
  reconstructed standalone masks and legacy full7-v4 updates. V4 retries uploads
  of validated cached live-view tables; don't promise zero timing/power cost.
- Slot restoration creates a fresh transaction over current state and preserves
  later changes to other slots; it rejects later changes to the selected
  table/title/recipe and clears the selected mask bit on first activation.
- Initial checkpoint rollback targets backup2 directly with fresh current bytes and
  restores only project look fields, never calibration or counters. Legacy FL23
  archives carry serial property `00e70003`; disclose the historical missing flash
  snapshot.

## Claims and evidence

- Offline manifests, candidates, emulation results and full disk readback are not
  an installation, a successful boot or a physical test. Ask for physical actions
  only after all I/O has ended. Confirm preview, photos/playback and original looks
  separately. No broad stability claim from one camera.
- Mac USB, stock first-install and physical restoration on other bodies remain
  untested unless the changelog records otherwise.
- DCP/LUT conversion is a fitted approximation; do not equate native-grid
  precision with full DCP fidelity. End-user conversion stays offline. The paired
  library needs all color pairs; monochrome entries require the owner's
  independent-error criteria.

## Privacy

Keep full firmware, body backups/calibration, photos, credentials, private paths
and private derived manifests out of the repository and packages. Original DCPs
are distributed only as Release attachments with unchanged bytes and original
attribution. The owner obtained permission for every DCP (Fuji-style, Ricoh,
FL2/FL3) and licensed them under MIT (October 22).

## Documentation

Keep the documentation set small: `README.md`/`README.zh-CN.md` (users),
`docs/{en,zh-CN}/` `lut-formats.md`, `changelog.md`, `notices.md` and
`development.md`, and this file. Keep English and Simplified Chinese in sync. Don't add
per-feature guides or research notes; record decisions in the changelog.
