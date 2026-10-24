# A7C II pre-capture research

Unfinished research for firmware 2.01, **not a working feature or installer**.
All public commands in this directory run offline.

This feature branch now includes current main's product/runtime files; the
research remains confined here and has no installable pre-capture entry.
At each phase boundary we review main updates and redundant dependencies,
and compare original-source/model reports before and after refactoring.

## Current evidence and remaining work

| Area | Evidence | Still missing |
|---|---|---|
| [Shooting workflow](WORKFLOW.md) / [controller](CAPTURE-LIFECYCLE.md) | Continuous save/cancel/restore controller; [Sony-kernel VM](VM-PROCESS.md) runs eight virtual-pixel transactions | Native sensor, RAW-reference, recording-writer and terminal-fence bindings |
| [Original CP startup](VM-CP-REQUEST-WORDS.md) | Conditional guests return after two write-first MTG period stores/readbacks; independent watchpoints qualify the next read `0xf5410004` | Its physical behavior, complete initialization, timing edges and actual AP/CP receipt |
| AP/CP transport | Physical isolated child completed context info, mapping,16-byte wait0 allocation/cancel and exit;20 journal records and two terminal observations; exact temporary files cleaned, four source files unchanged | Loaded-module byte qualification, CP receipt, peer readiness and safe callback teardown after sending |
| Isolated AP execution | [Physical file/process self-test](VM-PROCESS.md#physical-follow-up-fileprocess-only): one child exec completed,58 inherited descriptors closed, only two owned output descriptors remained; terminal state and exact temporary-file cleanup verified | Native UIPC/CP calls, sensor/RAW/writer bindings and safe teardown after sending |
| Original diagnostic response | [Original CP audit](audit_cp_rpc_default.py):756 default returns,12 supported-mode stop boundaries and the constructor's original registration arguments | Actual registration/receipt and remote ownership; this is not permission to send a query |
| Synchronous completion | Physical metadata identifies both FIFO148 workers, CPU masks4/8 and cpuset groups; [30 route/storage/tail slices](audit_sync_completion_route.py), [37 registration/callback slices](audit_cp_rpc_registration.py) and [conditional scheduling controls](audit_sync_lifetime.py) | Actual CP receipt, loaded code and an observed callback/preemption lifetime contract; same CPU alone is insufficient |
| Isolated caller binding | Revised combined diagnostic completes50 calls/102 records on CPU2, affinity7→4→7 and signal/context restoration; same child observed absent twice before cleanup; both USB sessions end normally without reload; ordinary photo/playback confirmed | Actual CP receipt and callback lifetime after sending; one completed diagnostic does not establish broad stability |
| Fresh RPC context | [Offline composition](ap_rpc_context.c) derives source ID from its own descriptor;33 generated-code cases; Sony-kernel CPU0 VM allocates24 bytes, refuses send, cancels and exits with two absent-process samples | Actual live send gate, loaded source/callback lifetime qualification and a separately reviewed physical sender; no CP request sent |
| Native condition checks | [Conditions](ap_rpc_conditions.c) read caller CPU/signals/policy, descriptor identity, worker identity/scheduling and RT budget twice;133 integrated models. No-AP Sony-kernel CPU0 VM with original PCIe module matches both samples, refuses send and restores/exits | Loaded code, atomic lifetime guarantee and physical validation. Stage2 always refuses; scheduling samples do not authorize a CP request |
| Loaded source | Physical proc/resource bootstrap,96-byte RAM bootstrap and9 named code spans match;12 PCIe CALL26 relocations reconstructed exactly;23 bounded reads/1,908 bytes, descriptors rechecked; exact cleanup, four program files unchanged, USB normal | This qualifies the named1,796 code bytes only. Remaining send routing/UIPC code and callback lifetime still need admission; no CP request sent |
| Preemption/initialization | [16 original scheduler slices](audit_rpc_preemption.py) qualify class precedence and single-CPU wakeup selection. Physical read matches six scheduler code/data spans, actual transport table/functions and sender-ready1;79 reader models, native VM read/exit | Conditional source facts and necessary state, not a completed callback/CP request. Current send gate remains closed |
| Loaded send implementation | Physical9 UIPC/PCIe send/finish fragments and82 exact relocations match;65 RAM reads/3,612 bytes;147 reader models and native Sony-kernel output qualified without replay | Source prerequisite only. No CP request, response, physical pre-capture or menu implementation yet |
| Physical-read route | [18 original-kernel slices](audit_kernel_memread.py) qualify range-check boundaries, error/zero-length branches, direct-map arithmetic and page split before task/user-copy access | Actual RAM ranges, module page-table binding and an admitted bounded read; module virtual addresses cannot be used as physical addresses |
| Manual in-camera switch | [Completion requirement](WORKFLOW.md): independent Off/On control, initially Off, manually enabled | Menu implementation, real state binding and safe disable; currently absent |
| Camera source | Latest October23 snapshot supersedes phase81; three verified copies; AP/CP carry current six-slot color calibration;17 named CP FILE windows and diagnostic spans match stock | Loaded RAM, actual look effects, native shooting admission, real pre-trigger exposures and saved photographs |
| [AP generated names](audit_ap_names.py) | Owner-supplied discovery method independently replayed with ELF section coordinates:28,808 target and29,345 FX2 names;30 shared Timeshift names,19 donor-only | Metadata-to-native-code binding and actual runtime state; names do not establish feature support |

The MTG/configuration fixtures store explicitly requested fields only. Their
zero/ones initial inputs and PLL experiment responses are **not** measured
reset values, physical timing or hardware readiness. Absent inputs retain the
unsupported access or original wait. The earlier whole-RAM helper test must
never replace the restricted native-startup model.

The old seventeen-range AT74 comparison used the wrong coordinate convention.
It is preserved and invalidated; [the corrected audit](audit_source_spans.py)
checks FILE offsets and original encoded calls. A matching historical span is
not whole-firmware or loaded-RAM admission.

CP parameter `00030072` caused a half-press crash and is retired. Never retry
it. The earlier file-only camera child failed setup and was cleaned. A new,
separately sealed file-only job completed child execution on this body. A later
independently scoped job also completed a never-sent UIPC context lifecycle;
it sent no CP message. Native frame
references, late ingress and all-stage release remain open even if a queue is
empty or a status word is zero. Ordinary shooting, exact physical restoration
and preservation of FL2/FL3/six looks need their own physical acceptance.

A privately pinned modern main transport can be wrapped by
[support/readonly_session.py](support/readonly_session.py): named existing
files and bool live/saved snapshots only, no upload/deletion/native execution
or automatic rescue after an unknown exchange. Its13 guard controls and43
focused latest-main tests are offline evidence. Camera contents may have
changed since any archived snapshot; preserve subsequent work and read
[AGENTS.md](AGENTS.md) before a device action.
The latest source snapshot was read without uploaded code or parameter/firmware
writes. Its disk layout structurally identifies current color calibration,
which the later temporary diagnostic preserved. Neither establishes loaded
look effects or authorizes restoring an older image.

The owner's six handoff memory documents were reviewed chronologically,
including their retractions. We reused the AP name-array discovery, not its
device scripts. The original property report reproduces379 marked successes,
but six enum records fail exact extent checks. That parser's result alone
cannot establish remote feature support or absence. Generated names are
parameter metadata, not a complete C++ symbol table or callable addresses.

The private one-shot query controller distinguishes an exact modeled successful
transaction, a verified never-sent boot-epoch refusal, and unknown/running state.
Qualified terminal process observations are required before source reads; a
result file alone cannot authorize cleanup. Physical query execution remains
unadmitted, and pre-capture remains unfinished.

The latest [original RPC audit](audit_native_rpc.py) rules out two shortcuts:
a nonzero callback argument selects finish bookkeeping rather than registering
a remote callback; asynchronous send omits the stack waiter but still reads
message metadata after the supplied send return. Neither establishes safe
message release. Ten added original-instruction slices preserve the previous
30 results. The unused abstract query-session model was removed after it
incorrectly allowed closure following an empty poll and an unrelated generation.
It had no native or camera callers. Physical lifetime proof is still missing.
The new code scope also identifies six fragments (288 bytes) outside the earlier
loaded-read extents. Their file audit does not establish current RAM contents;
future qualification needs fresh mappings and exact relocations as well as
the separate callback-lifetime proof.
Direct literal-load analysis adds two uncovered pointer words (16 bytes), making
the offline read scope eight spans / 304 bytes. Code/data mapping symbols and
encoded load targets are checked; the two pointer relocations are reconstructed
exactly. This is a read-scope preparation, not a camera read or send admission.
The subsequent bounded reader passes 141 instruction-model cases and a fresh
Sony-kernel VM run: 58 RAM reads / 704 bytes including page-table checks, all
eight source/literal spans exact, two independent child-absence observations.
The VM and body reader use identical C source with separately scoped inputs.
No physical camera execution or CP request is admitted by this result.
After the owner confirmed exclusive read-only access, fresh body snapshots and
metadata matched the retained boot/source/mapping inputs. A separately scoped
physical read then verified all eight spans and both relocations: 58 reads /
704 bytes including table/root checks. Exact temporary-file cleanup, four
unchanged program/driver files and normal USB exit were verified. This is loaded
source evidence only; no CP request, patch or pre-capture exposure occurred.

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
| `support/register_source.py`, `audit_mtg_select.py`, `audit_source_spans.py` | Shared explicit-input original register slices, MTG field/label evidence and named FILE-offset comparisons; no hardware ACK or loaded-source admission |
| `vm/cp_boot/config_rmw/qemu_source_word.h`, `vm/cp_boot/mtg_select/` | Shared restricted single-word storage and the optional MTG selector fixture; no timing edges, frame IRQ or sensor |
| `audit_mtg_period.py`, `vm/cp_boot/mtg_period/` | Original indexed period setters/getters and write-first requested-word storage; undefined-before-write, no timing generation |
| `support/ap_model.py` | Generated-component unit calls with explicit modeled outcomes; never used to supply successful native services in source audits |
| `ap_client_cpuset.c/h`, `verify_client_cpuset.py` | Single-thread diagnostic child moves only itself with tasks-file token0, verifies membership/CPU, then restores original membership/affinity; no AP/worker migration or CP request |
| `ap_client_context.c/h`, `verify_client_context.py` | Self cpuset → signal/affinity guard → fresh never-sent allocate/cancel context → inverse guards;62 generated-code controls; CPU0 VM and physical journals record50 calls/102 records; physical exit/session completion unresolved |
| `support/child_session.py`, `verify_child_session.py` | Gate post-child source reads on qualified terminal/process+journal evidence; unknown/running observations perform no source I/O; no camera entry or recovery permission |
| `ap_rpc_probe_once.c/h`, `verify_ap_rpc_probe.py` | Offline v4 RPC component: private binding/result spans, own-queue ID grammar, checks before allocation/send, exact original default reply only;66 models. No live gate/fresh-context adapter or physical send admission |
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
python dev/precapture/verify_capture_workflow.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
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

Phase109 已把单次查询的结果分成三类：模型中的精确成功、确认未发送的启动世代拒绝、以及未知/仍运行。
只有同一个子进程已经结束、两次进程观察一致且日志完整时，拒绝路径才会核对固定来源文件；
它不会被记录成 CP 成功。结果文件本身不能授权清理。新增的生命周期、父进程/观察、操作员、
后续观察和日志损坏控制均已通过。候选仍是离线研究，没有发送 CP 请求，也没有实现或执行预触发
曝光、RAW 保留、全按存盘、取消释放或机内菜单开关。

Phase110 对原厂 RPC 增加10段原指令核对，并保留原先30项结果：非零 callback 参数进入结束记账，
不会注册远端回调；非同步发送虽不携带栈上等待对象，但发送返回后仍读取消息标头，不能据此提前释放。
上一轮新增的抽象查询模型没有真实调用者，却能在空轮询后接受任意世代并报告可关闭，现已撤下并保留
反例及历史。没有执行相机操作，发送后的真实生命周期仍未证实。
另已定位6段、共288字节不在先前载入代码读取范围内；原文件核对不能替代当前RAM核对，
后续仍需新的地址映射、精确重定位，以及独立的回调生命周期证据。
Phase111 又核对了这些指令直接读取的位址常量，补入2个未覆盖的指针字，共16字节。
离线读取范围因此是8段/304字节；两处指针重定位已精确重建，也复现了原先82处重定位。
这里只完成读取范围准备，没有执行相机读取，更不能当作发送许可或预拍摄完成。
Phase112 已把读取程序编译并运行于新的 Sony 原厂核心虚拟机：58次RAM读取/704字节
（含页表检查），8段内容及两处重定位全部吻合；两次独立确认同一个子进程已不存在。
141项指令模型也通过。VM与机身候选的C代码相同，输入范围独立；实机尚未执行，也未发送CP请求。
随后在用户确认独占只读操作后，Phase113–115重新核对了机身来源、启动识别和段位址，
与既有已验证输入一致。单独限定范围的实机读取已完成：8段内容/两处重定位全部吻合，
58次读取共704字节（含页表与根指针检查）；临时文件精确清理，四个程序/驱动文件未变，
USB正常结束。这只补齐本批载入代码证据，没有发送CP请求、打补丁或产生预拍摄曝光。

本目录是未完成的预拍摄研究，公开工具只做离线验证，没有可安装的预拍摄版本。

开发分支已对齐当前main，产品文件保持一致。每阶段结束与实机准备前，都检查主线更新、
重复代码及失效依赖；精简前后比较原指令和模型报告，不能为了少文件而删掉必要的取证入口。
代码按“共用工具与原指令夹具、AP／CP 组件、验证与审计入口”分工；重复编译流程
已集中，旧导入名称仍兼容。原固件、机身备份和临时诊断程序保留在私有目录。

半按崩溃的 `00030072` 方案已停用，不能重试。新封存作业已在本机完成一次文件子进程
自检：关闭58个继承描述符，执行后仅保留自己的两个输出描述符；最终结果与两次进程
终态观察一致，临时文件已精确核对清理。初次观察未知时只观察同一进程，没有重新启动。
这没有访问UIPC或发送CP消息，同步请求的回调生命周期仍需验证。
随后另建当前来源专用的诊断权限，实机完成了未发送消息的UIPC上下文查询、共享映射、
16字节wait0分配与取消、解除映射及关闭。20条日志、6项生命周期系统调用、3次ioctl
与两次进程消失观察一致；关闭62个继承描述符，执行后仅有自己的两个输出描述符。
初次未知时保留原作业，随后只观察同一子进程；精确清理临时文件，四个程序/驱动文件
前后一致，USB正常结束。这仍未发送CP请求，不能证明真实曝光、RAW保留或预拍摄。

最新10月23日备份已取代phase81：文件结构显示FL23、六槽及当前双域色彩标定，
不代表RAM加载或实际色彩效果。禁止拿旧原厂/六款备份覆盖当前标定。
用户提供的6份交接记忆已按时间核对并保留推翻记录；复用了名称表发现方法，独立按
ELF段换算地址，核对A7C II的28,808项及FX2的29,345项名称。共有30项Timeshift名称，
FX2另有19项规则名称；这只定位元数据，不能把FUNC编号当函数地址或功能已实现。
原属性报告虽能复现379项成功标记，但6条枚举记录长度仍不吻合，不能据此判定功能门控。
另一次仅临时执行的只读探针已实测两个PCIe完成线程：FIFO优先级148、CPU亲和性分别为2和3；
读取前后进程身份/策略一致，临时文件已清理、四个程序/驱动文件未变、USB正常结束。
37项原厂注册/回调片段与20项优先级/完成线程路由片段通过；实际CP应答、同CPU抢占与
发送后的生命周期仍未证明。本轮没有CP消息、调度修改、参数、ROM或现有AP/CP RAM补丁。
后续已对应发送/完成队列与IRQ唤醒对象；共30项原指令路由/存储/尾段检查通过。
实机补读确认CPU0-3在线、两个完成线程处于cpu2/cpu3rt分组；内核配置接口未导出。
抽象事件交错控制发现跨CPU、或完成线程可能被节流时，存在等待上下文提前返回的反例；
严格同CPU/高优先级FIFO且不节流的条件模型通过，但不是原生调度执行或实机安全证明。
自身CPU/信号约束组件通过31个模型；同一静态子程序在原厂内核VM完成36条日志、17次调用及
精确恢复。实机请求CPU2返回0，亲和性读回却仍为mask7；程序停留，没有UIPC/CP或自动重试。
用户重新上电后，两次确认旧进程不存在，才按精确字节清理文件；四个来源文件未变。
现已核对原厂cpuset路径mask4→cpu2、mask7→cpu0_1_2，但未写入该控制器；不能当作修复完成。
后续目标仍是真实预触发曝光、像素保留、
全按存盘、取消释放、正常拍摄和精确还原。任何新写入遵守 AGENTS 中的授权边界。

只读主机诊断已适配单独固定来源的新版主线通讯代码，限制到明确文件与设置快照；
未知结果后不自动重认证，不上传、清理或执行诊断程序。13项封装检查、43项新版主线
相关检查（含6项实际解析器集成）均为离线结果，不能作为实机预拍摄可用的证据。
