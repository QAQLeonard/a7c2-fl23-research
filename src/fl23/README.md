# A7C II 2.01 · FL2／FL3 预览版 0.6.0

> 历史组件／研究记录。当前修复分支的命令、构建和验证方法以[开发指南](../../docs/zh-CN/development.md)为准。来源署名与许可继续保留。

在 ILCE-7CM2（A7C II）2.01 原厂固件上启用 FL2／FL3 两种创意外观的实验预览版。
只支持原厂未修改的 2.01，一台机身一份备份，写入前后都做逐字节校验。

## 目录约定（无需手动指定路径）

启动后会自动使用源码目录下的两个文件夹：

```text
a7c2_fl23_preview/
├─ workdir/                 每次工作自动在里面建一个会话目录
│  └─ 20261020-141200-3f9c1a2b/
│     ├─ original/          本次读回的原厂程序、色彩单元与机身设置
│     ├─ candidate/         本地生成的候选文件（未写入相机）
│     ├─ readback/          每次完整读回的留证
│     ├─ evidence/          原生模块结果、设置快照、错误栈
│     └─ state.json         阶段与审计流水
├─ backup/                  每个机身一份已验证备份
│  └─ 3f9c1a2b/
│     ├─ backup.json        清单：文件杂凑、机身编号、程序原厂杂凑
│     ├─ appFw.so.bin       原厂程序
│     ├─ cpapp-b.bin.bin
│     ├─ unit-02a40001.bin  原厂色彩单元（含本机校准）
│     ├─ unit-02a4000d.bin
│     └─ backup.private.bin 机身设置（私有，不要外传）
```

会话目录按「时间戳 + 机身短码」命名，永不复用旧目录，`workdir/` 里的历史记录全部保留。

## 启动

双击 **`Start.cmd`** 即可。

`Start.cmd` 是**纯批处理**，全程只调用 Python：

1. 找 Python 3.10+（先用工具自带的 `.venv`，没有就用 `py -3` 或 `python` 建一个）
2. 缺依赖时按 `requirements.txt` 装一次
3. 建好 `workdir/` 与 `backup/`
4. 跑 `app.py check-package` 自检
5. 启动 `gui.py`

**不调用 Windows PowerShell，也不需要安装任何新版脚本宿主。**
`Start.ps1` 只是给习惯用脚本的人准备的替代入口（5.1 与 7.x 都能跑），
`Start.cmd` 不会用到它，删掉也不影响。

排错：如果想指定某个解释器，先设环境变量再双击，或在命令行里执行

```bat
set A7C2_PYTHON=D:\Python310\python.exe
Start.cmd
```

## 四个按钮

| 按钮 | 做什么 | 何时可用 |
|---|---|---|
| **1 检查** | 先确认 `054C:0E8A` 的驱动，再让相机切到 SonyUSBDevice（`054C:0336`），最后复检 `0336` 的驱动。两次驱动验证都通过才算就绪 | 随时 |
| **2 备份** | 读回本机程序与设置，写入 `workdir/<会话>/original` 与 `backup/<机身>`，随后做三层校验 | 没有已验证备份时 |
| **3 安装** | 没有备份就先自动备份；已有备份则只读回一次确认机身仍是初始状态，读回后等 5 秒让 USB 身份刷新，再写入 | 电量 ≥ 50% |
| **还原** | 只用已验证的备份恢复原厂程序与设置，独立模块，不依赖某次工作目录 | 存在已验证备份时 |
| **重启后核对** | 冷启动后核对磁盘程序、保存参数与执行期内存 | 已有工作记录时 |

界面是简体中文；命令行保持同样的四个动作，可以脱离界面单独复核：

```powershell
python app.py check
python app.py backup
python app.py install --battery-percent 85
python app.py restore --battery-percent 85
python app.py verify
```

## 驱动要求

两个 USB 身份都要装好驱动，libusb 才能打开：

* `054C:0E8A` —— 相机插上就出现的海量存储身份
* `054C:0336` —— 主机完成认证后由相机切过去的 SonyUSBDevice 服务身份

**WinUSB 与 libusbK（以及 libusb-win32 的 libusb0）都可以**，检查时只要求是其中之一，
不强制某一种。检测方式是读取系统里该设备绑定的驱动服务名，并用 libusb 实际打开验证。

## 备份校验的三层判据

只有三层全过的备份才会被还原与安装接受：

1. **完整性** —— 清单里每个文件的 SHA-256 与记录一致，防篡改与拷贝损坏。
2. **原厂性** —— 两个完整程序必须与 `core.ORIGINAL` 完全一致。
3. **未打 FL2／FL3 补丁** —— AP 绑定槽（`0x02CF1287`／`0x02CF1289`）为空，
   CP 色彩单元里 FL2／FL3 的参数映射为空、目标色彩槽没有数据。

## 代码结构

| 文件 | 职责 |
|---|---|
| `core.py` | 离线判据与补丁应用，不接触 USB |
| `layout.py` | `workdir/` 与 `backup/` 的路径约定 |
| `usbdev.py` | USB 后端、驱动识别（WinUSB／libusbK）、模式切换 |
| `transport.py` | 有界的服务会话与 Jiritsu 通道 |
| `backup.py` | 备份写入与三层校验 |
| `workflow.py` | 检查／备份／安装／还原的编排 |
| `app.py` | 命令行入口 |
| `gui.py` | 图形界面（简体中文） |
| `fl23_color.py` | 色彩记录离线工具（检视、移植、核对、色相分析） |

所有相机访问都收敛在 `usbdev.py` 与 `transport.py`；其余模块可以离线运行与复核。

## 上机前

1. 先做完整 eMMC 备份，并确认本机实际程序与 `core.ORIGINAL` 一致。
2. 电量至少 50%，全程保持 USB 连接，不要拔线或关机。
3. 安装后需拔线、正常关机、等存取灯熄灭后取出电池 10 秒，再装回开机。

## 验证状态

82 项离线测试通过（`python -m unittest discover -s tests`），覆盖资产杂凑、色彩记录、USB 设备层、
Gamma 记录与路由、目录约定、备份三层校验、驱动识别与流程前置条件。
**0.5.2 的 Gamma 路由修正尚未重新上机实拍**，详见
`docs/fl23-v052-gamma-route-helper.md`。

历史说明（繁体）见 `README.zh-TW.md`。
