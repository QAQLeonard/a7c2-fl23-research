# Sources and licenses

[Home](../../README.md) · [简体中文](../zh-CN/notices.md)

Newly authored code is [MIT licensed](../../LICENSE). This is independent research, not affiliated with Sony, Fujifilm, Ricoh or Adobe; look names imply neither endorsement nor exact color equivalence.

## DCPs and paired looks

**DCP sources on Xiaohongshu (小红书):** Ricoh DCPs from **爸总林先森**; Fujifilm DCPs from **门萨特里顿**.

- **Original DCPs (18):** supplied by the owner and unchanged, distributed as a separate Release attachment: [download](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-dcp-profiles-2026-10-18.zip).
  - **Fuji-style (11):** Provia, Velvia, Astia, Classic Chrome, Pro Neg Std, Pro Neg Hi, Eterna, Reala Ace, Classic Negative, Nostalgic Negative, Bleach Bypass.
  - **Sony-adapted Ricoh GR III (7):** Standard, Vivid, Positive Film, Negative Film, Monotone, Hard Monotone, Soft Monotone.
- **Paired library in the app packages (15):** the 11 Fujifilm and 4 Ricoh color profiles. Each DCP sits next to its fitted `.a7look` under the same name. The 3 monochrome profiles did not meet the fitting-error criteria, so they have no pair.
- These DCPs are **RAW-development profiles for the Sony ILCE-7CM2**, not firmware. To use one manually in Lightroom on Windows, copy it into `%APPDATA%\Adobe\CameraRaw\CameraProfiles` and restart Lightroom/Camera Raw.

Licenses:
- **Fuji-style:** used with the author's permission and licensed under [MIT](../../LICENSE).
- **Ricoh-style:** used with the author's permission and licensed under [MIT](../../LICENSE).
- **FL2/FL3 DCPs:** the two Lightroom profiles matching the in-camera FL2 and FL3, used with the author's permission and licensed under [MIT](../../LICENSE); included with the 3.0 Release.
- Every DCP and the look data derived from it is used with the authors' permission and licensed under MIT, like the code. Original metadata is recorded in the [manifest](../profiles/manifest.json).

## Code and research sources

- [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE), pinned commit `a82f5baaa8e9c3d9f28f94699e860fb2e48cc8e0`: vendored service/USB Python code under `src/fl23/vendor/pmca`; [original MIT text](../../src/fl23/licenses/Sony-PMCA-RE-MIT.txt).
- [fwtool](https://github.com/ma1co/fwtool.py): parses an optional stock DAT; vendored under `src/desktopapp/vendor/fwtool`, license in `src/desktopapp/vendor/fwtool-LICENSE.txt`.
- [MDHan/a7c2-fl23-macos](https://github.com/MDHan/a7c2-fl23-macos), commit `1491f734df07f02fb77da6ea7062828bce0e30e7`: informed the macOS order for identifying camera storage and claiming USB; MIT notice kept in [docs/licenses](../licenses/a7c2-fl23-macos-MIT.txt).
- [A7CR FL2/FL3 research](https://github.com/lzh2016zzz/a7cr-fl23-research/tree/43ba74441c8f10459ade41e84a379ad8005e6ef4): parameter, label and WBI methodology. A7C II offsets were located independently; A7CR offsets are not flashed directly.
- [Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware): A7R V FL2/FL3 firmware adaptation and RAW color research; reference for porting the FL2/FL3 color data.
- [A7C II service-mode research](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a), documentation CC BY-SA 4.0. This tool uses native `libJit.so` loading, not the preload configuration or the clock-changing DEBUG command.
- The Adobe DNG specification/SDK documents the DCP format. This tool implements only limited look/tone stages, not the complete Adobe renderer.

## Third-party components in the packages

- Windows driver installation uses `wdi-simple` from [libwdi](https://github.com/pbatard/libwdi) (GNU LGPL v3 or later).
- The Lightroom plugin uses [ExifTool](https://exiftool.org/), shipped with its original license.
- The interface uses Qt for Python (PySide6, LGPL v3). Other Python dependencies are listed in `desktop-requirements.txt` and keep their own licenses.

## Firmware and data

Sony A7C II 2.01 and Alpha 1 II 4.00 firmware were analysis sources; Sony firmware, trademarks and data remain their owners' material. This project distributes no complete firmware, signed update container, body backup/calibration, photos, credentials or private derived data. The built-in factory reference holds only generic stock bytes for the regions this project changes.
