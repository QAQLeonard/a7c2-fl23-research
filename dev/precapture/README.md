# A7C II pre-capture research

Unfinished research for firmware 2.01, **not a working feature or installer**.
All public commands in this directory run offline.

This feature branch now includes current main's product/runtime files; the
research remains confined here and has no installable pre-capture entry.
At each phase boundary we review main updates and redundant dependencies,
and compare original-source/model reports before and after refactoring.

## Current evidence and remaining work

**One live head/tail/count sample and its exact restoration have completed;
pre-capture has not.** A separately approved58-byte passive callback change
(53 actual changed bytes) returned head816,tail699,count907 in one24-byte
transaction. The ring relation holds: `(699-816)&1023 == 907`. Its392-record
journal qualifies one allocation/send/release, same-child exit, exact cleanup
and unchanged source files. The inverse was fully read back; the owner confirmed
ordinary viewfinder, photography, playback and existing looks after cold reload.
The one-query allowance is consumed. No lock, IRQ change, exposure or RAW
retention was tested. This non-atomic sample counts management records, not
photographs or bytes of available image memory.

The earlier four fixed CP pointer reads remain a separate completed experiment.
An explicitly approved diagnostic reused58 bytes of the existing callback
(52 changed bytes), adding no code page, heap state or shooting hook. Its four
single-use queries returned `0x22a4760`, `0x22b4720`, `0x22b4728` and `0x22b4730`.
Each has392 journal records, one send/release and qualified same-child exit;
temporary cleanup and source preservation were checked. The owner confirmed
normal photography after installing/cold-loading the diagnostic. Its exact
inverse has now been written and fully read back; the owner confirmed ordinary
shooting/playback and original/custom-look selection after the final cold reload.
This completes that diagnostic's install/test/inverse cycle. This is live pointer evidence,
not a coherent pool snapshot, pixel lease or working pre-capture feature.

The earlier original-default query remains a separate completed checkpoint.
The owner approved one 24-byte unsupported-mode request (`0x908f084b`, mode
`0xe1`). It returned the exact expected `0x80` response. The final journal has
392 records and exactly one synchronous call. The same child exited, its own
CPU/signal/context state was restored, exact temporary files were cleaned and
four source files were unchanged. Both USB sessions ended normally. The owner
then confirmed normal viewfinder, photography and playback using the requested
direct test sequence. No firmware, shooting setting or existing code patch was
written by this experiment. This is one successful case, not broad stability.

The latest read-only acquisition (phase135) captured five current program/module
files twice with identical bytes and verified two backup copies; USB exited
normally. They match the retained current sources, including the LUT preview
repair. This is existing-file evidence, not live CP pool or exposure evidence.

| Area | Verified evidence | Remaining work |
|---|---|---|
| Fixed CP metadata access | Four pointer reads, then one separately approved three-word callback sample816/699/907; both exact inverses and cold reloads accepted | Owner-coherent pool state, backing pixels and resource lifetime; ring consistency alone is insufficient |
| AP/CP query and cleanup | One original unsupported-mode transaction, exact reply and nonce-tail validation, one allocation/send/release, terminal process observations and source preservation | Capture-specific protocol, real frame ownership and repeatability under separately approved tests |
| Caller scheduling/lifetime | Native Sony-kernel VM: 16 real wait/wakeup trials with normal/FIFO148 threads on CPU0; physical query: CPU2, affinity7→4→7, signal restoration and context release | General concurrent/lifetime guarantees; one completed query does not qualify arbitrary callbacks or schedules |
| Loaded source and current boot | Fresh kernel/section/worker metadata, 96-byte bootstrap and 35 selected code/state spans; exact relocation and page-table checks | Whole-module verification is not claimed; later boots require fresh bindings |
| Current camera image | The changed CP image was reconstructed exactly from nine existing LUT-preview repair windows (333 changed bytes); 17 original spans and diagnostic paths match | Preserve this current image; older snapshots are not rollback targets |
| [Shooting controller](CAPTURE-LIFECYCLE.md) | Continuous save/cancel/restore logic and eight VM virtual-pixel transactions | Native exposure, RAW references, durable photo writing and terminal release fencing |
| Native shooting order | Original target/donor AP start/data dispatch and96 admission cases; CP1224 post-prepare branches,544 table queries,22 sequence callbacks and one fixed state-pair interpreter | Native preparation, dynamic state rows, actual readout/retention and hardware completion |
| Native state feedback | Original feedback stores, masked completion, deferred task/notification dispatch and CAP handle checks;60 input combinations plus negative controls | Hardware feedback provenance, actual exposure/RAW ownership and a generation-bound terminal fence; two commands share event308 |
| RAW resource path | Staged slots → RAW client → MEMMGR_CP dispatch; native reply-ID, descriptor transfer, handle generation and reference checks | Actual backing pixel allocation and matched terminal release; native handle generation wraps, local invalidation precedes backing free |
| Existing free-block allocator | Original configuration-row → node creation → allocation → pinned descriptor, cached-block return and worker/client replies, on synthetic RAM | Current configured address/extent ownership, real pixels, queue/accounting/notification completion and growing/parent-backed paths |
| Metadata capacity and shared bookkeeping | Original1023-record initialization,2048 pops/2048 returns and shared bookkeeping layout on synthetic RAM | These counts and bookkeeping addresses do not establish RAW buffer capacity or ownership |
| [CP startup study](VM-CP-REQUEST-WORDS.md) | Conditional original startup slices and restricted peripheral fixtures | Physical timing, full initialization and sensor/frame integration |
| Manual in-camera switch | Required independent Off/On control, initially Off | Implementation and safe enable/disable binding |

The combined check reports the three requested physical verdicts together:
pool provenance, asynchronous completion and exposure timing all remain
**unverified**. Original backing descriptors depend on configuration and native
allocation; the AP-provided shared bookkeeping block is not itself a pixel lease.
The synchronization helper can wait again; the exposure-end callback
posts an event without saving an end counter. A new source/owner-bound observer
and real capture trace are needed before any of those verdicts can pass.

The observer now has a compiled trace core and uninstalled task/pool/exposure
wrappers. Thumb/AArch64 tests check bounded recording, corruption/overflow and
original entry preservation. It still lacks qualified native placement, IRQ/
stack/clock admission and native export binding; it is **not ready to install
on the camera**. The new fixed24-byte packet adapter reconstructs a frozen
3136-byte lane through262 bounded replies in both ISAs, but is not registered
or executed on the camera. It requires genuinely frozen, owned storage that
stays alive for the entire export; packet validity does not establish that.

A later small AP-only metadata diagnostic read boot ID, memory resources and49
loaded modules. The result file's fsync/close receipt, exact temporary cleanup,
five unchanged source files and normal USB exit were checked. The owner then
confirmed ordinary viewfinder/photo/playback without restarting. This admits
only that diagnostic, not CP pools, pixels or hooks. The original kernel DMA
ioctl was also checked offline: its timeout tail returns with a stack callback
cookie still in the request, without establishing cancellation/quiescence.
It is not admitted as a shortcut for reading CP memory.

Two preceding jobs sent nothing: source drift stopped the first before upload;
the second rejected a changed boot epoch, restored itself and exited. Their
records and one-shot fences remain retired. The successful job used fresh
paths/nonce, the current boot, worker starttime and verified RAM evidence.
The one-query authorization is now consumed; it is not general send/patch
permission. Public sender gates remain closed, and public commands stay offline.

CP parameter `00030072` caused a half-press crash and remains prohibited.
Never replay unknown jobs, infer cleanup from a result file alone, or overwrite
later calibration with an older image. Source/VM evidence is distinct from
physical acceptance. [AGENTS.md](AGENTS.md) records the rules;
[CONTROL-PATHS.txt](CONTROL-PATHS.txt) retains the detailed chronological evidence.
Private firmware, body data, compiled diagnostics and operators remain outside
this repository. Reusable offline fixtures live in `support/`; compatibility
exports remain only where retained evidence replays still need them.

## Earlier startup studies

These retain original evidence and negative controls; their separate scopes
do not add up to physical pre-capture.

| Subject | Studies |
|---|---|
| Entry and execution | [Loader](VM-CP-BOOT.md), [SMP](VM-CP-SMP.md), [timer](VM-CP-TIMER.md), [counter/callbacks](VM-CP-GPTIMER.md) |
| Configuration and transport | [TOMCO groups](VM-CP-CONFIG.md), [watchdog](VM-CP-WATCHDOG.md), [eDMA](VM-CP-EDMA.md), [GPIO/peer guards](VM-CP-GPIO.md) |
| Input and peripheral configuration | [I2C](VM-CP-I2C.md), [factory BK4](VM-CP-BACKUP.md), [DFS](VM-CP-DFS.md), [SPI selection](VM-CP-SPICLOCK.md) |
| Clock requests | [PLL wait](VM-CP-PLL.md), [conditional PLL source input](VM-CP-PLL-SOURCE.md), [gate masks](VM-CP-CLOCK-GATES.md), [request/configuration/MTG](VM-CP-REQUEST-WORDS.md) |

## Code map

| Location | Responsibility |
|---|---|
| `support/build.py`, `elf.py`, `aarch64_abi.py` | Shared offline compilation, ELF/ISA validation and independent target-header ABI checks |
| `ap_ipc_transport.h`, `ap_ipc_context.c`, `ap_rpc_context.c` | Shared fresh FD/map lifecycle; separate legacy cancel and guarded RPC compositions. RPC results use context version2 and their own send counter; UNKNOWN retains resources |
| `ap_rpc_conditions.c`, `verify_rpc_conditions.py` | Actual read-only condition checks in the RPC composition; failures and PID/FD drift controls. Known refusal permits never-sent cancellation; unknown gate resources retain the entire context |
| `support/kernel_mapping.py`, `audit_kernel_mapping.py`, `verify_kernel_mapping.py` | Offline proc/resource plan, strict module-page translation and original-instruction comparison. No device access or live admission; private operators bind epoch/read extents separately |
| `support/cp_mapping.py`, `cp_owner.py`, `native_gate.py`, `ap_codec.py` | Original-instruction fixtures shared directly by checks |
| `support/kernel.py`, `uipc.py`, `boundaries.py`, `reference.py`, `memory.py` | Pinned inputs, synthetic memory and execution stopped before native services; explicit code slices also expose their direct literal-load dependencies |
| `support/config_rmw.py`, `audit_config_rmw.py`, `vm/cp_boot/config_rmw/` | Pinned configuration-helper spans, original execution and isolated RAM-backed helper fixtures; no hardware initial value or native boot admission |
| `support/readonly_session.py`, `verify_readonly_session.py` | Explicit named-file/settings-only wrapper for separately reviewed modern host transport; offline guards, no camera enumeration or uploader |
| `support/initializer.py` | Shared integer-only AArch64 DSO initializer fixture on synthetic memory; supports only relative relocations, never a native loader |
| `support/ipc_journal.py`, `verify_ipc_journal.py` | Shared bounded never-sent context journal decoder and private-input corruption controls; file success never grants process cleanup |
| `support/capture_native.py` | Shared original CAP object/cancellation fixture; six audits import it directly, with legacy replay exports retained |
| `support/capture_completion.py` | Original requested/current state comparison, deferred notification and CAP callback boundaries; synthetic inputs only, no hardware completion or camera adapter |
| `support/capture_resources.py`, `resource_service.py` | Resource preparation, RAW service/task routing, dynamic reply IDs, descriptor/handle/reference lifetime; no native service success or camera I/O |
| `support/backing_memory.py` | Original cached-free-node allocator and request/reply composition on synthetic memory; explicit queue/accounting/notifier boundaries |
| `support/capture_validation.py`, `audit_capture_validation.py` | Combined pool/completion/exposure source checks bound to a completed read-only snapshot; physical verdicts stay unverified |
| `cp_trace.c/h`, `cp_trace_native.c`, `cp_trace_hooks.S` | Bounded owner-lane recording core, uninstalled native metadata/edge adapters and exposure entry wrappers; no loader/storage/export admission |
| `support/trace.py`, `decode_cp_trace.py`, `verify_cp_trace.py` | Offline record decoder and compiled cross-ISA/entry-wrapper checks; no camera entry or physical validation |
| `cp_trace_export.c/h`, `support/trace_export.py`, `verify_trace_export.py` | Uninstalled24-byte frozen-lane packet adapter and exact offline reconstruction; no native registration/lifetime admission |
| `audit_dma_reader.py` | Original kernel DMA ioctl/stack-cookie/timeout boundaries, executed on synthetic RAM; no live reader or successful service stubs |
| `support/cp_metadata_probe.py`, `verify_cp_metadata_probe.py` | Offline existing-callback prototype and original-instruction equivalence checks; private authorized four-word experiment completed, no public installer |
| `support/cp_pool_probe.py`, `verify_cp_pool_probe.py` | Offline three-word protocol/patch tests; one exact private installation/query/inverse completed separately, with no general deployment admission |
| `audit_metadata_capacity.py` | Original ring initialization/pop/return and post-reply shared bookkeeping layout; source-bound synthetic RAM only, no pixel or physical-capacity claim |
| `audit_pool_serialization.py` | Original task try-lock/release on synthetic Cortex-A9 state, plus original wrapper pre-service boundaries; no physical lock/IRQ admission |
| `support/cp_locked_pool_probe.py`, `verify_locked_pool_probe.py` | Uninstalled lock/sample/unlock experiment; failed-release/IRQ retention controls remain explicit; excluded from the passive sampler's proposed hardware scope |
| `support/register_source.py`, `audit_mtg_select.py`, `audit_source_spans.py` | Shared explicit-input original register slices, MTG field/label evidence and named FILE-offset comparisons; no hardware ACK or loaded-source admission |
| `vm/cp_boot/config_rmw/qemu_source_word.h`, `vm/cp_boot/mtg_select/` | Shared restricted single-word storage and the optional MTG selector fixture; no timing edges, frame IRQ or sensor |
| `audit_mtg_period.py`, `vm/cp_boot/mtg_period/` | Original indexed period setters/getters and write-first requested-word storage; undefined-before-write, no timing generation |
| `support/ap_model.py` | Generated-component unit calls with explicit modeled outcomes; never used to supply successful native services in source audits |
| `ap_client_cpuset.c/h`, `verify_client_cpuset.py` | Single-thread diagnostic child moves only itself with tasks-file token0, verifies membership/CPU, then restores original membership/affinity; no AP/worker migration or CP request |
| `ap_client_context.c/h`, `verify_client_context.py` | Self cpuset → signal/affinity guard → fresh never-sent allocate/cancel context → inverse guards;62 generated-code controls; the revised physical job completed50 calls/102 records, exit and session closure; earlier failed jobs remain retired |
| `support/child_session.py`, `verify_child_session.py` | Gate post-child source reads on qualified terminal/process+journal evidence; unknown/running observations perform no source I/O; no camera entry or recovery permission |
| `ap_rpc_probe_once.c/h`, `verify_ap_rpc_probe.py` | v4 RPC component: private buffers, own-queue ID, pre-allocation/send guards and exact original default response;66 component models. The public unguarded entry refuses; a separately reviewed private adapter completed one owner-approved physical query |
| `support/ap_names.py`, `audit_ap_names.py` | ELF-based generated parameter-name discovery and Timeshift name comparison; preserves interior string pointers and separate FILE/VA coordinates; offline metadata only |
| `capture_workflow.c/h`, `support/workflow_model.py` | Asynchronous ownership/save/cancel/restore controller and explicit virtual pixel actors; separate from the CP runtime and unbound to native hardware |
| `vm/workflow_guest.c`, `vm/verify_workflow_guest.py` | File-only continuous-controller integration under Linux and independent pixel/journal validation; no native camera adapter |
| `vm/cp_boot/` | Offline staged CP startup source fixtures, explicit EL3 context and QEMU GPIO/alias model; no camera installer |
| `audit_frame_reference.py`, `support/frame_reference.py` | Original frame add/drop and holder-pool lifetime slices; no successful lock, acquired pixel reference or native completion is supplied |
| `audit_frame_clock.py` | Original saved-latch and independent frame-clock stores; no timer or exposure-boundary interpretation is supplied |
| `audit_send_admission.py` | Original zero-return path with no remote transport; no native log or callback success is supplied |
| `audit_transport_registration.py` | Original registration/initialization-signal contracts; not a CP-ready or drain test |
| `audit_transport_startup.py`, `audit_cp_exec_mode.py` | Original GPIO/IRQ startup guards and loader/CP mode encoding; no forced signal, hardware success or qualified physical alias |
| `audit_loader_backup.py`, `support/backup.py` | Original BK4 scalar reader against exact factory inputs, with independent host layout/checksum validation; no live backup admission |
| `audit_cp_smp_boot.py`, `vm/cp_boot/smp/` | Original startup/phase comparison, four-CPU fixtures and architectural interrupt controls; no native timer/dispatch or physical pre-capture acceptance |
| `audit_cp_timer_boot.py`, `vm/cp_boot/timer/` | Original timer/task/peripheral admission slices and tested timer-routing fixtures; no sensor, camera-service or physical pre-capture acceptance |
| `verify_cp_gptimer.py`, `vm/cp_boot/gptimer/` | Host counter contracts and tested experimental QEMU timer fixtures; input clock/mode2/CP routing remain model assumptions |
| `audit_cp_config_group.py` | Original group admission and handler slices; exact original TOMCO required, no callback/service success supplied |
| `verify_cp_watchdog.py`, `support/host_test.py`, `vm/cp_boot/watchdog/` | Shared host-test runner and timed reset-mode watchdog fixtures; physical reset routing/TOP_INIT capability remain unqualified |
| `verify_cp_edma.py`, `vm/cp_boot/edma/` | Non-LL model byte movement/interrupt controls and exact tested fixtures; no native AP peer, physical DMA, LL/cancel or capture acceptance |
| `verify_cp_gpio.py`, `audit_transport_gpio.py`, `vm/cp_boot/gpio/` | GPIO state/input isolation and original AP/CP endpoint guards; no electrical wiring, GPIO IRQ, peer-ready or camera acceptance |
| `ap_child_exec.*`, `ap_ipc_context.*` | Isolated child setup and never-sent context lifecycle physically tested; no public camera adapter or physical CP transaction |
| `ap_client_binding.*`, `verify_client_binding.py` | Isolated child self-affinity/signal-mask bind/inverse component and generated models; VM-tested, physical affinity readback failed; not a live-RPC adapter |
| `ap_probe_once.*`, `ap_query_once.*`, `ap_poll_once.*`, `ap_reply_once.*` | Allocation/cancel, tagged send, one poll, status validation/release; no live transaction or teardown admission |
| `ap_binding_guard.h`, `precapture_query_wire.h` | Shared private-buffer checks and status wire constants; identity/queue provenance remains external |
| `cp_*.c`, `cp_*.h`, `cp_*.S` | CP control/runtime/retention components; integration incomplete |
| `cp_backend.c`, `cp_runtime_entries.c` | Tagged read-only status replies from the serialized owner; uninstalled, with native-send bounds still unproven |
| Other C sources | Protocol encoding, trigger/frame decisions and queue policy |
| `verify_*.py` | Generated-component models and original-instruction comparisons |
| `audit_*.py`, `trace_*.py`, `decode_cp_blog.py` | Source audits and trace analysis |
| `cp_probe_reply.py` | Exact-source observer review builder, not a deployment tool |

Executable sources stay beside their verifiers so existing compilation paths
remain valid. Reusable fixtures live in `support/`; previous helper names stay
exported from their original modules for private evidence replays. Specialized
LTO/linker-script builds and compile-only ABI checks retain their own commands.

[CONTROL-PATHS.txt](CONTROL-PATHS.txt) contains detailed findings and unresolved
boundaries. [history/implementation-notes.txt](history/implementation-notes.txt)
contains older chronological notes whose identities and commands may be obsolete.
Firmware, body backups, generated binaries, private operators and run reports
are deliberately excluded from this repository.

## Offline checks

Dependencies: Python with `unicorn`, `capstone`, `pyelftools`, `keystone-engine`;
compiled checks also need an explicit Zig path (reference version: 0.13).
Every source audit requires the exact private originals its fingerprints admit.
Use a fresh private output location for every run.

```text
python dev/precapture/verify_support.py
python dev/precapture/verify_readonly_session.py
python dev/precapture/verify_ipc_journal.py --journal PRIVATE_SUCCESS_JOURNAL --nonce JOB_NONCE --output NEW_PRIVATE_JSON
python dev/precapture/audit_cp_rpc_default.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_JSON
python dev/precapture/audit_cp_rpc_registration.py --cp PRIVATE_STOCK_CP --current-cp PRIVATE_CAPTURED_CP --output NEW_PRIVATE_JSON
python dev/precapture/audit_sync_completion_route.py --uipc-kernel PRIVATE_UIPC_MODULE --pcie PRIVATE_PCIE_MODULE --output NEW_PRIVATE_JSON
python dev/precapture/audit_ap_names.py --ap PRIVATE_TARGET_AP --donor-ap PRIVATE_DONOR_AP --output NEW_PRIVATE_JSON
python dev/precapture/verify_config_word.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_mtg_select.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_mtg_period.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_mtg_select.py --cp PRIVATE_STOCK_CP --donor PRIVATE_ORIGINAL_A1II_CP --output NEW_PRIVATE_JSON
python dev/precapture/audit_source_spans.py --cp PRIVATE_STOCK_CP --current-cp PRIVATE_CAPTURED_CP --output NEW_PRIVATE_JSON
python dev/precapture/audit_ap_capture_order.py --ap PRIVATE_STOCK_AP --donor-ap PRIVATE_DONOR_AP --current-ap PRIVATE_CAPTURED_AP --output NEW_PRIVATE_JSON
python dev/precapture/audit_capture_transition.py --cp PRIVATE_STOCK_CP --current-cp PRIVATE_CAPTURED_CP --output NEW_PRIVATE_JSON
python dev/precapture/audit_capture_validation.py --cp PRIVATE_STOCK_CP --current-snapshot PRIVATE_SNAPSHOT_ZIP --acquisition-report PRIVATE_COMPLETED_ACQUISITION_JSON --output NEW_PRIVATE_JSON
python dev/precapture/audit_metadata_capacity.py --cp PRIVATE_STOCK_CP --current-snapshot PRIVATE_SNAPSHOT_ZIP --output NEW_PRIVATE_JSON
python dev/precapture/verify_capture_workflow.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_cp_trace.py --zig PATH_TO_ZIG --cp PRIVATE_STOCK_CP --current-cp PRIVATE_CAPTURED_CP --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_frame_reference.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_JSON
python dev/precapture/verify_child_exec.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_client_binding.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_poll_once.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_query_once.py --help
python dev/precapture/verify_reply_once.py --help
python dev/precapture/verify_backend_query.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_ipc_context.py --uipc-kernel PRIVATE_UIPC_MODULE --uipc PRIVATE_UIPC_LIBRARY --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_ipc_context_lifetime.py --help
python dev/precapture/audit_native_rpc.py --help
python dev/precapture/audit_sync_lifetime.py --help
python dev/precapture/audit_async_reply.py --help
python dev/precapture/verify_offline.py --firmware-root PRIVATE_FIRMWARE_FOLDER --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

Other scripts expose their inputs through `--help`. Donor comparisons use
`a1ii-4.00/components/` and `a7c2-2.01/components/` under the firmware folder.
Model results, full file readback and inverse manifests do not establish
camera boot safety, successful recovery or physical pre-capture.

The linked runtime now requires two explicit code pages for both ABI3/ABI4.
The native unmap models retain the six-look prefix independently of the CAP
observer option. This remains an emulator layout, with no loaded-page or
physical storage approval. A tagged status reply is not a capture result.
The old `precapture_probe_once(...send_query=1)` now rejects before allocation:
its16-byte packet becomes configuration input on the new runtime. Use the
separate tagged12-byte query component; a matched reply is not quiescence.

## 简体中文

**已完成四次固定 CP 元数据读取，预拍摄尚未完成。**
经具体授权，诊断只复用原回调58字节窗口，其中52字节改变；没有新增代码页、堆状态或拍摄钩子。
四次分别返回 `0x22a4760`、`0x22b4720`、`0x22b4728`、`0x22b4730`，均有392条记录、
单次发送／释放、同一子进程退出、精确清理和来源未变的核对。机主已确认诊断版重开后普通拍摄正常。
诊断补丁的精确逆向已写回并完整读回，机主确认最终断电重开后普通取景／拍摄／回放及原有／自定义外观选择正常。
本次小型诊断的安装、验证、还原流程已完成。
这只是实机指针证据，四项也不是同时读取，不能当成一致资源池、像素归属或预拍摄可用。
下一步的单次回调 head／tail／count 有界采样原型已完成离线检查，尚未写入或授权实测；
即使三个数满足环形表关系，也不能据此认定原子快照、无并发变化或像素归属。
原厂尝试加锁／解锁已在显式虚拟CPU及锁对象上执行：竞争时不等待，成功时须由匹配释放恢复IRQ。
两条包装路径都使用锁 `0x6c`；尚未证明全部写入者覆盖或实际回调环境，未在机身调用这些锁。
加锁／采样／解锁组合原型已离线执行，故意改变所有者的控制案例仍会留下锁和IRQ屏蔽，不能据此宣称上机安全。
下一次拟实测的是不加锁、不改IRQ的58字节计数采样：新来源读取和机身只校验已通过，实际写入／查询等待具体授权。
其三个原始值使用独立类型字段保存；计数不一致时先完成查询资源释放，保存原始数据后报告，不自动重发。

此前一次原厂不支持模式查询仍作为独立完成的检查点保留。

经机主明确授权，只发送一次24字节的原厂不支持模式请求（目标 `0x908f084b`、模式 `0xe1`），
收到精确的 `0x80` 回覆。392条记录确认只调用一次同步发送；同一子进程退出，自身CPU、
信号与上下文状态恢复，临时文件精确清理，四个来源文件未变，两个USB会话正常结束。
机主随后按直接试拍流程确认取景、拍照和回放正常。这次没有改写固件、拍摄设置或现有程序代码。
一次成功不能作为全面稳定性证明。

此前两次作业都没有发送查询：一次在上传前发现CP来源变化；一次拒绝了新的开机世代并完成自身还原。
现有CP的333字节差异完整对应9个LUT即时预览修正窗口，17段原厂程序及诊断路径未变；
这些现有修改已保留。新作业使用独立路径、nonce和本次开机资料。旧作业与失败证据不重跑、
不覆盖；本次只允许一次查询的授权已经用完。

目前仍缺真实预触发曝光、RAW像素保留、全按保存、取消/结束后的资源释放，以及默认关闭、
手动启用的机内菜单。VM里的虚拟像素保存与原厂核心等待/唤醒测试不能代替这些实机步骤。
造成半按崩溃的 `00030072` 参数方案继续停用。后续新的实机发送/补丁需要独立具体范围与授权。
离线已核对原厂拍摄顺序、状态反馈、暂存槽到RAW客户端／MEMMGR_CP任务、句柄和引用路径。
还需连接实际像素分配、保留、保存及终止释放；软件事件、描述符复制或本地标识无效都不能作为完成证明。
两个命令共用事件308，原厂句柄也只有会回绕的5位代次，接入时必须独立核对请求／拍摄代次与资源归属。
更正：45dd24分配的是动态回复队列身份，RAW目标服务是61003c；直接／任务队列分派表的行为不同。
原厂已有空闲块的分配、绑定、引用和归还，以及分配／释放请求回复，已在测试内存中执行通过；
实机内存来源、实际像素、队列与通知完成仍未验证，不能据此上机启用预拍摄。
这些检查都不连接相机，也不代表实机预拍摄可用。
最新一轮只读采集确认五个当前程序／模块文件与保留来源一致，会话正常结束。资源池来源、异步完成、
曝光时序已合并检查，但三项实机结论仍为未验证：还缺同次开机／拍摄的CP观测与曝光结束/S2时间证据。
观测器已新增可编译记录核心、任务／资源池／曝光入口绑定原型与离线解码器；溢出和损坏记录不会被当成
完整证据。新增24字节分块导出原型，两种指令集都能从262个报文还原3136字节记录；尚未注册或在机身执行，
必须先证明记录区确实冻结、归本功能所有，并在完整读出期间保持存活。仍缺实机代码及存储位置、任务／中断／
栈／时钟及原生读出绑定，目前不能安装，五项功能尚未完成。
后续一次小型AP元数据实测已读到开机标识、内存区域和49个模块；结果文件收尾、临时文件清理、五个来源未变及
USB正常退出均已核对，机主随后未重启直接确认取景／拍摄／回放正常。这不代表CP资源池或曝光已验证。
离线还确认原厂DMA ioctl超时返回路径没有建立取消／回调终止证据，不能把它直接用作猜地址的CP内存读取器。
详细证据保留在 [CONTROL-PATHS.txt](CONTROL-PATHS.txt)，公开工具继续只做离线研究。
