# Changelog

[Home](../../README.md) · [简体中文](../zh-CN/changelog.md)

## Unreleased — restore native LUT upload conditions

- New builds and desktop stock/FL23 installs retain Sony's original CP instruction at `0x13553a`, instead of entering the v4 forced-repeat compensation. Normal uploads, native conditions, tables, photo support and FL2/FL3 remain. Dormant retry stubs remain only for historical layout compatibility.
- Reimporting a custom slot migrates a recognized old entry to the native instruction within the same readback/inverse transaction. Replanning an already-native entry adds no gate write. Unknown instructions, native continuation or old trampoline conflicts stop. Complete-code fingerprints normalize only these two exact reviewed entries; other code remains covered by the existing checks.
- Post-reload verification of old slot jobs accepts this validated one-way entry migration without changing their records or hashes. A fresh selected-slot restore preserves the current native entry. Pre-write checks, immediate readback and raw restoration do not use this exception. The legacy `prepare-preview-retry` command keeps its arguments, describes native upload conditions and reports bytes from actual windows.
- On one 2.01 A7C II using macOS, an isolated four-byte CP change removed the moving band in NC S35 4K60 recording; photos/playback and immediate ST↔NC preview switching worked. Samples decoded from the exported videos support this observation. NC S35 4K30 also reproduced before the change, but has not been retested afterward. This PR's integrated installation paths are offline-tested only, not physically accepted as a package.
- Refs #12 and #13 describe high-refresh EVF artifacts, without establishing the same cause as the recorded-video band. Native gating can expose the dropped-submission behavior the old compensation targeted; broader preview, EVF and recording regression is still needed. No universal stability or hardware timing root cause is claimed. The original stopped check remains preserved because 26 historical AP setting differences across physical testing are not fully explained.
- Added optional native-instruction regressions using private firmware with synthetic RAM/MMIO. All six slots switch correctly with a controller/consumer pair per cycle; an unchanged slot uploads once in ten cycles when the native repeat bit is clear, and ten times when it is set. Four synthetic hardware destinations, native looks and snapshot/direct paths are covered. Separate characterization cases reproduce stale hardware tables when a second controller call precedes consumption, or consumption returns without a destination/copy buffer. These interleavings are not captured camera schedules. No acknowledgment hook is installed: clearing the shared dirty byte after hardware upload has not been shown to preserve other consumers or concurrent updates. Candidate changes remain on a feature branch; no camera write or package update was performed for these tests.
- Added an opt-in four-byte A/B desktop trial (`A7C2_BUILD_PREVIEW_GATE_TRIAL=1` when packaging). Its visible controls restore the native upload entry, restore the exact historical repeat entry, and verify the saved trial after a cold reload. Both changes use fresh direct transactions and complete program readback without changing look tables, names, recipes or other features. Returning to the historical entry also validates both complete trampolines. A simulated camera covers the exact inverse, idempotency, unchanged settings and unknown-write stop; optional native replay covers switching and upload counts. The trial is intended first for high-refresh EVF comparison, not accepted as a fix for every reported line. Cold-boot identity and AP loaded spans do not directly verify CP RAM or frame timing; see the first owner acceptance below, with broader bodies and modes still pending.
- Owner acceptance on 2026-10-23: after applying the Windows EVF test-1 candidate (`b418d75`), the owner reported that the high-refresh EVF line disappeared and look switching, shooting and playback were normal. Using the same candidate without another write, the owner also confirmed no lines in either S35 live view or recorded-video playback under the previously affected settings. The local transaction reached `COMPLETE` after reload verification and owner confirmation; its recorded program plan contains one four-byte CP window at `0x13553a`, starting from the historical forced entry, and records complete program readback. This supports the native gate change for both reported line symptoms on this body. It does not establish a universal timing root cause, direct CP RAM verification or all-mode stability; broader camera coverage remains pending, and this S35 follow-up did not separately record codec or frame rate. No additional firmware write or release update accompanied this acceptance record.

## 3.0.3 — USB recovery and sound workflow fixes — 2026-10-23

- All desktop sound controls now work from the current selection/body: volume up/down/reset and conversion remain host-only; On/Off use fresh switch transactions; Restore original sound rebuilds only the supported AP sound-loader inverse from current bytes, preserves the switch and looks, and removes the boot call before its reader prerequisites. It no longer searches completed installation records or sends the user to full factory recovery. Sound verification reads currently loaded sound code/resources without a saved installation job. Optional listening/recovery statements can be recorded without an audition job. Stale staging is handled by the same current-request cleanup used by Save/Audition; no old pending task is an eligibility gate.
- Sound Save/Audition now replace the current selection without old-task, audition-report, recovery-confirmation or boot-ID prerequisites. Save ignores the old RAM audition lease; Audition archives/replaces that fixed temporary marker and registers the current bytes without releasing stale CP handles. Stale sound staging files are archived and cleared from the current namespace; actual execution-entry occupancy and process locking still prevent concurrent execution. The old reconnect-proof gate and its popup were removed from these actions.
- Limit the restored one-second end-packet read to direct CP unit READ40 requests, before a subsequent WRITE41. File and settings-snapshot reads retain the v2 no-eager-read path that completed all 72 reads in 9.75 s on the affected Windows camera. Nonempty CP lookahead is buffered. The captured v2 metadata trace also replays against this scoped implementation: 143 requests and 8,520 USB reads with matching lengths/order; payload contents were synthetic because raw camera bytes were not exported.
- The owner confirmed factory recovery works with cp-restore.2; its local transaction reached LOADED after the fresh-boot check. This is one-body physical evidence for recovery. The experimental OUT-fragmentation change remains withdrawn. The recipient has not yet physically tested this scoped revision.
- Regressed the reported Arabic-horizontal and Croatian-vertical resource sizes (161,360 and 119,160 bytes), including the 132-byte first extension and subsequent renaming, against the real ARM64 worker with synthetic contents. All output bytes matched the host planner. This does not establish filesystem corruption or repair pre-existing damage; the submitted report contains sizes and a replacement result, without the failed files for byte comparison.

### Earlier fixes in this release

Fixes important bugs: custom looks applied with the wrong base, extra shutter sounds on mechanical capture, USB read errors, and sound or restore actions blocked by old task records. Everyone should update.

- Restore original sound no longer stops on a latest installation record that stopped part-way: it uses the newest completed installation of the workspace (the restore plans its inverse from current camera bytes) and archives the stopped record unchanged. Without any usable record it says so in Chinese and points to Restore factory functions, which returns every sound program window to stock from current bytes. When a factory restore finishes its writes, the old sound workspace is retired (files kept) so later sound actions start fresh.
- Old sound task records never block a new sound button. Save, Audition and On re-read the connected body for the current selection; Off, Restore original sound and Verify archive an unresolved earlier operation and keep using the recorded switch/installation; Off adopts the current switch state when its record stopped part-way. Listening confirmations only archive the old record. Every camera action still reconciles only accounted sound files and stops, with power-cycle guidance, on unaccounted camera workers; nothing is replayed.
- A read-only USB session whose channel failed (for example "Wrong senser sequence" while reading names) now returns the camera from service mode `0336` with a fresh start/stop, so a battery pull is no longer needed. Sessions that sent any write (temporary files, CP/AP writes, settings save) and recovery sessions never do this. The log also names the camera file that was being read when the channel failed.
- Sound candidate: replace the shared mechanical/electronic capture-sound routing with a per-capture electronic-flag gate. Mechanical and electronic-front-curtain selector paths choose the native silent mode; ordinary electronic captures keep Sony's counter/skip/defer policy. One-click installation automatically repairs an already-enabled legacy patch without enabling a previously off feature. Save/overwrite folds the selector upgrade into its existing program-write transaction, including an unchanged audio payload with an existing boot hook; no separate On/restore step or sound-page UI change is needed. The desktop Off switch keeps mechanical playback muted while custom audio remains installed. Factory recovery includes the exact stock inverse. Windows/macOS share the implementation. Native-fragment and installer fault tests are offline evidence; physical playback/boot acceptance is pending, and no package has been replaced.
- Shared desktop USB transport: receive the payload length declared by each Senser header, consuming zero-length USB transfers during normal reads instead of issuing an extra read after every aligned chunk. This avoids swallowing a final end-packet timeout or discarding nonempty data as a terminator. Keep the existing overall deadline, reject short/mismatched headers with expected/actual fields, stop the channel after an exchange fails, and reject short command writes without replay. Recovery, looks and sound use this same Windows/macOS transport; the separate legacy CLI transport is unchanged. Offline regression and captured-length replay pass. The affected Windows camera completed the v2 read-only retest: all 72 reads in 9.75 seconds, without sequence mismatches. This is read-only evidence; physical write behavior remains unverified.
- Sound Save and Audition now start a fresh replacement of the current selection, archive stale host task pointers, and read the current body rather than reuse old enable evidence. One request shares one USB session. Completed, owned sound reports and lease markers are reconciled without replaying old workers; unaccounted camera workers get detailed cold-reconnect guidance followed by retrying the same button. No restore-original or listening-confirmation prerequisite was added. Original jobs and backups remain available.
- Persistent audio publication can replace captured stale temporary files and repair files-only interrupted installs. The inactive audio is read back before publishing its CSV; an already-installed boot hook stays unchanged for a resource replacement. Sound planning uses fixed byte windows without executing Unicorn/JIT, addressing the 3.0.0 macOS arm64 crash in `libunicorn.2.dylib` supplied in the October 23 sound-crash bundle. Developer emulation remains separate. Targeted offline regressions cover these changes; physical Mac/camera acceptance is still required.
- Sound: an unresolved earlier sound operation is now explained in Chinese, naming the operation, and sound diagnostics bundles include a summary of the sound workspace (pending operation, recent history, job phase, event names and file names; no audio or camera buffers).
- The old-backup section's verify button is now "Check loaded state after an old-backup restore". Clicked without an old-backup restore record (for example after a firmware-file restore), it offers the factory verification instead of failing with a raw "No such file" error; the worker also reports this case in plain words.

- Fix the post-sync preservation error reported in diagnostic (72): a selected base's associated 13-byte setting-attribute array can be updated by Sony's native setter too. Accept only changed elements equal to that base's selected target; unrelated properties, other bases and calibration remain checked. Apply the same rule to the inner native-sync check and the final settings readback.
- Continue completed-program installations stopped by this old array check in a fresh settings-only transaction. Require the existing successful program/name readback and native cleanup records, then confirm current programs and names still match the original plan. Only settings and reload preparation can run; this path cannot write program or name resources. Diagnostics retain public look values and targets while excluding firmware, serials and calibration.
- Fix ST resets that changed the backup settings while the running AP model still held BW or another old base. Direct LUT installation, selected-slot reset and factory recovery now synchronize selected bases through the native menu's locking, backing-value and notification sequence before completing setting readback. LUT programs are not written if synchronization fails. Unselected bases and the current selection are preserved; Windows and macOS share this backend.
- On the owner's C2, slot 4 reproduced backup ST / live BW. Both the original menu setter and the integrated worker restored the ST icon and color preview without rebooting or writing firmware programs; the owner confirmed both. Repeated application made no further model change. Offline coverage includes all 63 nonempty combinations of six custom slots and restoration/failure paths; physical coverage remains one body and slot 4.

## 3.0.2 — bug-fix release — 2026-10-22

Fixes software bugs reported after 3.0.1. If 3.0.1 works for you, you don't need to update.

- One-click factory restore now first removes name backups that earlier project jobs left in `/usr/share/app` (`.a7c2-lut-<16 hex>-<resource>.original/.stage` and `.a7c2-checkpoint-...`). Unfinished jobs of older versions could leave whole sets of 68 resource copies, more than 60 MB on one field camera, so name writes and restores failed with ENOSPC. A separate mode-5 build of the names worker lists the folder, matches only exact project names (never this restore's own prefix, never non-regular files) and removes them before the name preflight; the normal restore build rejects that mode. Other tools' files are kept. Emulated only; actual camera cleanup awaits confirmation on an affected body.
- A lone report left by the read-only camera probe (`a7c2.probe.result`) no longer blocks every later job with "Existing temporary state needs recovery". It is recorded and removed only when no other project worker file or preload exists. A camera still in service mode (`0336`) now gets a Chinese message asking for a battery-out power cycle.
- Fix the Windows plugin installation failure in report (49): reuse an identical complete ExifTool payload, including companion files; stage changed payloads at a new path instead of overwriting an executable that may be running or read-only. Plugin-only failures resume on the computer without repeating camera work, including the older `NEEDS_REVIEW` record once its saved loaded-state proof is present.
- Save and read back selected LUT slots as ST in RAM and persistent settings before their first program write, for single-slot and combined installs. Leave unselected slots unchanged; enable FL23 bindings and vertical settings at their existing final stage. A failed ST save stops before LUT program writes.
- Factory restore now saves the six custom bases and current Creative Look selection as ST before removing program support. Restore AP before CP. Previously a name restoration failure after program writes could leave saved FL2/FL3 recipes on stock programs; offline fault injection reproduces that state. Fresh, name-only and general continuation paths use the same early AP save, leaving CP calibration and color units for their existing restoration step. Actual post-restore camera behavior still needs affected-body confirmation.
- Improve post-reload mismatch diagnostics after report (46): record the program name, expected/actual lengths and first differing offset, and distinguish a target that already differs from the captured bytes from a later inconsistent read. Reuse existing reads; export no firmware or calibration bytes. The 3.0.0 report shows an earlier successful write/readback and a `LOADED` child, but lacks offsets, so its cause cannot be established from that bundle alone.
- Fix enabling/re-enabling FL23 after native custom looks were installed: update the active relocated gamma table as well as the original table. Preserve all six custom LUTs, native slot parameters and body calibration. Re-enabling also repairs the stale copied table left by earlier versions. This shared planner serves Windows and macOS.
- Audit merged PRs #5 and #6: their color records, still/movie gamma curves and routing helper are used by the GUI and included in the published Windows 3.0.1 package. The missed integration was the second table used by native custom looks. Offline reproduction and regression tests do not establish physical output on the affected body.
- Exercise the installed AP converter and CP gamma selectors/constructors in offline instruction emulation, and compile the actual write workers. Normal and custom-slot FL23 bases both map to CP modes 19/20 with bindings 10/11. The separate report that only the custom-slot entry works still needs the affected body's binding/reload evidence. Unicorn on Windows prints handled native exception diagnostics during the emulator tests even though the assertions pass and the process exits successfully.

## 3.0.1 — bug-fix release — 2026-10-22

Fixes software bugs reported by users after 3.0.0. If 3.0.0 works for you, you don't need to update.

- One-click factory restore no longer depends on the state of old tasks. Old records are evidence only: unreadable records, records without a body identity, or records from several bodies are kept and skipped. The restore then re-plans from the connected camera's current bytes and never stops. A finished restore is verified first. If the camera changed since (e.g. features were installed again), it re-plans instead of failing verification on every click. If another body is connected than the unfinished record names, the mismatch is caught from the USB serial before authentication and the restore re-plans for that body. A restore clicked before the cold reload stops without writing and says to power-cycle.
- Out-of-space name restoration is a known multi-pass case. Each replaced name file stays allocated while the running camera maps it, so a body with little free `/usr` space may stop part-way (e.g. 37/68). The message now gives the progress. After a full power-cycle, clicking restore again continues with the remaining files from current bytes.
- Shutter sound: a failed conversion now shows the backend's own reason instead of a generic "see log" error. A silent selection (common at the start of a file) is explained with its start and length. Audition checks for a converted clip before asking for the Mac password or opening USB. An audition that stopped before the native worker releases its workspace lock. The default clip length is now 0.5 s instead of 0.15 s, so a clip taken from the start of a file is less likely to be silent.
- One-click install continues after a USB error that follows completed names. In a field case all 68 names were committed and cleaned up, then "Wrong senser sequence" came before the first program stage, and every retry stopped with "Unknown operation after name commit". It now re-verifies every name and the original program windows, then installs the programs; anything that ran after the names still stops.
- Windows: the first one-click install on a computer suggests preparing drivers on the connection page first. Driver or connection failures point to the manual Zadig steps, which the READMEs now describe in full for both USB identities. The connection page has an "Install with Zadig" button beside the automatic driver install that shows these steps and opens the Zadig download page.
- macOS: SciPy 1.16 for the new dynamic loader; lenient USB-only `ioreg` parsing.
- Jobs resumed from earlier previews may rely on their service-serial body binding.
- READMEs: supported-cameras section with related projects for other models, manual Zadig driver install for both USB identities, a USB 2.0 hint when service mode never appears, and the original A7C listed as unsupported.

## 3.0.0 — first desktop release — 2026-10-22

- Integrated the portrait .5 work: Fn and submenu frames, the four Creative Look gauge backgrounds now drawn horizontally, and the withdrawal of the .4 shared-panel change (fresh plans keep Sony's original options; existing .4 installs restore the original 20 bytes). The owner confirmed the landscape UI is back to normal. Known: the portrait Creative Look selection border is still thick and the orange gauge pointer orientation is not yet corrected.
- Windows driver detection reads present Sony USB devices through SetupAPI instead of PowerShell; a failed query is no longer reported as a missing camera.
- USB stability check: the clock starts after the service connection is ready, reaching the round cap before the minimum duration is reported as incomplete rather than passed, and a slow read only fails below 2 MB/s (USB 1.1, hub or poor cable) instead of after a fixed 20 s.
- The publication check binds the desktop runtime's native workers to their manifest and to the identical published FL23 workers.
- This release is versioned 3.0: the first release built around a proper desktop interface.
- Rewrote both READMEs as a step-by-step user guide: install drivers first; on driver errors uninstall and reinstall; restore factory functions first if the camera used any earlier version; recommended read-only USB stability check before writing. Documented that both packages ship the 15 paired DCP/A7Look files.
- Restyled the desktop interface in a light blue-and-white theme: white pages, a light blue-gray sidebar, blue primary buttons and check boxes, and restyled inputs, scroll bars and a thin progress line. Colors and states only; page layout, sizes and spacing are unchanged. Styles now live in `src/desktopapp/theme.py`.
- Strengthened the read-only USB stability check: it now re-reads both program files (`/usr/lib/appFw.so`, `/cp/cpapp-b.bin`) for at least 2 minutes and 5 rounds in one service session, compares every round byte for byte with the first, and fails on any read error, mismatch, truncation or a single read longer than 20 s. Previously it read one ~10 MB image three times (about 1.5 s).
- Added acknowledgements and an optional sponsor section (WeChat Pay, Alipay, USDT on BEP20) to both READMEs; the QR codes are cropped without names.
- Reduced the documentation to the READMEs, this changelog, [LUT formats](lut-formats.md), [notices](notices.md) and one [development guide](development.md) for maintainers and AI agents. Merged `src/looks/AGENTS.md` into the root `AGENTS.md`. Per-feature guides, technical notes, research notes and legacy CLI guides were removed; they remain in git history (last present in commit `05f3cd2`).

## Desktop preview.10.25-portrait.1 — portrait frame manual test — 2026-10-22

- Combine portrait enable/disable and four Fn/submenu frame corrections into two repeatable operations. Disable saves OFF and turns the running display OFF before restoring references and removing aliases; no intermediate reboot or additional button.
- Append 15,676 bytes across two existing image banks, including recovery records, instead of copying full banks. Edit 15 portrait-only data references; retain original landscape images and executable code. Three shared gauge images remain unchanged.
- Keep byte readback and resumable current-byte planning, without a separate native image-size query. Retain any still-mapped appended tail during removal. Offline tests and native compilation pass; actual new-image recognition, placement and camera navigation await manual acceptance.

## Desktop preview.10.24 — shared service fixes and backend interfaces — 2026-10-22

- Integrate Claude's preserved service cooldown/bounce retry and senser end-packet fixes from `b651a6c` and `38a9195`. Apply the same transport to Windows and macOS: 30-second re-entry cooldown, 20-second service discovery, up to three attempts when service never appeared and MSC returned, and a one-second optional chunk-end wait. Authentication, payload-read and non-timeout errors remain failures; no firmware write is replayed.
- Prepare the Windows service driver after its USB identity is observed. If 0336 appeared but its interface cannot open, report that interface problem rather than authenticating again. Retain late-empty-packet rejection by the next response parser.
- Extract the shared action catalog and look/sound adapters from the worker, retaining existing action names, arguments, job states and user data paths. Document the backend contract for a later frontend replacement. Frontend appearance and README rewriting are separate work.
- Both host packages use this same source and the accepted 15-pair profile library. Packaging checks are separate from physical camera acceptance.

## Desktop preview.10.23 — paired profile library and source layout — 2026-10-22

- Fit all 18 supplied profiles against owner-authorized Lightroom references using 12 starts and 200 evaluations per solve on aep72, with additional native-first/zero/robust fits for three difficult monochrome looks. Include the 11 Fujifilm and 4 Ricoh color DCP/A7Look pairs. Exclude all three monochrome pairs after they fail the independent MAE <=3/255 and P95 <=12/255 inclusion criteria. Keep matching filename stems and synchronize the six defaults with the paired library.
- Make Windows packaging and exported native-build inputs carry the complete paired library; reject missing or incorrectly matched pairs at build time. Keep all original DCP bytes unchanged and exclude local diagnostic files.
- Additional owner-authorized Lightroom reference rendering and aep72 numerical fitting prepare distribution assets only. End-user conversion and camera operations remain independent of Lightroom.
- Move shared sound runtime into `src/shutter_sound/` and its camera workers into `native/`; keep tests and trace tools in `dev/shutter_sound/`. Group desktop OS adapters under `desktopapp/platforms/`, preserving exact module-object compatibility for old imports. Document shared feature engines and host differences in `docs/en/code-map.md`.

## Desktop preview.10.22 — offline conversion iteration stop — 2026-10-22

- Fix DCP/CUBE conversion aborting when the bounded linear initializer reaches 100 iterations. Retain its finite candidate for subsequent optimization, record the initializer status and iteration count, and preserve real numerical errors.
- Keep the better seed if table-only refinement worsens the fitting objective. Include initialization diagnostics in saved optimizer reports. Iteration budgets control computation; they do not limit the number of files or slots.
- Retain preview.10.21 sound-volume controls and shared portrait-image aliases. No portrait separator rework, full portrait-bank copies, or experimental resource compression.
- Reproduce the exact previous failure using the owner's GR III Hard Monotone DCP. The default three-pass conversion now completes with final optimizer convergence; a separate fresh conversion through the packaged Windows EXE also completes with a reduced fitting budget and records its nonconvergence. Nineteen focused tests and seven packaged startup pages pass. Numerical prediction is not physical color validation.

## Desktop preview.10.21 — Windows test package — 2026-10-21

- Add offline sound volume controls: decrease/increase by 3 dB and reset to the converted volume. Always re-encode from the unchanged selected PCM, retaining matched native audio and preview. Limit peak amplitude to avoid clipping; adjustment does not require USB, a backup, or completion of an older camera task.
- Retain the integrated driver preparation, built-in recovery, FL23, mixed selected-slot A7Look writes/resets, standalone DCP/CUBE conversion, optional Lightroom plugin, repeatable shutter-sound actions, and optional read-only USB stability sample.
- Vertical Display retains the earlier shared-image aliases and persistent switch. Exclude the Fn/submenu separator rework, full portrait-bank copies and experimental resource compression from this package.
- Validation is offline and includes the packaged executable; no physical camera acceptance is implied.

## Desktop preview.10.20 — Mac Terminal USB test build — 2026-10-21

- Integrate the reviewed Terminal sudo launcher: explicit camera operations open Terminal for the user's password, while the GUI stays unprivileged. Preserve the shared installation/recovery engines and user data paths; retain the actual worker outcome.
- Enable libusb debug logging in the administrator process and include it in existing authorization stderr/support logs. Detect a worker that exits without a terminal exit marker instead of waiting forever. Keep shell quoting and native no-USB authorization checks.
- This test branch excludes the portrait Fn/submenu line-bank rework. Vertical Display uses the earlier resource aliases; it does not create full portrait-bank copies. Resource compression and audio-volume controls are not part of this build.
- A successful recipient probe motivates the authorization change but does not validate the complete packaged app. Native CI and physical Mac camera results are reported separately. No camera operation is performed while building.

## Desktop preview.10.19 — portrait resource I/O correction — 2026-10-21

- Fix the portrait-copy worker treating short reads/writes and every negative syscall return as generic EIO (-5). Complete partial transfers with updated offsets, retry bounded EINTR results, and retain original negative error codes. The old user's -5 report does not establish its underlying errno.
- Add compatible version-2 portrait reports with the resource group, operation, progress and capacity figures. Check free space before bulk copying, retaining ENOSPC (-28), and leave old active resources intact if staging fails. No firmware hashes or camera writes are needed to inspect the report.
- Support exports now include the actual persistent vertical child transaction, which was previously missing when the request pointed to the parent folder. Preserve precise native errors and progress without including programs or calibration.
- Fault simulations cover short/interrupted reads and writes, capacity errors, full-disk writes, atomic rename rollback, legacy aliases and corrected resources. No physical camera I/O was performed for this correction. Actual recipient re-test remains necessary.

## Desktop preview.10.18 — repeatable actions and optional USB sample — 2026-10-21

- Keep the button named **Enable Vertical Display** while retaining in-place upgrades. FL23 and selected looks continue to re-plan from fresh state; identical content does not need another write.
- Native sound ON/OFF now use fresh byte-based direct plans, without requiring a previous sound job or restoration. Replacing a saved custom sound keeps the existing boot hook and writes a complete inactive audio file before atomically publishing its CSV reference. Same audio is not rewritten. No manual original-sound recovery is required. Final cold reload remains necessary for a changed loaded sound.
- Add **Check USB connection stability (read-only)** to the connection page: three bulk reads of a fixed graphic bank, byte comparison without hashes, first-error stop, detailed round/error report included in support ZIPs. This optional sample never writes firmware/settings or executes a native worker, and is not a guarantee against later disconnects or a new installation gate.
- Strengthen offline tests and the packaged self-test to forbid physical USB enumeration unless explicitly replaced with a simulated camera. Native sound-update tests cover alternating slots and failures before/after CSV publication. Physical acceptance of the new overwrite workflow and portrait rendering remains outstanding.

## Desktop preview.10.17 — portrait Fn / submenu line geometry — 2026-10-21

- Replace the landscape fallback for seven portrait-only Fn grid, submenu frame and scale assets. Fn rows use the native 480-pixel portrait geometry; submenu dividers use their native orientation and dimensions. The corresponding A7C II landscape rasters were compared equal to the A1 II reference; generated portrait visible pixels match its original portrait geometry offline.
- Derive two corrected portrait banks from the connected body's original graphics, retaining every unrelated record/index/payload. Do not modify original landscape banks, application code, color tables or recipes. The third bank retains its original alias.
- Existing installations can use **Enable Vertical Display** without disabling first. Files are completely verified before atomic replacement; OFF and factory recovery also recognize/remove these exact corrected files. Unknown resource files are preserved. Added native syscall tests cover fresh install, legacy upgrade, repeat install, removal and rollback after space/sync/rename failures.
- Offline geometry, native transactions and host workflow tests passed. No camera I/O was performed; actual portrait menus, both grip directions and loaded rendering remain manual acceptance checks.

## Desktop preview.10.16 — shared built-in recovery — 2026-10-21

- Fix diagnostic (25): Save Custom Sound creates its workspace and automatically prepares/adopts electronic-sound support before saving the converted clip. No manual On/Attach prerequisite. With no converted clip it requests conversion without camera I/O; a missing dependency stops before enabling support. All writes share the final cold-reload instructions.
- Change the common Windows/Mac recovery backend, beyond preview.10.15's retry instructions: privately archive inert project worker/request/report files, clear their shared namespace, then capture current camera programs/settings/names and build a new reset against the bundled original reference. Missing or incomplete old reports do not require an old LUT job. Never execute old work files.
- Failed GUI restores now use a fresh built-in reset plan instead of requiring the old worker binaries, source reference, ancestor directories or attempted-write windows. Saved body identity may reconnect an existing service session. Already-written recovery still requires a final cold-start verification.
- Retain an active-loader/concurrent-operation stop and exact fresh byte preflight/readback. Archive failures never delete camera work files. Preserve calibration and all settings outside the declared project reset scope; do not add firmware hash gates or full body backups.
- Focused offline recovery, dispatch and GUI cases passed, including both OS paths and partial/missing/stale reports. Recipient camera recovery remains unverified.

## Desktop preview.10.15 — recovery pre-write retry guidance — 2026-10-21

- Handle diagnostic (21)'s shared temporary-name conflict during a fresh factory reset. When all workers in this attempt were read-only and completed cleanup, show explicit cold-restart instructions and a "retry recovery; not written yet" button instead of an unexplained exception or a completion message.
- Retry creates a fresh plan from the current camera state without requiring an older LUT job. Keep the failed record; do not overwrite or delete unknown camera files. Started writes, unfinished workers, active plugins and resumed transactions retain their distinct recovery handling.
- Add this existing-state startup case to native package checks. Offline UI/recovery cases passed; clearing the recipient camera's temporary state by a cold restart remains a physical test.

## Desktop preview.10.14 — Mac / standalone DCP integration — 2026-10-21

- Integrate the reviewed Mac connection sequence and the existing-record startup fix with standalone offline DCP conversion. Windows and Mac retain the same camera install/recovery engines; Mac-specific changes cover authorization and USB ownership only.
- Correct whole-disk identity handling when diskutil omits ParentWholeDisk. Preserve stable no-card connections instead of requiring SD media before service access. Only camera-associated disks are unmounted, without forcing.
- Add DCP/CUBE contracts to native CI and real reduced-budget Astia fitting to packaged offline checks, alongside the six bundled source-profile evaluations. These checks do not establish physical USB recovery or photo color fidelity.
- The separate Windows diagnostic (20) interrupted-write continuation remains unresolved and is not claimed fixed by this integration.

## Desktop preview.10.12 — standalone DCP conversion — 2026-10-21

- DCP conversion evaluates LookTable / tone locally and fits the supported native stages. No Lightroom, rendering plugin, Node runtime, renderer configuration or network is required. The separate LrC profile-plugin installer remains optional.
- Keep original source-profile bytes, attribution and approximate-mapping scope in A7Look. Do not copy donor sensor matrices or HueSat calibration. Unsupported inputs fail explicitly; native output still uses the existing writer.
- All 18 public source DCPs passed local parsing/target-color evaluation. Real Astia completed the full fitting/output flow in source and in the actual Windows EXE, using a reduced verification budget; the output passed writer-format validation. This verifies local conversion, not camera preview/photo color accuracy. DCP/CUBE and integration cases passed; GUI smoke produced all seven pages.
- Implemented on feature/dcp-renderer-setup, separate from ongoing Mac USB fixes. Test ZIP: A7C2Tools-Windows-x64-Offline-DCP.zip. No camera I/O.


## Desktop preview.10.10 — 2026-10-21

- Fix macOS USB capture failing at `detach_kernel_driver(0)` with access denied. Explicit camera actions request macOS administrator authorization before backend execution; the normal-user GUI remains unprivileged. Passwords are handled only by the system dialog.
- Retain exactly the existing Windows/desktop restoration backend and workflow. The Mac adapter changes only authorization/USB host access, preserves the login user's data paths and returns generated files to that account. It does not adopt a different reference-repository firmware/restoration implementation.
- A connection failure with no identity/native journal now says restoration has not started, rather than presenting an unfinished write. Keep actual interrupted-write evidence and recovery verification intact.
- 40 focused offline cases passed. Native Apple Silicon CI passed AppleScript compilation and actual packaged privileged-worker execution through CI sudo: euid 0, original user HOME/data paths and returned ownership were verified without USB. Packaged offline/GUI, ExifTool, signature and DMG checks also passed. This does not validate the recipient's interactive authorization or physical camera connection; those remain recipient tests.


## Desktop preview.10.9 — 2026-10-21

- Cancel Intel macOS packaging at the owner’s request. Keep Windows x64 and macOS Apple Silicon ARM64 only; remove the Intel CI target and dependency override.

- Fix one-click installation stopping when the optional Lightroom plugin is selected but the caller has no valid ExifTool path. Use bundled or installed ExifTool automatically; otherwise download the official distribution before camera work, retaining complete connection errors.
- Bundle ExifTool 13.59 and its complete Windows companion files / macOS Perl modules and original licenses. The separate plugin button uses the same automatic preparation, with no hidden file-selection prerequisite. Missing paths saved on another computer fall back to the local helper.
- 50 focused offline tests passed for helper resolution/extraction, one-click setup and plugin integration. The Windows EXE installed the plugin into an isolated Adobe directory without an ExifTool argument, ran its real bundled helper and read JPEG metadata successfully, without camera I/O. Apple Silicon DMG passed native packaged offline/GUI, ExifTool, signature and container checks and was downloaded locally; physical Mac camera USB remains untested.


## Desktop preview.10.8 — 2026-10-21

- Rename Home continuation to “继续安装” (Continue installation). The post-restart dialog and persistent status explicitly tell users to reconnect USB and click it. Standalone look instructions no longer direct users to a removed verification button.
- Verified factory recovery clears active one-click / FL23 / look continuation pointers and the look editor, restoring a fresh Home state. Keep diagnostic evidence and pending recovery until its completion check succeeds.
- Add visible LUT guidance in the compiler/import page plus a bilingual format guide: direct GUI CUBE input is Sony ST / sRGB and output is sRGB, not S-Log3. Explain Log bridging, 3D CUBE structure, DCP rendering and approximation limits.
- Add separate ARM64 / Intel native Mac APP/DMG builds and CI asset import/export. Exclude Windows helpers, use fresh DMG staging and verify signatures/container structure. Targeted Mac storage unmount and interface capture draw on MDHan's adapter; preserve service-first admission.
- 62 focused offline cases passed before the final documentation edits. Windows output path stays unchanged. Native Mac build/DMG and physical USB validation have not run on this Windows host. No camera I/O in this update; formal full regression remains deferred.


## Desktop preview.10.7 — 2026-10-21

- Simplify workflow: no historical recovery-verification check at one-click startup. Custom looks perform checks/write/full readback through Apply, without a separate verification button or a post-write editor lock. Sound on/off and repeated completed auditions no longer require a recovery record. One-click installation retains one final combined check after all selected camera changes and restart; recovery retains its own mandatory completion check.
- After these workflow changes, use focused checks only (50 relevant cases); defer the next full regression to formal release. The earlier 334/20 result below predates the last workflow simplification.

- Fix direct upgrade from the project's published v2-era FL23 helper/curve table. Reproduce its `cpapp-b.bin + 0x138832` conflict using the original 2.01 programs and published patch list; migrate both reviewed old windows while preserving unrelated code and LUTs.
- Continue can re-plan an accounted read-only failure in a fresh child without reinstalling drivers. Preserve failed jobs and unknown native outcomes. Diagnostic exports now include original child-stage/error summaries without program or calibration snapshots.
- Show a startup notice explaining the camera's “Check the connected device” message during tool connection/driver switching, and distinguish it from actual tool errors.
- Recovery remains at 70% with “not complete; restart and verify” until loaded-state verification passes. Update the main button and restart dialog accordingly; keep physical acceptance separate.
- 334 tests passed / 20 skipped. Full offline one-click plans passed for stock, published old FL23 and old FL23 with LUTs; recovery/startup dialogs were rendered and inspected. No camera operations were performed for this update. The external reports lack actual source bytes/child state, so their exact original states still require recipient validation.

## Desktop preview.10.6 — 2026-10-21

- Save converted audio directly. Audition, listening confirmation and cold-recovery records are optional; cold reload is requested after actual write/readback.
- Bundle the missing Unicorn Python package/native DLL, pin the build dependency and execute a real ARM64 instruction in frozen self-test. Resolve compiler/emulator dependencies before creating a write intent.
- Automatically retire a failed host preparation with no native invocation, preserving its evidence and starting a new job. Unknown native writes are not replayed.
- 156 related cases passed. The packaged EXE used the owner's local program backup/current payload to verify valid/missing/oversized CSV, exact inverse and compile five native workers without camera I/O. Physical persistent installation remains owner-operated validation.

## Desktop preview.10.5 — 2026-10-21

- Successful audition now opens instructions to unplug USB while keeping the camera powered, test an electronic exposure, reconnect and confirm, then cold-recover before saving.
- Missing audition/listening/recovery steps return a guided waiting state instead of a `Cold-recover` exception. Show the appropriate dialog, do not report installation complete, create a write job or accept owner checks automatically.
- 151 related regressions passed, including exactly-once dialogs after worker exit. Both dialogs were rendered and inspected. The packaged EXE handled saving from a copy of the owner's current state with no camera I/O; physical persistent installation remains owner-operated acceptance.

## Desktop preview.10.4 — 2026-10-21

- Replace an exact owned marker from a completed prior registration before audition, fixing pre-allocation `-17 / EEXIST` without manual file cleanup. Archive the marker; never release an old CP address that may be stale after reboot. Cold power-off reclaims leased temporary buffers.
- A completed report proving no allocation/transfer/registration, with native cleanup verified, allows a fresh attempt. Preserve original evidence; unknown executions and unmatched markers remain stopped.
- Registration errors expose native phase/status/call fields. 144 related regressions passed. The packaged EXE replaced the owner's old marker on camera without registering new audio or writing firmware; listening remains owner-operated acceptance.

## Desktop preview.10.3 — 2026-10-21

- Fix legacy sound jobs being routed through LUT USB-descriptor binding, producing “Legacy job has no stable USB body binding”. Sound sessions retain their original Sony service body identity for normal USB, existing service sessions and re-enumeration waiting.
- Connection regressions execute the actual sound connector with only USB/protocol boundaries replaced, reproducing the same exception before the fix. 129 related offline tests passed.
- Add integrated read-only sound `check-connection`: no native worker, audition registration, program or settings write. The packaged EXE successfully connected to the owner's camera and read its current programs; sound support was disabled. Enable/audition still require owner-operated physical testing.

## Desktop preview.10.2 — 2026-10-21

- Release the active binding of a failed sound-enable job only when its read-only checks and temporary cleanup completed without any write invocation. Retain original evidence; unknown outcomes remain blocked.
- Audition can freshly adopt already-enabled sound support without writing the permanent switch. If disabled, it specifically asks the user to enable and cold-reload first.
- Sound sessions now use USB re-enumeration waiting and body-bound attachment to an existing service endpoint between preflight and apply.
- 77 audio-related offline tests passed; the owner's old failed job passed read-only classification. No camera operations were performed; physical audition acceptance remains pending.

## Desktop preview.10.1 — 2026-10-21

- Decouple audio conversion from camera jobs. Each conversion gets a fresh offline job; unresolved enable/audition/install records no longer block conversion. No prior camera enable or backup is needed.
- Store the selected conversion separately, preserving camera transaction state. Audition/install retain their own checks and accepted-payload binding.
- Remove partial outputs after failure/cancellation, preserving source files and the previous successful candidate. Conversion errors no longer imply unknown camera writes.
- 62 audio cases passed. The packaged EXE converted the owner's selected source/parameters successfully with the old camera record and source bytes unchanged.

## Desktop preview.10 — 2026-10-21

- Replace the custom-look page with an incremental operation list. No slots are selected initially; new items default to Restore ST. Slot, action, file and optional name share one item, supporting mixed batches.
- Compose imports/resets into one plan and full readback, preserving omitted slots, calibration, FL23, sound and Vertical Display. Support legacy layouts and clear restored-slot RAW profile mappings.
- Restore/lock pending plans, retain actual returned workspaces and clear completed lists. Proven pre-write failures can be edited/retried; unknown writes are not replayed.
- Fix Home's stale new-install label after entering reload wait.
- Include the missing `wave` module. Real EXE WAV/MP3 import passed; frozen self-test now converts generated mono WAV, stereo WAV and stereo MP3.

## Desktop preview.9.2 — 2026-10-21

- Audit two full stock → import → cold verification → restore cycles. New recovery does not require a physical-photo checkbox; historical jobs are not replayed.
- Recover child completion when the parent lost its result, using fresh read-only evidence. Handle unstarted resource dispatch, ready resource checkpoints and nested program children; preserve unknown nonempty children instead of replaying writes.
- Mark an already-original, read-only-verified no-op as finished immediately. Restore missing completed-step bookkeeping after parent interruption.

## Desktop preview.9.1 — 2026-10-21

- Fix Restore being redirected to verification of an old `LOADED` recovery with an already verified read-only mount. Later feature installation then caused a program mismatch instead of starting a new restore.
- Completed device verification exits automatic continuation. Restore now creates a fresh current-state plan; awaiting reload, unverified read-only state and unknown writes still take precedence. Physical acceptance remains separate and old evidence is preserved.
- 78 related offline tests passed, plus local-only discovery against the owner's existing records. No new camera I/O.

## Desktop preview.9 — 2026-10-21

- Include the saved native Vertical Display switch in new combined FL23/look/sound plans. Install and fully read back its three resources before saving ON, then load all selected features at the final cold restart; remove the separate session-only final step.
- Verify stored, Backup-RAM and native running values plus resources after reload. Stop on mismatch instead of faking persistence with a temporary RAM enable.
- The Vertical Display page saves ON/OFF. Disable and factory recovery save OFF before turning off runtime display and removing resources. Older jobs retain their plan without silently adding new writes.
- Retain preview.8.1 completion dialogs, archived errors and local result viewing. Persistence has offline validation only; no owner-camera write/cold-restart acceptance has occurred for this new path.

## Desktop preview.8.1 — 2026-10-21

- Show a final guided-setup completion dialog with selected looks/features, unselected sound and the current-run-only Vertical Display scope. Add a local-only previous-result button on Home.
- Archive resolved errors while keeping failed child transactions and full logs. Print a short result summary; new errors remain fully reported.
- The owner manually completed the resource reload, combined program write/readback and final loaded-state check: `COMPLETE` / `LOADED`. Vertical Display reported running `ON`, saved `OFF`; sound was unselected. Physical shooting, video color and long-term stability still require acceptance.

## Desktop preview.8 — 2026-10-21

- Handle fully committed names followed by read-only remount `EBUSY / -16`: verify all names and untouched programs, prepare reload and request explicit power removal. Verify a new boot and read-only mount before remaining program writes; do not rewrite names/drivers. The program installer's read-only prerequisite stays intact.
- Distinguish name-stage pause from program completion. Wait if reload was incomplete; skip extra power removal if the mount already recovered. Verification of names alone cannot mark the program installed.
- Preserve failed jobs and remove only exact completed temporary artifacts. Missing/partial reports, changed bytes and failed rollback/cleanup remain stopped.
- Integrate main PR #6: native FL23 photo/movie curve routing and missing-USB-device handling. Synchronize desktop curve assets and support edited-byte upgrades from prior curves while preserving LUT hooks/slots, without firmware provenance hash gates.
- Live read-only checks on the owner's body verified all 68 target names/original program windows, a writable mount and image mode 2. Complete continuation and video appearance still require physical acceptance; offline passing tests are not installation evidence.

## Desktop preview.7 — 2026-10-21

- Add six-slot batch import on the normal Creative Looks page, defaulting to NC/CC/NN/Astia/GR Positive/GR Negative. Empty fields preserve slots; optional titles and individual ST reset remain.
- Look-only batches preserve FL23/sound switches, combine inputs into one transaction and finish with complete readback and one reload prompt.
- Show bindings/skipped installation for both USB identities. Retain WinUSB/libusbK/libusb0 without reinstall/elevation; reuse the fresh service scan and bound installer waiting to 180 seconds with original errors retained.
- Fix approximately 9 MB of simultaneous name staging causing `phase=3/status=-28`. Byte-based writes replace files atomically one at a time, preserve original data/index information for rollback and reserve rollback space. Native fault tests cover writes, renames and synchronization.
- Preserve errno, staging/commit counts, rollback, cleanup and read-only results. Continue can review an older zero-commit ENOSPC, remove exact completed temporary artifacts and use a new transaction; failed evidence remains intact. Unknown outcomes stay stopped.
- Offline passing results do not establish physical preview/color/stability acceptance. This update does not automatically reflash the camera.

## Desktop preview.6 — 2026-10-21

- Home setup now installs six built-in looks by default: NC, CC, NN, Astia, GR Positive Film and GR Negative Film in custom slots 1–6. No per-slot file selection is required; custom-file mode remains available.
- Save look inputs before device access and retain that plan during continuation. A missing pack stops before USB; existing jobs never silently receive new presets.
- Show a completion dialog with USB removal, access-light waiting, shutdown, battery removal for at least one minute, restart and loaded-state verification. Add detailed confirmation text and a reusable help button.
- Fix installation progress incorrectly labeled as restoration. Explain that enabling FL23 after factory recovery is a new change requiring restart; verification does not flash again.
- Move standalone FL23 loaded-state checks into collapsed optional diagnostics. After the restart and camera checks, reconnecting to the computer is not required for use.
- Standalone FL23 enable/disable finishes at 100% after writing and complete readback. Release the UI controls immediately; power removal loads the finished change and is not a pending computer-side installation step.
- All successful cold-reload paths show detailed guidance, including sound toggles/persistence/restoration, post-audition cleanup and historical recovery. Temporary audition and adoption of enabled sound do not request restart. Failed/unknown outcomes do not tell users to unplug. Rename misleading “validation only complete” progress to “pre-write checks passed.”
- No camera writes in this update; the new complete installer still needs manual physical acceptance.

## Desktop preview.5 — 2026-10-21

- Add guided home installation: driver preparation, composed FL23/selected A7Look/native-sound writes and complete readback; continue with the same button after cold reload for loaded-state checks, sound-tool adoption, optional Lightroom plugin and session-only Vertical Display. Unselected slots remain; unknown writes are not replayed.
- Vertical Display Off also cleans auxiliary resources; remove the separate alias-removal button.
- Fix duplicate title appends during verification. Finish names before program references, clean old resources after verified cold reload, and invoke the rebuilt cleanup worker.
- Separate completed name content from a busy read-only remount. Only fully verified program/name targets with no remaining edits may finish settings/reload preparation before cold-boot mount verification. Reattach a recorded body's existing service session without re-authentication.
- Fix native FL23 curve differences between installation orders; include Keystone/Capstone in desktop packaging.
- Enumerate all Sony USB identities/interfaces without installing drivers for unknown PIDs. The reported `054C:0D68` remains unidentified; this body used normal/service `0E8A`/`0336`.
- Expand individual/repeated six-slot imports, selective reset, mixed-slot preservation, interruption/mount cleanup and guided workflow tests. **The owner's factory recovery passed new-boot, complete readback, loaded-state and read-only mount verification; new one-click installation/every feature have not all passed physical shooting acceptance.** Development branch/local test bundle only.

## Desktop preview.4 — 2026-10-21

- Unify factory recovery: discover unfinished transactions, ignore later attempts stopped before writes, and verify loaded state after completed recovery.
- Re-plan remaining program windows, names, settings and reload preparation from current bytes, preserving prior evidence and skipping matching content.
- Recover a complete native report directly from the camera after host download failure. Account for execution/cleanup/read-only mount before removing exact temporary contents; delete the result last so cleanup interruption remains recoverable.
- 92 offline cases passed; 9 skipped without private fixtures. Coverage includes name ENOSPC/I/O errors, partial programs/names, settings interruption, missing results, foreign temporary files, multiple bodies, repeated clicks and missing temporary state with an unconfirmed outcome. The owner's actual saved report was parsed and simulated offline. Manual camera continuation remains pending.

## Desktop preview.3.1 — 2026-10-21

- The main factory-recovery button recognizes the selected accounted name-space failure and, after write confirmation, dispatches continuation. A later failed full attempt does not hide the original source; completed continuations are not replayed.

## Desktop preview.3 — 2026-10-21

- Fix factory-name ENOSPC from staging all 68 resources: reconstruct and atomically replace one file at a time; check capacity before program writes.
- Add explicit continuation for accounted name-space failures: validate completed program bytes and the failed report; continue names/settings/reload preparation without program replay, preserving the failed transaction.
- Compiled ARM64 offline tests cover the original failure, 68 resources, space/inode limits, write/rename/fsync faults and mapped old inodes. Manual camera acceptance remains pending. Development branch only.

## Desktop development preview — 2026-10-21

**preview.2:** direct FL23 enable/removal and custom-slot import/ST-default reset no longer require complete backups. Factory functionality restoration uses included original 2.01 project regions, preserving body calibration without old backups or a full firmware download. Former recipes are not recovered. New flows have offline validation only and await manual physical acceptance.

- Added a six-page Windows/macOS desktop front end, native packaging and complete background-job error logs.
- Integrated explicit two-stage Windows driver preparation; macOS uses libusb without Zadig.
- Added manual camera driver removal with package export and Windows native-driver rebinding; no automatic system restart.
- Fixed rejection of Zadig/libusbK INF files using `USB\%DeviceID%` references; elevated worker failures now preserve the original error.
- Replaced the desktop battery field with per-operation power confirmation; stream administrator progress, retain raw Windows output and recover the finished GUI state.
- Added same-body automatic initial-checkpoint selection alongside manual complete recovery and independent LUT slot restoration.
- Connected FL23, A7Look import/compiler/LrC plugin installation, session-only Vertical Display and custom electronic shutter sound workflows.
- Retained the unchanged-name no-op fix and restored the byte-window native installer interface needed by recovery.

Development branch only. Packaged offline checks and physical camera acceptance are separate; this is not a new formal Release. [Desktop guide](../../README.md).


## v2.2-preview.1 — updated 2026-10-20

- **Independent Recovery:** restore the selected complete checkpoint or original FL23 backup2 without the original workspace or any LUT job. The tool saves a compressed copy of the current state, restores programs, project names/settings, and fully reads back the result. Recovery instructions.
- **Separate responsibilities:** FL23 installs/verifies; LUT imports/restores individual slots; Recovery performs complete rollback. FL23's restore command and desktop button have been removed.
- **Both installation orders:** FL23 → LUT and LUT → FL23 preserve each other's changes. Verification accepts the expected later changes.
- **Smaller LUT backups:** share a compressed foundation and record the selected slot's pre-write state. Later imports retain changed data instead of repeated complete copies. Keep the shared storage directories with the jobs/backups.
- **Single-slot restoration:** restore its previous table, title and recipe, including undoing first activation, while preserving other slots and FL23. No firmware or backup-file hash admission checks; edited-byte checks and full readback remain.
- **FL23 admission:** check the camera model and user-entered firmware version 2.01, without a firmware-provenance hash whitelist. Warn about other projects' modifications; retain actual patch-position conflict checks.
- **USB connection:** authenticate directly instead of blocking on storage `02/04/01` or application-query Busy. Confirm the USB model and bind the service backup's four-byte AP serial (`0x00E70003`) using the original hex-text digest, retaining existing backups. No separate USB-fix tool is required; Windows device drivers are still required.
- **Failure explanations:** integrated LUT job diagnostics explain native-name transaction failures from saved evidence without reopening USB or blindly repeating a write.

**Validation:** offline suites passed: 131 LUT cases (35 skipped without private fixtures), 22 FL23 cases and 46 host/USB cases, including nine service-first connection/failure cases. Historical real backup data reproduces its original body binding. Separately, 7 real-file order/slot cases and 44 native-name syscall/failure cases passed. This release update did not operate a camera; the user's reported service-route installation is separate evidence. Physical complete Recovery and Mac USB remain untested. Evidence and limits.

These fixes are included in `main` and the updated v2.2-preview.1 commit/release, as authorized by the owner. Existing v2.1/v1.0 releases remain available. ZIP and single-file tools are in the [preview release](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.2-preview.1).

## v2.1

Published FL23 and the independent LUT/DCP CLI, with single-camera Windows slot-update observations, original DCP attachments and film comparisons. [Release notes](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1).

## v1.0

FL23-only tool. [Release notes](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v1.0).
