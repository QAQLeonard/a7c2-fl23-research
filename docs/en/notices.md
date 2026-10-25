# Sources and licenses

[Home](../../README.md) · [简体中文](../zh-CN/notices.md)

Original project code owned or licensable by QAQLeonard in this distribution uses the unmodified standard [PolyForm Noncommercial License 1.0.0](../../LICENSE). All commercial use and profit-making are prohibited. This is independent research, not affiliated with Sony, Fujifilm, Ricoh or Adobe; look names imply neither endorsement nor exact color equivalence.

## DCPs and paired looks

**DCP sources on Xiaohongshu (小红书):** Ricoh DCPs from **爸总林先森**; Fujifilm DCPs from **门萨特里顿**.

- **Original DCPs (18):** supplied by the owner and unchanged, distributed as a separate Release attachment: [download](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-dcp-profiles-2026-10-18.zip).
  - **Fuji-style (11):** Provia, Velvia, Astia, Classic Chrome, Pro Neg Std, Pro Neg Hi, Eterna, Reala Ace, Classic Negative, Nostalgic Negative, Bleach Bypass.
  - **Sony-adapted Ricoh GR III (7):** Standard, Vivid, Positive Film, Negative Film, Monotone, Hard Monotone, Soft Monotone.
- **Paired library in the app packages (15):** the 11 Fujifilm and 4 Ricoh color profiles. Each DCP sits next to its fitted `.a7look` under the same name. The 3 monochrome profiles did not meet the fitting-error criteria, so they have no pair.
- These DCPs are **RAW-development profiles for the Sony ILCE-7CM2**, not firmware. To use one manually in Lightroom on Windows, copy it into `%APPDATA%\Adobe\CameraRaw\CameraProfiles` and restart Lightroom/Camera Raw.

Licenses:
- **Fuji-style:** used with the author's permission and licensed under [MIT](../licenses/project-legacy-MIT.txt).
- **Ricoh-style:** used with the author's permission and licensed under [MIT](../licenses/project-legacy-MIT.txt).
- **FL2/FL3 DCPs:** the two Lightroom profiles matching the in-camera FL2 and FL3, used with the author's permission and licensed under [MIT](../licenses/project-legacy-MIT.txt); included with the 3.0 Release.
- Every DCP and the look data derived from it is used with the authors' permission and retains its original MIT license without applying the new PolyForm noncommercial license. Original metadata is recorded in the [manifest](../profiles/manifest.json).

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

Sony A7C II 2.01, Alpha 1 II 4.00 and A7 IV 6.02 firmware were analysis sources; Sony firmware, trademarks and data remain their owners' material. This project distributes no complete firmware, signed update container, body backup/calibration, photos, credentials or private derived data. Original recovery bytes are obtained locally from user-provided sources; the distributed recovery layout contains only locations, lengths and digests.

## Risk notice and use statement

### Independent research and device authorization

This is a free, independent project for photographic color research, interoperability, learning and technical discussion. It is not affiliated with, authorized, approved, sponsored or endorsed by Sony, its affiliates or authorized repair providers. Product names identify compatible devices; the corresponding trademarks remain their owners' property.

Only operate a device you lawfully own or for which the lawful owner has given explicit, informed permission. Do not modify rental, display, sale-stock or another person's equipment without authorization.

### Important device risks and liability

**Modifications can cause a camera to fail to boot, repeatedly restart, malfunction or lose images/settings, and may result in repair or replacement costs. They can also affect official updates and warranty or repair eligibility.** Coverage depends on applicable law, the damage and service policies; free repairs are not guaranteed.

**Successful writes, complete readback and offline tests do not establish boot safety or stability in every mode. One-click restoration is not a complete system reinstallation and is not guaranteed to recover damage or an unbootable camera.** Preserve important images, same-body backups and any required official firmware. A backup does not guarantee recovery.

The software is provided as is to the extent permitted by law, without promises of correctness, fitness, safety or successful recovery. Users decide whether to proceed and bear risks that lawfully fall to them. **This statement does not exclude or limit liability that cannot lawfully be excluded**, including applicable non-excludable liability for intentional misconduct or gross negligence.

### No commercial use or profit-making

**All commercial use and profit-making are prohibited.**

### Do not impersonate Sony or claim author authorization

**The author has never authorized anyone to offer paid services, advertise or promise warranty coverage in the author's or Sony's official name. Do not impersonate Sony, the author or an authorized service provider.** Third-party fees imply no author involvement, approval, endorsement or guarantee. Those parties remain responsible for their own transactions and conduct under applicable law.

### License files and liability

Original project code in this distribution uses the unmodified standard [PolyForm Noncommercial License 1.0.0](../../LICENSE), available from the [PolyForm project](https://polyformproject.org/licenses/noncommercial/1.0.0). This license is granted only for original code owned or licensable by QAQLeonard. Other contributors' separately licensed contributions, third-party components, DCP/profile assets and firmware material retain their existing licenses and rights. Earlier permissions are not retroactively revoked; see the [legacy MIT text](../licenses/project-legacy-MIT.txt). This statement does not exclude liability that cannot lawfully be excluded.

Required Notice: Copyright (c) 2026 QAQLeonard, for original project-authored code.

### Firmware sources, copyright and DMCA considerations

To respect firmware copyright and reduce distribution and anti-circumvention risks, including those under the US Digital Millennium Copyright Act (DMCA), the project does not supply complete Sony firmware, signed official update packages, original voice packs or other bodies' backups for download. Factory recovery always requires an original source; use your own same-body backup or obtain a compatible **ILCE-7CM2 2.01 `BODYDATA.DAT`** from Sony for local processing.

This is a project distribution policy, not a claim that the DMCA requires every user to download firmware. Device ownership, backups, personal research or non-commercial purpose do not automatically authorize circumvention; applicable restrictions and exceptions depend on the law and conduct involved.

Some implementations contain or process small instruction/data fragments derived from firmware research and FL2/FL3 donor color data; it would be inaccurate to claim that the project contains no Sony-derived bytes. Rights remain with their owners, and authorization for every implementation is not guaranteed. **This statement, the research purpose and user consent neither confer Sony authorization nor prevent objections, takedown requests or litigation.**

### Confirmation and rights-holder contact

Each normal desktop launch requires manually checking the agreement and selecting the continue button. Leaving it unchecked, declining or closing the dialog does not open the operation interface. Confirmation provides risk notice; it does not waive rights that cannot lawfully be waived.

Rights holders may identify disputed content and the basis of their claim through [project Issues](https://github.com/QAQLeonard/a7c2-fl23-research/issues); the author will review and address the report.
