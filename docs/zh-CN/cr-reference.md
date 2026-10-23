# A7CR 像素位移参考数据收集

[研究进度](pixel-shift.md) · [English](../en/cr-reference.md)

给愿意协助的 **Sony A7CR／ILCE-7CR** 机主。这份工具收集原厂功能的参考数据，不安装破解，不要求升级或降级固件。请记录机身实际版本；2.01 最便于与当前研究对照，其他版本的数据也可以保留。

需要的数据有三类：

| 数据 | 用途 | 数量 |
|---|---|---|
| 像素位移关闭的前／后 RAW，以及原厂四张组 | 测量正确的位移顺序、像素尺度和结束前后画面差异 | 最少 6 张 ARW；再拍一组可提高可信度，共 10 张 |
| 菜单照片、手机拍摄过程视频、设置说明 | 对照选项、间隔、完成时序及异常 | 固件／四张设置照片各一张，过程视频一段 |
| 可选 USB 参数快照 | 比较 OFF → 四张已选择 → OFF 的原厂参数状态；可附 CP 备份缓冲区 | 三个状态各运行一次读取命令 |

**USB 采集是参数快照，不是 CP 执行内存，也不是拍摄中位移／到位信号的轨迹。** 当前纯读取路径不能提供这些轨迹。真实位移、稳定到位和完成后归位仍需研究者结合原始照片与其他证据判断，工具不会自动宣称已验证。

## 1. 准备工具

解压收集包，进入该目录。仅整理文件需要 Python 3.8 或更新版本，不需要其他软件。Windows 命令中的 `python` 可换成 `py -3`；macOS 使用 `python3`。

```text
python collect_cr_reference.py init CR-reference --firmware 2.01 --lens "填写实际镜头"
```

将 `2.01` 换成你的实际版本。程序创建独立目录，不覆盖旧目录，也不连接相机。[源码](https://github.com/QAQLeonard/a7c2-fl23-research/tree/feature/pixel-shift/dev/pixelshift)与收集包中的 Python 文件一致；不依赖 FL23／LUT 安装。

## 2. 拍摄原厂参考照片

相机架稳，对准静止且有细节的纸张、书架等实物，避开屏幕、闪烁灯光、移动的人和树叶。使用静态 M 模式，固定曝光、ISO、白平衡和手动对焦；关闭防抖并记下原设置。选择 RAW；机身若限定 RAW 类型，保留其原厂选择并记录。

整组尽量保持相机、镜头、构图和设置不动，拍摄时断开 USB：

1. 像素位移设为 **关**，拍一张普通 RAW，复制到 `before`。
2. 进入原厂「像素位移多重拍摄」，选择 **四张、间隔 1 秒**；若没有该间隔，选机身实际提供的值，记入 `session.json`。
3. 只按一次快门，等四张及写卡完成，把四张**原始 ARW**复制到 `four-shot`。请勿转换为 DNG、缩图、改写元数据或只提供合成文件。
4. 建议保持同场景，再按一次快门拍完整四张组，复制到 `four-shot-repeat`；不方便可留空。
5. 将像素位移设回 **关**，等机身正常取景后再拍一张普通 RAW，复制到 `after`。结束后恢复自己的设置。

用手机拍一段完整过程，尽量同时看到手指按快门和机身屏幕；放到 `evidence`。固件版本、四张选项／间隔的菜单照片也放这里。可选附上 Sony Imaging Edge 原厂合成的 ARQ 或合成成功截图，原始四张仍需保留。

各目录只放对应照片，保留原文件名。打开 `session.json`，补充实际镜头、间隔、拍摄条件、是否有移动／重启／报错；确认同机同场景且设置固定后，将两项 `...user_confirmed` 改为 `true`。

## 3. 可选：连接电脑只读采集

这部分使用 Sony 服务读取协议，**会临时改变 USB 身份**。它不写入 ROM、拍摄设置、机内文件或内存补丁，不上传／执行临时代码，不保存参数，不控制快门。读取完正常退出服务；失败时保留结果，不自动重试。

USB 部分需要 Python 3.9 或更新版本。安装仅 USB 部分需要的依赖：

```text
python -m pip install -r cr-reference-usb-requirements.txt
```

Windows 需要相机 USB 接口可由 WinUSB／libusbK 访问。若需要 Zadig，目标必须是实际连接的 **ILCE-7CR**；服务身份为 **Sony USB Device，054C:0336**，不要照抄 C2 的设备编号或替换其他设备驱动。首次切换服务身份可能因该身份缺少驱动而停止：保留失败报告，等程序结束后处理驱动，再拔线、正常重新进入大量存储模式，重新运行一次。工具本身不安装／替换驱动。

macOS 不使用 Zadig；通过上述依赖提供 libusb。先退出占用相机的照片导入软件。文件流程使用跨平台 Python；USB 采集尚未在真实 A7CR／Mac 上验证，首次结果必须按报告核对，不能视为已实测支持。

仅连接一台 A7CR，机身选「大量存储」模式，电量充足。**每条命令结束并显示读取完成后，才拔 USB 或操作菜单。** 不要边采集边拍摄。

```text
python collect_cr_reference.py usb CR-reference --label off-before --cp-shadows
```

第一次在原厂像素位移 **关** 时采集。`--cp-shadows` 额外读取原生 19 个 CP 备份缓冲区，用于对照本机数据；这些不是 CP 执行 RAM，也不直接等同于位移标定。

拔 USB，通过原厂菜单选择 **四张**，不必按快门，接回大量存储，再运行：

```text
python collect_cr_reference.py usb CR-reference --label four-selected
```

读取结束后拔 USB，原厂菜单设回 **关**，接回再运行：

```text
python collect_cr_reference.py usb CR-reference --label off-after
```

USB／服务模式可能改变机身状态，因此 `four-selected` 是机主操作标签，不保证所有运行字段在连接后仍保持拍摄时的值。每次会保存 RAM 参数与已保存参数两份原始快照，供之后实际比较。

如果中途报错、黑屏或连接失败，停止后续步骤，保留 `runtime` 中该次的 `snapshot.json` 和已有文件；不要运行初始化、破解或恢复工具。无需为了补齐数据反复开关机。

## 4. 检查并打包

```text
python collect_cr_reference.py check CR-reference
python collect_cr_reference.py pack CR-reference
```

生成相邻的 `CR-reference.private.zip`。工具检查机型、四张分组／编号和曝光一致性，保留原始文件，不计算固件来源哈希。可选 USB／视频缺失会明确列为提示；缺少必需 RAW 时不会默认生成完整包。如只能提供部分数据，用 `pack CR-reference --allow-partial`，报告会标明 `INCOMPLETE`。

**请私下提供 ZIP，不上传公开 issue 或仓库。** 原始照片及参数可能带有拍摄时间、位置、机身序号和其他本机信息；收集器不会改写它们，也不会自动上传。原厂 CR 数据只用于研究对照，不应写入其他机身。

目前工具通过了离线文件与协议测试；不代表已在 A7CR 实机上完成 USB 验证。回传时附上哪些步骤完成、固件实际版本，以及相机最终是否正常取景／拍照。
