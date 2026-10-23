# Sony-kernel VM process test

On October 21, 2026, a separate instance of the existing
[a7c2-re QEMU lab](https://github.com/chocotan/a7c2-re) ran the public
`ap_child_exec.c` component under the original Sony ARM64 kernel and native
AP menu process. This is an actual guest-kernel execution, separate from
the Unicorn component models.
The launcher is a guest-shell child; the AP is running independently. This
does not test creation of a child from inside the native AP service.

The completed run established:

- Guest kernel: `4.9.337-scel+`, AArch64; native `im.elf` was running.
- Static launcher and payload bytes matched their SHA-256 values inside the
  guest before execution. Neither binary needs a dynamic interpreter.
- The child component closed **5 inherited descriptors** and executed the
  payload through its pinned executable FD path.
- The new image observed **0 inherited descriptors**, read the exact 64-byte
  test input, and returned matching nonce and content checksum evidence.
- The shell received successful completion and `/proc/PID` confirmed the
  child was gone. The result was collected before destroying the guest.

The first three runs retain their original failed harness reports: BusyBox
did not provide `sha256sum`, `od` or `ps`. Dedicated read-only collection
helpers and a shell-only terminal check resolved those harness dependencies.
The fourth fresh run passed every stage. Earlier reports were not rewritten.

Only disposable guest `/tmp` files were written. No USB, physical card, block
device or networking was passed through. Original assets were read-only;
the guest image and run directory were private copies. Other VM sessions and
the sealed camera diagnostic job were not used or modified. Compiled tests,
Sony assets, private host operators and full reports remain private.

This verifies file/exec/descriptor behavior in that VM. It does not establish
camera-side child creation from AP, asynchronous peer/context lifetime, CP startup,
sensor exposure, retained RAW ownership, actual photographs or camera safety.
Successful exec does not identify whether `execveat` or its allowed `ENOSYS`
fallback performed the final image replacement; that route was not traced.
Preflight checks hash privately staged guest files before opening the pinned
FD. This controlled-file harness does not replace concurrent-tamper-resistant
FD admission required by the eventual camera operator.

## Follow-up: isolated UIPC allocate/cancel

The public `ap_ipc_context.c` and `ap_probe_once.c` now also pass a real
post-exec guest-kernel test with the original `osal_uipc.ko`. Its exact SHA-256
was checked in the actual initramfs, and the VM's transport-error replacement
module was not requested. No successful driver responses were mocked.

The worker completed six lifecycle syscalls and three driver ioctls:

| Operation | Observed result |
|---|---|
| Path stat, open, FD stat | Same character device; descriptor0 was valid |
| Local context query | 2 MiB shared area and expected pool sizes; a fresh opaque user queue ID |
| Shared mapping | Returned a valid, aligned mapping |
| One wait0 allocation | Native16-byte packet with matching allocator header/guards |
| One cancellation/free | Returned0; **no send attempt** |
| Unmap, close | Each attempted once and returned0 |
| Process completion | Ownership NONE; worker absent in `/proc` |

This establishes the never-sent allocation/cancel case in that VM. It does
not authorize the same teardown after sending: a matched reply, empty poll,
or successful close is not a peer-quiescence proof. The retained-UNKNOWN path
remains in the component and test worker; this successful run did not exercise
an unresolved native outcome. CP receipt, native AP child creation, capture
and camera-side operation remain unverified.

## Follow-up: AP local send/receive/free

A fresh private guest completed an AP self-loop using its own newly allocated
user queue ID for allocation, source, destination, receive and release. The
driver allocated32 bytes; the worker set an opaque test payload, sent once,
called the public `ap_poll_once.c` once with timeout0, checked the received
header/guards and every payload word, then released the received message.
Allocation, send, receive, free, unmap and close returned0; ownership resolved
and the worker exited. The received pointer matched the outgoing pointer.
There was no post-send access until the receive returned caller ownership,
and no payload/header access after free.

This is an AP-local test message, not a CP status response or capture command.
Pointer equality is specific to this self-loop; it is not a requirement for
independently allocated CP replies. Source and receive IDs are equal here,
so this case does not test the different-ID release contract of a CP reply.
It does not exercise `ap_reply_once.c` or qualify a real remote peer.

`audit_send_admission.py` also checks the original driver's missing-transport
branches. With either the transport object or its function absent, the code
logs and returns0. The audit stops before that log, then runs the independent
post-log return instructions; it does not fabricate a successful log/callback.
Thus a zero send result alone cannot authorize CP receipt or context teardown.

## Follow-up: original PCIe transport registration

A separate guest profile disabled AP launch and loaded the original
`pcie-if.ko`. The module load returned0. Read-only QMP samples of actual
kernel memory, with addresses derived from original section offsets and
guest sysfs section addresses, confirmed:

- UIPC's callback slot changed from zero to the PCIe module's actual table.
- Its async/sync entries matched the original module's expected functions.
- The sender initialization signal remained **0**.
- Native high/low PCIe interrupt descriptors were present; both observed
  counters were0 in this run.

The module identities were checked inside the actual boot image. No CP request
was sent, no readiness value was forced, and no native module was unloaded.
The first observer attempt failed on HMP filename syntax before module loading;
its original report remains. The corrected independent run completed, and
the disposable guest was closed.

This verifies registration, not CP startup or working DMA. The underlying
VM still omits parts of normal PCIe/PCIDMA hardware initialization. Table
presence cannot replace a functioning peer, native initialization, firmware
qualification or a matched reply.

`audit_transport_registration.py` separately checks11 original contracts.
UIPC rejects an occupied registration slot, but the PCIe wrapper discards that
return and reports0. UIPC also accepts a nonzero table without validating its
first function. The init signal is stored before wait notifications, and
unregister only clears the pointer. None supplies a peer-drain guarantee.

## Follow-up: initialization and unimplemented hardware

The existing lab's catch-all bus shim returns `0xffffffff` for missing MMIO
and absorbs writes. Polling a ready bit against that value cannot establish
hardware readiness. An independently relinked private QEMU adds `legacy`,
`zero` and `fault` controls over the source-qualified PHY/controller windows.
Twelve firmware-free EL1 instruction tests cover read/write in both windows.
Fault mode produces actual synchronous external aborts with exact FAR and
read/write syndrome. It is a negative control, not a PCIe hardware model;
unselected devices still have the lab's existing behavior.

With fault mode active, separate guests boot the unchanged Sony kernel while
allowing both original PCIe/PCIDMA initialization wrappers. All five native
DMA pointers are statically nonzero even when their virtual addresses are
unmapped. Adding the missing virtual-I/O ranges makes all five translations
correct. It does not implement their devices. Native wrappers return0 and
DMA IRQ descriptors appear, but the controlled ranges receive no accesses.

Another guest combines those mappings/initcalls with original `pcie-if.ko`
loading. Native registration again matches the callback table/functions;
its sender initialization signal remains0. No AP or CP request is launched,
no readiness value is forced, and there is no module unload. Retained native
DTB host/endpoint nodes are disabled; the VM uses a generic PCI host. Native
role/fixup behavior and actual CP-core startup remain unresolved. Pointer
presence, mappings, init return0 and registration are separate observations.

## Follow-up: actual GPIO startup condition

Subsequent [staged CP startup](VM-CP-BOOT.md) runs the original mode writer and
architectural handoff against pinned factory data and an explicit alias/GPIO
model. It reaches stock CP runtime entry; physical peer startup remains open.

`audit_transport_startup.py` checks28 original module/kernel contracts. After
its interrupt-output call, module startup reads GPIO **port17/bit4**. It calls
`pcieif_snd_init_done` only when the getter returns0 and the value equals1.
IRQ92 also reaches that initializer before receive/send processing; IRQ91's
first handler boundary is receive processing. Source checks stop before GPIO
access, IRQ operations and thread notifications. Independent post-getter
inputs exercise the exact conditional without fabricating a native return.

A fresh no-AP guest then samples original kernel state before and after loading
`pcie-if.ko`. Port17 is registered at `0xfffffffff102e000`; its input register
translates to physical `0xf102e010`. Both actual snapshots contain0, including
bit4, and the sender signal remains0. Module table/functions still match.
These are the VM's register-backing values, not a physical CP signal. No input
bit, initialization flag or IRQ was forced. A missing register mapping is
therefore not the immediate explanation in this guest; peer behavior is absent.

`audit_cp_exec_mode.py` separately checks105 loader/CP contracts. The loader's
`0xfa0173` lookup supplies the destination pointer for its EXEC_MODE word.
Its low byte is1 only for raw context mode1 with bit2 clear; CP uses that byte
to choose the alternate text source `0xd0220000` versus its existing source.
Byte1 comes from context bit0. That bit's producer calls a GPIO strap helper
whose port/bit are obtained through backup IDs `0xf909d5` / `0xf909d6`.
Negative lookup results or a configured `-1` take the helper's zero path;
positive lookup sizes are also accepted. The real configuration/load/log calls
remain unexecuted boundaries. No live strap values are inferred from these IDs.

The CP consumer at `0x108974` polls byte `0x03e42001`: original instructions
repeat for the generated nonzero byte and return for zero, without changing
the input. A host copy into independent CP test RAM checks the encoding only.
The actual AP destination, cross-core physical alias, production of the real
strap/input, full startup and peer reply remain unresolved. This does not
justify clearing a wait byte, raising a GPIO or marking the CP ready.

```text
python dev/precapture/audit_transport_startup.py --pcie PRIVATE_PCIE_MODULE --kernel PRIVATE_KERNEL_IMAGE --output NEW_PRIVATE_REPORT.json
python dev/precapture/audit_cp_exec_mode.py --loader PRIVATE_NOR_LOADER --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
```

## Follow-up: continuous controller under the original kernel

[vm/workflow_guest.c](vm/workflow_guest.c) links the unchanged
`capture_workflow.c` and `frame_route.c` with file-only **virtual** actors.
The static AArch64 executable's hash is verified inside a fresh no-AP guest
before execution. Eight transactions run on the original `4.9.337-scel+` kernel:

- Pre-trigger selection excludes expired frames and frames at/after S2;
  queued late frames enter before the virtual terminal fence.
- Save → cancel → save rearms the same state with increasing generation and
  action tickets. Releasing S1 after S2 preserves the selected saves.
- Capacity pressure rejects caller-owned references without overwriting held
  pixels; an ineligible synthetic frame never transfers ownership.
- Cancellation before start prevents readout. Full press before an in-flight
  start completion leads through stop/fence/save/restore.
- Even leases are consumed by the virtual writer; odd leases need a separate
  release. Every transferred reference is released exactly once.

All 71 action lifecycles finish. Eight 32×16 16-bit PGM files pass guest
fsync/reopen/content checks. The child exits0 and its `/proc` entry is absent.
After export, a separate host verifier checks every pixel against an independent
formula, action ordering, the exact saved set and release accounting. All files
and journals match a host execution byte for byte. Six corruption cases—pixel
change, missing completion, duplicate request, duplicate application, unexpected
file and duplicate transferred offer—are rejected.

To build this file-only test from the repository root using Zig0.13:

```text
zig cc -target aarch64-linux-musl -O2 -g -static -Wall -Wextra -Werror dev/precapture/vm/workflow_guest.c dev/precapture/capture_workflow.c dev/precapture/frame_route.c -o PRIVATE_DIRECTORY/workflow-guest.elf
```

Run it **inside a disposable Linux VM**, using a new output directory:

```text
/simulation/workflow-guest.elf --virtual-only /tmp/NEW_WORKFLOW_DIRECTORY
```

Export only that directory's two text files and eight PGM files to a private
host folder, then verify it:

```text
python dev/precapture/vm/verify_workflow_guest.py --run-dir EXPORTED_FOLDER --output NEW_PRIVATE_REPORT.json
```

The verifier checks artifacts; it cannot attest their execution origin. The
private VM run separately records kernel/ELF/source hashes and process termination.
This executable includes a static libc and is a guest test, not an integer-only
ROM payload or installer. Virtual metadata is synthetic input to the admission
guard, not evidence of a qualified native frame. No original sensor, CP RPC,
RAW-reference method, recording writer or native completion is substituted with
a successful return. Guest tmpfs is not an SD card. Native camera bindings and
physical pre-capture remain incomplete; no camera was used in these tests.

## Physical follow-up: file/process only

On October23 a fresh, separately sealed temporary job created one child from
the native AP process on the physical camera. It reused `ap_child_exec.c`;
the static child used direct file/process syscalls only. It did not open a
device, issue an ioctl, map shared memory, send CP messages or call original
AP/CP functions. No parameter, ROM or existing AP/CP RAM patch was written.

The first observation was UNKNOWN: an empty cmdline and no finalized child
result did not prove failure or exit. A later bounded observation followed
the **same child**, without another clone, and found:

- A finalized success record: stage3/status0,58 inherited descriptors closed.
- Exactly two descriptors after exec, both belonging to the self-test output.
- Two fresh process samples reporting ENOENT; the child was terminal/absent.
- All owned temporary files matched their expected bytes before removal.
- Complete AP/CP program files unchanged across the session; USB ended normally.

The parent used ordinary clone exit signal `SIGCHLD=17`; no explicit signal,
kill, wait or reap was issued by the operators. Host and camera exclusive
receipts remain archived and must not be reused. Successful exec does not
identify `execveat` versus its ENOSYS-only fallback. Private evidence retains
both the initial UNKNOWN and the successful follow-up, without rewriting them.

This qualifies isolated AP file/process execution on this body. The earlier
VM findings above retain their original scopes. UIPC allocation/cancel in this
new physical child, remote ownership, CP receipt, sensor exposure, retained RAW,
native recording and physical pre-capture remain unverified.

## Follow-up: journaled isolated context (VM only)

A fresh static child now reuses the public context/cancel components with a
bounded append-only journal. Every native context operation has durable BEFORE
and AFTER records; final context/probe ownership is separate from process exit.
The child permits only context-info,16-byte wait0 allocation and cancellation
ioctls. It parks on unknown ownership or journal failure, without sending a
message, retrying an action or exiting on a host deadline.

The same compiled child completed under the original Sony kernel and original
UIPC driver in a fresh disposable VM:6 lifecycle syscalls,3 ioctls,20 records,
ownership NONE and two subsequent absent-process samples. It closed3 inherited
descriptors before exec; its own file check found only the journal/directory
descriptors. The initial VM attempt stopped before child execution because
startup remounted `/tmp`, hiding the initramfs-staged image. Its report remains;
the next guest staged and hashed the same child after boot. No candidate code
or source guard was changed to pass that preflight.

Offline evidence covers40 candidate instruction models and the existing39
context models unchanged. The private journal checks reject18 corruptions;
the shared decoder adds mapping/probe/status checks, rejects25 corruptions
against both the native and modeled journals and retains19 incomplete prefixes.
The source
audit preserves earlier lifetime contracts and separately covers queue stats
and pending references. A success-looking journal with a parked process still
cannot authorize cleanup; empty stats do not prove remote quiescence.

A separate two-file read on the physical body matched the original UIPC module
and user library, with three verified private copies and unchanged rereads.
It did not upload/execute the new child or prove the loaded module's bytes.
The first read attempt stopped on a host identity-schema mismatch before file
reads; the corrected attempt checked the normal-USB and service identities
separately, preserving both checks. No firmware, parameter or RAM patch was made.
Native context operation on this physical body and any CP transaction remain
separate, unfinished gates.

A separate fixed parent, metadata preflight and process observer are now built
for that next physical job, preserving the already VM-tested child bytes.
There are122 offline controls:25 parent,48 preflight/observer,16 malformed
observations,2 reused-BSS cases,18 metadata-only adapter and13 one-shot operator
cases. Only the metadata preflight has a sealed execution scope; it cannot
upload the parent/child or open UIPC. This new job has not run on the camera.
The camera was absent from OS USB inventory during preparation; no connection
or diagnostic was attempted. The previous physical file-only job remains fenced.

## Physical follow-up: never-sent context

A separately reviewed current-source scope subsequently ran the exact
VM-tested journaled child once on the physical body. The metadata preflight
observed kernel4.9.337-scel+, a Live UIPC module and its character device.
It did not establish loaded kernel text identity.

The first process observation was UNKNOWN. The original child and permanent
host fence were retained; a separate metadata-only follow-up observed that
same child, without respawn, explicit signal, kill, wait or reap. Its20-record
journal established6 lifecycle syscalls and3 ioctls: context info, shared
mapping,16-byte wait0 allocation and cancellation, unmap and close. The child
closed62 inherited descriptors; only its two owned output descriptors remained.
All native results and final ownership NONE matched the independent decoder.

Two absent-process samples, the full journal and exact owned bytes jointly
authorized temporary-file cleanup. Four complete AP/CP/driver/library file
rereads matched their fresh sources; both USB sessions ended normally and
the OS subsequently saw normal0E8A.212 private evidence members were archived
and independently verified on both backup volumes. The initial observation
and all fences remain preserved. No CP send, camera parameter/ROM or existing
AP/CP RAM patch occurred. Teardown after sending, peer receipt, sensor exposure,
retained RAW and native saving remain separate unfinished boundaries.

The source acquisition used here supersedes phase81. It preserves the body's
new six-slot/native-ST-dual-domain-v2 color calibration; historical AP/stock CP
images are not restoration targets for this job. Structural FILE matching
does not identify actual loaded look effects.

## Physical follow-up: read-only scheduling metadata

A new independently sealed syscall-only temporary initializer sampled numeric
`/proc` entries, selected process comm/stat/status, read-only scheduler queries
and the two RT sysctls.20 actual-generated-program models,5 result-corruption
controls,10 operator models and5 adapter guards preceded execution. Target
AArch64 headers independently checked the query syscall/flag/structure ABI.

The physical sample found both completion workers, with matching process
identity and scheduling fields before/after: SCHED_FIFO, priority148, allowed
CPU masks4 and8 (CPU2 andCPU3). The native AP caller was normal policy0,
priority0, allowed mask7 (CPU0-2). The observed global RT budget was runtime=-1,
period1000000us. This does not measure group-specific limits, loaded code,
the priority/affinity of a future child or an actual completion/preemption.

The probe sent no message and opened no device. It created no child and made
no signal, scheduler/affinity change, parameter, ROM or existing RAM patch.
All three exact owned temporary files were removed after the complete result;
four full source files remained unchanged, USB finished and normal0E8A returned.
The snapshot does not authorize synchronous RPC or prove physical pre-capture.

The next fixed-file sample confirmed CPU0-3 online and stable process identities,
with the two workers in cpuset groups cpu2/cpu3rt. `/proc/config.gz` and the
guessed CPU-controller root files returned ENOENT. This cannot prove that RT
group scheduling is disabled. The initial direct service-file attempt returned
an empty proc-stat file and stopped; its immutable report/fence remains. A
separately sealed temporary reader reused the reviewed bounded read loop,
passed15 generated-program models,5 result controls,10 operator cases and5
adapter guards, then completed physically. Its three owned files were cleaned,
all four source files stayed identical and USB ended normally. No CP send,
device open, scheduler change or existing program/RAM patch occurred.

## Isolated caller binding: VM pass, physical readback rejection

The new `ap_client_binding.c` component targets only an isolated child's own
affinity and catchable-signal mask.31 generated models check bind/inverse and
every syscall failure, with independent AArch64 header ABI checks. SIGKILL and
SIGSTOP cannot be blocked; this is no guarantee against termination. The
component does not qualify a worker, native callback lifetime or pending RPC.

A new static child adds a bounded272-byte append-only journal.27 actual-child
models preserve unknown states instead of replaying or exiting. The SAME child
then completed under the original Sony kernel in a fresh device-free VM:
36 records,13 bind plus4 inverse calls, affinity and signal-mask readback and
two absent-process samples. CPU0 was selected by a VM-only argv entry, because
that VM has one CPU. The worker bytes were unchanged for the physical candidate.
An initial host harness attempt rejected incompatible lab flags before launch;
its report was preserved, and the next attempt supplied required lab modules.
No candidate/source guard changed to obtain the VM pass.

A separately sealed physical scope admitted one child self-bind/inverse only,
with no device open, ioctl, CP send or existing AP/CP RAM patch.25 parent,
48 metadata-observer/preflight,23 adapter,15 operator,10 follow-up,16 malformed
observation and2 reused-BSS controls preceded execution.252 pinned members
were independently verified on both backup volumes before that execution.

The physical child closed62 inherited FDs and retained its two owned output
descriptors. It stopped after10 bind calls: the CPU2 setaffinity call returned0,
but getaffinity returnedmask7 instead ofmask4. The22-record final journal shows
UNKNOWN ownership; the child parked, with no UIPC/CP/device access and no guessed
inverse or respawn. Its default observed_CPU field is not an actual getcpu result:
execution stopped before that syscall. This disproves physical binding success,
not the component's earlier conditional VM result, and does not identify why
the affinity remained unchanged.

After the owner reported a reload, exact program reads still matched but old
temporary files remained. A same-child metadata observer rejected the old AP
receipt (previous PID518, current519). A NEW fixed recovery reader subsequently
observed ENOENT twice for old PID1522 and the fresh uptime/boot identity. Only
then were the exact failed-job files and recovery files cleaned; raw bytes and
old fences remain archived. Four full program/driver/library reads matched
before/after and USB finished normally. No old program or body setting was
restored. Ordinary shooting is separate from this FILE/process evidence.

Original kernel slices now check its global signed RT-budget guard: runtime-1
returns before per-runqueue bandwidth handling. This is exact cached-binary
evidence combined with prior live-1 samples, not loaded-kernel or immutable
runtime proof. Original UTM source routes mask4 through `/dev/cgroup/cpu2/tasks`
and mask7 through `/dev/cgroup/cpu0_1_2/tasks`. Format/open/write calls remain
BEFORE boundaries; no cgroup write occurred. That alternative needs a new
candidate, live group-mask checks and exact self-membership inverse.

## 简体中文

已用独立原生相机虚拟机实际执行诊断子进程：关闭 5 个继承描述符，经固定 FD
执行新程序，新程序检测到 0 个遗留描述符，64 字节文件内容、nonce 与校验值
匹配，随后确认子进程已退出。它验证了原厂来宾内核中的这段文件／执行流程。

原有相机诊断封存包未动，实机没有操作。真实 AP 子进程创建、IPC／CP、传感器、
RAW 保留和拍摄存盘仍未完成，不能把本测试当作实机预拍摄或上机安全验证。

后续已用原始 UIPC 驱动完成独立上下文的实际建立、查询、共享映射、一次分配／
取消、解除映射与关闭，各阶段返回0。消息没有发送，子进程退出后确认已消失。
它验证的是这一个未发送消息的生命周期，不能据此关闭已有请求在途的上下文，
也不能当作 CP 已接收请求或预拍摄已经完成。

另一次独立测试已跑通 AP 私有队列的32字节本地回环，内容和原生保护字段完整匹配，
接收、释放和退出均通过。它没有连接 CP。原驱动在缺少远端传输回调时也可能返回0，
因此后续不能仅凭发送返回值判断 CP 已收到或安全清理上下文。

原始PCIe模块也已在另一个未启动AP的虚拟机实例中成功装载，内核回调表与原模块
函数地址匹配。但发送初始化标志仍为0，尚无CP握手证据。这次没有发CP请求、
强行改ready标志或卸载模块；注册成功不能代替CP启动、DMA与实际应答验证。

进一步检查发现虚拟机未实现的寄存器原来会返回全1，不能把轮询成功当作硬件就绪。
新加的独立负对照能让选定寄存器访问真实触发总线异常，12项无固件指令测试通过。
原厂PCIe／PCIDMA初始化及5路DMA地址映射已在独立来宾中接回；原模块也能注册，
但初始化没有访问这些硬件窗口，发送初始化标志仍为0，未建立CP通信。

同一连续控制器现已在原厂内核虚拟机里实际跑完8组事务，生成8张虚拟图像、记录
71次动作的发出／执行／完成，保存、取消、重用、迟到帧及逐项释放均通过。程序退出，
导出图像与日志和电脑端逐字节一致；6组故意损坏的材料均被独立校验器拒绝。
这是控制逻辑与内核文件操作的连续验证，曝光／像素／服务回执属于显式虚拟设备；
尚未接通真实传感器、CP、RAW引用和原生写卡接口，因此实机预拍摄仍未闭环。

启动条件进一步定位到原模块读取GPIO17/bit4：读取成功且值为1才通知发送线程。
独立来宾已确认这个端口及地址映射存在，但模块加载前后实际输入位均为0，发送标志
也为0。28项模块／内核原指令合同通过，没有强行修改GPIO、ready或IRQ。

另105项检查把CP早期EXEC_MODE等待字节追到加载器的配置GPIO读取：端口／位来自
备份ID f909d5／f909d6，context bit0进入模式字第二字节，CP原指令据此等待或返回。
测试只在独立RAM间复制编码；真实配置、物理地址别名及CP完整启动仍需继续验证。

10月23日另建并封存的新作业，已从本机AP创建一次子进程并成功执行文件自检：关闭58个
继承描述符，执行后仅保留自己的两个输出描述符。首次观察结果未知时保留原作业，后来
只观察同一进程，取得最终成功记录与两次ENOENT终态证据后，才精确核对并清理临时文件。
AP/CP完整文件前后一致，USB正常结束。clone使用正常SIGCHLD退出信号，操作器没有另行
发信号、kill、wait或reap。没有设备访问、ioctl、共享映射、CP消息或现有程序补丁；这项
实机文件执行结果不能替代CP通讯、曝光、RAW保留、写卡和真正预拍摄的验证。

后续为未发送消息的上下文候选加入了逐次持久记录：每项原生调用前后都记录，未知
所有权或记录失败就停留，不发送、不重试、不因主机超时退出。同一编译文件已在新建
原厂内核虚拟机中完成6项生命周期系统调用、3次ioctl、20条记录及两次退出观察。
首次来宾在执行前因/tmp重挂载遮住文件而停止，保留失败报告；修正来宾暂存路径后，
原候选字节及校验条件没有变化。40项候选模型、原39项组件模型一致；共用解析器分别
对原生/模型日志拒绝25种损坏，并保留19个不完整前缀。另已只读核对当前机身的驱动/
库文件匹配原始来源，尚未上传执行
此候选，也没有据文件匹配推断运行中驱动字节或CP通信。预拍摄仍未闭环。

下一阶段已准备独立启动器与观察器，保留上一轮实际在VM运行过的子程序字节。
122项离线控制通过；当前只封存了读取内核/模块信息、stat设备节点的元数据预检权限，
不允许启动子进程、打开UIPC或执行ioctl。准备期间电脑没有识别到相机，因此没有
上传、连接或执行新诊断；旧文件自检作业及一次性凭据全部保留。

以上是phase84时点；后续phase85另行封存当前来源专用权限，已在实机执行同一份VM验证过
的未发送消息子程序。第一次观察未知时没有重跑，保留原子进程与一次性凭据，再以独立
只观察流程确认同一进程。最终20条日志记录6项生命周期系统调用、3次ioctl，完成查询、
映射、16字节wait0分配/取消、解除映射及关闭，所有权归零；关闭62个继承描述符，
执行后只剩自己的两个输出描述符。两次进程消失与完整日志共同通过后才精确清理文件。
四个程序/驱动/库文件完整读回一致，两次USB会话正常结束，并确认回到正常0E8A身份。
212项私有证据已在两块备份盘分别核对。没有CP消息、参数、ROM或现有AP/CP RAM补丁。
这不证明发送后的安全回收、真实曝光、RAW保留、存盘或完整预拍摄。

phase87另行执行了只读调度元数据探针，实测两个通信完成线程为FIFO优先级148，允许CPU
分别为2和3；AP调用者为普通策略、优先级0、允许CPU0-2。读取前后身份/策略一致，
全局实时预算runtime=-1、period=1000000us。它未发CP请求、未打开设备、未创建子进程、
未改调度/亲和性或现有程序；临时文件精确清理，四个完整来源文件一致，USB正常结束。
这补齐运行信息，仍不代表真实应答、回调抢占安全、组级调度行为或完整预拍摄。

phase88的固定文件读取已确认四核在线，完成线程分组为cpu2/cpu3rt；/proc/config.gz
及猜测的CPU控制器根文件不存在，不能据此声称已排除实时分组节流。直接服务接口读取
动态stat返回空内容而停止，失败作业完整保留；另行封存的临时读取器通过离线检查后
实机读取成功，临时文件清理、四个来源文件读回一致、USB正常结束。仍未发送CP请求。

phase89自身CPU/信号约束组件完成31个生成模型，同一静态子程序在原厂内核VM完成36条日志、
17次绑定/恢复调用及两次退出观察。实机CPU2设置返回0，但读回仍为mask7，因此停留，
没有执行getcpu、逆操作或UIPC/CP调用。不能把默认observed_CPU=0当成已测CPU0。
用户重新上电后，AP PID已变化，旧回执被拒；新只读恢复检查两次确认旧PID不存在，
才精确清理残留文件。所有失败记录和封条保留，四个来源文件一致，USB正常结束。
原厂UTM确实走/dev/cgroup/cpu2/tasks，尚未对它写入；新方案需另做自进程范围与还原核对。

phase90随后只读确认目标组配置及有效CPU均为2、原组均为0–3；AP亲和性仍为7。
这没有证明上次setaffinity读回不符的根因。该探针已精确清理、四个来源文件一致。

phase91另建仅自身分组候选：写入tasks文件的内容固定为`0\n`，内核将其解释为当前任务，
不拼接PID、不创建或截断控制文件。34项组件模型、28项实际程序模型通过；同一静态程序
先在原厂内核单CPU虚拟机验证，再在实机完成CPU2迁入/迁回。各50条记录、24次调用；
实机getcpu实际返回2，亲和性7→4→7，关闭60个继承描述符。首次观察为空时保留同一子进程，
后续两次确认进程不存在才精确清理文件，四个来源文件一致、USB正常结束。
这次没有UIPC设备访问、ioctl、CP请求、参数/ROM/现有RAM补丁或AP/原线程迁移。
下一步是组合信号保护、独立上下文与同步完成生命周期；不能把CPU绑定成功当成发送许可
或真实预拍摄成功。
