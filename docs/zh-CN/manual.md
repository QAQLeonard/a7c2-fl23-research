# Windows／macOS 安装准备

[首页](../../README.zh-CN.md) · [English](../en/manual.md)

FL23 保留现有 Windows 命令行和桌面入口，见[FL23 教程](fl23.md)。下面的 Python／驱动准备适用于独立的 LUT 和 Recovery 入口。

## Python 和依赖

安装与系统架构一致的 64 位 Python 3.10+。打包的 Zig 依赖要求 macOS 12+，提供 Intel／Apple Silicon 版本。使用完整源码包时：

| Windows 终端 | macOS 终端 |
|---|---|
| `python -m venv .venv-lut` | `python3 -m venv .venv-lut` |
| `.venv-lut\Scripts\python.exe -m pip install -r src/looks/requirements-device.txt` | `.venv-lut/bin/python -m pip install -r src/looks/requirements-device.txt` |
| `.venv-lut\Scripts\python.exe lut.py doctor --device` | `.venv-lut/bin/python lut.py doctor --device` |

在[八步教程](custom-lut.md)中，用这个解释器替换 `python`。不需要激活环境、PowerShell 脚本、修改执行策略或 AI 服务。Apple Silicon 使用原生 arm64／universal2 Python，不复制 Windows 虚拟环境。

下载独立单文件 `lut.py` 时，用同一个解释器安装依赖：

```text
python -m pip install "numpy>=1.24,<3" "scipy>=1.10,<2" pyusb==1.3.1 libusb-package==1.0.30.0 pycryptodomex==3.24.1 PyYAML==6.0.3 "pyelftools>=0.31,<1" ziglang==0.13.0
python lut.py doctor --device
```

Mac 将 `python` 换成 `python3`。单文件会将内置源码／原生程序释放到 `~/.a7c2-tools/runtime`；工作和备份目录独立保存，不随工具更新覆盖。依赖不内置，也不会自动安装。`doctor` 不连接相机。

## 相机连接

只连接一台受支持的 A7C II，使用数据线、大量存储模式和充足电池，关闭其他相机工具。Windows 按[原有 USB 说明](fl23.md#3-连接相机并准备-usb-驱动)准备普通／服务身份的驱动。LUT 只复用通讯代码，不运行 FL23 安装流程。

Windows 首次替换 libusbK 后若出现倒计时断开或「请检查所连接的设备」，见[两阶段驱动排查](fl23.md#首次替换驱动后断开提示请检查所连接的设备)。LUT 用户安装完两个身份的驱动后，先运行不带 `--write` 的 `import`；不要为了准备驱动安装 FL23，也不要在未知写入结果后重新导入。

Mac 使用 libusb，不安装 Zadig。遇到设备占用，关闭“照片”／“图像捕捉”，并在设备访问前推出已挂载的相机磁盘。macOS 若拒绝接口访问，应停在准备阶段、保留报错，不重试写入或修改系统安全设置。**尚未进行 Mac 实机 USB 安装测试。**

有空格的路径／名称加引号。不支持的固件、缺失依赖、备份变化或未知事务都会停止命令；报错不等于需要重装驱动。

## 主要命令

| 命令 | 执行内容 |
|---|---|
| `import FILE --name NAME --slot N` | 备份、转换、编译、只校验 |
| 再加 `--write --battery-percent N` | 同时写入并完整读回 |
| `install JOB --battery-percent N` | 写入已准备的工作 |
| `verify JOB --accept-photos` | 核对重新加载，记录已完成的实机验收 |
| `diagnose-job JOB` | 离线解释已有错误及名称还原报告，不连接相机 |
| `restore-slot JOB --battery-percent N` | 恢复一个槽位（含首次导入），保留其他槽位和 FL23 |
| `recover JOB` | 读取已有证据，不重新执行加载器 |
| `resume JOB --battery-percent N` | 继续已确认状态的中断阶段 |
| `configure --calibration MODEL --backup-root DIR` | 可选：保存自己的色彩模型／备份位置 |

表中命令都加前缀 `python lut.py`。原有离线研究命令仍在 `--help`，普通安装无需使用它们。

## 独立 Recovery

完整回退使用 `python recovery.py restore BACKUP --firmware-version 2.01 --battery-percent N`。独立[教程](recovery.md)包含旧 backup2／新存档、重载和核对。与 LUT 共用 Python／设备依赖，运行不需要 LUT Job；Mac 使用 `python3`。混装使用显式 FL23 prepare／install／verify 流程；保留的旧原厂来源还原辅助入口不能替代 Recovery。
