# 开发与验证指南

[返回首页](../../README.zh-CN.md) · [English](../en/development.md) · [变更记录](changelog.md)

本文对应基于上游 `0bf1dbb` 的修复分支，目标为 Sony ILCE-7CM2 固件 2.01，包含电脑端流程修复与新版 FL23／LUT 兼容适配。这是开发版本，尚未完成实机发布验收。首页下载链接仍指向上游 Release，不会自动包含本分支尚未合入的修改。

## 1. 入口与职责

| 入口 | 职责 | 是否操作设备 |
|---|---|---|
| `FL23.cmd --help`、`--check`、`check-package` | 帮助、电脑环境或套件资产检查 | 不连接 |
| `FL23.cmd prepare ...` | 确认版本、绑定机身、双份备份、完整存档、候选及原生预检查 | 连接 USB／服务模式，会执行临时诊断 |
| `FL23.cmd install ...`／`verify ...` | 安装已准备事务／核对程序、设置及已加载 AP 片段 | 连接设备；安装会持久写入 |
| `python lut.py` | 单槽外观转换、导入、重载核验、单槽撤销 | `doctor` 和离线研究命令不连接；设备任务会连接 |
| `python recovery.py` | 从完整存档或支持的旧备份独立完整回退 | `inspect` 离线；restore／verify 连接设备 |

当前重构后的图形界面和命令行还保留早期 `check`、`backup`、`restore` 路径。简化备份／自动安装使用原厂备份库，仅接受原厂来源；旧 FL23 还原辅助入口不负责 FL23／LUT 混装的完整回退。兼容开发使用显式 `prepare`，完整回退使用独立 Recovery。`check` 会认证进入服务模式，不属于离线检查；不带 `--write` 的 LUT `import` 也会连接相机并执行准备，只是不安装候选。

## 2. 代码结构

| 源码 | 职责与边界 |
|---|---|
| `dev/windows/bootstrap.cmd`、`src/launcher.py` | 解释器选择、依赖准备、参数和退出码传递 |
| `src/fl23/app.py`、`workflow.py` | 命令行解析及持久化的准备／安装／核验阶段 |
| `src/fl23/usbdev.py`、`transport.py` | 单设备发现、有界服务会话、USB 型号与 AP 序列号绑定 |
| `src/fl23/core.py`、`backup.py`、`layout.py` | 固定原厂资产、本机色彩合并、旧备份结构及校验 |
| `src/fl23/compat.py` | 基于当前字节规划 FL23，保留 LUT 路由，构建事务专用程序并核对候选 |
| `src/looks/looktool/device_layout.py`、`fl23compat.py` | 精确导入来源、槽位位图／色表转换、新版曲线合并 |
| `src/looks/looktool/devicejob.py`、`devicesettings.py` | LUT 事务、新鲜设置保留、读回与重载证据 |
| `src/looks/looktool/checkpoint*.py` | 独立存档、逆向计划、原生模块及完整回退 |
| `src/fl23/native/installer.c`、`src/looks/native/names.c` | 程序窗口与名称资源事务，不提供通用相机 shell |
| `dev/build_lut_compat.py` | 离线复现 `src/looks/assets/runtime-fl23-current.json` |
| `dev/release/` | 源码／单文件打包、文档与发布检查 |

`docs/en/` 和 `docs/zh-CN/` 是当前成对维护的指南。`src/fl23/docs/`、组件 README、`docs/wb_docs/` 保留研究历史；其中旧路径、旧命令和历史观察不能替代当前指南或代码。来源署名和许可见[许可说明](notices.md)。

## 3. 为什么需要新的兼容适配

旧 LUT 导入器识别的 FL23 CP 为 `60a9de1a…`，新版 FL23 产物为 `442c9261…`。仅增加一个允许的哈希不够：LUT 启用代码与 FL23 都修改曲线路由和代码加载信息。

新适配数据由精确匹配的官方 2.01 程序复现，共合并 8 个已核对窗口、982 字节，保留 LUT 路由及较大的代码加载范围。FL2／FL3 的照片／视频分别使用 `(48,46)`、`(49,47)` 行；自定义标记 249–254 保留基于 ST 的路由。旧 `runtime-v1.json` 保持不变，新适配数据独立保存。

| 起始程序 | 计划行为 |
|---|---|
| 精确原厂 AP／CP | LUT 导入构建新版合并运行程序，但不启用 FL23 菜单标志 |
| 精确新版 FL23 AP／CP | LUT 导入保留新版 FL23 曲线，并增加选定槽位功能 |
| 已识别的独立 LUT 程序 | 显式 FL23 准备保留槽位，与“先 FL23 后 LUT”得到相同结果 |
| 已有旧版固定来源 | 继续识别旧导入／更新来源；完整历史回归仍需要作者保留的样本 |
| 未知或冲突来源 | 在身份／字节窗口检查处停止，不通过修改预期哈希强行准入 |

导入来源指纹、备份完整性、机身身份和改写字节检查用途不同。显式 FL23 规划器核对用户确认的版本和真实补丁位置，不使用完整文件来源白名单；LUT 导入保留精确来源／代码身份。单槽和完整恢复核对所属改动与完整字节。任何一种检查都不等同于启动安全证明。

## 4. 开发环境

使用 64 位 Python 3.10+；本次 Windows 验证使用 Python 3.14.7。设备依赖固定 Zig 0.13.0，研究依赖增加 Capstone、Keystone、Unicorn。图形界面还需要 Tkinter。安装依赖不会连接相机。

在仓库根目录的 PowerShell 中，为尚无环境的工作区创建环境：

```powershell
python -m venv .venv
$devPython = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $devPython -m pip install -r src/looks/requirements-device.txt
& $devPython -m pip install -r src/looks/requirements-research.txt
& $devPython src/fl23/app.py --help
& $devPython src/fl23/app.py check-package
& $devPython lut.py doctor --device
```

已有有效环境时复用；不要为了重试而覆盖不完整环境。macOS 使用原生 Python 环境及对应解释器路径；离线可移植不代表已经验证 Mac USB。

## 5. 官方程序样本与适配数据复现

[索尼官方 2.01 更新包](https://support.d-imaging.sony.co.jp/www/cscs/firm/?area=jp&lang=jp&mdl=ILCE-7CM2)使用 [fwtool PR #52](https://github.com/ma1co/fwtool.py/pull/52) 的 `3955d7890fc38daf942bb52827599bfe35de4a14` 提交离线解包。下载容器为 1,139,929,560 字节，SHA-256 为 `eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`。容器、提取的完整程序和生成的完整程序均保存在 Git 工作区之外。解包文件不会更新相机。

组件目录需要以下两个文件：

| 文件 | 字节数 | 必须匹配的原厂 SHA-256 |
|---|---:|---|
| `appFw.so` | 99,960,744 | `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b` |
| `cpapp-b.bin` | 18,090,880 | `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428` |

先复现到忽略目录：

```powershell
$env:A7C2_STOCK_COMPONENTS = 'D:\Private\A7C2-2.01\components'
& $devPython dev/build_lut_compat.py --components $env:A7C2_STOCK_COMPONENTS --output private/generated/runtime-fl23-current.json
git diff --no-index -- src/looks/assets/runtime-fl23-current.json private/generated/runtime-fl23-current.json
```

最后一条命令应无差异。构建器会校验两份原厂指纹、重建旧目标、生成新目标、限制变化只发生在已核对的 FL23 区域，并验证完整合并结果。不从不匹配的文件更新适配表。输出仅含有限补丁窗口和指纹，不含完整固件或机身校准。

`A7C2_RESEARCH_FIXTURES` 是另一组输入：作者历史三款／六款版本的样本索引 JSON，格式见[数据格式](technical/formats.md)。官方原厂文件不能替代这些历史版本。缺少样本时保留跳过状态，不通过给无关文件改名来制造通过结果。

## 6. 离线验证

在仓库根目录使用同一解释器：

```powershell
& $devPython -m unittest discover -s src/fl23/tests -v
& $devPython -m unittest discover -s dev/usb/tests -v
& $devPython -m unittest discover -s dev/release/tests -v
Push-Location src/looks
try { & $devPython -m unittest discover -s tests -v } finally { Pop-Location }
& $devPython dev/release/check_publication.py
git diff --check
```

设置 `A7C2_STOCK_COMPONENTS` 后会启用 12 项新版固件集成用例，覆盖两种顺序、精确逆向、单槽撤销、电脑端准备／安装／核验、完整存档回退、冲突拒绝及真实 AArch64 编译。其中一个用例执行 512 组 Thumb 曲线路由组合。程序文件是真实官方字节；USB、设置／校准及相机事务为模拟。测试不得意外发现或操作连接着的相机。

已记录的功能测试为：96 项 FL23、52 项主机／USB、111 项 LUT 通过，35 项历史样本用例跳过；111 项中包含上述 12 项。文档规则测试另外报告。缺少官方组件时还会额外跳过这 12 项，不能称为集成验证通过。

## 7. 状态、身份与数据保留约束

兼容流程为 `prepare` → `prepared` → `install` → `installed_pending_cold_start` → 人工实机检查 → `verify`。准备记录用户填写的固件版本、同机身份、双份原始数据、候选程序和独立完整存档；存档包含两个程序、实时／已保存设置及 68 份名称资源。非空或互相包含的工作／备份目录会被拒绝。

安装在写入前重新核对完整当前程序、目标设置及无关的未保存配方。程序写入后比较完整目标字节；色彩／设置写入后读回并核对保存结果。核验检查当前 FL23 启用状态、保存参数和运行中的 AP 片段，因此后来合法安装 LUT 不会触发过期的整份输出检查。

服务入口先检查普通 USB 产品字符串，只认证一次，再用四字节 AP 序列号 `00e70003` 的旧十六进制文本摘要绑定机身。LUT 任务还保留普通 USB 序列号绑定。存储就绪和 `getCameraInfo` 不作为服务入口前置条件，HASP 不作为稳定身份。

超时、中断、原生结果损坏或写入结果未知时，停止后续报文并保留首次证据。不要重试认证／加载器、删除未知临时文件，或修改阶段来允许再次写入。重构时保留机型／机身绑定、已有字节冲突、完整读回及原生结果／挂载状态检查。

兼容设置检查覆盖可写 AP `02cf` 组及四个受保护 CP 单元。只有两项计划内 FL23 色彩单元可在受保护的合并范围内变化，其余校准仍受保护。无关运行计数器只备份，不作为配置比较，也不写回。无关且尚未保存的配方会在组保存可能将其持久化之前阻止写入。

## 8. 原生模块与恢复

`installer.c` 同时支持原有完整哈希检查构建和用于兼容／恢复的 `BYTE_WINDOWS_ONLY` 构建。后者检查改写字节，且必须进行电脑端完整字节读回，不是无校验写入。`INSTALL_REQUEST`／`INSTALL_RESULT` 支持 Recovery 独立命名空间。两种模式都必须能编译，满足 65,536 字节暂存上限，并通过 `nativebuild.py` 的 ELF／无外部符号检查。

完整回退使用 `recovery.py` 和选中的存档。单槽撤销清除选中位图／名称／配方，保留其他槽和 FL23，共用 LUT 代码可以继续以不生效状态存在；完整 Recovery 相对所选存档时间点撤销程序改动。保留所有存档／共用存储依赖。模拟器中逐字节恢复成功不代表实机或断电恢复成功。

## 9. 文档与打包检查

`dev/release/documentation-layout.json` 明确列出 15 对当前英文／简体中文指南和 17 份保留的历史／署名文件。唯一的历史语言例外限定为具体路径。保留文档仍接受私有信息标记、失效链接、标题和编码检查；未登记或缺失的文档都会被拒绝。增删文档时明确更新清单，当前命令维护在成对指南中，不把归档笔记当作安装说明。

以下命令只在本地打包，不发布：

```powershell
& $devPython dev/release/build_lut.py --output dist/lut.py
& $devPython dev/release/build_lut.py --entry recovery.py --output dist/recovery.py
& $devPython dev/release/build_release.py
```

`verify_release.py` 除工具 ZIP、两个单文件外，还需要上游 v2.1 原始的 `dist/a7c2-dcp-profiles-2026-10-18.zip`。仅在原附件齐全时运行；不要构造替代 DCP，也不要在缺输入时宣称完整发布验证通过。打包检查证明附件与源码一致，不证明相机行为。单文件入口会将内置源码释放到以清单摘要命名的缓存目录，任务／备份单独保存。

## 10. 提交与实机验证

修改使用功能分支。没有上游写权限时，先 fork，再推送分支、创建草稿 PR。提交说明应写明基线、具体前后行为、测试命令和通过／跳过数量、未改动的预编译资产，以及实机限制。不发布完整固件、机身备份／校准、照片、私有样本索引、凭证或本地诊断输出；代码修复不应顺带改写上游标签和 Release。

宣称可用于相机的正式版本之前，需要另行获得授权并记录实际机型／版本、源码版本、备份／恢复位置、真实电量与连接条件、设备读回、冷启动／AP 运行证据、不按快门的预览切换、新照片／回放、相关视频模式及真实还原。本分支尚无真实 USB／安装／冷启动／拍摄／恢复验收。历史单机回报属于历史证据，不能充当这些新字节的验收。
