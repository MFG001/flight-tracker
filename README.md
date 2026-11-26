# Flight Tracker

A cockpit-style ADS-B display for the Maverick Field Gear Flight Tracker: a Raspberry Pi 4 and a Waveshare 4-inch round 720×720 DSI touch screen.

![Flight Tracker showing live ADS-B traffic](docs/build/photo-live-radar.jpg)

![Aircraft detail card](docs/build/photo-detail-card.jpg)

![Assembled Flight Tracker instrument, with the thin faceplate, original dome caps, and knob](docs/build/hero-assembled.jpg)

Flight Tracker by **Maverick Field Gear**. Purpose-built. Field-proven.

**[Print on MakerWorld](https://makerworld.com/en/models/3669492-aircraft-flight-tracker-desktop-ads-b-radar)** · **[Download latest release](https://github.com/MFG001/flight-tracker/releases/latest)** · **[Build guide](docs/BUILD.md)** · **[Software](docs/SOFTWARE.md)** · **[License](LICENSE)**

**Instruction booklets (PDF):** [Overview and Build](docs/Flight_Tracker_Overview_and_Build_Booklet.pdf) · [Software](docs/Flight_Tracker_Software_Booklet.pdf)

## Contents

1. [What you need](#what-you-need)
2. [Build](#build)
3. [Use the unit](#use-the-unit)
4. [License](#license)

## What you need

### Printed parts

Print the case from the [MakerWorld listing](https://makerworld.com/en/models/3669492-aircraft-flight-tracker-desktop-ads-b-radar). Use the thin faceplate and the original dome caps, not the later flush plugs.

- [ ] **Set A** — faceplate and knob (plate 1, black)
- [ ] **Set B** — can, foot, and four dome caps (plate 2, Dark Gull Gray)

H2S, Set A + Set B: about 5 h 56 m, 224 g. A1: about 7 h 16 m, 224 g; plate 1 needs AMS lite for the gray legends. Supports off.

### Hardware

- [ ] Raspberry Pi 4 and a microSD card
- [ ] Waveshare 4inch DSI LCD (C) — the 4-inch round 720×720 panel for this unit
- [ ] Waveshare PI4-FAN-PWM fan and heatsink
- [ ] USB-C power supply and a **straight** USB-C cable
- [ ] 4 × M2.5×4 heat-set inserts
- [ ] 4 × M2.5×8 socket-head screws
- [ ] 3 × M4×8 button-head screws

The Pi mounts on the display kit’s standoffs. No receiver is required. The default feed is [adsb.fi](https://adsb.fi/).

### Tools

- Soldering iron for the inserts
- Hex key with about 30 mm of reach, for the rear M4s
- Hex driver for the M2.5 screws

## Build

Photos and full steps: **[docs/BUILD.md](docs/BUILD.md)**. Printable sheet: [assembly_sheet.pdf](https://mfg001.github.io/flight-tracker/assets/build/assembly_sheet.pdf).

![One-page Flight Tracker assembly sheet](docs/build/assembly_sheet-web.jpg)

1. Print Set A and Set B from [MakerWorld](https://makerworld.com/en/models/3669492-aircraft-flight-tracker-desktop-ads-b-radar). Peel the brim.
2. Press four M2.5×4 inserts into the front corners of the can. Let them cool.
3. Mount the Pi and fan on the display. Thread the USB-C cable through the rear exit, then plug it in.
4. Front-load the stack. Fit the three M4×8 screws from the rear. Snug only.
5. Fit the faceplate with four M2.5×8 screws. Snug only.
6. Press the four dome caps over the screw heads.
7. Snap the BRT knob in from the front.

How to flash the card and install the software is in the [build guide](docs/BUILD.md#6-flashing-the-os).

## Use the unit

Full steps: **[docs/SOFTWARE.md](docs/SOFTWARE.md)**. Or download the [Software booklet (PDF)](docs/Flight_Tracker_Software_Booklet.pdf). Current release: [v1.0.20](https://github.com/MFG001/flight-tracker/releases/tag/v1.0.20).

1. Plug in power and wait for the radar screen. You may see the Raspberry Pi start first, then a Flight Tracker splash. A new unit starts on KJFK until you set your own location.
2. Hold the clock at the bottom of the radar screen for 2 seconds, then tap **WI-FI SETUP**. Or use the join card if it is already on the screen.
3. The screen shows one Wi-Fi card at a time, and it changes through three screens. Scan the first QR (**NO WI-FI** / **Join setup**) so your phone joins **FlightTracker-Setup**. When the card changes to **PHONE JOINED** / **Open setup**, scan the second QR to open the setup page. Open **WI-FI**, pick your network, enter the password, and tap **CONNECT**. When the card changes to **CONNECTED**, join that same home Wi-Fi on your phone and scan the third QR, or open the address shown, or open `http://flighttracker.local/`.
4. Set your location under **LOCATION**. For night dim, open **NIGHT**, choose **Sunrise and sunset**, and enter a US ZIP code or coordinates.
5. For updates, open **SOFTWARE** and tap **CHECK FOR UPDATES**.

On the setup page, **WI-FI** lists saved networks. You can forget one, make one preferred, or change its password. On the screen, hold the clock for 2 seconds for **TRAFFIC LIST**, **TOUCH TEST**, and the radar sweep. Tap a tail-number box for flight details. Use **−** and **+** to change range.

## License

Software is under the [Maverick Field Gear Flight Tracker License](LICENSE): personal, non-commercial use; no modification or sale. Case print files are [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/). Print files: [MakerWorld](https://makerworld.com/en/models/3669492-aircraft-flight-tracker-desktop-ads-b-radar).

© 2026 Maverick Field Gear. All rights reserved.
