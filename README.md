# A7C II Tools

**Unreleased repair branch:** this checkout includes host workflow fixes and current-FL23/LUT compatibility checked offline against official 2.01 components. See the [repair record](docs/en/changelog.md) for changes and physical-validation limits. The v2.2-preview.1 links below refer to the upstream historical package and do not contain these local changes.

**Community:** [Telegram — recommended](https://t.me/sonyfwlab) · [Discord](https://discord.gg/SwPdfSd9c). We recommend joining the Telegram group.

**Author:** Xiaohongshu: [QAQLeonard（读研版）](https://www.xiaohongshu.com/user/profile/660501f7000000000600d03c) · Douyin: **LeonardZ** (ID: `90860261487`).

**v2.2-preview.1 (main):** three independent entries: FL23 installs/checks, LUT imports/restores one slot, and [Recovery](docs/en/recovery.md) performs complete rollback. Both installation orders are supported. Includes the service-first USB connection fix; [changes and validation](docs/en/changelog.md).

**English** · [简体中文](README.zh-CN.md)

For **Sony A7C II / ILCE-7CM2 firmware 2.01**, choose the workflow:

| FL2 / FL3 | Custom LUT / DCP | Recovery |
|---|---|---|
| [Install and verify](docs/en/fl23.md) | [Reference file to camera / slot restore](docs/en/custom-lut.md) | [Complete rollback](docs/en/recovery.md) |
| Prefer **`.\FL23.cmd --help`** for CLI; double-click `FL23.cmd` for desktop | **`python lut.py import "look.dcp" --name "Classic Neg." --slot 1`** | **`python recovery.py --help`** |

**Preview: [v2.2-preview.1](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.2-preview.1)** · [Changelog](docs/en/changelog.md). Previous non-preview release: [v2.1](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1).

Download standalone `lut.py`, standalone `recovery.py`, or the complete tools ZIP from the preview release. [Original DCPs](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-dcp-profiles-2026-10-18.zip) remain a separate download. [FL23 v1.0 release](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v1.0).

[Setup and Windows/macOS commands](docs/en/manual.md). FL23 retains its existing launcher, interface and installation flow. LUT/DCP and Recovery are CLI-only, with 64-bit Python 3.10+ and no Tkinter/CMD dependency.

LUT conversion, backups, actual writing/full readback, reload checks and restoration are implemented; no AI or prior FL23 installation is needed. One Windows camera passed an existing-six-look slot update, preview/photos and standalone reload verification. Stock first-install and Mac USB remain untested. The default color bridge is a shared one-scene approximation, not full DCP fidelity or a Sony-signed update.

[AI entry](docs/en/ai.md) · [Development](docs/en/development.md) · [Validation](docs/en/technical/validation.md) · [DCP references](docs/en/profiles.md) · [Licenses](docs/en/notices.md)

**DCP sources on Xiaohongshu (小红书):** Ricoh DCPs from **爸总林先森**; Fujifilm DCPs from **门萨特里顿**.

## Film look comparisons

Camera JPEGs, resized, arranged and labelled only; no exposure, white-balance or color edits. Capture settings vary, so these are visual examples rather than controlled measurements.

Each scene shows three separate comparison images in order: **ST / FL / FL2 / FL3**, **ST / NC / CC / NN**, **ST / E / GR Positive / GR Negative**. Read each grid top-left, top-right, bottom-left, bottom-right. NC = Classic Neg., CC = Classic Chrome, NN = Nostalgic Neg., E = Eterna; Astia is not included.

[Download all 19 full-resolution comparisons (about 152 MB)](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-film-comparisons-2026-10-18.zip), including the first scene’s extra ST comparison and the overview.

**01 · Drinks cabinet**

![01 · Drinks cabinet — ST / FL / FL2 / FL3](docs/images/film-comparison/01_饮料柜/01-1_ST_FL_FL2_FL3.jpg)

![01 · Drinks cabinet — ST / NC / CC / NN](docs/images/film-comparison/01_饮料柜/01-2_ST_NC_CC_NN.jpg)

![01 · Drinks cabinet — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/01_饮料柜/01-3_ST_E_GR正片_GR负片.jpg)

**02 · Plants**

![02 · Plants — ST / FL / FL2 / FL3](docs/images/film-comparison/02_绿植/02-1_ST_FL_FL2_FL3.jpg)

![02 · Plants — ST / NC / CC / NN](docs/images/film-comparison/02_绿植/02-2_ST_NC_CC_NN.jpg)

![02 · Plants — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/02_绿植/02-3_ST_E_GR正片_GR负片.jpg)

**03 · Counter**

![03 · Counter — ST / FL / FL2 / FL3](docs/images/film-comparison/03_柜台/03-1_ST_FL_FL2_FL3.jpg)

![03 · Counter — ST / NC / CC / NN](docs/images/film-comparison/03_柜台/03-2_ST_NC_CC_NN.jpg)

![03 · Counter — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/03_柜台/03-3_ST_E_GR正片_GR负片.jpg)

**04 · Spiral staircase**

![04 · Spiral staircase — ST / FL / FL2 / FL3](docs/images/film-comparison/04_旋转楼梯/04-1_ST_FL_FL2_FL3.jpg)

![04 · Spiral staircase — ST / NC / CC / NN](docs/images/film-comparison/04_旋转楼梯/04-2_ST_NC_CC_NN.jpg)

![04 · Spiral staircase — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/04_旋转楼梯/04-3_ST_E_GR正片_GR负片.jpg)

**05 · Bookshelves**

![05 · Bookshelves — ST / FL / FL2 / FL3](docs/images/film-comparison/05_书架/05-1_ST_FL_FL2_FL3.jpg)

![05 · Bookshelves — ST / NC / CC / NN](docs/images/film-comparison/05_书架/05-2_ST_NC_CC_NN.jpg)

![05 · Bookshelves — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/05_书架/05-3_ST_E_GR正片_GR负片.jpg)

**06 · Posters**

![06 · Posters — ST / FL / FL2 / FL3](docs/images/film-comparison/06_海报/06-1_ST_FL_FL2_FL3.jpg)

![06 · Posters — ST / NC / CC / NN](docs/images/film-comparison/06_海报/06-2_ST_NC_CC_NN.jpg)

![06 · Posters — ST / Eterna / GR Positive / GR Negative](docs/images/film-comparison/06_海报/06-3_ST_E_GR正片_GR负片.jpg)
