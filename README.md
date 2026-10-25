# A7C II Tools 3.0

**English** · [简体中文](README.zh-CN.md)

> [!WARNING]
>
> ### Read before use · Disclaimer
>
> **This is an unofficial, independent research tool for learning and technical discussion. It is not affiliated with, authorized or endorsed by Sony.**
>
> ### No commercial use or profit-making
>
> **All commercial use and profit-making are prohibited.**
>
> ### Do not impersonate Sony or claim author authorization
>
> **The author has never authorized anyone to offer paid services, advertise or promise warranty coverage in the author's or Sony's official name. Do not impersonate Sony, the author or an authorized service provider. Third-party fees imply no author involvement, approval, endorsement or guarantee.**
>
> ### Use at your own risk · Recovery is not guaranteed
>
> **Modifications can cause boot failure, repeated restarts, malfunctions or data loss, and can affect official updates, warranty or repair. Successful writes and matching readback do not establish boot safety; restoration is not guaranteed to recover the camera.**
>
> **Only operate a device you lawfully own or for which the owner has given explicit permission. Back up important data. Do not proceed if you cannot accept device damage and repair costs.**
>
> **Original project code in this distribution uses [PolyForm Noncommercial License 1.0.0](LICENSE). See [Sources and licenses](docs/en/notices.md) for scope and third-party rights. This statement does not exclude liability that cannot lawfully be excluded.**
>
> **[Read the full risk notice and use statement](docs/en/notices.md#risk-notice-and-use-statement)**

A desktop tool for the **Sony A7C II (ILCE-7CM2) on firmware 2.01**. It adds FL2/FL3, custom Creative Looks, electronic shutter sound and Vertical Display, and can restore factory functions in one click.

**3.0 is the first release with a proper graphical interface.** Driver setup, installation, cold reload and verification all happen with buttons in one window; no command line needed.

## Supported cameras

> [!IMPORTANT]
> **This tool supports only the Sony A7C II (ILCE-7CM2) on firmware 2.01.** It does **not** work on any other model, including the original A7C, the A7 IV, A7CR, A7R V, A6700 and A7 V. The app refuses to connect to them; please don't try.

For other models, these independent projects may help. They are not part of this project; check each one for its own scope and risks:

| Camera | Project | What it is |
| --- | --- | --- |
| A7CR | [lzh2016zzz/a7cr-fl23-research](https://github.com/lzh2016zzz/a7cr-fl23-research) | FL2/FL3 porting research |
| A7CR | [injectiver/a7cr-creative-look-tools](https://github.com/injectiver/a7cr-creative-look-tools) | Research tools for FL2/FL3 and custom looks on firmware 2.01 (source only, no flashing command) |
| A7R V | [Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware) | FL2/FL3 firmware adaptation and RAW color research |
| A7 IV | [DavidBuchanan314/ILCE-7M4-RE](https://github.com/DavidBuchanan314/ILCE-7M4-RE) | Firmware reverse-engineering notes |
| A6700 | [xyzhangxin/sony-a6700-powerful](https://github.com/xyzhangxin/sony-a6700-powerful) | Chinese guide for firmware 2.00: Pico wiring, Fastboot, backups and feature unlocks |
| A7 V | No in-camera firmware project yet | [751K/sony-a7m5-looks](https://github.com/751K/sony-a7m5-looks) ports the A7 V Creative Looks to Lightroom/Capture One profiles (computer only; the camera is not modified) |

**Community:** [Telegram (recommended)](https://t.me/sonyfwlab) · [Discord](https://discord.gg/SwPdfSd9c)
**Author:** Xiaohongshu [QAQLeonard（读研版）](https://www.xiaohongshu.com/user/profile/660501f7000000000600d03c) · Douyin **LeonardZ** (ID `90860261487`)

> [!IMPORTANT]
> This tool modifies programs and settings in the camera firmware. Read the whole [step-by-step guide](#step-by-step-guide) before you start. If the app reports an error, **export a diagnostic bundle first. Do not keep retrying the write.**

Each normal desktop launch shows a risk summary and requires manually accepting it before the interface opens. The linked [risk notice and use statement](docs/en/notices.md#risk-notice-and-use-statement) provides the full text. The tool is free and unofficial. The author opposes paid flashing and prohibits false claims of Sony/author authorization; code remains MIT-licensed.

**Backups and recovery sources:** ordinary installation does not require a backup or a full firmware download. The recovery page offers an optional current-project backup, with voice data saved separately. To respect firmware copyright and reduce legal risks, including DMCA considerations, packages omit complete official firmware and original voice packs. All factory recovery requires a usable original same-body backup or **ILCE-7CM2 2.01 `BODYDATA.DAT`** obtained from Sony for local extraction. This policy does not establish authorization for every modification, guarantee recovery, or prevent litigation.

The interface is in Simplified Chinese. Button names below are given in Chinese with an English translation, so you can match them on screen.

## Contents

- [Supported cameras](#supported-cameras)
- [What it does](#what-it-does)
- [Download and requirements](#download-and-requirements)
- [Before you start](#before-you-start)
- [Step-by-step guide](#step-by-step-guide)
  - [Step 1: Install the drivers (Windows)](#step-1-install-the-drivers-windows)
  - [Driver errors: uninstall, then reinstall](#driver-errors-uninstall-then-reinstall)
  - [Still failing: install with Zadig](#still-failing-install-with-zadig)
  - [Step 2: Installed an earlier version? Restore factory functions first](#step-2-installed-an-earlier-version-restore-factory-functions-first)
  - [Step 3: One-click install](#step-3-one-click-install)
  - [Step 4: Check on the camera](#step-4-check-on-the-camera)
- [Using each feature on its own](#using-each-feature-on-its-own)
- [Troubleshooting](#troubleshooting)
- [Verification status](#verification-status)
- [Command line and development](#command-line-and-development)
- [Older releases](#older-releases)
- [Credits and licenses](#credits-and-licenses)
- [Film look comparisons](#film-look-comparisons)
- [Acknowledgements](#acknowledgements)
- [Sponsor](#sponsor)

## What it does

| Feature | Description |
| --- | --- |
| **One-click install** | Always removes accessibility speech audio and locks Voice Guide off, then installs selected looks, sound and Vertical Display. The Lightroom plugin is optional. |
| **FL2 / FL3** | Adds FL2 and FL3 to the Creative Look list. You can remove them again at any time. |
| **Custom Creative Looks** | Writes `.a7look` files into custom slots 1–6 with your own names, or resets slots to ST. Slots you don't list stay unchanged. |
| **Look conversion** | Converts DCP or CUBE files to `.a7look` offline, without Lightroom. Ships with 15 paired DCP/A7Look profiles. |
| **Lightroom plugin** | When you import RAW files, applies the DCP that matches the custom slot used for each shot. |
| **Electronic shutter sound** | Turns on Sony's native electronic shutter sound, or uses a clip from any audio/video file as a custom sound. |
| **Vertical Display** | Rotates shooting information and icons when the camera is held vertically. The full MENU does not rotate. |
| **Restore factory functions** | Removes every change this project makes and restores stock 2.01 behavior. **No old backup needed**; body calibration is kept. |

## Download and requirements

| System | Download | Notes |
| --- | --- | --- |
| **Windows 10/11 x64** | `A7C2Tools-Windows-x64.zip` from [Releases](https://github.com/QAQLeonard/a7c2-fl23-research/releases) | Extract the whole archive and run `A7C2Tools.exe`. Keep the `_internal` and `Profiles` folders next to it; don't copy the EXE out on its own. No Python install needed. |
| **macOS 14+ (Apple Silicon)** | `A7C2Tools-macOS-arm64.dmg` from [Releases](https://github.com/QAQLeonard/a7c2-fl23-research/releases) | Drag the app into Applications. It isn't signed by a developer, so allow it once under System Settings → Privacy & Security. No Intel build. **USB on a real Mac has not been verified yet.** |

Both packages include **15 paired DCP and `.a7look` files** (11 Fujifilm, 4 Ricoh color). The two files for each look share the same name and sit side by side:
- **Windows:** in the `Profiles` folder next to the EXE.
- **macOS:** inside the app. Open them with **打开内置 DCP／A7Look 配对库 (Open paired DCP/A7Look library)** on the Custom Creative Looks page.

The `.a7look` goes into the camera; the matching `.dcp` is for RAW development in Lightroom.

Camera: **ILCE-7CM2 on firmware 2.01**. No other model or firmware version is supported.

## Before you start

- **Battery:** at least 50%. The app asks you to confirm power before every write.
- **Cable:** use a USB cable that carries data, plugged straight into the computer (avoid docks and hubs). Connect one camera at a time.
- **USB mode:** set the camera's USB connection to **Mass Storage**.
- **Expected message:** while connecting or switching drivers, the camera may show **"Please check the connected device"** and the computer may not show a drive letter. Both are normal. Judge success by the app's progress and log, not by that message; don't unplug the cable or reinstall drivers because of it.
- **During a write:** while the app shows a task running, don't unplug the cable, power off the camera or close the app. Act only after the app says reading and writing have ended.
- **Opening the app** never connects to or writes the camera by itself.

> [!NOTE]
> **Cold reload** is the key step of every workflow; you'll do it after every write. The app shows a dialog each time:
>
> 1. Unplug USB and any other external power.
> 2. Wait for the access light to stop blinking.
> 3. Switch the camera OFF and wait for the screen and access light to go dark.
> 4. Remove the battery and wait **at least one minute**.
> 5. Put the battery back and switch the camera on.
>
> Switching off and on again is not enough. Newly written programs only load after a cold reload.

## Step-by-step guide

Follow these four steps in order.

```text
Step 1  Install drivers (Windows) ──error──→ uninstall drivers → replug → install again
   │      └─ recommended: USB stability check (read-only); change cable/port if it fails
   │
Step 2  Ever used any version of this project? ──yes──→ restore factory functions → cold reload → verify
   │no
Step 3  One-click install → cold reload → reconnect USB → continue → installation complete
   │
Step 4  Check looks, FL2/FL3, shutter sound and Vertical Display on the camera
```

### Step 1: Install the drivers (Windows)

The app talks to the camera through two USB identities: normal Mass Storage `054C:0E8A`, and the authenticated service connection `054C:0336`. Both need a WinUSB driver.

1. Turn on the camera, choose Mass Storage and connect it to the computer.
2. Open **连接与驱动 (Connection & drivers)** in the left sidebar.
3. Click **检测相机与驱动 (Detect camera & drivers)**. The log should show `054C:0E8A`. If it doesn't, check the cable and the USB mode.
4. Click **准备两阶段驱动并测试连接 (Prepare two-stage drivers & test connection)**:
   - The app first installs the driver for `0E8A`, then switches the camera to its service connection and installs the driver for `0336` once it appears.
   - Windows may ask for administrator permission **once or twice**. Click Yes.
   - An identity that already has a usable driver (WinUSB, libusbK or libusb0) is kept as it is.
   - The camera may show "Please check the connected device" during this step. That's expected.
5. You're done when the log says **"服务连接成功，驱动准备结束" (service connection succeeded; driver setup finished)**. This step **does not write the camera firmware**.
6. **Recommended:** before your first write, click **检测 USB 连接稳定性（只读）(Check USB stability, read-only)** to test the cable and port.
   - The check runs for **at least 2 minutes**. It repeatedly reads the camera's two program files (the same files a write reads back in full) and compares every round with the first, byte for byte.
   - Any read error, any mismatch, or any single read taking longer than 20 seconds fails the check.
   - It only reads and never writes to the camera.
   - If the connection drops during a write or readback, the result can become "unknown", which is hard to recover from. Confirm the connection is stable before you write.
   - If the check fails, try another cable or a USB port on the back of the computer until it passes.
   - Passing doesn't guarantee the connection will never drop during a write. Keep the cable and power steady while writing.

> [!TIP]
> One-click install also checks and prepares the drivers at the start. Doing this step separately first means any driver problem shows up before anything is written.

**macOS:** no driver installation is needed.
- Close Photos, Image Capture and anything else that might be using the camera's card.
- On **连接与驱动**, click **准备 USB 服务连接 (Prepare USB service connection)**.
- Every camera operation opens a Terminal window. Type your **Mac login password** there so the app can take over USB through sudo. The app never reads or stores the password; closing the window before typing it cancels the camera operation.

### Driver errors: uninstall, then reinstall

The driver state may be wrong if any of these happen:
- Step 1 fails, or reports that `0336` appeared but its interface couldn't be opened.
- You previously installed another driver with Zadig or a similar tool.
- Windows keeps recognizing the camera incorrectly after you connect it.

In that case, **uninstall first, then reinstall with Step 1**:

1. On **连接与驱动**, click **卸载相机驱动，恢复 Windows 默认连接 (Uninstall camera driver, restore Windows default)**. Confirm, and allow administrator permission in the Windows prompt.
   - Only third-party drivers for Sony `054C:0E8A` and `054C:0336` are removed. Other devices are untouched, and the camera firmware is not modified.
   - The driver packages are backed up to the job folder before removal.
2. Follow the log:
   - Usually: **unplug USB and plug it back in using Mass Storage mode**, so Windows rebinds its default driver.
   - If the log says Windows needs a restart, restart the computer (the app never restarts it for you).
3. Go back to [Step 1](#step-1-install-the-drivers-windows) and click **准备两阶段驱动并测试连接** again.

If it still fails, try another cable and a USB port on the back of the computer, and run **检测 USB 连接稳定性（只读）** to narrow it down. If that doesn't help, click **导出诊断包 (Export diagnostics)** at the bottom of the window and share the bundle in the community group.

### Still failing: install with Zadig

On computers where the app's automatic driver install fails, installing the driver by hand with [Zadig](https://zadig.akeo.ie/) usually works. Nothing is written to the camera; this only changes which driver this computer uses for the camera's two USB identities.

On the app's **连接与驱动 (Connection & drivers)** page, the **用 Zadig 手动安装驱动（自动失败时） (Install with Zadig)** button sits next to **准备两阶段驱动并测试连接（自动） (automatic)** and opens these same steps with a Zadig download link.

**First: the camera has two USB identities, and both need a driver**

| Stage | Name in Zadig | USB ID | When it appears |
| --- | --- | --- | --- |
| Normal connection | `ILCE-7CM2` | `054C` `0E8A` | Camera on, Mass Storage selected, plugged in |
| Service mode | `Sony USB Device` | `054C` `0336` | Only after the app authenticates; the camera usually shows "Please check the connected device" |

**Prepare**

1. Download the latest `zadig-x.x.exe` from the Zadig website (a single file, nothing to install).
2. Close this app completely.
3. Switch the camera on and set USB connection to **Mass Storage** in its menu. Connect it directly with a data cable: no hub, and on a desktop PC use a port on the back.

**Part 1: driver for `0E8A`**

1. Right-click Zadig and choose **Run as administrator**. If it asks about checking for updates, either answer is fine.
2. In the **Options** menu, tick **List All Devices**. Without it the camera doesn't show up.
3. Pick **`ILCE-7CM2`** in the drop-down at the top.
4. **Check that the USB ID reads `054C` `0E8A`.** If it doesn't, you picked the wrong entry; try another. Don't change the driver of keyboards, mice, USB drives, network adapters or any other device.
5. The current driver (for example `USBSTOR`) is left of the green arrow. In the driver box right of the arrow, use the up/down arrows to choose **libusbK**.
6. Click the big **Replace Driver** button (it reads **Install Driver** when there is no driver yet). Wait 1–2 minutes until it says **The driver was installed successfully**.
7. Afterwards the camera's drive letter disappears and the camera shows "Please check the connected device". Both are normal.

**Part 2: make `0336` appear, then give it a driver**

1. Leave Zadig open. In this app open **连接与驱动 (Connection & drivers)** and click **准备两阶段驱动并测试连接 (Prepare drivers and test connection)**.
2. The app uses the `0E8A` driver you just installed and authenticates. The camera then becomes `Sony USB Device` (`054C 0336`).
   - If the app installs the `0336` driver itself and the log says **“服务连接成功，驱动准备结束” (service connection succeeded, drivers ready)**, you're done; go to Part 3.
   - If the log says `0336` has no driver, its interface can't be opened, or `0336` never appears: **don't unplug the cable or switch the camera off**; continue with the next step.
3. Back in Zadig, click **Options → List All Devices** again to refresh. Pick **`Sony USB Device`** and **check that the USB ID reads `054C` `0336`**.
   - If `0336` isn't listed, the camera has already left service mode. Repeat step 1 of this part and refresh Zadig as soon as `0336` appears.
4. Choose **libusbK** again, click **Replace Driver** or **Install Driver**, and wait for the success message.

**Part 3: power-cycle and test again**

1. Unplug USB, switch the camera off and **remove the battery for about a minute**. Put it back, switch on, select Mass Storage and reconnect.
2. In this app click **准备两阶段驱动并测试连接** again. Once the log says **“服务连接成功，驱动准备结束”**, continue with [Step 3: One-click install](#step-3-one-click-install).

**Check the result:** Windows Device Manager should show a **libusbK USB Devices** category containing `ILCE-7CM2`, and `Sony USB Device` once the `0336` driver is installed.

**Problems**

- **libusbK fails to install:** run Zadig as administrator again. If it still fails, choose **WinUSB** instead. The app works with WinUSB, libusbK or libusb0.
- **The camera isn't in the drop-down:** make sure **List All Devices** is ticked, the camera is on in Mass Storage mode, and try another data cable.
- **To undo it:** click **卸载相机驱动，恢复 Windows 默认连接 (Uninstall camera driver)** on the **连接与驱动** page; this also removes drivers installed with Zadig. Then unplug and replug USB and the camera appears as a drive again.
- **Macs need no driver.**

### Step 2: Installed an earlier version? Restore factory functions first

**If this camera has ever used any version of this project, restore factory functions before installing 3.0.** That includes FL23 v1.0/v2.x, looks imported with `lut.py`, `shutter.py` or `vertical.py`, and earlier desktop previews. This clears leftovers from older versions so 3.0 starts from a clean stock 2.01 state.

A camera that was never modified can skip this step.

1. On the camera, switch Creative Look to **ST**.
2. Open **恢复原厂功能 (Restore factory functions)**, select an original recovery source, optionally tick **同时恢复无障碍语音包 (Also restore Voice Guide audio)**, and click **开始一键恢复 (Start one-click recovery)**.
   - Select official 2.01 firmware or a usable original same-body backup. The app ships a recovery layout, not original recovery bytes. Voice restoration is optional within this full recovery flow.
   - Body calibration, counters and unrelated settings are kept.
3. After the write and full readback, a dialog says **the restore is not finished yet**. Do a [cold reload](#before-you-start) and check that the camera shows a live view.
4. Reconnect USB (Mass Storage) and click the same primary button, now labeled **继续完成一键恢复 (Continue and finish recovery)**. The restore is complete only when this check passes; the app then clears the old installation state.

> [!WARNING]
> Restoring sets all six custom slots to ST. Recipes you had in them **cannot be recovered**. Write down any settings you want to keep first.

If recovery reports an error, preserve its diagnostic bundle. When the primary button says **继续完成一键恢复**, it verifies completed writes without flashing the programs again. Recovery from interruption or damage is not guaranteed.

### Step 3: One-click install

> [!IMPORTANT]
> Finish [Step 1](#step-1-install-the-drivers-windows) before the one-click install, and make sure the log says “服务连接成功，驱动准备结束” (service connection succeeded, drivers ready). Many failed installs come from starting the one-click install before the drivers work. The app also reminds you the first time you run it on a computer. If the drivers won't install, use [install with Zadig](#still-failing-install-with-zadig).

1. Open **首页 · 一键安装 (Home · One-click install)**. These are selected by default:
   - **Install the six built-in looks** (replaces custom slots 1–6; Sony's own Creative Looks are kept)
   - **Enable FL2/FL3**
   - **Enable Sony's native electronic shutter sound**
   - **Save Vertical Display as on**
   - **Install the Lightroom auto-profile plugin**: optional, needs Lightroom Classic on this computer
2. Click **一键安装 (One-click install)** and confirm power. The app checks the drivers, merges every selected option into a single write and reads everything back.
3. When the dialog says reading and writing have ended, do a [cold reload](#before-you-start).
4. Switch the camera on, reconnect USB (Mass Storage) and click **继续安装 (Continue installation)** on Home. It's the same button. The app checks that the camera has restarted and loaded the changes, then sets up sound and the plugin. **Nothing is written again.**
5. An **Installation complete** dialog lists the looks and features that were installed. You can reopen it later with **查看上次安装结果（不连接相机）(View last installation result, no camera access)**.

If the app says that names are written but programs are not yet, the camera is still holding its old resources. Do a cold reload as the dialog says, reconnect and click **继续安装** again. Names are not written twice.

**Default six looks:**

| Custom slot | 1 | 2 | 3 | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- | --- |
| Look | Classic Neg. (NC) | Classic Chrome (CC) | Nostalgic Neg. (NN) | Astia | GR Positive Film | GR Negative Film |

To install your own looks instead, untick the built-in six, expand **改用自己的 A7Look 文件 (Use your own A7Look files)** and pick an `.a7look` file for each slot. Slots left empty stay as they are.

### Step 4: Check on the camera

- Switch between ST and each custom slot. The live view should change immediately. Take a photo and play it back.
- Keep each custom slot's base look set to ST; with another base look the custom look may not apply.
- In the Creative Look list, check that FL2 and FL3 can be selected, shot and played back.
- Take a shot with the electronic shutter and listen for the sound. If you hear nothing, check the camera's Audio Signals setting.
- Hold the camera vertically and check that the shooting information rotates.

The built-in looks are fitted approximations of their source DCPs; colors may not match the DCP exactly.

## Using each feature on its own

Every write follows the same pattern: write → full readback → dialog asking for a cold reload. Once Step 1 is done, each page can be used on its own.

### FL2 / FL3

- **启用／重新启用 FL2 / FL3 (Enable / re-enable)**: cold-reload after the write. If you can select them on the camera, you're done; no need to reconnect and verify.
- **从列表移除 FL2 / FL3，保留自定义外观 (Remove from list, keep custom looks)**: hides the menu entries only. Shared code used by custom looks stays, so you can enable them again later.
- Switch the camera to ST before removing them.

### Custom Creative Looks

1. Click **+ 添加操作项 (Add operation)** once for each slot you want to change:
   - **写入 A7Look (Write A7Look)**: choose a `.a7look` file and, optionally, the name shown on the camera (empty uses the name stored in the file).
   - **恢复 ST 默认 (Restore ST)**: resets the slot to ST. New items default to this.
2. Click **查看并应用这 N 项更改 (Review and apply N changes)**, check the list and confirm. All listed slots are written in one go; other slots are left alone.
3. Cold-reload and it's ready to use. No separate verification needed.

> [!NOTE]
> Custom looks are written with **ST as their base look**. Just select the custom slot on the camera; you don't need to switch the Creative Look to ST. But don't change that custom slot's base look to anything other than ST in the camera menu, or the custom look may not apply or the colors may be wrong; switching it back to ST fixes it. The camera does not lock this option.

Tools on the same page:
- **打开内置 DCP／A7Look 配对库 (Open paired DCP/A7Look library)**: 15 pairs (11 Fujifilm, 4 Ricoh); each DCP sits next to its `.a7look` with the same name.
- **从 DCP／LUT 生成 A7Look… (Generate A7Look from DCP/LUT)**: offline conversion; doesn't connect to the camera.
  - A **CUBE** must take **Sony ST / sRGB** input and output sRGB. **Log LUTs such as S-Log3 can't be used directly**; see [LUT formats and color spaces](docs/en/lut-formats.md).
  - A **DCP** is parsed and fitted by the app itself; Lightroom isn't needed.
- **安装 LrC 自动识别插件… (Install Lightroom plugin)**: after installing, enable it once in Lightroom's Plug-in Manager. From then on, when you import RAW files it applies the DCP for the slot each shot used. It never alters the RAW data itself.

### Electronic shutter sound

1. **开启电子快门声 (Turn on shutter sound)**: turns on Sony's native electronic shutter sound. Cold-reload after the write.
2. Choose an audio or video file, set the **start** and **length** (0.01–2 s), then click **转换所选片段 (Convert selected clip)**. This runs on the computer only.
3. Optionally adjust the volume with **−3 dB / +3 dB / 还原转换时音量 (reset to converted volume)**.
4. Click **保存当前自定义声音 (Save current custom sound)** and cold-reload after the write.
5. **相机内临时试听 (Temporary in-camera audition)** is optional. While auditioning, **keep the camera on**, unplug USB and take a test shot; reconnect and save if you like it.
6. To go back to the original sound, click **恢复原厂音效 (Restore factory sound)**.

### Vertical Display

> [!NOTE]
> The vertical menu frames are being rewritten. This section will be updated when that work is finished.

- **启用竖屏显示 (Enable Vertical Display)**: saves the switch. After a cold reload, shooting information and icons rotate when you hold the camera vertically.
- **关闭竖屏显示 (Disable Vertical Display)**: turns it off first, then reverts the related changes.
- Both buttons are safe to click again; nothing is rewritten when the state already matches.

### Restore factory functions

See [Step 2](#step-2-installed-an-earlier-version-restore-factory-functions-first). The advanced section also offers two other ways to restore:
- Import a complete stock `BODYDATA.DAT` and restore from it.
- Return to an earlier state from an old body backup (one made by older FL23 or `lut.py` versions).

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Camera shows "Please check the connected device" | Normal. Follow the app's log. |
| `054C:0E8A` not found | The camera isn't in Mass Storage mode, or the cable can't carry data. Fix it and replug. |
| `0336` never appears | The app cools down and retries automatically, up to 3 times. If it still fails, see [Driver errors](#driver-errors-uninstall-then-reinstall) or [install with Zadig](#still-failing-install-with-zadig). |
| After authentication the camera jumps to playback and `0336` never appears | Try a USB 2.0 port on the computer (or a USB 2.0 cable or hub). On some computers the camera won't enter service mode over a USB 3 high-speed link. |
| `0336` appears but its interface can't be opened | A driver problem. Uninstall and reinstall the driver; don't keep clicking install. |
| Install or restore was interrupted | Click **the same button** again. The app reads the current state and picks up where it stopped; finished parts aren't rewritten. |
| App reports an unknown result or asks for review | **Don't retry the write.** Click **导出诊断包 (Export diagnostics)** and share it in the community group. |
| No shutter sound | Check that Audio Signals is on in the camera menu. |
| Look colors differ slightly from the DCP | Expected: the in-camera table is a fitted approximation. |
| Terminal asks for a password on a Mac | Enter your Mac login password; it's used by sudo to take over USB. |

A diagnostic bundle contains device information and local paths, so review it before sharing it publicly. It never includes firmware, body calibration or photos.

## Verification status

| Area | Status |
| --- | --- |
| FL2/FL3, six-look install, factory restore | Written, read back and verified after restart on the author's Windows + A7C II |
| Custom look preview/photos, temporary audition | Tested on the same camera |
| Persistent custom shutter sound | Offline tests and packaged self-test pass; long-term camera testing in progress |
| Vertical Display (including menu frames) | Being rewritten; camera acceptance pending |
| macOS USB | Package builds; USB on a real Mac not yet verified |

Offline tests and byte readback can't prove the camera works correctly in every situation, and everything so far has been verified on a single camera. Test records for each version are in the [changelog](docs/en/changelog.md).

## Command line and development

The interface covers everyday use. The original command-line tools remain for advanced users and development:

| Entry | Purpose |
| --- | --- |
| `python desktop.py` | Run the desktop app from source (64-bit Python 3.11; `pip install -r desktop-requirements.txt` first) |
| `FL23.cmd` | Legacy FL2/FL3 command-line installer |
| `python lut.py` | Legacy look import and single-slot restore |
| `python recovery.py` | Full rollback from an original backup |
| `python a7look_compile.py` | Offline DCP/CUBE → `.a7look` compiler |

Offline tests (no camera access): `python -m pytest dev/desktop -q`. Architecture, build and packaging: [development guide](docs/en/development.md). Read [AGENTS.md](AGENTS.md) before letting an AI change the code.

## Older releases

- [v2.2-preview.1](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.2-preview.1): command-line FL23, `lut.py`, `recovery.py`
- [v2.1](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1) · [v1.0](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v1.0)
- [All 18 original DCP files](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1/a7c2-dcp-profiles-2026-10-18.zip) ([sources](docs/en/notices.md))

If your camera used an older version, do [Step 2](#step-2-installed-an-earlier-version-restore-factory-functions-first) before upgrading.

## Credits and licenses

Original project code in this distribution uses the unmodified standard [PolyForm Noncommercial License 1.0.0](LICENSE). All commercial use and profit-making are prohibited. Earlier versions and third-party material retain their original terms; see the [legacy MIT text](docs/licenses/project-legacy-MIT.txt). DCPs, reference looks and bundled third-party components keep their own licenses and attribution; see [notices](docs/en/notices.md). Fujifilm DCP references are credited to **门萨特里顿** and Ricoh references to **爸总林先森** on Xiaohongshu.

This is independent research, not affiliated with Sony, Fujifilm, Ricoh or Adobe. Look names imply neither endorsement nor exact color equivalence, and this tool is not a Sony-signed update.

## Film look comparisons

<details>
<summary>Open the scene-by-scene comparison gallery</summary>

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

</details>

## Acknowledgements

This is my first open-source project, and I never expected this much attention and support. Thank you, everyone.

- **Collaborators:** thanks to [@UzLung1435](https://github.com/UzLung1435) for the FL23 refactor, the USB compatibility fixes and the photo/movie curve routing ([#5](https://github.com/QAQLeonard/a7c2-fl23-research/pull/5), [#6](https://github.com/QAQLeonard/a7c2-fl23-research/pull/6)), and to everyone who opened issues, sent pull requests or shared ideas.
- **Color:** thanks to **门萨特里顿** and **爸总林先森** on Xiaohongshu for the DCPs, and to the community members who helped fit and compare the color standards. The built-in looks wouldn't exist without you.
- **Projects this work builds on and cites:**
  - [lzh2016zzz/a7cr-fl23-research](https://github.com/lzh2016zzz/a7cr-fl23-research): FL2/FL3 porting research on the A7CR, the starting point for this project's parameter, label and WBI methods.
  - [Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware): FL2/FL3 firmware adaptation and RAW color research for the A7R V, a key reference for porting the FL2/FL3 color data.
  - [MDHan/a7c2-fl23-macos](https://github.com/MDHan/a7c2-fl23-macos): the macOS take on the A7C II, the reference for identifying camera storage and claiming USB on a Mac.
  - [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE), [ma1co/fwtool.py](https://github.com/ma1co/fwtool.py) and [YuuLuo/a7c2-service-preload](https://github.com/YuuLuo/a7c2-service-preload): service-mode communication, firmware parsing and A7C II service-mode research.
  - And thanks to every developer who cites, shares or builds on this project.
- **Testers:** thanks to everyone who tested on their own cameras and patiently sent back logs. Every report made the tool safer.
- **Everyone:** thanks to all who starred, shared and joined the community chats. You brought this project to 3.0.

## Sponsor

If this project helped you, you're welcome to buy me a coffee ☕. Sponsoring is entirely optional, unlocks nothing, and the project will stay free and open source.

<table>
  <tr>
    <td align="center"><img src="docs/images/sponsor/wechat.png" alt="WeChat Pay QR code" width="200"><br>WeChat Pay</td>
    <td align="center"><img src="docs/images/sponsor/alipay.png" alt="Alipay QR code" width="200"><br>Alipay</td>
    <td align="center"><img src="docs/images/sponsor/usdt-bep20.png" alt="USDT (BEP20) QR code" width="200"><br>USDT (BEP20)</td>
  </tr>
</table>

**USDT address** (USDT on **BNB Smart Chain / BEP20** only):

```text
0xbf0b2900f7a45a029a42013b90911f796735a753
```

> [!WARNING]
> Send USDT over BEP20 only. Other networks or tokens may be lost, and please don't send NFTs to this address.
