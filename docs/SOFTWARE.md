# Software

[Flight Tracker](../README.md) / Software

**[README](../README.md)** · [Build guide](BUILD.md) · **Software** · [Developer notes](DEVELOPER.md)

This document is for the Maverick Field Gear Flight Tracker. That is the desk unit with a Raspberry Pi 4 and a Waveshare 4-inch round 720×720 touch screen.

This document covers how to use the unit after the software is installed. For printing and assembly, use the [build guide](BUILD.md). For install scripts and source builds, use the [developer notes](DEVELOPER.md).

Print files are on the [MakerWorld listing](https://makerworld.com/en/models/3669492-aircraft-flight-tracker-desktop-ads-b-radar).

This software guide is also a printable booklet: [Software booklet (PDF)](Flight_Tracker_Software_Booklet.pdf). The companion volume is the [Overview and Build booklet (PDF)](Flight_Tracker_Overview_and_Build_Booklet.pdf).

---

## 1. Turn it on

1. Plug the USB-C cable into power.
2. Wait for the radar screen. You may see the Raspberry Pi start first, then a Flight Tracker splash. The first start can take a few minutes.
3. A new unit is centered on KJFK until you set your own location.

## 2. Connect it to Wi-Fi

The unit needs Wi-Fi for live aircraft, weather, and the setup page.

The screen shows one Wi-Fi card at a time. That card changes through three screens, each with its own QR code.

1. Hold the clock at the bottom of the radar screen for 2 seconds, then tap **WI-FI SETUP**. Or use the join card if it is already on the screen.
2. The first screen says **NO WI-FI** and **Join setup**. Scan the QR code with your phone so the phone joins **FlightTracker-Setup**. The password is the eight characters under the QR. Stay on that network.
3. When your phone has joined, the same card changes to a second screen: **PHONE JOINED** and **Open setup**. Scan this new QR code to open the setup page.
4. On the setup page, open **WI-FI**. Pick your home network, enter the password, and tap **CONNECT**.
5. When the unit joins your network, the card changes to a third screen: **CONNECTED** and **Connected**. It shows the unit's address and a new QR code.
6. Join that same home Wi-Fi on your phone, then scan the **CONNECTED** QR, or open the address shown, or open `http://flighttracker.local/`.

### Saved networks

On the setup page, **WI-FI** lists **SAVED NETWORKS**. Tap **MAKE PREFERRED**, **CHANGE PASSWORD**, or **FORGET** for one network. **FORGET SAVED NETWORKS** removes every saved network.

## 3. Open the setup page

The setup page is where you change location, maps, night dim, brightness, and other settings.

1. Use a phone or computer on the same Wi-Fi as the unit.
2. Open the address on the **CONNECTED** card, or open `http://flighttracker.local/`.

The map stays centered on the home location you set here. You cannot drag or pan the map on the screen.

## 4. Settings

These are the sections on the setup page, in order.

### WI-FI

See [Connect it to Wi-Fi](#2-connect-it-to-wi-fi). Use **SAVE COUNTRY** to save the **Wi-Fi country**.

### BACKGROUND

1. Open **BACKGROUND**.
2. Tap **DARK MAP**, **LIGHT MAP**, **SATELLITE**, **SECTIONAL**, or **RADAR SCOPE**.

### SCREEN

1. Open **SCREEN**.
2. Set **Daytime brightness**. The backlight changes when you let go of the slider. The printed knob does not change brightness.
3. Set **Map orientation** to **North Up** or **Track Up**.
4. Set **Altitude filter** to **All altitudes**, **Below 10,000 ft**, **10,000–18,000 ft**, **18,000–35,000 ft**, or **Above 35,000 ft**.
5. Tap **SAVE SCREEN**.

### LOCATION

1. Open **LOCATION**.
2. Tap **AIRPORT CODE** and enter an **ICAO or IATA** code, or tap **LAT / LONG** and enter **Latitude** and **Longitude**.
3. Tap **SAVE**.

The screen stays centered there; it cannot be panned on the display.

### DISPLAY

1. Open **DISPLAY**.
2. Set **Default range**, **Range rings**, **Units**, **Show clock on radar screen**, **Clock format**, **Minimal text while tracking**, **Radar sweep**, **Sweep seconds per turn**, and **METAR**.
3. These settings save when you tap **SAVE** under **ADS-B**.

### ADS-B

1. Set **Source** to **Internet (adsb.fi)**, **My receiver (readsb / dump1090)**, or **Demo tracks**.
2. For **My receiver**, fill in **readsb / dump1090 host**, **Port**, **Or full JSON URL**, or **Local file**.
3. Tap **TEST CONNECTION**.
4. Tap **SAVE**.
5. Tap **RESTART DISPLAY** to refresh the picture on the screen, or **RESET DEFAULTS** to restore the built-in settings.

### WEATHER

1. Open **WEATHER**.
2. Turn **Show weather radar** on or off.
3. Set **Overlay opacity**.
4. Tap **SAVE WEATHER**.

### WATCH

1. Open **WATCH**.
2. Enter a tail number, callsign, or ICAO hex code under **Add aircraft**.
3. Tap **ADD TO WATCH LIST**.
4. Tap **SAVE WATCH**.

### ALERTS

1. Open **ALERTS**.
2. Turn on **Watched Aircraft**, **Military Aircraft**, **Emergency (7500, 7600, 7700)**, or **Chime (if available)**.
3. Tap **SAVE ALERTS**.

### TRAILS

1. Open **TRAILS**.
2. Set **Fading track history** and **Trail length**.
3. Tap **SAVE TRAILS**.

### NIGHT

1. Open **NIGHT**.
2. Set **Dim** to **Sunrise and sunset**.
3. Tap **US ZIP CODE** and enter a **US ZIP code**, or tap **OUTSIDE THE US / EXACT COORDINATES** and enter **Latitude** and **Longitude**.
4. Set **Night brightness**.
5. Tap **SAVE NIGHT**.

To use set times instead, choose **Fixed hours** and fill in **From (HHMM)** and **Until (HHMM)**, then tap **SAVE NIGHT**.

### RECEIVER

Shows receiver status when **Source** is **My receiver**.

### SOFTWARE

See [Updates](#6-updates).

### SOURCES

Credits for maps, weather, METAR, and aircraft data.

## 5. On the screen

The names printed on the case are labels only. They do not change settings. Set brightness, maps, and the other options on the setup page.

1. Hold the clock at the bottom of the radar screen for 2 seconds to open the About menu.
2. Tap **WI-FI SETUP**, **TRAFFIC LIST**, **TOUCH TEST**, or **SWEEP OFF** / **SWEEP ON**.
3. Tap a tail-number box — not the aircraft icon — for flight details. A green outline is military. A cyan ring is the watch list. A red flash is an emergency.
4. Use **−** and **+** under the top of the screen to change range. The steps are 10, 20, 30, 40, 50, 75, and 100 nm (100 is the maximum).
5. When an update is ready, tap **UPDATE NOW** or **LATER**.

Aircraft use the Maverick icon set.

## 6. Updates

1. Open the setup page and go to **SOFTWARE**.
2. Tap **CHECK FOR UPDATES**.
3. Read the notes, then tap **INSTALL UPDATE**.
4. When the screen asks, tap **UPDATE NOW**.

To install later, use **Install later at** (Eastern time) and **SAVE TIME**, or turn on **Install updates automatically**. The default time is 2:00 AM Eastern. Tap **CANCEL SCHEDULE** if an install is booked.

A daily check runs at about 09:00 AM Eastern. Background checks right after boot and every 6 hours are skipped between 21:00 and 09:00 Eastern.

Updates are signed and published on the public GitHub page. No account is required. If an update does not start cleanly, the unit goes back to the previous version.

---

[← Build guide](BUILD.md) · [README](../README.md) · [Developer notes →](DEVELOPER.md)

Software is under the [Maverick Field Gear Flight Tracker License](../LICENSE). Case print files are [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/).

© 2026 Maverick Field Gear. All rights reserved.
