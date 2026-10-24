# Pre-capture research

Read README.md for current state and CONTROL-PATHS.txt for detailed evidence.
This directory is not a camera installer. Keep main/releases untouched when
working on the pre-capture feature branch.

Latest physical checkpoint: one explicitly approved original-default CP query
completed in phase129 (mode e1,24 bytes,392 journal records,one sync call). Exact
reply, context/free/CPU/signal restoration, same-child absence, exact owned-file
cleanup and four unchanged sources were verified; both USB sessions ended
normally. The owner confirmed ordinary viewfinder/photo/playback afterward.
That one-query authorization is consumed, not blanket permission for further
sends or patches. Physical exposure/RAW/save/cancel/menu integration is still
unfinished. Keep all retired job fences and unknown-state rules intact.

Phase130 resumes native shooting integration offline: AP event6/7 and pending
record admission, CP postprepare branches and original state sequences. Never
inject fake AP pending records to defeat the earlier empty-deque assertion.
The runtime state-pair table has246 fixed rows plus62 dynamic rows; the prefix
experiment does not admit the dynamic rows, full native initialization, physical
readout or completion. The next boundary is action application/real completion,
not another generic transport test. Current-source comparisons are FILE spans.

Phase131 traces original requested/current feedback through masked completion,
deferred task and internal events to the CAP callback. Commands3014/3032 share
event308; the32-byte event has no command/generation token and original code
clears the pending slot BEFORE posting. Never use it alone as a shot/RAW terminal
ACK or replay it after ambiguous delivery. Mask8027 waits only indices0/1/2/5;
unwatched current words can differ when the local check succeeds. This is not
physical sensor/RAW quiescence. Native CAP continuation still stops before
a05976 or a06e5e under explicit synthetic configuration/reference inputs.

Phase132 reaches original staged-slot copy/prefetch/RAW-client lookup and
descriptor consumption. Sixteen initialized descriptor positions are not16
retained photographs. Flags11/31 can copy zero-count/zero-address reply metadata;
source-copy success is not a pixel lease. Originala04fe6 invalidates local ID
and descriptor aftera13a60 without checking its return. Never complete release
from invalid local ID, a zero metadata count or that caller's return alone.
Keep native locks/waits/endpoint lookup as unexecuted boundaries; post-service
slices never supply successful native returns or qualify physical allocation.

Phase133 corrects the45dd24 label: flags2a/type5 allocate a dynamic reply queue
ID; the RAW service target is61003c, registered to callbackb1620a and received
by task256 MEMMGR_CP. Direct/worker dispatch tables differ (direct14 unsupported,
worker14 category selection/query). Never infer capability from the wrong table.
Native handle checks use10-bit slot/5-bit generation; the high marker bit is
not checked there and generation31 wraps to1 on reuse. Neither a metadata slot
nor a successful pin is a physical-pixel lease or a never-reused capture epoch.
Final-owner release clears native state before backing free; retain UNKNOWN
ownership until the qualified resource transaction and backing release finish.
Worker14 writes category-selector state and invokes a notifier. Do not present
or deploy it as a read-only capacity query; physical use needs separate review
and authorization even when only a returned configured value is wanted.

Current CP source supersedes phase113:333 changed bytes exactly reconstruct
from the existing nine-window LUT-preview repair;17 original spans and the
diagnostic constructor/callback/registration are unchanged. Preserve that
repair. Phase117 stopped before upload on source drift. Phase119 then refused
the new boot epoch, restored/exited and sent nothing. Neither is a failed CP
send to retry. Fresh metadata120-123/source reads124-127 bind the new boot;
query128 uses new paths/nonce, worker start132 and14 verified evidence entries.
Its successful physical host job is phase129; never reuse the old epoch or
restore the older preview behavior as a pre-capture prerequisite.

At each phase boundary and before device preparation, refresh origin/main
and review its shared-runtime changes. Keep main as an ancestor of this
feature branch; retain main's product files outside this research directory.
Do not push unfinished research to main. A transport fix is not a pre-capture
implementation or permission to inherit its cleanup/recovery behavior.
Record the reviewed main commit and the next native shooting-path blocker at
that checkpoint. Keep one active path toward exposure/retention/save/release;
retire duplicate active plumbing, not immutable failed-job evidence. Do not
extend host/VM scaffolding without identifying which native blocker it resolves.

At the same checkpoint, review imports and active callers for redundancy.
Consolidate repeated plumbing into support/; remove unused alternatives only
after checking source, docs and private evidence replay callers. Keep a small
compatibility export when a real replay still uses it. Refactors must preserve
original-source reports and model results, not just pass new replacement tests.

- Put shared emulator/build/source fixtures in `support/`. Do not make a new
  verifier depend on another verifier for general ELF or boundary utilities.
  Use shared original-instruction fixtures directly from support/; retain old
  exports when private evidence replay paths depend on them. Use build.py for
  ordinary component builds; keep specialized linker/LTO settings explicit.
- Boundary execution stops BEFORE original external services. Never insert a
  fake successful native call to make an audit pass. Instruction exhaustion
  without the expected boundary is a test failure.
- Use `ap_linux_aarch64.h` for Linux open flags and independently check them
  with `support/aarch64_abi.py`. Do not copy host/x86 flag literals into ARM64
  code or use those same literals as the verifier's only expected values.
- Keep explicit target FP/NEON exclusions in `support/elf.py`. Zig0.13 can
  append target features after `-mgeneral-regs-only`; that switch alone does
  not prevent vector aggregate copies. Never bypass the generated ISA check.
- Preserve source fingerprints, ownership UNKNOWN states, one-shot fences,
  inverse evidence and original/known-working backups. A source drift needs
  independent reconstruction, not a masked or relaxed hash check.
- SPECS ranges/calls in support/reference.py are FILE OFFSETS. The staged
  CP copy uses a separate +108000 fixture base. Record both coordinates and
  independently check encoded calls before qualifying named ranges. The old
  AT74 seventeen-range comparison mixed these coordinates and is invalid;
  AT78 repeats it correctly, preserving the original report. Neither admits
  whole current firmware, physical loaded addresses or RAM.
- CP parameter `00030072` half-press testing caused a crash and is retired.
  Do not recreate the removed forced-native-plan generator or retry that path.
- Current camera CP can belong to another native-photo calibration trial.
  An old pinned fixture is not a fresh camera identity. Do not restore or
  overwrite another trial as part of pre-capture diagnostics.
- The latest October23 acquisition supersedes phase81: AP and CP now differ
  from those historical sources. Structural FILE evidence identifies FL23,
  six slots and native-ST-dual-domain-v2 calibration;17 named CP FILE spans
  still match stock. This is not loaded-state or actual look-effect proof.
  Never restore phase81 or the old six-look image over this current work.
- Public files are offline source/evidence only. Keep firmware, body data,
  compiled diagnostics, private operators and deployment artifacts private.
- Device work needs current ownership of the camera. New parameter/ROM/AP or
  CP RAM patches require a concrete candidate and recovery review plus the
  owner's explicit approval. Temporary diagnostic execution must respect the
  separately reviewed scope; no replay of an unknown operation.
- Initial empty cmdline/missing child output is UNKNOWN, not exec failure or
  process exit. Observe the same fenced child; never respawn it. The physical
  file-only follow-up needed a finalized result and two terminal process samples
  before exact owned-file cleanup. That success admits no UIPC/CP operations.
  Normal clone SIGCHLD is distinct from operator-issued kill/wait/reap; the
  successful exec route (execveat or ENOSYS fallback) was not traced.
- The journaled never-sent context child has now completed on the physical
  body:20 records,6 lifecycle syscalls,3 ioctls and two absent-process samples,
  then exact owned-file cleanup. This admits no CP send or teardown after send.
  BEFORE/AFTER/final file records
  do not grant process cleanup; a failed final fsync/close can leave a success-
  looking file while the child parks. Observe process state separately. Current
  module/library FILE matches do not identify loaded kernel text or a live context.
  Never inherit phase82's file-only admission for this new ioctl-capable purpose.
- Phase109's parser distinguishes an exact successful terminal transaction from
  an exact boot-epoch refusal that sent no CP request. Only the same-child,
  terminal, two-observation proof may read pinned sources after either accepted
  terminal result; unknown/running/refusal-looking files retain the fence.
  Refusal is never reported as CP success, and the result file alone never
  grants cleanup. Offline controls cover lifecycle, parent/observer,
  operator/follow-up and journal-corruption cases; no physical query was sent.
- Phase110 retires the unused QuerySession model: an empty poll plus claimed
  reply and unbound positive generation falsely allowed closure. Preserve its
  counterexample/history; never treat observed=True as a native quiet fence.
  Original RPC slices show that nonzero callback selects finish bookkeeping,
  and async sending still reads message metadata after its supplied return.
  Neither is an admitted shortcut around actual send/completion lifetime.
- Phase111 expands the prepared source-read scope from6 code spans/288 bytes
  to8 spans/304 bytes by adding the UIPC13b0 and PCIe2d50 literal words.
  Keep .text code/data mapping and exact ABS64 reconstruction; matching LDR
  instructions alone does not qualify their pointer literals or referents.
  Historical section bases and offline expected bytes are not live read
  authorization. No physical read or send occurred in this phase.
- Phase112's fresh8-span reader passed141 models and the original-kernel VM:
  58 reads/704 bytes, all8 spans/2 ABS64 values exact and same child absent
  twice. Retained raw output and every table/root recheck were independently
  qualified without replay. VM inputs use its own RAM range and actual section
  bases; never copy those bounds or the body's historical addresses into a
  current live admission. Physical camera ownership and fresh state remain
  prerequisites. This phase performed no physical camera operation or CP send.
- The later owner-confirmed read-only session completes source113, map114 and
  sections115, then the separately admitted scope112 physical reader. Fresh
  boot/metadata/section bases match the retained epoch; the binary is unchanged
  from VM/model review. All8 spans/2 ABS64 values match with58 RAM reads/704
  bytes and descriptor/root rechecks; exact temporary cleanup, four unchanged
  sources and normal USB exit. This admits only those loaded code/literal
  observations, not CP sending, callback lifetime or an installation. Do not
  replay completed scopes or infer authority to write from exclusive read access.
- Phase116's native Sony-kernel VM runs original wait/wakeup helpers, not a CP
  completion.244 source bytes/8 relocations match before real normal/FIFO148
  threads execute16 CPU0 trials. Waker-return precedes wait-return in each;
  exact33 task PIDs are absent in two independent observations. The caller
  keeps its stack object alive until both helpers finish. Do not generalize
  this finite conditional test into physical CPU2 lifetime or CP-send admission.
  The first launcher failed shell syntax before module loading; no-module
  observations qualified disposal of that empty guest. Preserve it, never
  replay it. Background commands must remain valid after serial_command adds
  its '; rc=...' suffix; syntax-check the composed command before a new guest.
- The new phase84 seal admits metadata preflight ONLY: files/proc reads and
  device stat, no child/device open/ioctl. Its parent/observer models are not
  a physical execution. The stock diagnostic audit stops before registration
  and supported-mode services; default response bytes are not a live CP receipt
  or safe-send/remote-quiescence admission.
- Phase85 used a separately sealed current-source child scope, not phase84's
  metadata permission. Initial UNKNOWN stayed fenced; follow-up observed the
  same child without respawn/signals/reap. All four AP/CP/driver/library files
  reread unchanged; both sessions ended normally. Keep those artifacts frozen.
- Phase87's separately sealed temporary probe read process/stat/status,
  read-only scheduler queries and two RT sysctls. It observed FIFO148 workers
  with masks4/8; it changed no affinity/policy and sent no CP request. It was
  fully cleaned, with four source files unchanged and a normal USB exit.
  A metadata sample is not loaded-text/CP-receipt/preemption-lifetime proof.
- RAM-only does not imply restart recovery: executing code can issue persistent
  writes or hardware actions, and a kernel callback can retain old stack data.
  Review the actual side effects and lifetime; never rely on reboot alone.
- Phase88 linked the original send/completion queues and IRQ wait objects and
  checked two independent after-wakeup tails. Conditional event models show
  why cross-CPU or throttled-worker schedules need further lifetime protection;
  they are not native scheduler executions or demonstrated physical defects.
  Fresh proc metadata shows CPU0-3 online and cpuset groups cpu2/cpu3rt;
  /proc/config.gz and guessed CPU-controller files were absent. Do not infer
  disabled RT group scheduling from absent files or a cpuset-only task listing.
  Direct service reads of dynamic proc files returned empty; the fixed bounded
  temporary reader succeeded and was exactly cleaned. Keep both jobs/fences.
- Phase89's exact self-binding child passed the Sony-kernel VM on CPU0, then
  failed physically at CPU2 affinity readback: sched_setaffinity returned0 but
  getaffinity still returnedmask7. It parked, sent no CP request and never
  opened UIPC; no inverse was guessed/replayed. After the owner's reload,
  fresh metadata proved two old-PID absence samples before exact-file cleanup.
  Current program files stayed unchanged. Do not reuse that child/job or claim
  physical binding works. Its default observed_CPU=0 is not a getcpu sample:
  the failed path stopped before that syscall.
- Original UTM routes mask4 to /dev/cgroup/cpu2/tasks and mask7 to cpu0_1_2/tasks;
  those are source arguments only. The later phase91 self-task experiment is
  separately scoped; it does not execute UTM or admit arbitrary cgroup writes.
  Group names do not establish actual CPU masks, and missing config export
  does not prove a controller absent. Any alternative needs separate scoped
  self-only candidate/inverse review; never move AP or existing kernel workers.
- Phase90's completed fixed-file probe read the actual cpuset controller/groups:
  target configured/effective CPU2, original group0-3; AP remained mask7.
  This does not establish why the earlier setaffinity was ineffective.
- Phase91's fresh self-task candidate writes token0 once to cpu2/tasks and once
  to its exact original cpu0_1_2_3rt/tasks; no control creation/truncation or
  PID formatting.34 component models and28 worker models pass; same worker
  completes50-record migration/inverse in Sony-kernel CPU0 VM and physical
  CPU2. Physical getcpu=2, affinity7->4->7. Initial empty observation stayed
  UNKNOWN; follow-up observed the same fenced child, two absent samples and
  exact cleanup. Four source files unchanged, USB_FINISHED, normal0E8A.
  No UIPC open/ioctl/CP request, AP/worker migration, parameter/ROM/existing-RAM
  patch or signal manipulation. Old phase89 failure remains retired. This
  does not admit a synchronous send or establish physical pre-capture.
- Phase92's combined self-cpuset/signal/fresh-context component has no camera entry.
  Its62 generated-code controls cover all50 modeled calls, short move/inverse,
  invalid/reused inputs and preservation of unknown nested ownership. It has
  completed a102-record/50-call combined child under Sony-kernel CPU0 VM, with
  original VM UIPC query/map/allocate16 wait0/cancel/unmap/close and both guard
  inverses; two process-absence samples. No camera execution or CP send path.
  Raw VM report's inherited device_open=false label is incorrect: preserve it
  with the explicit qualification recording actual VM UIPC device access.
  Separate physical successes do not admit that composition automatically.
- Phase93/94 replaces the oversized combined debug image with a12,664-byte
  symbol-retaining strip-debug candidate; all allocated sections/load extents
  match its full-debug build.58 exact-worker controls and CPU0 native VM pass.
  Linker strip-debug initially removed symbols and was rejected, not bypassed.
- Phase93 stopped before any upload/spawn because current CP differs from the
  old baseline. Fresh read-only acquisition proves only4 changed bytes at FILE
  13553a, now stock movw, with AP/UIPC files unchanged and17 named CP spans plus
  diagnostic constructor/callback matching stock. Preserve those current bytes;
  never rewrite the old LUT retry hook to match a historical source hash.
- Phase94's separately reconstructed current-source job spawned PID982/AP518.
  First observer saw empty cmdline/no journal, therefore UNKNOWN. Continuing
  full source reads before terminal proof was an orchestration defect; later
  CP-file selection timed out. One read-only service attachment also timed
  out, without authentication/upload. Exact USB root cause remains unknown.
  Retained journal after owner cold boot has102 records/all50 calls, CPU2,
  masks7->4->7, restored signals and context ownership0, send_attempts0.
  This proves nested calls/inverses, NOT normal pre-reload process exit or
  successful end-to-end session closure. Keep the failed job/fence retired.
- Owner reported full power removal and normal viewfinder. Fixed recovery
  metadata then proved two old-PID absence samples and fresh boot data; all4
  source files match pre-test.9 exact archived temp files were cleaned; USB
  ended normally; owner confirmed ordinary photo/playback. Recovery is not a
  completed pre-capture test or permission to replay the failed candidate.
- Future orchestration must defer source reads while a child is UNKNOWN or
  RUNNING. support/child_session.py enforces that policy;10 focused controls,
  existing32 support/session tests and15 revised controller models pass.
  The revised controller is model-only; no new physical job is admitted.
- Phase95 supersedes that controller-only checkpoint. A fresh nonce/path/worker
  passes58 models and CPU0 native VM. The new initial session skips source
  reads after UNKNOWN and exits USB normally. Follow-up uses a separately
  reviewed fixed syscall-only observer with original source epoch/body/receipt
  binding and native AP PID checking; it does NOT pretend to freshly pin full
  programs or permit arbitrary uploads. Source reads are blocked until terminal.
  13 observer-only adapter and11 follow-up controls cover those distinctions.
  Physical same child1003/AP519 has102 records/50 calls, CPU2, masks7->4->7,
  signals/context restored; two absent samples BEFORE any reload, exact cleanup,
  four sources unchanged, both USB sessions normal. Owner photo/playback normal
  without reboot. Phase94 remains retired; one success is not a broad USB fix.
- Phase96 read-only scheduling refresh again finds FIFO148 workers with allowed
  masks4/8 and runtime-1/period1000000. Their sleeping-task CPU field remains1:
  allowed masks are NOT an observed callback executing on CPU2/3. Probe cleaned,
  four sources unchanged and USB normal. No policy/affinity change or CP send.
- RPC component v4 is OFFLINE ONLY. The unguarded entry now returns-95 without
  I/O; guarded entry needs checks before allocation and before payload/send.
  A refused second gate cancels the untouched allocation once. Only the exact
  original e1/80/zero-middle/fresh-tail default response qualifies release after
  sync; unexpected/unchanged/non-default replies retain unknown ownership.
  Original40 models are preserved:34 retained protocol/ownership outcomes,
  5 intentionally retain unexpected replies,1 now rejects the old foreign-type
  source fixture. Positive source fixtures use the own-queue grammar; binding/
  result spans must be private/disjoint.26 added controls give66. No live gate or
  physical RPC launcher exists. Do not treat a modeled allow callback or
  the completed never-sent context as permission for a real CP request.
- Phase97 supplies an OFFLINE fresh RPC-context composition, not a live gate:
  source comes from its own descriptor info[3], context version2/reserved1
  marks the operation, and rpc.rpc_attempts is its send counter. Never infer
  no-send from the unused legacy probe result. Its CPU0 Sony-kernel VM only
  allocates24/refuses send/cancels/closes, with two native exit observations;
  no physical CP send or after-send callback lifetime is admitted.
- Manual in-camera Off/On control is required for completion, initially Off.
  It is NOT implemented. Do not auto-enable pre-capture or reuse the retired
  look display/segment/icon approach to fabricate an entry.
- Phase98's native condition gate always refuses stage2. Its successful
  no-AP Sony-kernel CPU0 test uses the actual original PCIe worker and native
  syscall/file replies; no fake thread, forced readiness or CP send. This is
  necessary-condition evidence only. Lost UIPC FD identity or unknown gate
  resources use-117, preserving the whole RPC context even before allocation.
  Never turn that status into a clean cancellation/exit. The earlier VM with
  no PCIe worker stopped before diagnostic launch and stays as a negative.
  Its separate physical metadata probe locates loaded sections only: no kernel
  code read or device open. kmem/kcore absent; mem node presence is not a safe
  read route. Never guess physical mappings or treat section addresses as
  loaded-byte admission. Reused gate records retain UNKNOWN without overwrite.
- Phases100-102 supersede address-only evidence for9 named code spans only:
  exact boot/resource bootstrap, actual init_mm.pgd, RAM-only page walks and
  descriptor rechecks qualify1,796 bytes with12 CALL26 sites reconstructed.
  Do not infer full module, UIPC send-path or callback-lifetime admission.
  The VM's first next-table refusal correctly enforced body RAM bounds. It
  was observed as known-95/devclose0/only standard FDs before disposable-guest
  shutdown; original failed scope is never replayed. A fresh VM-specific RAM
  input passes; never widen physical-body RAM bounds to make a VM pass.
- Phases103-104 add original preemption/single-CPU wakeup facts and loaded
  scheduler/transport-state samples. Native VM sender0 remains a negative;
  physical sender1 and matching callback table/functions are necessary only.
  No CP response or live sender has been admitted. Code walks require executable
  leaves; only explicitly scoped metadata walks may accept normal NX kernel
  data. Never transfer that data policy to a code comparison implicitly.
- Phase107 qualifies9 loaded UIPC/PCIe send/finish fragments,82 exact
  relocations and65 bounded reads; not a whole-image or lifetime proof. Its
  native VM collector had a stale6920-byte header assertion after growth to
  7432 bytes. Same child was already absent twice and raw output retained;
  offline qualification passes with no native replay. Preserve both reports.
  Phase108's typed sampler only collects necessary facts. Original public
  gate still denies stage2; sampling success is never send permission.
- The owner's October19-23 handoff includes superseded hypotheses. Reuse its
  offline name-array discovery with actual ELF coordinates, not hardcoded
  paths, cross-model IDs or its camera operators. Generated PRM/VAL/FUNC names
  are metadata, not full ELF symbols, code addresses or proof of a feature.
  Its property parser's379 marked successes include six enum extent mismatches;
  do not infer feature support/absence from that incomplete parse alone.
- Modern host transports must be independently pinned/reviewed, not imported
  from a changing sibling worktree. For existing-file-only sessions use the
  read-only wrapper: no upload/removal/arbitrary packets or auto-rescue after
  an unknown exchange. Main's probe cleanup and read-only reauthentication
  recovery do not become authorized simply by importing its Camera class.
- For refactors, compare original-source audit reports and existing component
  models before/after; validate the service-stop helpers' failure paths.
  Model success is not physical pre-capture, boot safety or camera recovery.
- Derive VM CPU reset entries from the admitted ELF header and executable
  segments. Section alignment/build notes can move `_start` beyond the linker
  origin; do not hardcode that origin for secondary CPUs.
- Use `cpu-index` on each HMP/QMP per-CPU observation. A standalone `cpu N`
  command does not persist its selection across separate QMP HMP calls.
- Do not read banked GIC MMIO through debugger `memsave`: QEMU's callback can
  require `current_cpu`, absent in that observer context. Use actual guest
  instructions or source-qualified RAM state; retain failed observer evidence.
- In stock2.01 CP, the `0x63476c` workers wait on flag0x56/bit1 before the
  UFI finalization path. Do not force that event or treat its `0x634e80`
  return as a required normal initialization boundary.
- Stock2.01 TOMCO sets usrrtn_cfggrp=2. A fixture without it defaults to0
  and admits only TOPPERS_KERNEL. Do not infer transport initialization
  from that narrower callback walk or directly force the group word.
- Watchdog VM profiles use action=pause and retain expiry evidence. Do not
  silently reboot/replay or disable original watchdog settings to pass boot.
- The later I2C-stage boundary is a null table at 0x1a7e868, consumed at
  0xbe9a14 in UIN callback13. Reconstruct its original binding/input; do not
  install invented data or force the pointer to pass native initialization.
  Original BACKUP_INIT rejects the staged VM's zero input at 0x04000000
  and skips the secondary binder; this is not a physical-camera failure.
  The following factory-input stage binds exact original BK4 bytes at their
  declared base and reaches write f1388f4c/value101 at 595cfc. Its register
  meaning is unqualified. Factory fixtures are not current body backups.
- The DFS-stage block has endpoint-specific CP/AP register sequences, not
  generic SCU DATA/SET/CLR aliases. Its model roles remain inferred; absent
  backend must retain pending requests. No clock rate or IRQ route is modeled.
  Native DFS initialization returns with starts=0. The next boundary is
  clock-select SET f1388234/value0 at b716b8, followed by a scratch readback.
- SPI selector masks total 0x30777. Its alias-readback words are explicit
  unknown-value fixtures; local readback independence does not establish
  hardware values or independence in other paths. No clock rate/ready signal
  is supplied. Two native profiles reach PLL SET f1388204/cc10 at b716b8;
  do not generalize SPI storage into an unqualified whole-SCU RAM mapping.
- PLL programming uses original ROM tables; generated reports containing
  those tables stay private. Control/response roles remain inferred. Guest
  bit24 writes must not produce LOCK; absent backend retains the original
  b74b02/b74b04/b74b08 poll. Native observations cover three retained cycles,
  not a clock transition or full UIN return. Gate storage admits only the
  audited masks documented in VM-CP-CLOCK-GATES.md, not entire SCU banks or
  a physical clock tree. Logic-bank bit24 is not the separate PLL LOCK bit.
- The optional PLL source-fixture is an explicit conditional experiment.
  Its private source tuples and guest-ROM comparison do not prove analog
  validity, clock rates, real LOCK or boot safety. Keep the absent-backend
  negative control intact. Packaged cxd clock-source presence does not admit
  its fixed rates/layout as the current CP hardware. Original helper/startup
  audits qualify the gate masks; conditional execution reaches f54005d4. That
  subsequent source-policy stage admits paired software request words only;
  hardware clock/reset completion remains unqualified. Its next f5408038
  read is unsupported without the later explicit single-word experiment;
  do not return a guessed ready/configuration value.
- The isolated config_rmw helper fixture maps register addresses as ordinary
  test RAM. It is not a peripheral model or native-boot continuation. Never
  reuse that broad RAM mapping to pass an unsupported startup access. Its
  current-file span comparison is not loaded-RAM or whole-firmware admission.
- The optional config-word model admits only bit14 at f5408038 under an
  explicit zero/ones initial input and per-I/O original-code checks. Initial
  words are not hardware reset values or ready signals. Absent input retains
  the fault. Conditional continuation reaches f5411000 read at b9b5a2;
  its role/value remain unqualified. Never expand this into whole-bank RAM.
- Original diagnostic display identifies f5411000 as MTG_REG_SEL. Target
  and donor selector/getter bytes match, but this is not physical timing or
  reset-value qualification. Original log calls remain boundaries; do not
  make the following independent store slice a successful logger return.
- The MTG selector experiment stores only bits0..1 at f5411000; explicit
  initial inputs, source/caller/name pins and every-I/O checks remain. It
  provides no MTG edge, frame IRQ, clock rate or sensor. Conditional original
  execution next writes f5411010 at b9b69e/value1b7e47; role/timing remain
  unqualified. Do not create a permissive timing bank to pass it.
- The period-word experiment admits only f5411010/1014/1018, with an explicit
  write-first profile. Unwritten words stay undefined and fail reads; only
  full-word writes may define them. No period unit, rate, edge or completion
  is modeled. Conditional execution next reads f5410004 at b9b146, still
  unqualified. Do not substitute a reset value for that different word.
- A64 source-drift controls must use naturally aligned reference DATA access,
  and verify the actual mutation plus the expected device fault address and
  syndrome. Loader-order failures or alignment exceptions are not successful
  source-guard controls. Retain and qualify those failed observer artifacts.
- Sparse command policy files and original execution reports stay private.
  Admit only canonical policy/code pins, bounded words and source masks.
  Requested-bit latches are experimental state, not confirmed hardware or
  native peer readiness. Original zero software returns do not prove success.
- A debugger step reply alone is not instruction progress. Verify the target
  CPU/PC and observed value; preserve repeated-PC failures. Current poll
  controls explicitly select the GDB CPU and journal their step packets.
- Upstream DesignWare CLR_TX_ABRT releases the IRQ but retains its source
  syndrome until reset. Treat this as a model limitation, not silicon proof.

No Claude or additional agents without explicit user authorization.
