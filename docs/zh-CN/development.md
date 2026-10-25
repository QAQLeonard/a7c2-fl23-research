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
| `src/double_exposure/native/` | 实验性的平均内核、拍摄配对器、串流 JPEG 核心与 MPR 读写适配；尚未接通真实绑定、拍摄钩子与媒体库登记 |
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

配对器允许源图／媒体库条目使用原生 Fsys 盘符路径，这些路径不能直接交给独立 Linux 文件处理器的 POSIX 接口；其文件任务中的暂存输出仍使用 POSIX 路径。

`jpeg_stream.c` 通过调用者持有的读写回调执行相同的平均处理。`mpr_stream.c` 适配已初始化 AP 进程中的同步 MPR 文件函数和 Fsys 刷新函数，由调用者提供函数指针。只读打开使用原生标志 1，路径／句柄存活期持续到关闭。写入端只能附接到调用者已持有的暂存句柄，不自行创建或截断目标。核心不刷新、关闭文件、发布或登记输出，这些仍属于调用者的事务。适配层目前尚未绑定真实 SDK。

使用独立输出目录构建 `--component stream`，可得到本机库或面向 glibc 2.25 的 ARM64 共享库；相机构建会检查 ELF 依赖及所需 libc 符号版本。`A7C2_STREAM_LIBRARY` 指向本机 DLL／SO，供读写回调及适配测试使用。相机目标加 `--harness` 可额外构建仅供测试的模拟 MPR 程序，`A7C2_STREAM_COMMAND` 是其运行器命令的 JSON 参数数组。该程序在 QEMU 中验证共享库 ABI，不代表真实相机读写。

共享模块内的编解码符号保持局部绑定；原生测试程序故意导出不兼容的宿主编解码符号，确认核心不会调用它。

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
