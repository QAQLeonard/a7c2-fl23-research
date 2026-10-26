# 开发说明

[首页](../../README.zh-CN.md) · [English](../en/development.md)

这一篇是给维护者和 AI 的唯一总览。先读 [AGENTS.md](../../AGENTS.md)：那里是不能违反的规则。本页讲代码怎么组织、怎么协作；细节请直接看本页指向的代码。

## 范围

- 集成分支：`dev`（由 `develop` 改名）；发布历史保留在 `main`。
- 相机：只支持 Sony ILCE-7CM2、固件 2.01。
- 产品：3.0 桌面程序（`desktop.py`），支持 Windows 10／11 x64 和 macOS 14+ Apple Silicon。两个平台共用界面、规划、相机写入和恢复；只有 USB 驱动、提权和存储卷处理因系统而异。
- 旧版命令行工具（`FL23.cmd`、`lut.py`、`recovery.py`、`shutter.py`、`vertical.py`、`a7look_*.py`、`raw_*.py`）保留给高级用户。它们基于备份的流程，与桌面版不需要备份的直接操作相互独立。

## 目录

| 路径 | 职责 |
| --- | --- |
| `desktop.py` | 入口：界面、`--worker`、`--privileged-worker`（macOS）、`--raw-profile-worker`（Lightroom）、`--offline-self-test` |
| `src/desktopapp/` | 界面（`window.py`、`lookeditor.py`；颜色和状态样式在 `theme.py`）、任务（`jobs.py`）、worker 分发（`worker.py`）、一键安装协调（`allinone.py`）、弹窗文字（`reloadguide.py`、`connectionguide.py`、`lookguide.py`、`completion.py`） |
| `src/desktopapp/actions/` | `catalog.py`：哪些动作会访问相机、哪些需要确认供电。`look_compiler.py`、`sound.py`：离线转换和声音运行时的适配器 |
| `src/desktopapp/platforms/` | 系统相关代码：`usb_drivers.py`（Windows 用 libwdi 装 WinUSB、UAC 提权、卸载）、`windows_pnp.py`、`macos_authorization.py`（终端 + sudo）、`macos_media.py`。`drivers.py`、`macadmin.py` 只是兼容别名 |
| `src/looks/looktool/` | 核心引擎：`direct.py`（不需要备份的事务）、`bundle.py`（组合计划）、`requestcleanup.py`、`compilelook.py`（DCP／CUBE → `.a7look`）、`rawauto.py`／`rawidentity.py`（Lightroom），以及旧版检查点／任务模块 |
| `src/camera_runtime/` | USB 服务会话（`transport.py`）、FL23 规划与资源、macOS 主机辅助（`macos_host.py`）、内置 Sony-PMCA-RE |
| `src/shutter_sound/` | 声音转换／音量、试听、持久安装；`native/` 是 AArch64 相机 worker |
| `src/vertical/` | 竖屏显示 worker 与竖屏资源（**正在重写**） |
| `src/double_exposure/native/` | 实验性的平均／串流核心、文件请求入口、SDK 事件转发、后台流程、DCF 发布及 SIDB 登记；离线候选，实机验收待进行 |
| `src/fl23/` | 旧版独立 FL23 安装器；其 `native/` worker 被各引擎复用 |
| `plugins/A7LookAuto.lrplugin/` | Lightroom Classic 自动识别插件 |
| `calibration/` | 编译器使用的 2.01 虚拟响应模型 |
| `dev/desktop/` | 打包（`build.py`、`desktop.spec`、`prepare_assets.py`、`prepare_presets.py`、`profilepack.py`）与桌面测试 |
| `dev/shutter_sound/`、`dev/vertical/`、`dev/usb/` | 测试、模拟器和研究工具 |
| `dev/release/` | v2.x 命令行时代的发布脚本，以及 `check_publication.py` |
| `desktop-assets/`（忽略） | 仅用于发行的输入：默认六款、配对配置库、Windows／macOS 辅助程序 |
| `build/`、`dist/`（忽略） | 缓存、私有证据和构建产物 |

并非每个保留的源码文件都是桌面功能。独立 CLI 仍使用 `devicejob.py`、`devicecli.py` 和旧 FL23 模块；`fl23_color.py` 用于重建、检查供体彩色资产，`standalone.py` 和 `photobuild.build()` 用于离线重建、核对随包指令模板。原生 worker 源码统一维护在 `src/fl23/native`。某些导入虽未在本模块内使用，却承担对外重导出（`jobs` 动作分类、macOS 卷卸载）或必要的路径初始化（`files_worker` 导入 `candidate`），删除前需核对这些用途。

## 一次点击如何变成相机写入

1. **界面**（`window.launch`）：写入类动作先弹出供电和机型确认，请求里带上 `power_confirmed=True`。界面线程从不直接调用相机、驱动或原生 worker。
2. **任务**（`jobs.new_job`）：创建 `<数据目录>/runs/<UTC 时间>-<动作>-<id>/`，写入 `request.private.json`（schema `a7c2-desktop-job/1`）和 `status.private.json`。
3. **Worker**（`desktop.py --worker`）：每个任务一个新子进程。macOS 上的相机动作会先通过每个任务单独生成的终端 sudo 脚本，以 root 重新运行同一个 worker。Worker 写 `worker.log`，状态依次为 `RUNNING`，然后是带 `result` 的 `SUCCEEDED`，或带 `error`、`error_type` 和完整堆栈的 `FAILED`。
4. **分发**（`worker.run`）：把动作交给对应引擎，见下方动作表。供电确认由实际后端记录，桌面不会测量或输出电量百分比。
5. **界面收尾**（`window.finished`）：读取状态和 `result.phase`，弹出相应提示：断电重开、资源重开、声音提示或安装完成。

`SUCCEEDED` 只代表 worker 正常返回，下一步要看阶段（phase）：

| 阶段 | 含义 |
| --- | --- |
| `AWAITING_RELOAD`／一键安装的 `WAIT_RELOAD` | 已写入并完整读回，需要用户断电重开 |
| `AWAITING_RESOURCE_RELOAD`／`WAIT_RESOURCE_RELOAD` | 名称已写、程序未写；断电重开后继续 |
| `LOADED`／`COMPLETE` | 新开机后核对通过（`COMPLETE` 另外记录了机主的实机检查） |
| `NEEDS_REVIEW` | 已停止。保留现场，结果不明的写入绝不重放 |

数据目录：Windows 为 `%LOCALAPPDATA%\A7C2Tools`，macOS 为 `~/Library/Application Support/A7C2Tools`，可用 `A7C2_DESKTOP_DATA` 覆盖。界面设置保存在 `desktop.json`。

## 动作表

| 动作 | 引擎 | 说明 |
| --- | --- | --- |
| `setup_all` | `allinone.run` | 一键安装／继续；在同一进程内调用其他动作 |
| `driver_scan`、`usb_prepare`、`driver_install`、`driver_uninstall`、`mac_unmount` | `platforms.usb_drivers` | 只处理 `054C:0E8A`、`054C:0336`；已有 WinUSB／libusbK／libusb0 绑定直接沿用 |
| `connect`、`usb_stability` | `devicesession.Camera`、`usbcheck` | 只读 |
| `direct_factory_reset`／`direct_verify` | `looktool.direct` | 内置原厂参考；每次按当前相机字节重新规划 |
| `direct_fl23_enable`、`direct_fl23_disable` | `looktool.direct` | |
| `direct_looks_import`（→ `direct_resume_looks`） | `lookbatch` + `looktool.direct`（`install_all`） | `operations`：`slot`、`action=write/restore`、`path`、可选 `name` |
| `vertical_enable`、`vertical_disable` | `looktool.direct`（持久） | 正在重写 |
| `sound_on`、`sound_off` | `looktool.direct`（`sound_enable/disable`） | |
| `sound_mechanical_on`、`sound_mechanical_off` | `looktool.direct`（`sound_mechanical_enable/disable`） | 原生扬声器分段音效；保留电子音效开关及快门设置 |
| `sound_import`、`sound_volume` | `actions.sound` → `shutter_sound.sound_cli` | 只在电脑上处理，不连接相机 |
| `sound_audition`、`sound_install`、`sound_verify`、`sound_restore_sound` | `actions.sound` | 相机操作 |
| `compile_look` | `actions.look_compiler` → `looktool.compilelook` | 离线 |
| `plugin_install` | `desktopapp.plugins` | 可选 Lightroom 插件，自带 ExifTool |
| `restore`、`restore_auto`、`restore_verify` | `checkpointjob.Rollback` | 从所选或发现的完整备份恢复（可选） |

替换前端时，只需调用 `jobs.new_job(action, arguments)` 和 `jobs.worker_command(...)`，并按上表理解阶段。参数名与 `Window.common()` 和动作表保持一致。

可选动作 `backup_current` 由 `desktopapp.backup` 执行，只读保存当前项目检查点，也可另存语音包 ZIP，不要求供电写入确认；macOS 仍按相机只读任务取得所需权限。

## 核心流程

**可选当前备份：**恢复页可生成沿用现有格式的 `checkpoint.private.zip`，保存当前 AP／CP 程序、运行／保存设置和 68 份名称资源；来源标记为 `current-project-backup`，可手动选择还原，但不参与自动寻找最早原始备份。可选 `voice-resources.private.zip` 单独保存二十份语音指南文件，在所选检查点还原需要解除语音关闭限制时作为语音恢复来源。安装和内置原厂恢复均不要求先备份。语音资源也可由 `desktopapp.screenreader` 从用户自行提供的 2.01 更新文件在本机提取，应用不内置这些数据；语音写回采用 1 MiB 分块写入固定暂存文件，完整校验哈希并逐文件发布后，才解除关闭限制。

**直接事务**（`looktool/direct.py` 的 `DirectJob`）：
1. `plan()` 是纯函数：把相机当前字节转换为目标字节和要改的设置，每种模式只改自己声明的区域。`bundle.plan()` 把多个模式（FL23、外观、ST 恢复、声音、竖屏）叠成一个计划。
2. `run_direct()` 的顺序：读取当前状态 → 生成计划 → 保存 `PLANNED` → 原生预检 → 先写名称、再写程序窗口 → 完整读回程序 → 名称资源 → 设置 → WBI → `AWAITING_RELOAD`。每一步都记在 `direct.private.json` 里。
3. 名称写完后，如果只读重新挂载返回 EBUSY，就停在 `AWAITING_RESOURCE_RELOAD`。等核对到新的开机后，再用新事务写程序。
4. `verify_direct()` 用当前字节重新算一遍计划，必须已经无事可做；再核对 RAM 和已保存设置、确认 `boot_id` 已经变化（证明确实冷启动过），并确认已加载的程序与磁盘一致。恢复原厂另外要求 `/usr` 为只读挂载。

**一键安装**（`allinone.py`，状态保存在 `setup.private.json`）：
`READY → DRIVERS → PREPARED → INSTALLING → WAIT_RELOAD →（核对）→ FINALIZING → COMPLETE`，另有 `WAIT_RESOURCE_RELOAD` 分支。
- `FINALIZING` 阶段接入声音、安装插件和 RAW 映射，并核对竖屏的持久化状态。
- 失败后再点继续：写入前就失败的子事务会改用新的 `install-retry-*` 计划；结果不明的则停止，保留现场。

**恢复原厂**：`src/looks/assets/factory-layout-2.01.json` 只包含位置、长度及原厂内容摘要。`official.prepare_restore` 在打开 USB 前，从用户提供的官方 2.01 文件或可用同机原始备份提取实际恢复字节；本地私有缓存支持重启后的完成核对，不随软件分发。一个主按钮先开始恢复、重启后继续完成。是否补回语音记录在本次事务中，取消补回时保留语音禁用限制；其他字节和机身校准保留。

**USB 服务入口**（`camera_runtime/transport.Session`）：
1. 检查普通 USB 的产品字符串。
2. 认证。
3. 等待 `0336` 出现。
4. 再次认证。
5. 用属性 `00e70003`（十六进制文本序列号摘要）绑定机身。

如果 `0336` 始终没出现、相机回到了 `0E8A`，会冷却 30 秒后重试，最多 3 次。认证没到达 `0336` 时，之后不会再向相机发送任何命令。

**声音**（`src/shutter_sound/`）：`media.py`／`native_codec.py` 在电脑上转换音频；`sound_cli.py` 同时驱动桌面版和 `shutter.py` 的流程；`candidate.py`／`boot_sound.py`／`files_worker.py` 构建固定的原生修改。试听和确认记录是可选的，不影响保存。

**外观转换**：`compilelook.py` 解析 DCP 的 LookTable／色调曲线，或 ST／sRGB 的 CUBE，再用 `calibration/a7c2-2.01.virtual.npz` 拟合成机内色表，不需要 Lightroom。支持哪些输入见 [LUT 格式](lut-formats.md)。

语音空间由 `voicelock.py` 限制原生支持入口和三个普通设置写入口，共四个既有指令窗口、20 字节；另将五个语音菜单各十三个模式状态从 1 改为 2，共 130 字节数据，保留原生非零可见判断，但不满足等于 1 的可选判断。设置与触发值保存为关闭。新一键安装固定先执行 `voice_cleanup`，首次写入限制后要求断电重开，后续请求必须通过实际加载指令核对，才删除十种语言的音频 BIN，保留索引。`resource_files.c` 只接受编译时固定路径和当前读取的大小／哈希，每次操作后将 `/usr` 重新挂为只读，文件完整哈希一致后才发布恢复结果。原生仿真使用合成文件系统，不证明真实掉电后的文件系统行为或启动安全。原厂恢复将快门设为机械、静音模式关闭、恢复原生声音路径，重开核对后才清理私有音效文件并完成；保留对焦提示音设置。

原生竖屏候选由 `desktopapp.vertical_native` 先沿用既有逆向撤回旧补偿并要求冷重开。`verticaltool.nativeportrait` 使用当前机身图片与既有竖屏绘图生成独立 `_23` 库，保留原图像 ID，`_32` 横屏原库与 AP 绘制代码保持原生。`resourceworker` 只接受三个固定图形库路径，复制前检查已加载的原生 AP 窗口；原生 worker 在资源修改时还要求运行中竖屏开关为 OFF。`verticalpersist.Stage` 可识别完整或部分本项目文件，用于关闭／恢复；原厂恢复语音前先回收这些文件。需要撤回旧补偿并重开的新一键安装，在程序／LUT 阶段前暂停。当前只通过离线验证，尚未真机验收。

## 构建与测试

使用原生 64 位 Python 3.11：

```text
python -m pip install --no-build-isolation -r desktop-requirements.txt pyinstaller==6.16.0 pytest==8.3.5
python -m pytest dev/desktop dev/shutter_sound/tests dev/vertical -q
python desktop.py
```

根目录的 `conftest.py` 在所有测试中禁止枚举实体 USB。其他测试：`python -m unittest discover -s src/looks/tests`，以及 `src/fl23/tests`、`src/camera_runtime/tests`、`dev/usb/tests`。私有样本（`A7C2_RESEARCH_FIXTURES`）是可选的，没有时相关测试会跳过。

**双重曝光开发**：`dev/double_exposure/build_jpeg.py` 使用本地未修改的 libjpeg-turbo 3.1.2 源码、Zig、CMake 与 Ninja，构建静态 ARM64 Linux 处理器。传入 `--source`、`--output`、`--zig`、`--cmake`、`--ninja`；`--target host` 可将同一份 C 流程构建为本机测试程序。构建工具列在 `dev/double_exposure/requirements.txt`，输出目录包含编解码库的声明与许可。处理器读取两张已完成写入、尺寸／方向一致的基线 8 位 sRGB／无标记 JPEG，逐行对 RGB 采样取平均，另存质量 95 的 JPEG。运行 `python -m unittest discover -s dev/double_exposure -v`；内核测试需要 `A7C2_ZIG`，JPEG 测试需要将 `A7C2_JPEG_COMMAND` 设为程序或运行器命令的 JSON 参数数组。处理器尚未加入桌面安装包、相机菜单或拍摄钩子；处理文件本身不会将结果登记到相机媒体库。

`capture_pair.c` 是独立的无外部依赖配对器，实际适配层需要提供已关联的拍摄开始／完成事件、解析后的 JPEG 路径和介质代次，并持久保存会话状态；它本身不执行 I/O 或固件调用。拍摄结果解析只读取预留身份。可选将 `A7C2_CAPTURE_AP` 指向原始 2.01 `appFw.so`，在模拟器中与原生自动回放读数函数对照目录／文件编号；此检查拦截模型／字符串辅助调用，不执行相机硬件操作。

配对器允许源图、暂存和媒体库条目使用原生 Fsys 或 POSIX 路径；实际执行的适配层必须另行取得输出所有权，提出暂存路径本身不等于完成预留。原生 Fsys 路径不能直接交给独立 Linux 文件处理器的 POSIX 接口。

`jpeg_stream.c` 通过调用者持有的读写回调执行相同的平均处理。`mpr_stream.c` 适配已初始化 AP 进程中的同步 MPR 文件函数和 Fsys 刷新函数，由调用者提供函数指针。只读打开使用原生标志 1，路径／句柄存活期持续到关闭。写入端只能附接到调用者已持有的暂存句柄，不自行创建或截断目标。核心不刷新、关闭文件、发布或登记输出，这些仍属于调用者的事务。运行时绑定器已实现，但尚未对真实 SDK 执行。

使用独立输出目录构建 `--component stream`，可得到本机库或面向 glibc 2.25 的 ARM64 共享库；相机构建会检查 ELF 依赖及所需 libc 符号版本。`A7C2_STREAM_LIBRARY` 指向本机 DLL／SO，供读写回调及适配测试使用。相机目标加 `--harness` 可额外构建仅供测试的模拟 MPR 程序，`A7C2_STREAM_COMMAND` 是其运行器命令的 JSON 参数数组。该程序在 QEMU 中验证共享库 ABI，不代表真实相机读写。

共享模块内的编解码符号保持局部绑定；原生测试程序故意导出不兼容的宿主编解码符号，确认核心不会调用它。

`ap_runtime.c` 只绑定已载入的 SDK（`RTLD_NOLOAD`），核对函数所属模块并保留核心自身引用。`BOUND` 只代表导出已解析，不代表相机／SDK 已就绪。任务使用引用需要持续到读写及句柄核对完成；回调使用引用需要持续到注销与原生回调全部结束。退出会拒绝仍有使用引用的情况，并将模块引用交还调用者，在核心函数之外关闭。绑定本身不初始化 SDK、不操作照片、不安装回调。`--harness` 还会构建加载测试程序及 `test-sdk/` 中的模拟 SDK 库；它们只用于测试，不能作为设备资源。`A7C2_BINDING_COMMAND` 是该 ARM64 测试运行器命令的 JSON 参数数组。

`output_reservation.c` 将纯规划／意图状态与实际创建目录／打开暂存文件分开，每个 SDK 步骤前需先持久记录意图。它使用选定 DCF 照片目录下新建的独立目录，单独的“写入＋创建”标志 6 不建立独占所有权。既有或结果不确定的状态会保留，不自动重试或删除。下面的统一流程接入发布、媒体库登记及模块加载；当前实际执行的 SDK 测试仍全都使用本地模拟后端。

`bootstrap.c` 是独立的小型显式调用加载控制器。它解析并核对核心 ABI／启动／查询／退出导出的所属模块，在控制调用期间保持临时模块引用，只在核心返回后关闭交还的自身引用。查询／退出使用 `RTLD_NOLOAD`，关闭失败即停止，不重试。外层调用者必须串行执行请求、先持久记录调用意图并保留未知结果。`dev/double_exposure/build_bootstrap.py --output <dir> --harness` 构建 ARM64 控制器（限制为 64 KiB 内）及测试加载程序。它没有 libJit `_init` 分发入口或设备传输。载入已校验核心仍可能执行其 ELF 启动代码，因此必须先验证文件及其所有权。控制器报告不包含可转交的加载句柄。

`dev/double_exposure/staging_model.py` 模拟离线本地事务：每块 48 KiB，逐块及完整核心 SHA-256，新目录所有权、先记录意图以及本地不覆盖发布。重新打开时核对所有已确认字节；未完成意图保留证据并停止，只有校验通过的已确认前缀可以续传。它不实现相机上传，也不证明相机文件系统／断电行为。`READY` 只表示字节已校验，不表示 ELF／SDK 就绪。设置 `A7C2_ZIG` 可执行九项加载故障注入测试；`A7C2_BOOTSTRAP_COMMAND`（以控制器路径和模拟 SDK 目录结尾的运行器 JSON 参数数组）与 `A7C2_STAGE_CORE` 可启用五项实际 ARM64 加载测试，包括先分块重组核心，再完整载入／退出。

`staging.c/.h` 将模型落实为原生 Linux POSIX 接收器。80 字节的小端请求包含事务身份、核心大小／哈希、操作和块编号；CREATE 另附各块哈希。CREATE 取得新目录所有权，PUT 只接受下一块，ASSEMBLE 独立核对完整核心哈希并以不覆盖方式发布，QUERY 重新核对不可变计划、意图／数据／确认记录及实际文件内容。未完成意图会停止而不重放；丢失回复后，只有持久确认和字节匹配才能通过 QUERY 核对结果，重复 PUT／ASSEMBLE 仍会被拒绝。目录 `flock` 串行化配合协议的调用者；基于目录描述符、不跟随链接、独占创建的操作保留外来文件，只移除成功发布后本次组装的临时链接。报告为 112 字节，`pending_fd` 仅作诊断证据，不能据此重试关闭。

使用 `build_bootstrap.py --component staging --output <dir> --harness` 构建独立小型 ARM64 接收器及本地测试程序。`A7C2_STAGING_COMMAND` 是原生运行器的 JSON 参数数组，`A7C2_STAGING_FAULT_COMMAND` 是单独的故障注入运行器。二十九项 ARM64 测试覆盖 SHA-256 填充边界、并发请求、损坏、部分／零写入、读回／刷新／关闭失败、进程中断及发布重名；其中一项由 C 接收器接收实际核心，再使用模拟 SDK 库载入／退出。另有两项主机协议编码测试。接收器本身没有 SDK／照片读写，下面的文件入口和统一流程接入其已校验的输出。

`file_entry.c` 是小型一次性 libJit 文件请求入口。构造函数只读取固定的 `/tmp/jiritsu/a7c2.dex.{request,payload}`，执行前独占建立结果意图文件，返回时追加带校验与完成标记的结果。暂存使用 80 字节协议，控制使用 64 字节 `A7DEX001` 的 ARM／WORK／QUERY／DISABLE 协议。ARM 要求核心暂存完整且已校验；QUERY／DISABLE 只使用 `RTLD_NOLOAD`。命令凭据完整不等于照片已完成。使用 `build_bootstrap.py --component entry --output <dir> --harness` 构建，入口文件限制在 64 KiB 内；大的暂存缓冲放在堆／模块内存，不占 AP 请求线程的大块栈空间。测试运行器关闭自动构造函数执行，仅使用明确的本地测试目录。

`device_request.c`、`pipeline.c`、`native_session.c` 与 `resident_entry.c` 连接请求、回调队列、JPEG 平均、发布、SIDB 事务与独立确认。一个后台线程使用 512 KiB 栈，回调只复制有界事件并唤醒线程，文件／编解码／媒体库操作都在后台执行。意图和结果以只追加、带校验的记录写入独立的新建 POSIX 任务目录。未知结果保留源／结果路径、待核对句柄、原生错误和 UID，不重放。DISABLE 可以排在正在运行的任务之后，等上下文排空才完成。实例身份及递增请求编号阻止旧请求启动新任务。报告不包含指针：流程报告 2,800 字节，设备报告 2,832 字节。

`sony_sdk.c` 核对已载入 Sony 库的导出，并检查映射范围和 2.01 AP／DCF 布局。`sony_begin.c` 原样转交 SDK countdown／write-finished 的原始参数指针；SDK 的 88 字节通知保留了 AP 转换前的照片 UID，再由后台重新 Select SIDB 解析路径。原有 AP delegate 的注册／注销仍由原所有者管理。停用时排空 sink／上下文，转发代码、SDK 引用及 AP 代码因缺少可证明的 SDK 指针分发卸载边界而保留至 AP 进程结束，停用一组拍摄不能据此热卸载／替换驻留核心。独立的 `capture_delegate.c` 适配接口要求调用者掌握原 delegate 所有者的完整生命周期，生产路径使用 SDK 转发。这些适配不安装传感器、固件或设置补丁。

`dcf_publish.c` 选取空闲的 DCF 数字目录，在原生编号互斥锁下预留／确认目录条目及文件编号位图，建立新目录并发布 `A7AV0001.JPG`，重新枚举数字别名，对照编码写入流的摘要核对暂存文件完整读回，再校验移动后的目标哈希；目录缓存更新使用原生字符串构造与赋值。当前原型每组结果新建一个目录，适用 DCF 的 100..999 上限。`media_catalog.c` 使用原生记录 clear／Select、IssueUniqueId、Update 和 Flush，保留源图时间，只领取一次新 UID，重新 Select 确认路径／大小／时间后才进入 COMPLETE。

`dev/double_exposure/device_driver.py` 只接受调用者明确提供的已打开会话，导入／构造不会枚举、认证或连接 USB。显式 stage／arm／query／disable 操作使用有界上传、持久主机意图及对应凭据归档；删除前核对全部本次临时内容，最后删除结果，遇到不确定结果保留证据并阻止后续命令。每个驱动用非阻塞锁覆盖完整操作及电脑端状态保存。操作开始后，任何失败（包括原生请求返回后的最终日志保存失败）都会将驱动标为 REVIEW、会话标为 unhealthy/mutating，禁止继续发命令；开始前发现的 ARM 参数错误仍允许修正。不同驱动实例共用会话时，外层仍须保证独占。现有传输允许列表只增加三个固定临时文件名；桌面尚未提供这个开发接口。

ARM 可以传明确的原生介质 ID，也可使用驱动默认的 `UINT32_MAX`，由第一条有效 SDK begin 通知选择介质，再将两张照片绑定到该 ID。应在没有拍摄进行时 ARM，并查询确认请求已接受后再拍两张。

`A7C2_PIPELINE_LIBRARY` 用于主机集成测试，`A7C2_PIPELINE_COMMAND` 用于 ARM64 异步流程运行器，`A7C2_FILE_ENTRY_COMMAND` 用于 ARM64 文件入口运行器（后两项为 JSON 参数数组）。`A7C2_NATIVE_MPR` 可指向本地原始 2.01 库，在模拟 RAM 中重放编号位图辅助函数，原始库不随项目分发。测试使用模拟 SDK／AP 提供者和本地文件，验证实际编译的编解码／控制代码及失败／排空约定，不是对真实 Sony SDK 执行。真实拍摄、预览／回放、介质插拔、相机文件系统／缓存行为、AP 重启和断电验收仍待进行；介质代次由调用者提供，其逻辑编号或导出解析成功都不能代替实机验收。

**打包：**
1. 准备被 Git 忽略的发行资源：`python dev/desktop/prepare_assets.py`。用 `--preset-archive <zip>` 从导出的资源包或 Windows 安装包中导入默认六款和配对库；用 `--export-presets <zip>` 导出资源包。
2. 构建：`python dev/desktop/build.py`。

产物：
- **Windows**：`dist/A7C2Tools-Windows-x64.zip`，包含 `A7C2Tools.exe`、`_internal/`、`Profiles/`（配对库）、两份 README 和 `LICENSE`。
- **macOS（仅 Apple Silicon）**：`dist/A7C2Tools-macOS-arm64.dmg`，配对库在 APP 内部（`desktop-assets/profile-library-v1`）。
- `profilepack.py` 要求富士 11 组、理光彩色 4 组配对全部齐全，否则拒绝打包。黑白配对只有满足独立误差标准（MAE ≤3/255、P95 ≤12/255）才能加入。

CI：`.github/workflows/desktop-preview.yml` 在原生 Windows 和 `macos-15` runner 上构建并上传产物，不发布 Release。修改 `dev/desktop/native-build-request.json` 会触发 Apple Silicon 构建。ARM64 上 Keystone／Unicorn 从源码编译（需要 Xcode 命令行工具和 CMake 3.31.6）；Zig 版本为 0.13.0。

安装包没有 Developer ID 签名。离线测试、打包自检和字节读回都不能证明相机能安全启动，也不能证明颜色或声音正确。实机验收单独记录在[更新日志](changelog.md)中。

## 文档规则

文档保持精简：

| 文件 | 读者 |
| --- | --- |
| `README.md`／`README.zh-CN.md` | 用户：下载、操作指南、常见问题 |
| `docs/*/lut-formats.md` | 用户：支持的 LUT／DCP 输入 |
| `docs/*/changelog.md` | 所有人：版本历史和测试记录 |
| `docs/*/notices.md` | 所有人：来源与许可 |
| `docs/*/development.md` | 维护者和 AI：本页 |
| `AGENTS.md` | AI：不能违反的规则 |

每篇英文文档在同一路径下都有对应的简体中文版，两者保持同步。不要再新增按功能拆分的说明或研究笔记：直接读代码，把决策记在更新日志或提交说明里。历史文档保留在 git 历史中。
