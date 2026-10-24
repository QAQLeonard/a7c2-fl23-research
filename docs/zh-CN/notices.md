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

Sony A7C II 2.01、Alpha 1 II 4.00 和 A7 IV 6.02 固件被用作分析来源，固件、商标和数据的权利仍归原权利人。本项目不发布完整固件、官方更新容器、机身备份／校准、照片、凭据或私人衍生数据。内置的原厂参考只包含本项目会修改的区域的通用原厂字节。

## 风险告知与使用声明

### 非官方研究与设备授权

本项目为独立的摄影色彩与设备互操作性研究，免费提供，目的为学习和技术交流。项目与索尼及其关联公司、授权维修机构不存在隶属、授权、认可、赞助或背书关系。产品名称与商标仅用于识别兼容机型，权利归各自权利人；提及名称不表示已获得授权。

仅可操作本人合法持有，或已取得合法机主明确、知情授权的设备。不得未经授权修改租赁、展示、待售或他人器材。

### 重要设备风险与责任范围

**修改相机可能导致无法开机、反复重启、功能异常、素材或设置丢失，并产生维修或更换费用；也可能影响后续官方更新及保修／维修资格。**是否保修取决于适用法律、实际损坏原因及服务政策，不保证修改后仍可享受免费维修。

**程序写入、完整读回和离线测试通过，不代表相机一定能正常启动或在所有模式下稳定工作。一键恢复不是完整系统重装，不保证能够修复损坏或救回无法开机的相机。**请妥善保存重要素材、同机备份及所需官方固件；备份本身也不保证可以恢复。

软件在法律允许范围内按原样提供，不作无错误、适用性、安全性或恢复成功的担保。使用者应自行判断是否操作，并承担依法应由其承担的设备及数据风险。**本声明不排除或限制法律禁止免除的责任**，不以勾选确认免除依法不得免除的故意、重大过失等责任。

### 免费提供、反对收费代刷与禁止冒充授权

**严禁第三方冒充索尼官方或本项目作者授权。**作者不提供有偿代刷，不授权第三方以索尼或作者名义宣传、收费、承诺保修或提供安全保证。

作者明确反对第三方个人、网店（包括闲鱼、淘宝、拼多多、转转等平台卖家）、摄影工作室或商业机构通过本项目提供有偿代刷、远程收费安装、误导性打包售卖、制作加密狗／激活码或捆绑硬件销售等服务。第三方收费不代表作者参与、认可或担保，相关交易及行为依法由其实施者负责。

**代码继续遵循 MIT 许可证。本段表达作者的服务立场并禁止虚假关联，不撤回或缩减 MIT 已授予的商用、复制、修改、再分发和销售权限。**第三方组件、固件资料及商标分别适用各自的权利和许可，MIT 不授予其额外权利。

### 固件来源、版权与 DMCA 风险

为尊重原厂版权、降低包括美国《数字千年版权法》（DMCA）在内的版权分发与反规避法律风险，本项目不提供完整索尼固件、官方签名升级包、原厂语音包或他人机身备份供下载。需要完整恢复来源时，请使用自己的同机备份，或自行从索尼官方取得适配的 **ILCE-7CM2 2.01 `BODYDATA.DAT`**，由工具在本地处理。

这是一项项目分发政策，不代表 DMCA 要求每位用户必须下载固件，也不代表持有设备、制作备份、个人研究或非商业使用会自动取得规避技术保护措施的许可。具体限制及例外取决于适用法律和实际行为。

部分实现包含或处理固件研究所得的小范围指令／数据片段和通用原厂参考，不能据此声称“项目完全不含任何索尼来源字节”。相关权利仍属于原权利人，不保证所有实现已获得其许可。**本声明、非商业研究目的和用户勾选均不构成索尼授权，也不能阻止权利人提出异议、下架请求或诉讼。**

### 确认方式与权利人联系

每次打开桌面应用，需手动勾选“我已阅读并接受”并点击“接受并进入”；未勾选、拒绝或关闭弹窗均不进入操作界面。此确认用于提示风险，不表示放弃依法不得放弃的权利。

如权利人认为具体内容侵犯其权利，可通过[项目 Issues](https://github.com/QAQLeonard/a7c2-fl23-research/issues)说明涉及的内容与权利依据，作者会核实并处理。
