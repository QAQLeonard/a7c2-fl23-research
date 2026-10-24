# 来源与许可

[返回首页](../../README.zh-CN.md) · [English](../en/notices.md)

新编写的代码使用 [MIT 许可](../../LICENSE)。本项目是独立研究，与 Sony、Fujifilm、Ricoh、Adobe 无隶属关系；风格名称不代表官方认可或颜色完全一致。

## DCP 与配对外观

**DCP 来源：**理光 DCP 来自小红书 **爸总林先森**；富士 DCP 来自小红书 **门萨特里顿**。

- **原始 DCP（18 款）**：机主提供，文件内容未修改，作为独立 Release 附件发布：[下载](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-dcp-profiles-2026-10-18.zip)。
  - **富士风格 11 款：**Provia、Velvia、Astia、Classic Chrome、Pro Neg Std、Pro Neg Hi、Eterna、Reala Ace、Classic Negative、Nostalgic Negative、Bleach Bypass。
  - **适配 Sony 的 Ricoh GR III 7 款：**Standard、Vivid、Positive Film、Negative Film、Monotone、Hard Monotone、Soft Monotone。
- **安装包内的配对库（15 组）**：富士 11 款和理光彩色 4 款，每款的 DCP 与拟合生成的 `.a7look` 同名并排存放。黑白 3 款的拟合误差未达到收录标准，因此没有配对。
- 这些 DCP 是 **Sony ILCE-7CM2 的 RAW 显影配置文件**，不是固件。想在 Lightroom 里手动使用时，Windows 可把 DCP 放到 `%APPDATA%\Adobe\CameraRaw\CameraProfiles`，然后重启 Lightroom／Camera Raw。

许可：
- **富士风格**：作者授权本项目使用，适用 [MIT 许可](../../LICENSE)。
- **理光风格**：作者授权本项目使用，适用 [MIT 许可](../../LICENSE)。
- **FL2／FL3 DCP**：Lightroom 中与机内 FL2、FL3 对应的两个 DCP，作者授权本项目使用，适用 [MIT 许可](../../LICENSE)，随 3.0 Release 一起提供。
- 全部 DCP 及由其生成的外观数据都已获得作者授权，与代码一样适用 MIT 许可。原始元数据记录在[清单](../profiles/manifest.json)中。

## 代码与研究来源

- [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)，固定提交 `a82f5baaa8e9c3d9f28f94699e860fb2e48cc8e0`：服务／USB 的 Python 源码位于 `src/fl23/vendor/pmca`；保留[原 MIT 文本](../../src/fl23/licenses/Sony-PMCA-RE-MIT.txt)。
- [fwtool](https://github.com/ma1co/fwtool.py)：用于解析可选的原厂 DAT，位于 `src/desktopapp/vendor/fwtool`；许可见 `src/desktopapp/vendor/fwtool-LICENSE.txt`。
- [MDHan/a7c2-fl23-macos](https://github.com/MDHan/a7c2-fl23-macos)，提交 `1491f734df07f02fb77da6ea7062828bce0e30e7`：参考了 macOS 上识别相机存储卷并接管 USB 的顺序；MIT 声明保留在 [docs/licenses](../licenses/a7c2-fl23-macos-MIT.txt)。
- [A7CR FL2／FL3 研究](https://github.com/lzh2016zzz/a7cr-fl23-research/tree/43ba74441c8f10459ade41e84a379ad8005e6ef4)：参考了参数、标签和 WBI 方法。A7C II 的偏移是另行定位的，没有直接刷入 A7CR 偏移。
- [Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware)：A7R V 的 FL2／FL3 固件适配与 RAW 色彩研究，是移植 FL2／FL3 色彩数据的参考。
- [A7C II 服务模式研究](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a)，文档为 CC BY-SA 4.0。本工具使用原生 `libJit.so` 加载入口，不使用预载配置或会改时钟的 DEBUG 命令。
- Adobe DNG 规范／SDK 提供了 DCP 格式说明。本工具只实现了有限的 look／tone 阶段，不是完整的 Adobe 显影器。

## 安装包中的第三方组件

- Windows 驱动安装使用 [libwdi](https://github.com/pbatard/libwdi) 的 `wdi-simple`（GNU LGPL v3 或更高版本）。
- Lightroom 插件使用 [ExifTool](https://exiftool.org/)，随附其原始许可。
- 界面使用 Qt for Python（PySide6，LGPL v3）。其他 Python 依赖见 `desktop-requirements.txt`，各自保留原始许可。

## 固件与数据

Sony A7C II 2.01 和 Alpha 1 II 4.00 固件被用作分析来源，固件、商标和数据的权利仍归原权利人。本项目不发布完整固件、官方更新容器、机身备份／校准、照片、凭据或私人衍生数据。内置的原厂参考只包含本项目会修改的区域的通用原厂字节。
