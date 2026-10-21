# Validation and limits — October 19, 2026

[Home](../../../README.md) · [简体中文](../../zh-CN/technical/validation.md)

**Repair-branch evidence:** see the [development guide](../development.md) and [changelog](../changelog.md). The observations below describe earlier builds and do not establish physical acceptance of this branch.

## Current independent tools (offline)

FL23 exposes prepare/install/verify only. `lut.py restore-slot` supports native first activation and previous imported-table restoration; `recovery.py` performs complete rollback from a new checkpoint or original raw FL23 backup2, without an old workspace/LUT job.

Both FL23→LUT and LUT→FL23 produce identical final AP/CP bytes in real-file tests. Selected-slot undo preserves later FL23 and another slot; the zero-mask state can import again. All 68 original name resources were reconstructed exactly after repeated appended titles. Slot restoration passed with intentionally incorrect recorded file hashes. Native byte-only name workers passed 44 syscall/failure cases; the tested native program worker was 8,464 bytes. Table FNV fields are generated for the camera format; they are not host file admission gates.

These are offline tests and native syscall simulations, without new camera I/O, boot acceptance or physical Recovery validation. Earlier validation records below remain historical evidence.

Latest offline runs: 131 LUT cases (35 private-fixture skips), 22 FL23 cases and 46 host/USB simulations passed. Seven real-file order/slot cases passed separately, including wrong recorded hashes; 44 byte-only native name cases passed.

## Service-first USB update — October 20, 2026

Nine active-transport simulations cover direct service entry without TUR/GetModelInfo, legacy serial compatibility including leading zero bytes, new preparation, wrong body/model, malformed serial, missing service identity, and authentication/read timeout or interruption without retries. A historical real backup's AP `00e70003` hex-text digest matches its recorded normal-query identity; the historical HASP sample contains neither that raw serial nor its hex text. This update did not operate a camera. The user reported successful installation by another AI using the service route; the exact amended release build and physical Recovery/Mac USB remain untested.

## Physical observations

The `feature/backup2-rollback` branch adds an initial checkpoint and byte-based FL23/rollback workers. Software checks covered multiple later LUT edits followed by one rollback, original titles/recipes, unrelated settings, legacy supplementation, and stopping after unknown completion/readback errors. A real six-look→stock fixture compiled into two workers of 23,368 and 23,088 bytes (74 windows); the final 68-resource worker was 18,104 bytes. Actual name-worker ELF replay passed 28 syscall/failure cases across stock and already-named targets. These are offline tests, with no camera writes or physical rollback acceptance. Routine LUT imports still use compressed incremental backups; an initial archive is saved once per body.

Development regression: 119 LUT cases (29 private-fixture skips), 22 FL23 cases including real-source compilation, and 37 host/USB simulations passed. Five additional private-fixture job/slot simulations passed with initial checkpoint capture enabled. These simulations do not open a camera.

The compact-backup development branch has no new camera validation. An offline AP/CP measurement used 118,051,624 original bytes: the first shared store used 27,018,672 compressed payload bytes, and one later slot-6 replacement added 2,152 bytes. These figures are per copy and exclude names, settings, manifests, logs and compiler cache; they are not USB timing measurements. Host simulation covers ordinary install/exact restore and restoring an earlier slot after a later different-slot update. The current slot restorer also handles first activation, leaving zero-mask shared code dormant.

| Item | Evidence | Limit |
|---|---|---|
| FL2/FL3 | Owner previously captured and replayed FL2/FL3/ST successfully | One body; portable frontend not independently installed on a second body |
| Six imported looks | Owner confirmed normal photo output and six-name operation | Color differences are not Fuji/Ricoh pixel-equivalence measurements |
| Earlier six preview | Owner repeatedly reported stale viewfinder colors; pressing shutter restored display | Photos were already correct; this was a preview problem |
| Preview v4 | Owner says current repeated switching tests appear normal | No measured duration/count or frame recording; long-term stability not established |
| Startup | Owner clarified slower startup happened only the first time after power removal, then said it was fine | No timed boot benchmark or persistent slowdown demonstrated |

V4 installation completed native and independent host full-file readbacks, AP 24-span checks,54 selected recipe checks, four protected CP-unit comparisons, original read-only mount and temporary-file cleanup. Fresh before/after complete setting preservation passed. The retained-image state was already0 from the preceding invalidation and was verified read-only; the mode 2→0 worker was not blindly repeated.

Those checks preceded the owner's physical v4 report. At that historical checkpoint, a separate v4 post-reload machine check had not been recorded; the later public-CLI trial below adds a fresh check. Earlier switch-v2 had a new-kernel-boot check and fullCP readback. Neither stage directly captured running CP instructions or tables. Do not silently relabel earlier evidence as a newer build's runtime verification.

## Color and precision

Six owner-supplied DCP fits use NC/CC/NN/Eterna/GR-positive/GR-negative order. Fuji LookTables are72×12×16; Ricoh90×16×16, both with sRGB value axis and128 tone points. Only look/tone stages are used. Sony physical calibration is retained even where Ricoh profile matrices differ.

Each native table is5×9×9×3 signed 7-bit corrections,1215 bytes; six total 7290 plus32 header bytes. No additional coefficient precision reduction was installed. A previous lower-precision experiment was abandoned. Native-grid fitting does not retain all original high-resolution DCP entries.

Historic same-scene spatial holdout used2293 patches with mean encoded RGB fit errors around 0.0057/0.0042/0.0044/0.0035/0.0042/0.0038. These diagnose fitting against a provisional one-scene rendering model; they are not an end-to-end camera-match score or independent-scene validation. The public fit CLI may produce different candidates and must report its own calibration and error.

## Preview and native tests

V4 uses three instruction windows totaling44 B. Native query/controller/uploader tests cover48 lost-submission reproductions, four random120-frame schedules,38 native/snapshot comparisons, six direct-path comparisons, and invalid-storage/effect-disabled/missing-bank cases. Source fails the controlled omitted-submission case; v4 restores exact packed1620 B bytes on later submits. Memcpy and interrupt barriers are modeled. Actual camera scheduling and hardware timing are not captured.

The existing text extent and generated native mapper were checked; segment/BSS boundaries do not move. A direct-branch audit checks overwritten instruction boundaries. A byte pattern decoded as a branch inside an identified old raw table was classified as data, not ignored as an unexplained executable reference.

Re-submitting a cached table costs extra transfers. Ten identical controlled updates: source1 upload/v410 uploads, both1 build. CPU load, frame rate, power, heat and video behavior remain uncharacterized. A single positive switch test does not settle these questions.

The native transaction worker passed16 controlled install/restore/failure cases. Complete on-camera and host readbacks are additional evidence, not a full RTOS/ISP/boot emulator or a guarantee of power-loss recovery.

## Public reproducibility

Public tests cover DCP/cube parsing, color domains, ST ownership, fitting, range/plane order, selected-slot checksum updates, strict fingerprints, exact reverse transitions and output preservation. Research tests add AArch64/Thumb hooks. Optional private-fixture tests reproduce the complete installed AP 690b5f17… and CP 90d1ed6d… from the same private sources without distributing them, and test the44 B preview transition plus slot6 data replacement. These tests do no USB I/O.

The original host USB support subset has 22 offline tests: readiness/busy bounds, initial-query recovery, timeout-stop behavior, no identity authentication, unchanged service/write AST and atomic updater/original-backup guards. The single-file Windows updater was also verified offline. No other user's completed camera installation is inferred from those tests.

## Unfinished validation

- Longer randomized physical preview runs and direct running-CP evidence.
- Multi-scene/color-chart characterization, skin/neutral/high-saturation accuracy and direct preview/photo comparison.
- Other bodies, region/settings combinations, RAW/HEIF/burst/video regressions, durability and power/heat/frame-rate effects.
- A camera-menu ST lock, if desired; the current gate is not a lock.
- Stock first-install, physical restoration and Mac USB installation.
- Future official firmware compatibility. Current offsets/hashes do not carry across upgrades.

See [failures.md](failures.md) for the restart-loop incident and withdrawn candidates. No claim of universal stability or guaranteed recovery is made.

The current two-entry publication additionally passed 38 host/launcher tests, 35 look-toolkit tests and 8 FL23 offline tests. These are offline software checks, not another camera installation.

## New importer: software evidence only

The implemented job flow has simulated import/readback/reload/acceptance/exact-restore and lost-completion/partial-settings/reverse-continuation coverage. Offline first-import tests cover exact stock and FL23 sources and arbitrary later slot additions. The new title/converter replay covers all64 masks, 13,824 title cases (native base getter controlled) and11,648 converter cases, with no external direct branch into replaced interiors. Both stock/update resource workers passed32 native syscall/fault cases each, using official file ownership. All68 original and68 six-look resource files were transformed/inverted exactly. An actual DCP fit compiled a22,472-byte first-install worker; these results include no camera USB I/O.

At the initial software checkpoint, the public importer, first-install AP/CP and single-file runtime had not been physically installed/boot-tested. The later device trial is recorded below. Mac dependency wheel availability was checked; physical Mac execution/USB remains untested. Shared appearance-model residuals are not full DCP fidelity or independent-scene calibration.


## Windows device trial — October 19, 2026

The development CLI converted the owner's A7C II Ricoh GR Positive Film DCP, captured two verified copies of 73 complete backup files, compiled and passed both native preflights, then installed custom slot 5. Complete AP/CP and 68 name-resource readbacks passed. Only the slot-5 CP table (1,215 bytes) and checksum (4 bytes) changed in the programs; AP, preview code, the other five tables and recipes were unchanged. Protected calibration and the writable AP settings group passed the scoped preservation check. Name-resource text remains GR Positive Film. The owner reported normal cold-boot preview switching, slot-5 photos/playback and FL2/FL3 operation. The rebuilt standalone CLI then verified a new boot, full programs/resources, loaded AP spans and recipes, cleaned its owned name backups and reached `COMPLETE`. Running CP memory was not directly dumped.

This trial also exposed and fixed unstable HASP-based identity, busy/no-card service acquisition and unrelated runtime-field false failures. Three read-only sessions confirmed a stable normal USB serial hash and a changing runtime field. Installation now compares relevant writable AP settings and four protected CP units while keeping complete private snapshots. No unrelated runtime values are written back.

The owner then requested Astia in slot 4 specifically through the packaged `v2.1-preview.2` file. The exact release `lut.py` (SHA-256 `8fd89b52522aea75f05677160c9903803815984b490d4cd16c6d291899926b1a`) completed `import --write`: conversion, two fresh 73-file backups, preflight, Astia title/table installation, full readbacks and reload preparation. Only slot-4 table/checksum changed in programs; other five tables/titles and AP stayed intact. The owner confirmed normal preview/photos and retained original looks after cold boot. The same packaged file verified the reload and reached `COMPLETE`.

Current checks: 82 LUT tests, 8 FL23 tests and 37 host tests passed; the final USB identity subset was rerun after removing the redundant HASP query. These are two updates of an existing six-look installation on one Windows camera; stock first-install, physical Mac USB and physical restoration remain untested. The owner approved the experimental pre-release after physical acceptance, then approved merging the LUT work into main on October 19, 2026.
