# Flight Tracker

A round, cockpit-style ADS-B display for a Raspberry Pi 4 and a Waveshare 4-inch DSI touch panel.

![Assembled Flight Tracker instrument, with the thin faceplate, original dome caps, and brightness knob](docs/build/hero-assembled.jpg)

Flight Tracker by **Maverick Field Gear**. Purpose-built. Field-proven. Live traffic is drawn inside the circular glass, with range rings, selectable maps, precipitation radar, and the eight bezel actions printed on the case.

**[Print on MakerWorld](https://makerworld.com/en/models/3666834-flight-tracker-instrument-case)** · **[Download latest release](https://github.com/MFG001/flight-tracker/releases/latest)** · **[Build guide](docs/BUILD.md)** · **[License](LICENSE)**

## Contents

1. [What you need](#what-you-need)
2. [Build](#build)
3. [Software](#software)
4. [Troubleshooting](#troubleshooting)
5. [License](#license)

Further docs: [Build guide](docs/BUILD.md) · [Software](docs/SOFTWARE.md) · [Signed updates](docs/tokenless-updates.md) · [Wi-Fi QR test](docs/wifi-qr-test.md)

## What you need

### Printed parts

Print files are on the [MakerWorld listing](https://makerworld.com/en/models/3666834-flight-tracker-instrument-case) ([@mavfieldgear](https://makerworld.com/en/@mavfieldgear)). The listing is one print profile with two plates. Print the `.gcode.3mf`. Use the thin faceplate and the original ribbed dome caps. Do not use the later flush, flat-top corner plugs.

- [ ] **Set A — Faceplate + knob** (plate 1), black `#161616` with Dark Gull Gray `#545C61` legend inlays (AMS). Thin 140 mm faceplate and the snap-in BRT knob. About 1 h 19 m, 43.08 g. File: `FlightTracker_SetA_SetB_2plate_H2S.gcode.3mf`, plate 1 (or the matching Set A file).
- [ ] **Set B — Can + caps** (plate 2), Dark Gull Gray `#545C61`. One-piece can and desk foot, plus four original `caps_fit_v2` dome caps. About 4 h 38 m, 181.13 g. Same file, plate 2.
- [ ] **Optional insert-fit coupon**, gray. A small bar with holes at Ø3.4 / 3.6 / 3.8, about 11 m, 5.53 g. Print this first if you want to confirm the heat-set insert fit.

Set total (A + B): about 5 h 56 m, 224.22 g. Bambu H2S, 0.4 mm nozzle, textured PEI, PLA Matte, 220 °C / 55 °C, 0.20 mm layers, 3 walls, 20 % gyroid, Arachne, outer brim, **supports off**. The faceplate prints face-down. There are no supports to remove.

### Hardware

Confirm the display is a Waveshare **4inch DSI LCD (C)**, not the 4-DSI-TOUCH-C, which needs a different overlay. Details are in the [software notes](docs/SOFTWARE.md#hardware).

- [ ] 1 × Raspberry Pi 4
- [ ] 1 × Waveshare 4inch DSI LCD (C), 720 × 720 capacitive touch
- [ ] 1 × USB-C power supply suitable for a Raspberry Pi 4
- [ ] 1 × microSD card, for Raspberry Pi OS (Bookworm or Trixie, with a desktop)
- [ ] 1 × USB-C cable, **straight** plug, 15–20 mm body, cable no thicker than about Ø4.8 mm. No 90° adapter
- [ ] 1 × cooling fan and heatsink on the Pi — Waveshare PI4-FAN-PWM (Armor-lite + 3510 fan), 17 mm stack, verified on the built unit
- [ ] 4 × CNC Kitchen M2.5×4 heat-set inserts (TC-M2.5x4.0)
- [ ] 4 × M2.5×8 socket-head screws, ISO 4762, no washer
- [ ] 3 × M4×8 button-head screws, ISO 7380, into the display’s own bosses (verified on the built unit)

**Totals: 4 inserts, 4 × M2.5×8, 3 × M4×8.** The Pi screws into the display kit’s own standoffs. No washers, no magnets, no other inserts. The brightness knob is a printed part and snaps in from the front.

No receiver is required. The default live feed is [adsb.fi](https://adsb.fi/) over the internet, for personal, non-commercial use. You can point the setup page at your own readsb or dump1090 `aircraft.json` later; see [Software](docs/SOFTWARE.md#receiver).

### Tools

- [ ] Soldering iron for the heat-set inserts, 10–20 °C above print temperature (CNC Kitchen guidance)
- [ ] Hex key with about 30 mm of reach, for the rear M4s
- [ ] Hex driver or key for M2.5 ISO 4762 socket-head screws

## Build

The illustrated, step-by-step guide is in **[docs/BUILD.md](docs/BUILD.md)**. A one-page letter assembly sheet (hardware photographs, parts, and print settings) is shown below. A printable PDF of the same sheet is on the [Pages build guide](https://mfg001.github.io/flight-tracker/build.html) as [assembly_sheet.pdf](https://mfg001.github.io/flight-tracker/assets/build/assembly_sheet.pdf).

![One-page Flight Tracker assembly sheet](docs/build/assembly_sheet-web.jpg)

Numbered steps, matching the photographs in the [build guide](docs/BUILD.md):

1. **Print the parts.** Run Set A (faceplate and knob) and Set B (can, foot, and four dome caps) from the [MakerWorld listing](https://makerworld.com/en/models/3666834-flight-tracker-instrument-case). Peel the brim; there are no supports to remove. ([Printing](docs/BUILD.md#2-printing))
2. **Set the heat-set inserts.** Press four M2.5×4 inserts into the front corners of the can, flush and square, and let them cool. ([Heat-set inserts](docs/BUILD.md#3-heat-set-inserts))
3. **Mount the Pi.** Fit the Pi 4 and 17 mm fan/heatsink on the display. Connect the DSI ribbon and 4-pin lead. Thread the USB-C cable through the rear exit from the outside, then plug it in. ([Mounting](docs/BUILD.md#4-mounting-the-pi-fan-and-display))
4. **Seat the stack.** Front-load the display, Pi, and fan into the can. Fit the three M4×8 screws from the rear. Snug only.
5. **Fit the faceplate.** Drive four M2.5×8 screws into the inserts, snug only.
6. **Press in the caps.** Press the four original dome caps over the screw heads until they seat.
7. **Snap in the knob.** Press the BRT knob into the faceplate from the front until it snaps.

Then flash the OS, install the software, and do first setup, as in [Software](#software) below and sections [6](docs/BUILD.md#6-flashing-the-os)–[8](docs/BUILD.md#8-first-setup) of the build guide.

## Software

Current release: **[v1.0.13](https://github.com/MFG001/flight-tracker/releases/tag/v1.0.13)**. Download `flight-tracker-1.0.13.tar.gz` from [Releases](https://github.com/MFG001/flight-tracker/releases/latest). Safari may unzip it to a `.tar` file, which also works.

Full install notes, the desktop demo, configuration, and signed-update design are in **[docs/SOFTWARE.md](docs/SOFTWARE.md)**.

### Flash Raspberry Pi OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on a computer, not the Pi.

1. Choose Raspberry Pi OS with a desktop, Bookworm or Trixie.
2. In OS customisation: hostname `flighttracker`, username `flighttracker` (set a password for SSH and sudo), wireless LAN if you already know the home network, and SSH on with password authentication.
3. Write the image to the microSD card, then put the card in the Pi.

### Install from a computer on the same network

Power the unit, wait until it has booted and is on the network, then from a Mac or Linux computer:

```bash
cd ~/Downloads
curl -L -O https://github.com/MFG001/flight-tracker/releases/download/v1.0.13/flight-tracker-1.0.13.tar.gz
tar xf flight-tracker-1.0.13.tar.gz deploy/push-update.sh
bash deploy/push-update.sh ~/Downloads/flight-tracker-1.0.13.tar.gz flighttracker@flighttracker.local
ssh flighttracker@flighttracker.local 'sudo reboot'
```

If `flighttracker.local` does not resolve, use the Pi’s IP address. You can also clone this repository on the Pi and run `sudo bash install.sh`.

### Wi-Fi setup

If the Pi has no saved Wi-Fi, the round display raises a WPA hotspot named **FlightTracker-Setup**. Scan the on-screen QR to join, then save the home network at `http://10.42.0.1/`. After it connects, the card shows `http://flighttracker.local/` and closes. **MNU → WI-FI SETUP** opens the card again.

The setup page is `http://flighttracker.local/`. The scope opens on **KJFK** until you set your own home airport or coordinates.

### Updates

The Software card on the setup page is the place to check, read notes, install, or turn on auto-update. Auto-update is off by default. A daily check runs at about 09:00 AM Eastern. **CHECK FOR UPDATES** always runs at once. Releases are Ed25519-signed on this public repository. No API token is stored on the Pi. See [Software updates](docs/SOFTWARE.md#software-updates) and [Signed updates](docs/tokenless-updates.md).

To try the display on a computer, without the case or a receiver, see the [desktop demo](docs/SOFTWARE.md#desktop-demo).

## Troubleshooting

Restart the kiosk if the glass is up but the display is stuck or blank:

```bash
ssh flighttracker@flighttracker.local 'sudo systemctl restart flight-tracker-kiosk'
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

More detail is in the [build guide troubleshooting](docs/BUILD.md#9-troubleshooting). To test the setup hotspot and join QR on a unit that is already on Wi-Fi, see the [Wi-Fi QR test](docs/wifi-qr-test.md).

## License

Flight Tracker is source-available, not open source. It is released under the **Maverick Field Gear Flight Tracker License** ([LICENSE](LICENSE)):

- Free to download, install, and run on your own personal, non-commercial builds.
- No modification and no distribution of modified versions. Changing settings on the setup page or in `config.json` is allowed.
- No commercial use: no selling the software, or devices, kits, or images that include it.
- You may share unmodified official releases, with the license and credit ("Flight Tracker by Maverick Field Gear", linking to https://github.com/MFG001/flight-tracker).
- Updates come only from official signed releases.
- No warranty. Not for navigation or any safety-of-flight use.

The 3D-printable case files are published separately under [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/), not under the software license. Print files are on the [MakerWorld listing](https://makerworld.com/en/models/3666834-flight-tracker-instrument-case).

Bundled third-party components (node-qrcode, IBM Plex fonts) keep their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Map, weather, and aircraft data terms stay with their owners; see [Data sources and attribution](docs/SOFTWARE.md#data-sources-and-attribution).

© 2026 Maverick Field Gear. All rights reserved.
