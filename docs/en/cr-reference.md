# A7CR Pixel Shift reference collection

[Research progress](pixel-shift.md) · [简体中文](../zh-CN/cr-reference.md)

For an owner of a **Sony A7CR / ILCE-7CR** willing to contribute reference data from the native feature. No modification, firmware upgrade or downgrade is required. Record the actual firmware version; 2.01 best matches the current research, but retain data from other versions too.

| Data | Purpose | Amount |
|---|---|---|
| Ordinary RAW before/after, plus native four-shot sources | Measure the reference displacement pattern, pixel scale and before/after image difference | At least 6 ARWs; a repeated four-shot group brings the total to 10 |
| Menu photos, phone video and notes | Identify options, interval, completion timing and errors | Firmware/settings photos and one full-cycle video |
| Optional USB settings snapshots | Compare native OFF → four-shot selected → OFF settings; optional CP backup shadows | One read command at each state |

**USB collection reads settings snapshots, not CP execution memory or an in-exposure motion/settling trace.** The current pure-read path cannot provide those traces. Actual displacement, settling and return to center require further interpretation of original images and other evidence; the tool does not claim to verify them.

## 1. Prepare

Extract the collector ZIP and open a terminal there. File collection needs Python 3.8 or later and no extra dependencies. Windows can replace `python` with `py -3`; macOS uses `python3`.

```text
python collect_cr_reference.py init CR-reference --firmware 2.01 --lens "actual lens"
```

Replace `2.01` with the camera's actual version. This creates a new directory without accessing USB or replacing an existing session. The [source](https://github.com/QAQLeonard/a7c2-fl23-research/tree/feature/pixel-shift/dev/pixelshift) is included in the package. FL23/LUT installation is not required.

## 2. Capture native reference images

Use a tripod and a static, detailed physical subject such as printed text or books. Avoid displays, flickering light and moving subjects. Use still-photo M mode, fixed exposure/ISO/white balance and manual focus. Turn stabilization off and record the original settings. Choose RAW; retain and record any RAW type enforced by the native feature.

Keep the camera, lens, composition and settings fixed; disconnect USB during capture:

1. Set Pixel Shift **OFF**, take one ordinary RAW and copy it to `before`.
2. Choose native **four-shot Pixel Shift, 1-second interval**. If unavailable, use an offered interval and record it in `session.json`.
3. Press the shutter once, wait for all four images and card writing to finish, then copy the four **original ARWs** to `four-shot`. Do not convert to DNG, resize, rewrite metadata or supply only a composite.
4. Preferably capture another complete group in the same scene and copy it to `four-shot-repeat`. This group is optional.
5. Set Pixel Shift back to **OFF**, wait for normal live view, take one ordinary RAW and copy it to `after`. Restore personal settings afterward.

Record the whole cycle with a phone, preferably including the shutter press and camera display, and place the video in `evidence`. Include firmware/menu/interval photos. An optional Sony Imaging Edge ARQ or composition-success screenshot is useful, alongside the original four sources.

Keep original filenames and put only the relevant images in each folder. Complete `session.json` with the actual lens/interval, shooting conditions and any movement, restart or error. Set the two `...user_confirmed` fields to `true` after confirming one camera/static scene and fixed settings.

## 3. Optional read-only USB collection

This uses Sony's service reading protocol and **temporarily changes USB identity**. It does not write ROM, camera files, capture settings or memory patches; upload/execute native payloads; save parameters; or operate the shutter. A successful session exits service mode; failures preserve partial evidence without automatic retry.

USB collection requires Python 3.9 or later. Install dependencies needed only for USB:

```text
python -m pip install -r cr-reference-usb-requirements.txt
```

Windows needs a WinUSB/libusbK-accessible camera interface. If Zadig is needed, select the connected **ILCE-7CR**; the service identity is **Sony USB Device, 054C:0336**. Do not reuse a C2 product ID or replace another device's driver. The first identity switch may stop because the service driver is missing. Preserve its report, wait for the program to finish, address the driver, disconnect and normally reconnect in Mass Storage mode before making a fresh attempt. The collector does not install or replace drivers.

macOS does not use Zadig; the dependencies supply libusb. Close photo-import applications using the camera. File handling uses portable Python. USB operation has not been physically validated on an A7CR or Mac; the first report needs review and is not established hardware support.

Connect only one A7CR, with adequate battery, in **Mass Storage** mode. **Wait for each command to finish before unplugging or changing menus.** Do not shoot during collection.

```text
python collect_cr_reference.py usb CR-reference --label off-before --cp-shadows
```

Run this first with native Pixel Shift **OFF**. `--cp-shadows` additionally reads nineteen native CP backup-shadow units for reference. They are not CP execution RAM or automatically identified displacement calibration.

Disconnect USB, select native **four-shot** mode without shooting, reconnect Mass Storage and run:

```text
python collect_cr_reference.py usb CR-reference --label four-selected
```

When finished, disconnect USB, select **OFF**, reconnect and run:

```text
python collect_cr_reference.py usb CR-reference --label off-after
```

USB/service mode can change observed camera state. `four-selected` records the owner's preceding action; it does not guarantee every runtime field retains its shooting-state value after connection. Each command preserves both RAM settings and saved settings for comparison.

If the camera or connection reports an error, stop subsequent steps and retain that `runtime` folder's `snapshot.json` and files. Do not run initialization, modification or recovery tools to complete the collection, or repeatedly power-cycle to obtain missing data.

## 4. Check and package

```text
python collect_cr_reference.py check CR-reference
python collect_cr_reference.py pack CR-reference
```

This creates the adjacent `CR-reference.private.zip`. The tool checks model, four-source grouping/ordinals and exposure consistency, preserves originals and uses no firmware-provenance hash gate. Missing optional USB/video evidence is reported. Required RAW errors prevent normal packaging; `pack CR-reference --allow-partial` explicitly produces an `INCOMPLETE` report if only partial data is available.

**Share the ZIP privately, not in a public issue or repository.** Original photos/settings may contain capture times, locations, serial numbers and other camera/owner information. Files are preserved without metadata changes, and nothing is uploaded automatically. Reference CR data must not be written into another body.

The collector has offline file/protocol tests; that is not physical A7CR USB validation. Include completed steps, actual firmware version and whether the camera ended with normal live view/capture.
