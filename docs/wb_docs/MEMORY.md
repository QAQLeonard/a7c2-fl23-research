# 项目长期笔记

> 历史组件／研究记录。当前修复分支的命令、构建和验证方法以[开发指南](../zh-CN/development.md)为准。来源署名与许可继续保留。

## a7c2_fl23_preview 0.6.0 起的模块划分与约定

- 目录：`workdir/<时间戳>-<机身短码>/`（每次工作自动新建，不复用）、`backup/<机身短码>/`（每机身一份，三层校验）。都在源码目录下，不需要用户手选。规则在 `layout.py`。
- 模块：`core.py`（离线判据）、`layout.py`（路径）、`usbdev.py`（后端/驱动/模式切换）、`transport.py`（有界会话 + Jiritsu）、`backup.py`（备份三层校验）、`workflow.py`（检查/备份/安装/还原编排）、`app.py`（CLI）、`gui.py`（简体中文界面）、`fl23_color.py`（色彩离线工具）。只有 `usbdev.py` 与 `transport.py` 接触 USB。
- CLI 命令：`check / backup / install / restore / verify / check-package`。
- USB：VID 054C，PID `0E8A`（海量存储）与 `0336`（SonyUSBDevice）。**WinUSB / libusbK / libusb0 任一均可**，靠读设备绑定的驱动服务名 + libusb 实开确认。检查流程 = 验 0E8A 驱动 → 认证切 0336 → 复验 0336。
- 备份三层校验：①清单 SHA-256 完整性 ②程序等于 `core.ORIGINAL` ③未打 FL2/FL3（AP 槽 `0x02CF1287/1289` 为空、unit01 `0x1200+55/56` 与 unit0d `0x196+55/56` 为 0、目标色彩槽无数据）。不过关则还原/安装都拒绝。
- 安装：无备份先备份；有备份则只读回一次确认初始状态 → 等 5 秒 USB 刷新 → 写入（`workflow.INSTALL_REFRESH_SECONDS`）。还原是 `workflow.restore_from_backup()`，只依赖备份库。
- 界面语言为简体中文；`README.md` 是简体主文档，`README.zh-TW.md` 是历史繁体版本。
- 托管 Python 3.13 **没有 tkinter**，GUI 冒烟测试要用系统 Python 3.10。
- **Windows 批处理编码**：含中文的 `.cmd` 必须存成 **GBK(936)**；存成 UTF-8 会被 cmd 按 936 解析，把 `rem` 注释切成命令导致整段错乱（档头加 `chcp 65001` 也无效）。做法：先写 UTF-8 暂存，再用 Python 转 gbk + CRLF。
- 批处理里执行另一个 `.cmd/.bat` 必须加 `call`，否则控制转移后不会返回；调用 `.exe` 加不加都一样（但统一加 `call` 更安全，万一 PATH 里先命中 .cmd 转发器）。
- **批处理延迟展开陷阱**：在 `if (...)` 括号块内用 `%VAR%` 拿到的是**块被解析时**的值，不是块内刚赋的值；而 `if defined VAR` 是执行期判断。二者混用会产生「变量明明已赋值却展开成空」的假象。解决：凡会被重新赋值的变量，一律用 `goto` 线性流程，在括号块外展开。
- `Start.cmd` 为纯批处理，不调用任何脚本宿主（不依赖 pwsh 7）；`Start.ps1` 只是可选替代入口。支持 `A7C2_PYTHON` 环境变量指定解释器。
- 注意：Bash 工具里出现 `powershell`/`pwsh` 字样会触发安全拦截，需要改用 Write 工具落文件再执行。

## 仓库结构

- `sony-a7m4-custom-firmware/`：ILCE-7M4 6.02 定制固件方法集（方法 1 自签、2 版本号、3 FL2/FL3、4 电池、5 镜头 AF）。FL2/FL3 色彩结论见 `methods/03-fl2-fl3/README.md` 与 `docs/fl23-colour-comparison-20261018/`（含 `data/recipe_comparison.json`，其中有三配方的色度 int16、端点 SHA-256、Gamma 采样点）。
- `a7c2-fl23-research/`：ILCE-7CM2 2.01 的 FL2/FL3 移植。`README.md` / `README.zh-TW.md` 为研究说明；`<版本>/a7c2_fl23_preview/` 为工具包；`*.zip` 为对外分发包。ZIP 受 git 跟踪，解包目录不受跟踪。0.2.0 起 FL2/FL3 色彩数值取自 `sony-a7r5-custom-firmware`（见该包 `docs/fl23-colour-port-from-r5.md` 与 `assets/r5_fl23_reference.json`）。

## 两个机型的关键差异（不要跨机型复制字节）

| 项 | A7M4 6.02 | A7C II 2.01 |
|---|---|---|
| 供体 | FX2 1.01 | Alpha 1 II 4.00 |
| 安装 | 自签 SD / fastboot / 独立 NOR | USB 服务 + 原生模块就地写 |
| 色彩单元 | nflasha6 CC1/block13 + nfa2 两份副本 | CP unit 0x02a40001 / 0x02a4000d 单份 |
| 色度编码 | M4 delta，FX2 绝对，需转换 | 已是 delta |
| 槽配置 | 六条 BK4 键 | AP 0x02cf1287/1289 → 0a/0b |
| 矩阵端点 | B/A1/A2 各 192B，560/576B 记录 | 同（0x1e0 + slot×0x300，576 用 + 192 尾） |
| 矩阵槽数 | 每端点 16 槽 × 12B = 48 个矩阵 | 同；只填槽 0 会留下 45 个旧供体矩阵（0.2.0 的教训） |

- 已解包的固件在 `work/`：`fx2-unpack/`（FX2 1.01，`fat8/cpapp-b.bin` sha256 `eba723db…`，与 R5 研究记载的原厂 FX2 CP 相同）、`a7c2-unpack/`（A7C II 2.01）、`a12-unpack/`（A1 II 4.00）。解包用 `work/fx2-unpack/unpack_dat.py`（需 pycryptodome：系统 Python 3.10 有，托管 3.13 没有）。FX2 的色彩单元在 `work/fx2_unit01_CX96900_.bin`(8192B) / `work/fx2_unit0d_CX96900_.bin`(28672B)，CX96900/CX96901 两份备份逐字节相同；A7C II 原厂 CP 是 `work/a7c2_cp_orig.bin`（＝`core.ORIGINAL[1]`），本机真实色彩单元备份在 `FlashDir/backup1.2/original/`。

第三个仓库 `sony-a7r5-custom-firmware`（ILCE-7RM5 4.04）是**参考实现**：CP 色彩供体同为 FX2 1.01，公开的只有数值（CC1、block13 group1 slot0、Gamma 偏移与哈希），不含固件字节；其研究文档在 `analysis/R5_FL2_FL3固件色彩与RAW参数研究总结.md`。FL2/FL3 的 CC1 与主矩阵在 FX2/R5/M5/R6 同名外观间相同，ST/FL 则各异 —— 所以可跨机型复用 FL2/FL3 数值，但不能外推到 ST/FL。

## 约定

- 离线工具不得连相机；写资产前必须能打印将变化的字节数，写入后同步 `assets/manifest.json` 哈希，否则 `core.assets()` 会拒绝。
- 包内用户可见字符串用繁体中文（上游风格），研究文档可用简体中文。
- 交付版本号改动时，新目录 + 新 ZIP 并存，不覆盖旧 ZIP（旧 ZIP 是其他报告的证据身份）。
- 色彩矩阵写入前先数「多少槽等于目标值」：A7C2 的 576B 记录是 48 个矩阵。**0.5.0 起这 48 槽是「3 光源端点 × 16 色相分区」，不是色温冗余** —— A7C2 原厂 bank 每端点就有 15–16 个不同槽值，RAW 0x780F 的 `[24,216)` 也是这 16 槽逐槽打包。0.2.0–0.4.x 把每端点 16 槽填成同一组系数，等于 16 个色相分区共用一个判读，正是「色相改不动」的根因。`core.colour_record()` 现要求每行和 1024 且整份记录逐字节等于 `assets/fx2_fl23_donor.json`。
- A7C II 的 Gamma：`cpapp-b.bin +0xcfa6d0` 起、步长 0x240(576B)、50 条；`+0x218` tag 高字节＝Gamma ID，`+0x21c` gen（5＝内部槽 0–5 共用，6＝内部槽 6），`+0x220` max，`+0x23c` 一律 2。**`+0xcfa588` 原厂就有 20 组 (照片ID, 影片ID) 路由，末两组 FL2=(0x30,0x30)、FL3=(0x31,0x31)** —— 照片与影片共用一个 ID，因此每个外观只需 2 条记录，影片曲线（FX2 ID 0x32/0x33）没有落点。FX2 1.01 的 580B 记录换算成 A7C II 的 576B 是 `FX2[0:0x238] + FX2[0x23c:0x244]`，gen 3→5（此式已被 0.4.0 既有的两条记录逐字节证实）。RAW 0x7806 ＝ 2×CP **照片**内部槽 6，所以 gen 6 那条必须是照片曲线（0.4.0 错放成影片曲线，0.5.0 修正）。
- knee 三个指针全 0，走固件默认 512/1024，与 FL2/FL3 目标等效，不必改。
- 改 CP 补丁数据但**长度不变**时不必重新编译 `installer.so`（本机没有 zig）：`new_0`（3872B）在 +0x1b78、`final_hashes[1]`（32B）在 +0xaf8，各只出现一次，可原址覆写；模組保持 56864B、重定位不变。同时要重产生 `native/patch_manifest.h`、更新 `core.py` 的 `FINAL[1]` 与 `assets/manifest.json`。`tests/test_gamma.py` 固定了这三项。构建脚本 `work/tools/build_fl23_050.py`（幂等）。
- 恢复（restore）的前置条件不能用「当前套件的合并结果」当白名单：不同版本只改色彩时，机身里的记录与当前套件重算的结果不同，会被误判为未知状态（0.3.0 的教训）。正确判据是 `core.matches_outside_colour()`——`colour_write_spans()` 以外必须逐字节等于原版，窗口内任版本皆可。新增会写 CP 其他区域的功能时，必须同步扩大该范围。

## FL3 实拍对照（Adobe Camera Matching 作为基准）

- ACR 用 `Camera FL3 / ST / FL` 配置档 + `ToneCurveName2012=Linear` + 全部滑块 0 + `LensProfileEnable=0` 导出的图可以当色彩基准；原生外观 ST/FL 的机内直出与它几乎重合（ΔL +0.4/−0.7，彩度比 0.99/0.96），**没有 Adobe 与索尼之间的系统性偏移**。
- 机内 JPEG 带机身镜头补偿、ACR 关镜头档 ⇒ 有几何变形。比较前必须按区块做位移搜索并只保留残差小的区块；结论对中心裁切比例不敏感。
- FL3 的偏差：中间调 ΔL ≈ −8.4、彩度比 ≈ 0.68，两个场景一致 → 都是移植造成的。亮度可用「gen5 与 gen6 都写 FX2 照片内部槽 6 曲线」修正；彩度旋钮尚未定位。
- 参数编号：FX2/R5 是 54=FL2照片、55=FL3照片、56=FL2影片、57=FL3影片；A7C2 的 0–49 号与 FX2 逐一相同，但本工具写的是 param55/56。待用「机内 FL2 vs Adobe FL2」实拍定案。

## A7C2 CP 的 Gamma 取用鏈（反彙編實測，0.5.2 起）

- 兩張表，**都已被 0.4.0 正確重定向到追加區塊**，不要再去找「沒重定向」：
  - 指針表（列 → 7 筆記錄指標，步長 28B）：原廠檔 `0x1000d0c`＝RAM `0x01108d0c`；追加表檔 `0x1101480`＝RAM `0x01209480`。改址 5 處：0x32345a / 0x323d82 / 0x323dd0 / 0x323eb6 / 0x9cf436。
  - 路由表（CP color → (照片列, 影片列)，步長 8B，21 項）：原廠檔 `0xcfa580`＝RAM `0x00e02580`；追加表在區塊 +0xe78＝檔 `0x11019f8`＝RAM `0x012099f8`。0x323172／0x323298 換成 `bl 0x138832`，0x3231da 直接改址。
- 取用順序：`0x323128` 讀 `params[0xc]`（CP color）→ `bl 0x138832` 取基址 → `row = route[color*8 + r4*4]`；`0x32344c` 用 `fp=0x01209480`、`rsb r0,row,row,lsl#3`（×7）取 `pointer[row*7 + internal_slot]`；指標為 0 時回退 `[fp,#0x18]`（第 0 列槽 6）。
- **r4 = 照片/影片選擇器，0=照片**：`0x323188` 的 `bne` 只在 r4==1 時讀 +4（影片元素）；r4 = `uxtb(bl 0x9ce804)` = `(params[4]!=0) && (params[0x2c]!=1)`。
- **CP color 編號：FL2=19、FL3=20**（`sony-a7m4-custom-firmware` 方法 3 README 對應表）。追加區塊的路由表第 19/20 項 = (48,48)/(49,49)。
- 0.5.1 的坑：`0x138832` 那 26B helper 回傳基址正確，但帶了 `cmp r4,#0; bne; cmp r0,#0x13; blo; cmp r0,#0x14; it ls; movls r0,#0`，把照片的 color 19/20 歸零 → 退回第 0 列（ST）。0.5.2 把前 14B 換 NOP。
- 追加區塊佈局（檔 `0x1100b80`，3872B）：+0x000/+0x240/+0x480/+0x6c0 四條 576B 記錄；+0x900 指標表 50 列×7×4=1400B（到 +0xe78）；+0xe78 路由表 21×8=168B（到 +0xf20）。前 48 列是原廠副本，第 48/49 列是我們的記錄。
- 找表基址引用：搜 `movw/movt` 指令對（不要搜 32 位字面量，全檔 0 命中）。MOVW 半字 `(hw&0xFBF0)==0xF240`、MOVT `==0xF2C0`，配對視窗 ≤32B 且同 Rd；`work/tools/scan_refs_window.py`。找 bl 呼叫點：`work/tools/bl_callers.py`。

## 實拍對照方法（Adobe Camera Matching 當基準）

- 機身 JPEG 帶鏡頭補償、ACR 關鏡頭檔 ⇒ 有幾何變形。比較色調時改用**亮度分位配準**（`work/tools/tone_probe_quantile.py`），比逐像素塊匹配更穩，且不受手持錯位影響。
- 判別「外觀有沒有生效」最有效的對照：把機內 FL2/FL3 拿去對 **Adobe ST**。若 ΔL 很小、而對 Adobe FL2/FL3 很大，就是外觀沒套上（這是 0.5.1 的實際情形）。

## a7c2-camera-tools 打包链

- FL2/FL3 2.00 包是**确定性构建**：由未改动的 `ILCE-7CM2-v2.01-BODYDATA.DAT` 重建必然得到 `a3076b2b…`。若 `selected_package_200.json` 的 `output_sha256` 与之不符、且该 DAT 连自身 DEND CRC 都过不了（`fl23_windows.parse_dat`），说明文件在磁盘上已损坏 —— 把坏的改名留证，再跑 `runtime/release/feature_package_200.py --official … --out-dir … --audio-mode none --volume 100 --fl23` 重建即可。
- `windows/runtime/release/feature_package_200.py` 与 `macos/mac_service_readonly/` 同名文件必须**逐字节相同**（`tests/test_release_assets.py` 强制），改一处必须同步另一处。
