# A7C II 工具

**修复分支，尚未发布：**当前源码含电脑端流程修复，以及使用官方 2.01 程序离线验证的新版 FL23／LUT 兼容修复；内容和实机验证边界见[修复记录](docs/zh-CN/changelog.md)。下方 v2.2-preview.1 链接指向上游历史发布包，不包含本地改动。

**交流群：**[Telegram（推荐加入）](https://t.me/sonyfwlab) · [Discord](https://discord.gg/SwPdfSd9c)。**更推荐大家加入 Telegram 群。**

**作者：**小红书 [QAQLeonard（读研版）](https://www.xiaohongshu.com/user/profile/660501f7000000000600d03c) · 抖音 **LeonardZ**（抖音号：`90860261487`）。

[English](README.md) · **简体中文**

**v2.2-preview.1（main）：**三个独立入口：FL23 安装／核对，LUT 导入／单槽恢复，[Recovery](docs/zh-CN/recovery.md) 完整回退。支持两种安装顺序，已集成直接服务认证的 USB 连接修复；见[更新与验证记录](docs/zh-CN/changelog.md)。

用于 **Sony A7C II／ILCE-7CM2 固件 2.01**，按需求选择入口：

| FL2／FL3 | 自定义 LUT／DCP | Recovery |
|---|---|---|
| [安装与核对](docs/zh-CN/fl23.md) | [导入与单槽恢复](docs/zh-CN/custom-lut.md) | [完整回退](docs/zh-CN/recovery.md) |
| 优先用 **`.\FL23.cmd --help`**；双击 `FL23.cmd` 打开桌面版 | **`python lut.py import "look.dcp" --name "Classic Neg." --slot 1`** | **`python recovery.py --help`** |

**预览版：[v2.2-preview.1](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.2-preview.1)** · [更新日志](docs/zh-CN/changelog.md)。此前非预览版：[v2.1](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1)。

在预览版发布页下载单文件 `lut.py`、单文件 `recovery.py` 或完整工具包。[原始 DCP](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-dcp-profiles-2026-10-18.zip)继续独立下载。[FL23 v1.0 下载](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v1.0)。

[安装依赖和 Windows／macOS 命令](docs/zh-CN/manual.md)。FL23 保留原启动器、界面和安装流程；LUT／DCP 和 Recovery 使用纯命令行，需 64 位 Python 3.10+，不依赖 Tkinter 或 CMD。

LUT 已实现转换、备份、真实写入／完整读回、重载检查和还原，不依赖 AI 或预先安装 FL23。已在一台 Windows 相机上通过既有六款版本的单槽更新、预览／拍照及单文件重载验证。原厂首次导入和 Mac USB 尚未实测。默认映射是共用单场景近似，不保证完整 DCP 还原，也不是 Sony 签名更新。

[AI 接手](docs/zh-CN/ai.md) · [开发维护](docs/zh-CN/development.md) · [验证记录](docs/zh-CN/technical/validation.md) · [DCP 参考](docs/zh-CN/profiles.md) · [许可](docs/zh-CN/notices.md)

**DCP 来源：**理光 DCP 来自小红书 **爸总林先森**；富士 DCP 来自小红书 **门萨特里顿**。

## 滤镜效果对比

相机直出 JPG，仅缩放、拼接和添加标签；没有曝光、白平衡或色彩调整。拍摄参数存在变化，供效果参考。

每组依次展示三张独立对比图：**ST／FL／FL2／FL3**、**ST／NC／CC／NN**、**ST／E／GR 正片／GR 负片**；每张四宫格按左上、右上、左下、右下读取。NC＝Classic Neg.，CC＝Classic Chrome，NN＝Nostalgic Neg.，E＝Eterna；这批不包含 Astia。

[下载全部 19 张高清对比图（约 152 MB）](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-film-comparisons-2026-10-18.zip)，含第一组 ST 补充对比及总览。

**01 · 饮料柜**

![01 · 饮料柜 — ST / FL / FL2 / FL3](docs/images/film-comparison/01_饮料柜/01-1_ST_FL_FL2_FL3.jpg)

![01 · 饮料柜 — ST / NC / CC / NN](docs/images/film-comparison/01_饮料柜/01-2_ST_NC_CC_NN.jpg)

![01 · 饮料柜 — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/01_饮料柜/01-3_ST_E_GR正片_GR负片.jpg)

**02 · 绿植**

![02 · 绿植 — ST / FL / FL2 / FL3](docs/images/film-comparison/02_绿植/02-1_ST_FL_FL2_FL3.jpg)

![02 · 绿植 — ST / NC / CC / NN](docs/images/film-comparison/02_绿植/02-2_ST_NC_CC_NN.jpg)

![02 · 绿植 — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/02_绿植/02-3_ST_E_GR正片_GR负片.jpg)

**03 · 柜台**

![03 · 柜台 — ST / FL / FL2 / FL3](docs/images/film-comparison/03_柜台/03-1_ST_FL_FL2_FL3.jpg)

![03 · 柜台 — ST / NC / CC / NN](docs/images/film-comparison/03_柜台/03-2_ST_NC_CC_NN.jpg)

![03 · 柜台 — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/03_柜台/03-3_ST_E_GR正片_GR负片.jpg)

**04 · 旋转楼梯**

![04 · 旋转楼梯 — ST / FL / FL2 / FL3](docs/images/film-comparison/04_旋转楼梯/04-1_ST_FL_FL2_FL3.jpg)

![04 · 旋转楼梯 — ST / NC / CC / NN](docs/images/film-comparison/04_旋转楼梯/04-2_ST_NC_CC_NN.jpg)

![04 · 旋转楼梯 — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/04_旋转楼梯/04-3_ST_E_GR正片_GR负片.jpg)

**05 · 书架**

![05 · 书架 — ST / FL / FL2 / FL3](docs/images/film-comparison/05_书架/05-1_ST_FL_FL2_FL3.jpg)

![05 · 书架 — ST / NC / CC / NN](docs/images/film-comparison/05_书架/05-2_ST_NC_CC_NN.jpg)

![05 · 书架 — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/05_书架/05-3_ST_E_GR正片_GR负片.jpg)

**06 · 海报**

![06 · 海报 — ST / FL / FL2 / FL3](docs/images/film-comparison/06_海报/06-1_ST_FL_FL2_FL3.jpg)

![06 · 海报 — ST / NC / CC / NN](docs/images/film-comparison/06_海报/06-2_ST_NC_CC_NN.jpg)

![06 · 海报 — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/06_海报/06-3_ST_E_GR正片_GR负片.jpg)
