# Build the Flight Tracker

[Flight Tracker](../README.md) / Build guide

**[README](../README.md)** · **Build guide** · [Software](SOFTWARE.md) · [Signed updates](tokenless-updates.md) · [Wi-Fi QR test](wifi-qr-test.md)


Flight Tracker by **Maverick Field Gear**. Purpose-built. Field-proven.

This is the step-by-step build for the compact B desk instrument: a 140 mm printed case, a Raspberry Pi 4, and a Waveshare 4inch DSI LCD (C). The current software release is [v1.0.13](https://github.com/MFG001/flight-tracker/releases/tag/v1.0.13). Print files are on the [MakerWorld listing](https://makerworld.com/en/models/3666834-flight-tracker-instrument-case) ([@mavfieldgear](https://makerworld.com/en/@mavfieldgear)).

A one-page letter assembly sheet, with the hardware photographs, a parts list, and print settings, is shown below. A printable PDF of the same sheet is on the [Pages build guide](https://mfg001.github.io/flight-tracker/build.html) as [assembly_sheet.pdf](https://mfg001.github.io/flight-tracker/assets/build/assembly_sheet.pdf).

![One-page Flight Tracker assembly sheet](build/assembly_sheet-web.jpg)

## Contents

1. [Parts and hardware](#1-parts-and-hardware)
2. [Printing](#2-printing)
3. [Heat-set inserts](#3-heat-set-inserts)
4. [Mounting the Pi, fan, and display](#4-mounting-the-pi-fan-and-display)
5. [Closing the case](#5-closing-the-case)
6. [Flashing the OS](#6-flashing-the-os)
7. [Installing the software](#7-installing-the-software)
8. [First setup](#8-first-setup)
9. [Troubleshooting](#9-troubleshooting)

## 1. Parts and hardware

Finished size is about **140 × 155 × 100 mm**. The files are sliced for a Bambu H2S, supports off. It also prints on a Bambu A1; re-slice the models for that printer.

![Kit layout: faceplate, knob, screws, gray dome plugs, can, and the Pi mounted on the display](build/photo-kit-layout.jpg)

The faceplate, knob, four original gray ribbed dome plugs, screws, can, and the Pi already mounted on the round display.

### Printed parts

| Part | Colour | Delivery file (print the `.gcode.3mf`) |
| --- | --- | --- |
| Set A: 140 mm thin faceplate and BRT knob | Black `#161616` with Dark Gull Gray `#545C61` legend inlays (AMS) | `FlightTracker_SetA_faceplate_knob_black_H2S.gcode.3mf` |
| Set B: can + foot, and four original dome caps | Dark Gull Gray `#545C61` | `FlightTracker_SetB_can_caps_gray_H2S.gcode.3mf` |
| Optional insert-fit coupon | Gray | `FlightTracker_compactB_H2S_insert_coupon.gcode.3mf` |

Set A is the thin faceplate and the knob. Set B is the can and foot, plus the four original ribbed dome caps in Dark Gull Gray. These are the original dome caps, not the later flush (flat) plugs.

![Printed parts laid out: faceplate, knob, four gray dome plugs, and the can with inserts](build/01-printed-parts.jpg)

Printed parts, ready to assemble. The four gray ribbed parts are the original dome plugs.

![Thin faceplate, legends, corner pockets, and the BRT hole](build/photo-faceplate.jpg)

The thin 140 mm faceplate, printed face-down, with MAP / TFC / WX / MNU along the top and NAV / HDG / ALT along the bottom.

### Electronics

| Qty | Part | Notes |
| --- | --- | --- |
| 1 | Raspberry Pi 4 | The installer default is a Pi 4 |
| 1 | Waveshare **4inch DSI LCD (C)**, 720 × 720 capacitive touch | Confirm the model on the board. This is not the 4-DSI-TOUCH-C, which needs a different overlay |
| 1 | USB-C power supply suitable for a Raspberry Pi 4, and a microSD card | Raspberry Pi OS Bookworm or Trixie, with a desktop |
| 1 | USB-C cable, **straight** plug | 15–20 mm body, cable no thicker than about Ø4.8 mm. No 90° adapter is needed |
| 1 | Cooling fan and heatsink on the Pi | Waveshare PI4-FAN-PWM. The 17 mm stack fits and works on the built unit |

The Pi screws into the display kit’s own standoffs.

### Fasteners

| Qty | Part | Where |
| --- | --- | --- |
| 4 | CNC Kitchen M2.5×4 heat-set inserts (TC-M2.5x4.0) | Front corners of the can |
| 4 | M2.5×8 socket-head screws, ISO 4762, no washer | Faceplate to the can, under the corner plugs |
| 3 | M4×8 button-head screws, into the display’s own bosses | From the rear. The lower-left display mount is omitted. Verified on the built unit: 3 × M4×8 |

No washers, and no nameplate screws.

## 2. Printing

The MakerWorld files are sliced for a Bambu H2S, PLA, supports off. It also prints on a Bambu A1; re-slice the models for that printer.

- Bambu H2S, 0.4 mm nozzle, textured PEI
- PLA Matte, 220 °C nozzle / 55 °C bed
- **Supports off**

| Set | Time | Filament |
| --- | --- | --- |
| Set A, thin faceplate + knob in black (AMS) | **1 h 18 m 51 s** | **43.08 g** (42.39 g black + 0.68 g grey) |
| Set B, can + foot + 4 dome caps in Dark Gull Gray | **4 h 37 m 32 s** | **181.13 g** |
| Optional insert-fit coupon | 11 m 9 s | 5.53 g |
| **Set total** (A + B) | **5 h 56 m 23 s** | **224.21 g** |

Times are slicer predictions for the H2S profile. The coupon is extra. Print the `.gcode.3mf` for each set, or re-slice the models for an A1. The faceplate prints face-down. Peel the brim. There are no supports to remove.

![Rear of the can, three M4 ports, grille, and desk foot](build/photo-can-rear.jpg)

The rear: three M4 ports, the fan grille, and the wedge foot.

## 3. Heat-set inserts

Press the four CNC Kitchen M2.5×4 inserts into the front corners of the can before you load the electronics.

![Can interior with four brass heat-set inserts visible at the front corners](build/photo-can-interior.jpg)

The four brass inserts, set flush at the front corners. These should need heat.

1. Stand the can on its foot with the front face up and level, or prop it so the front face is level.
2. Use a soldering iron at 10–20 °C above print temperature (CNC Kitchen guidance).
3. Go straight down each hole’s own axis, square to the front face.
4. Set each insert flush with the column face, and square to it.
5. Let the inserts cool before you load the electronics.

Print the optional coupon first if you want to confirm the insert fit.

## 4. Mounting the Pi, fan, and display

Build the display stack on the bench first, then load it into the can.

![Raspberry Pi 4 with fan and heatsink on the back of the round display, DSI ribbon, and a straight USB-C cable](build/02-pi-display-stack.jpg)

The Pi 4 on the back of the Waveshare 4inch DSI LCD (C), with the fan and heatsink, the amber DSI ribbon, the 4-pin power and I2C lead, and a straight USB-C cable.

1. Mount the Pi on the display kit’s own standoffs. Fit the cooling fan and heatsink if you are using one.
2. Connect the 15-pin DSI FPC between the display and the Pi’s DSI connector, and connect the 4-pin lead for 5 V and I2C, as in the [4inch DSI LCD (C) wiki](https://www.waveshare.com/wiki/4inch_DSI_LCD_(C)). In the photograph the ribbon is looped at the side of the Pi.
3. **Before** you seat the stack, thread the USB-C cable through the rear exit from the **outside**, plug end first. Then plug it into the Pi.
4. Confirm the board is **4inch DSI LCD (C)**. A Pi 4 has one 15-pin DSI connector.

Display orientation in this case: USB-C at the lower left, pointing left. The Waveshare PI4-FAN-PWM 17 mm stack fits and works. A taller heatsink may not clear the rear wall.

![Round display seated in the open can, before the faceplate](build/03-display-seated.jpg)

The display seated in the can, before the faceplate goes on.

5. Front-load the display, Pi, and fan stack into the can.
6. Fit the **three** display M4s from the rear, into the display’s own bosses. A hex key needs about 30 mm of reach. Snug only.

## 5. Closing the case

Fit the faceplate, press in the caps, then snap in the knob from the front.

![Faceplate fitted, with four M2.5 screws visible in the corner pockets](build/04-faceplate-screws.jpg)

1. Set the faceplate on the can. Drive four M2.5×8 screws into the inserts, snug only.

![Finished faceplate with four original gray ribbed dome plugs seated, knob beside the unit](build/06-corner-plugs.jpg)

2. Press the four original gray ribbed dome plugs straight over the screw heads until they seat. They sit slightly proud of the bezel. These are the original dome caps, not the later flush (flat) plugs.

![BRT knob installed, with one original gray ribbed dome plug beside it](build/05-knob.jpg)

3. Press the BRT knob into the faceplate from the front, until it snaps.

If a dome plug is too tight, warm it slightly or ream lightly. If it is loose, a dot of glue will hold it.

## 6. Flashing the OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on a computer, not the Pi.

1. Choose **Raspberry Pi OS** with a desktop, Bookworm or Trixie.
2. In Imager’s OS customisation settings:
   - Hostname: `flighttracker`
   - Username: `flighttracker` (set a password you will use for SSH and sudo)
   - Configure wireless LAN if you already know the home network. You can also join Wi-Fi later from the on-screen QR setup.
   - Enable SSH, with password authentication.
3. Write the image to the microSD card, then put the card in the Pi.

The installer also sets the hostname to `flighttracker` and enables Avahi, so the unit answers at `flighttracker.local`. The first-install script below logs in as `flighttracker@flighttracker.local`, so that username needs to match.

## 7. Installing the software

Do this from a Mac or Linux computer on the same network, not on the Pi. The current release is [v1.0.13](https://github.com/MFG001/flight-tracker/releases/tag/v1.0.13). Download `flight-tracker-1.0.13.tar.gz` from that page, or use `curl` as below. Safari may unzip the download to a `.tar` file, which also works.

Power the unit, wait until it has booted and is on the network, then:

```bash
cd ~/Downloads
curl -L -O https://github.com/MFG001/flight-tracker/releases/download/v1.0.13/flight-tracker-1.0.13.tar.gz
tar xf flight-tracker-1.0.13.tar.gz deploy/push-update.sh
bash deploy/push-update.sh ~/Downloads/flight-tracker-1.0.13.tar.gz flighttracker@flighttracker.local
```

The script asks for the Pi password for SSH, then again when `sudo` on the Pi asks. It copies the tarball, unpacks it, and runs `sudo bash install.sh` on the Pi. When it finishes it prints `flight-tracker.service is running 1.0.13`. Then reboot so the display overlay is applied:

```bash
ssh flighttracker@flighttracker.local 'sudo reboot'
```

If `flighttracker.local` does not resolve, use the Pi’s IP address in place of the hostname, still with the user `flighttracker`.

The installer writes the Pi 4 overlay for the 4inch DSI LCD (C), copies the app to `/opt/flight-tracker`, starts `flight-tracker.service` and the fullscreen kiosk, sets the hostname, and leaves settings in `/etc/flight-tracker/config.json`. If you later have the other Waveshare board, 4-DSI-TOUCH-C, that is a different overlay; see the [software notes](SOFTWARE.md#hardware).

You can also clone this repository on the Pi and run `sudo bash install.sh` from the tree. The release tarball and `push-update.sh` are the usual first install from a computer on the LAN.

## 8. First setup

The setup page is `http://flighttracker.local/`. Open it from a phone or computer on the same network.

The scope opens centred on **KJFK**, John F. Kennedy International Airport (latitude 40.6399, longitude −73.7787, the FAA airport reference point). METAR defaults to KJFK. Set your own home on the setup page: an airport-code search, or a latitude and longitude. Save writes `/etc/flight-tracker/config.json` and the running display picks it up without a reboot.

### Wi-Fi QR setup

If the Pi has no saved Wi-Fi, the round display raises a WPA hotspot named **FlightTracker-Setup**. The password is random per device, eight letters, and is shown under a QR code on the glass. A phone camera can scan `WIFI:T:WPA;S:FlightTracker-Setup;P:<password>;;`.

When the phone joins, the display switches to a second QR code for `http://10.42.0.1/`. That is NetworkManager’s usual shared-hotspot address. Save the home Wi-Fi there. After the home network connects, the card changes to “Connected” and a QR code for `http://flighttracker.local/`, then closes.

**MNU → WI-FI SETUP** opens the card again.

### Updates

The Software section on `http://flighttracker.local/` is the place to check, read notes, install, or turn on auto-update.

- A daily check runs at about **09:00 AM Eastern** (America/New_York), with up to five minutes of random delay, so the on-screen prompt appears while people are awake. A unit that was off at 9:00 catches up when it next comes on.
- Background checks 90 seconds after boot and every 6 hours are skipped between 21:00 and 09:00 Eastern.
- **CHECK FOR UPDATES** on the Software card always runs at once.
- When a signed release is ready, the round screen offers **UPDATE NOW** or **LATER**. Later, or no answer within two minutes, books the install for the “Install later at” time (2:00 AM Eastern by default).
- Automatic night installs are **off** until you turn them on. If you turn them on, a 03:10 AM Eastern timer may install when the hour is between 01:00 and 05:00 and the glass and setup page have been idle for 15 minutes.
- Releases are Ed25519-signed and published on this public repository. No API token is stored on the Pi. A failed health check rolls the previous version back.

## 9. Troubleshooting

Restart the kiosk if the glass is up but the display is stuck or blank:

```bash
ssh flighttracker@flighttracker.local 'sudo systemctl restart flight-tracker-kiosk'
```

Other useful checks:

```bash
ssh flighttracker@flighttracker.local 'systemctl status flight-tracker.service flight-tracker-kiosk.service'
ssh flighttracker@flighttracker.local 'sudo journalctl -u flight-tracker.service -n 50 --no-pager'
```

| Symptom | What to try |
| --- | --- |
| `flighttracker.local` does not resolve | Use the Pi’s IP address. Confirm Avahi is running, and that you are on the same network. |
| The script cannot log in | Hostname and username should both be `flighttracker`. Enable SSH in Imager. |
| `sudo: a terminal is required` | Use the `push-update.sh` from this release (1.0.6 and later). Run it in a real Terminal window, not a pipe. |
| Safari turned the download into `.tar` | That is fine. Pass the `.tar` path to `push-update.sh`. |
| The display is blank or the wrong size after the first install | Reboot so the Waveshare overlay loads. Confirm the board is 4inch DSI LCD (C), not 4-DSI-TOUCH-C. |
| No Wi-Fi on first boot | Use the on-screen FlightTracker-Setup QR, then save the home network at `http://10.42.0.1/`. |
| An update never appears | Tap **CHECK FOR UPDATES** on the Software card. The automatic check is at 9:00 AM Eastern. |
| The kiosk does not come back after an update | Restart it with the command above. `journalctl` on `flight-tracker.service` shows whether the server came up as the new version. |

## What the glass shows

Sample screens from [v1.0.13](https://github.com/MFG001/flight-tracker/releases/tag/v1.0.13), home at KJFK, 20 NM, using the bundled demo traffic (not a live feed). Each aircraft label is the tail number; tap the label, not the icon, for the detail card. Helicopter rotors spin on the glass. These three images are the 1.0.13 previews, each on a different background.

| Traffic | Detail card | Standby |
| --- | --- | --- |
| ![Live traffic on the round glass, navy background](build/screens/screen-traffic-navy.jpg) | ![Flight detail card, olive background](build/screens/screen-detail-olive.jpg) | ![Standby screen, cream background](build/screens/screen-standby-cream.jpg) |

Map backgrounds, from the built-in demo. Cycle them with **MAP**.

| Dark | Light | Satellite | Sectional | Scope |
| --- | --- | --- | --- | --- |
| ![Dark map](build/screens/screen-dark.png) | ![Light map](build/screens/screen-light.png) | ![Satellite](build/screens/screen-satellite.png) | ![FAA sectional](build/screens/screen-sectional.png) | ![Radar scope](build/screens/screen-scope.png) |

A render of the thin faceplate on the compact B can:

![Render of the thin faceplate on the compact B case](build/render-thin-faceplate-hero.png)

## Verified on the built unit, and still unverified

**Verified on the built unit:**

- **Display screws:** 3 × M4×8 button-head screws, into the display’s own bosses, from the rear.
- **Fan and heatsink:** Waveshare PI4-FAN-PWM, 17 mm stack, fits and works.

**Still unverified:**

- **USB-C plug length.** A straight 15–20 mm plug is designed to fit, and a straight plug is shown in the photographs.
- First boot on the physical 720 × 720 panel, touch alignment, Avahi, the setup hotspot, a real over-the-air install, and backlight sysfs writes were not verified in this environment. The [software notes](SOFTWARE.md#verified-here-and-not-verified-on-the-hardware) list those items in full.

## License

Software is under the [Maverick Field Gear Flight Tracker License](../LICENSE). It is source-available and free to install and run on a personal build, for non-commercial use. You may not modify it, distribute modified versions, or sell it.

Case print files are [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/). Print files are on the [MakerWorld listing](https://makerworld.com/en/models/3666834-flight-tracker-instrument-case).

---

[← README](../README.md) · [Software →](SOFTWARE.md)

© 2026 Maverick Field Gear. All rights reserved.
