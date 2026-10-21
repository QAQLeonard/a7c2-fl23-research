# Recovery：独立完整回退

[首页](../../README.zh-CN.md) · [English](../en/recovery.md)

Recovery 负责完整回退；FL23 只安装／核对，LUT 工具只导入／恢复单槽。本页适用于 v2.2-preview.1，v2.1 下载不含此入口。[Python／驱动准备](manual.md)与 LUT 共用依赖，但运行 Recovery 不需要调用 LUT 工具或提供 LUT Job。

下载[单文件 recovery.py](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.2-preview.1/recovery.py) 或[完整工具包](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.2-preview.1/a7c2-tools-2.2-preview.1.zip)。[更新日志](changelog.md)。

完整源码包从根目录运行；打包后的单文件 `recovery.py` 可单独使用，内部已包含支持代码，Python／设备依赖仍需安装。

## 选择备份

支持新版 `checkpoint.private.zip`、包含它的备份目录，以及旧 FL23 工具的原始 backup2。旧 backup2 可直接使用，机身编号从备份自身读取，名称由当前文件中的原生记录重建。原工作目录、首次 LUT Job 都不需要。

恢复的是所选备份时间点的程序、创意外观名称／配方及 FL23 参数。当时已经存在的功能会保留；无关拍摄设置和计数器不重置。备份属于原机身，请妥善保管。

先离线查看：

```text
python recovery.py inspect "E:/CameraBackup-A7C2-01"
```

## 恢复并完整读回

相机接回大量存储模式，以实际电量执行；`RecoveryWork` 使用新目录：

```text
python recovery.py restore "E:/CameraBackup-A7C2-01" --work-dir "D:/RecoveryWork" --firmware-version 2.01 --battery-percent 90
```

Recovery 自动读取当前状态、保存压缩副本、生成回退、写入并完整读回。后来装过 FL23 或 LUT 都不要求倒序卸载，不检查固件来源哈希。原始备份不覆盖。

## 重新加载并核对

出现 `RESTORED_AWAITING_RELOAD`、所有读写结束后，拔掉 USB 及其他供电，正常关机，等存取灯熄灭，再取出电池至少一分钟。开机检查取景、名称、新照片和回放，然后接回相机执行：

```text
python recovery.py verify "D:/RecoveryWork" --accept-photos
```

`--accept-photos` 记录你已经完成的实机观察。软件完整读回、AP 运行片段及实际拍摄分别核对。本开发版按离线测试验收，未新增实机回退测试。

## 给 AI 的实现说明

入口是 [recovery.py](../../recovery.py)，共用后端为 [checkpoint.py](../../src/looks/looktool/checkpoint.py)、[checkpointjob.py](../../src/looks/looktool/checkpointjob.py) 和 [checkpointworker.py](../../src/looks/looktool/checkpointworker.py)。混装完整回退不得转给保留的原厂来源 FL23 还原辅助入口，也不要求 LUT Job。

旧备份从 AP 属性 `00e70003` 读取机身编号，与正常 Sony 身份查询绑定；这不是固件哈希门槛。`resources.before_custom()` 根据 2860 个原生索引中的最后记录确定原始末尾，逆转本工具追加的六个名称索引／字符串。已用全部 68 份原始资源做精确重建；该算法处理本工具的追加式修改，不修复任意第三方资源替换。

旧版只捕获了当时读到的设置，未单独保存闪存快照；恢复采用已有记录，限制保存在清单中。新版存档同时保存内存／闪存设置和完整名称。只恢复项目字段，保留机身校准；未知写入结果保留证据并停止，不重放。只在实际保留镜像模式为 2 时处理 2→0。

离线运行 `test_checkpoint`、`test_install_order` 与入口／原生程序回归。分别记录离线结果、相机读回、运行加载和实机行为。[完整验证记录](technical/validation.md)。
