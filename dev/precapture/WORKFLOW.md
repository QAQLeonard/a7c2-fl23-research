# Pre-capture workflow review

Reviewed on October 21, 2026 (Asia/Taipei), against code `094a214`.
**The continuous native-camera shooting workflow is not established.**

Subsequent implementation: [CAPTURE-LIFECYCLE.md](CAPTURE-LIFECYCLE.md) describes
the new continuous controller and virtual-pixel transaction tests. It does
not replace the missing native bindings in the table below.

The controller has since also run unchanged in an original-Sony-kernel
full-system guest, with eight continuous virtual-device transactions, eight
pixel files and 71 complete action lifecycles. [VM-PROCESS](VM-PROCESS.md)
records this additional evidence. Actual CP/ISP/sensor/native-writer services
are still absent from those transactions, so the native workflow remains open.

The existing Unicorn ARM/AArch64 instruction emulator ran 28 offline check
groups, including both linked runtime variants. Those checks pass within
their stated scope. They execute generated components and original firmware
slices with synthetic inputs. They do not emulate the complete camera,
sensor, ISP, RTOS scheduling or SD storage. Original external-service calls
remain stop boundaries; separate slices are not a continuous execution.

User-facing completion also requires an independent in-camera **Pre-capture:
Off / On** control, initially Off and enabled manually. No such menu or live
control binding exists yet. Turning Off must complete native cancellation,
fencing and release; after S2, already-triggered saves must finish before the
feature reports disabled. A hidden background enable is not the requested
product. Menu/resource/parameter bindings need their own safety validation.

| Stage | What the emulator checks | Missing connection or evidence |
|---|---|---|
| Manual in-camera switch | Requirement only; no menu implementation | Independent Off/On entry, default Off, actual enabled-state binding and verified disable/release behavior |
| Load and initialize | Linked code, runtime publication checks, rejection of incompatible sources | Real executable-page ownership, loader integration and fresh loaded-source admission |
| Configure | Request encoding, disabled-only configuration, generation matching, error states | Live AP/CP transaction and safe context lifetime/teardown |
| Half-press | Start/stop predicate and request13 command construction | Native admission, timer/sensor execution and actual pre-trigger exposures |
| Prepare a frame | Original parameter acquisition/producer, derived flag and marker consumption | Real parameter refresh before cancellation release; a committed enabled word does not update an existing parameter object |
| Retain pixels | Native frame-class/retention selection and time-policy decisions | Eligible physical frames, RAW-buffer ownership, capacity and cross-task delivery; marker2 alone is insufficient |
| Full-press/save | Native recording-reference handoff and dequeue routing decisions | Saving actual retained pre-trigger pixels as photographs |
| Cancel/finish | Original marker3, event4, S2-reference and later-stage owner slices | A terminal fence excluding late frames and completing actual pixel/holder release; state0/count0 is insufficient |
| Restore/ordinary shooting | Empty-idle policy inverse and ordinary-routing models | Physical restoration, ordinary shooting and look preservation after a real pre-capture transaction |

Specific observations reproduced in this review:

- [Parameter lifecycle checks](verify_frame_gate_hook.py) reproduce a stale
  derived flag when only committed state changes. Re-running the original
  producer updates it. The test does not deliver a real refresh event.
- [Frame classification](audit_frame_profile.py) and
  [retention admission](audit_retention_entry.py) execute original target
  and donor selectors. Their synthetic input distributions are not camera
  success rates or a mapping to named drive/shutter modes.
- [Retention policy](verify_retention.py) passes 3,186 native-comparison and
  configuration cases. [Storage initialization](verify_storage.py) verifies
  500 metadata nodes, not 500 full-resolution image buffers.
- [Linked entry tests](verify_runtime_entries.py) pass 106 ABI3 and 135 ABI4
  boundary cases. Native sends, posts, frees and enqueues are not executed.
- [Terminal processing](audit_retention_terminal.py) and
  [later-stage ownership](audit_late_stage_owner.py) show why queue emptiness
  does not establish completion of image-resource release.

The archived six-look reference is also rejected by the old runtime source
guard before candidate generation. It is not a fresh camera read. Keep the
guard intact; compatibility requires separate exact-source qualification.
No camera operations were performed in this review. Detailed originals,
commands and reports remain private. See [README](README.md) for check inputs
and [CONTROL-PATHS](CONTROL-PATHS.txt) for source contracts.

## 简体中文

2026 年 10 月 21 日重新执行了 28 组离线检查，覆盖加载、配置、半按、帧参数、
保留策略、全按路由、结束清理和还原模型。检查通过，但连续拍摄流程尚未走通。
这里使用的是 ARM 指令模拟器，没有完整相机的传感器、ISP、实时系统与存储硬件。

完整交付还需要独立的机内“预拍摄：关／开”入口，初始为关闭，由用户手动启用。
目前没有实现这个菜单，也没有接通其真实状态。关闭时必须完成取消、终态栅栏和释放；
若已全按触发，则先完成已触发的保存，再报告已关闭。不能默认在后台启用。
菜单资源、参数绑定与界面安全需要单独验证。

主要断点是：真实加载与通信生命周期、参数刷新及传感器启动、RAW 像素所有权和
跨任务保留、实际保存预触发照片，以及取消后的所有资源释放。已复现“启用开关
改变不会自动更新旧参数对象”；队列为空也不能作为像素释放完成的证明。

本轮没有操作相机。旧版本运行时对现有六款外观参考文件仍会拒绝，不能放宽指纹
强行继续。此前造成半按崩溃的 `00030072` 参数方案继续停用。离线通过不代表
预拍摄已完成，也不构成新补丁的上机批准。
