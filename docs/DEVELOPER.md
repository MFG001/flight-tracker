# Developer notes

[Flight Tracker](../README.md) / Developer notes

**[README](../README.md)** · [Build guide](BUILD.md) · [Software](SOFTWARE.md) · **Developer notes** · [Signed updates](tokenless-updates.md) · [Wi-Fi QR test](wifi-qr-test.md)

These notes are for people working on the Flight Tracker source and install. For everyday use of the unit, start with the [software guide](SOFTWARE.md).

This project is the Maverick Field Gear Flight Tracker: a Raspberry Pi 4 with a Waveshare 4inch DSI LCD (C), 720 × 720, round.

---

## Desktop demo

The production build is already in `dist/`. From this directory:

```bash
python3 server/flighttracker.py --demo --host 127.0.0.1 --port 8741
```

Open http://127.0.0.1:8741 . The round bezel is the case. The keys on the screen are the touch targets. On a machine with a wide window you also get the printed legends outside the screen. Add `?kiosk=1` for the full-screen panel layout.

Sample traffic is fictional and flies out and back around KJFK. `--demo` ignores the saved feed until you start the server without that flag.

Keyboard, for the simulator: `M` map, `T` traffic, `W` weather, `U` menu, `N` clear selection, `H` heading mode, `A` altitude filter, `B` brightness, `+`/`-` range, scroll to zoom, Escape to close a panel. Clear the selection. The map stays centered on the home location from Settings; it cannot be panned.

To change the UI and rebuild:

```bash
npm install
npm run build
python3 -m unittest discover -s server/tests -v
```

`npm run dev` serves the UI on port 8742 and proxies `/api` to the Python server on 8741.

## Install on the Pi

Flash Raspberry Pi OS with a desktop (Bookworm or Trixie). Clone this repository, then:

```bash
sudo bash install.sh
```

That script:

- installs Python 3, certificates, DejaVu, and Chromium when `apt` can
- copies the app to `/opt/flight-tracker`
- keeps settings in `/etc/flight-tracker/config.json` (created from the example on first install)
- caches tiles in `/var/cache/flight-tracker`
- enables `flight-tracker.service` (the local server on port 8741)
- enables `flight-tracker-kiosk.service` (Chromium fullscreen on `?kiosk=1`)
- appends the 4inch DSI LCD (C) overlay for a Pi 4 when no Waveshare DSI overlay is already there
- sets the hostname to `flighttracker` and enables Avahi
- allows backlight, Wi-Fi helper, and kiosk restart through sudoers
- enables a service that starts the setup hotspot when no Wi-Fi is saved, or when saved Wi-Fi stays down for about two minutes at boot

Reboot after the overlay is added. The usual first install from a computer on the LAN is the release tarball and `deploy/push-update.sh`. Those steps are in the [build guide](BUILD.md#7-installing-the-software).

A cooling fan can be fitted in the case. The display software does not PWM a fan header. If the fan is wired as a Raspberry Pi `gpio-fan` (control pin to a transistor, not a direct motor connection), turn that on in the config or install with `--fan`. The default control pin is BCM 14 and the default threshold is 60 °C, which the installer writes as `dtoverlay=gpio-fan,gpiopin=14,temp=60000`.

## Display overlay

This unit uses the **4inch DSI LCD (C)**. That is the installer default on a Pi 4.

From the [4inch DSI LCD (C) wiki](https://www.waveshare.com/wiki/4inch_DSI_LCD_(C)), checked for this build:

- Bookworm and Trixie: add `dtoverlay=vc4-kms-v3d` and `dtoverlay=vc4-kms-dsi-waveshare-panel,4_0_inchC`. The wiki’s `,dsi0` form is for boards with two MIPI ports (Pi 5 and Compute Modules). A Pi 4 has one DSI connector, the 15-pin FPC, plus the 4-pin lead for 5 V and I2C. The installer writes the Pi 4 line only.
- Touch on Bookworm and Trixie: the wiki says the touch works after that overlay boots. It does not install a separate touch package. The rotation steps identify the device as **10-0014 Goodix Capacitive TouchScreen**. Binding that touchscreen to the panel in Screen Configuration is a manual step if you rotate the display. The installer does not do that.
- Backlight: the Waveshare driver registers a 0–255 RAW backlight, usually named like `10-0045` or `11-0045`. **Daytime brightness** on the setup page stores a percent and writes a value scaled onto each node's `max_brightness`. A udev rule (installed by `install.sh`) lets the `video` group write the node; `sudo` on `/usr/local/sbin/flight-tracker-brightness` is the fallback. The screen darkens itself when a write does not succeed, including when a sysfs node exists but is not writable.

Waveshare lists the display area as a square. The screen is round, and they do not publish a smaller active-pixel diameter inside the 720 × 720 framebuffer. The visible image is the inscribed circle: diameter 101.52 mm, 720 px. Flight Tracker clips all drawing to that circle.

If you are bringing up a different Waveshare 720 × 720 board, such as 4-DSI-TOUCH-C, that is not this unit. It needs a different overlay (`dtoverlay=vc4-kms-dsi-waveshare-panel-v2,4_0_inch_c`). Only then would you run `sudo bash install.sh --panel touch-c`.

## Configuration

`data/config.example.json` is the template. On the Pi the live file is `/etc/flight-tracker/config.json`. In a checkout the server creates `data/config.json` on first launch.

| Field | Meaning |
| --- | --- |
| `home` | Name, latitude, longitude of the scope center |
| `rangeNm` | Range in nautical miles. The display converts it for statute and metric units |
| `units` | `aviation` (NM, kt, ft), `imperial` (mi, mph, ft), or `metric` (km, km/h, m) |
| `feed.mode` | `adsbfi` (default, internet), `local` (receiver file), `remote` (receiver URL), or `demo` |
| `feed.localPath` | Absolute path to `aircraft.json` |
| `feed.remoteUrl` | `http` or `https` URL. No API key is stored |
| `feed.fallbackDemo` | If the local file is missing, play the sample tracks and say so |
| `feed.host`, `feed.port` | readsb/dump1090 host. The JSON URL is `http://host:port/data/aircraft.json` unless `remoteUrl` is set |
| `background` | `dark`, `light`, `satellite`, `sectional`, or `scope` |
| `weather.enabled`, `opacity`, `animate` | Precipitation overlay |
| `metar` | Nearest observation |
| `metarStation` | ICAO code. Follows the home airport when home is set by airport search; blank uses the nearest observation |
| `orientation` | `north` or `track` |
| `facingDeg` | Used for track-up when no aircraft is selected |
| `altitudeBand` | `all`, `low` (below 10,000 ft), `mid`, `high`, `upper` |
| `brightness` | 0–100. Written to the Waveshare backlight node (0–255, scaled to `max_brightness`) |
| `night.mode` | `off`, `sun` (sunrise and sunset), or `schedule` (fixed hours) |
| `night.from`, `night.to` | Custom hours as `HHMM`, used when `mode` is `schedule` |
| `night.loc` | `zip` (US ZIP code) or coordinates (`lat` / `lon`) for sunrise and sunset. This is for this unit, not the map center |
| `night.zip`, `night.lat`, `night.lon` | Night-dim location. A US ZIP is looked up offline from the bundled Census ZCTA table |
| `icons` | Always Maverick |
| `gpio` | Optional buttons and encoder. Off by default |
| `fan` | Optional `gpio-fan` pin and temperature |

The eight printed bezel names (BRT, MAP, TFC, WX, MNU, ALT, NAV, HDG) are case labels. They do not change settings on this unit. Brightness is set on the setup page (**Daytime brightness** and **Night brightness**). On the screen, hold the clock for 2 seconds to open the About menu. Optional GPIO can fire those keys only if `gpio.enabled` is turned on and switches are wired; the printed knob is not wired on this unit.

Leave `gpio.enabled` false until real switches are wired. Inputs are BCM, active-low to ground, internal pull-up. The encoder is quadrature; one detent is four edges. Swapping `clk` and `dt` reverses the direction. The encoder switch also fires **BRT**.

Default pins, chosen to avoid I2C (GPIO 2 and 3, used by the panel touch controller) and the default fan pin 14:

| Function | BCM |
| --- | --- |
| MAP, TFC, WX, MNU | 5, 6, 16, 17 |
| NAV, HDG, ALT, BRT | 22, 23, 24, 25 |
| Encoder clk, dt, sw | 12, 13, 20 |

The server prefers `gpiozero` and falls back to `lgpio`. If neither can open the chip, the display keeps running and `/api/controls` reports the error. Nothing in the default config claims a pin.

## Live aircraft data

The default source (`feed.mode` `adsbfi`) is the free [adsb.fi](https://adsb.fi/) open data API over the internet, so no receiver is needed. The display asks `https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{nm}` for aircraft around home, with the radius set to the display range plus a margin (at most 250 NM). adsb.fi limits public requests to one per second. Flight Tracker sends at most one request every 5 seconds, however many screens are open. It caches the last answer, and after an error it waits twice as long each time, up to 5 minutes (at least 60 seconds after HTTP 429). Requests time out after 6 seconds and carry a `FlightTracker/<version>` User-Agent. If adsb.fi cannot be reached and `fallbackDemo` is on, the scope shows demo tracks marked DEMO · NO FEED. The last good answer is shown as STALE for up to 60 seconds.

adsb.fi terms: the open data is for personal, non-commercial use only. adsb.fi must be cited with a link to https://adsb.fi/. The credit is in the About menu → Sources and on the setup page. adsb.fi asks users to support it by running a receiver. In adsb.fi data, `type` is the message source (for example `adsb_icao`), not the aircraft type, so the aircraft type is read from `t` only.

Choose **My receiver** on the setup page (`feed.mode` `local` or `remote`) to use your own readsb or dump1090 `aircraft.json`. The default local path is `/run/readsb/aircraft.json`. dump1090-fa often uses `/run/dump1090-fa/aircraft.json`. A remote receiver is any HTTP or HTTPS URL that returns the same document, for example `http://receiver.local:8080/data/aircraft.json`.

Fields that are read: `hex`, `flight`, `lat`, `lon`, `alt_baro` (including `"ground"`), `alt_geom`, `track`, `true_heading`, `mag_heading`, `gs`, `baro_rate`, `geom_rate`, `squawk`, `category`, `seen_pos`, `seen`. Aircraft without a position are skipped.

## Aircraft icons

Aircraft icons follow the ADS-B emitter category: A1/A2 light, A3–A6 jet, A7 rotorcraft, B2 lighter-than-air, B6 UAV. Anything else stays a neutral diamond. Maverick, the only icon set, uses a separate filled silhouette for a light single, a twin, a business or regional jet, an airliner, a fighter, and a drone. Helicopters use a slender rotorcraft body with spinning blades; airships use an envelope with fins. Every aircraft is white with a thin dark outline. Military is a green outline (`#14944A`), distinct from the sweep. A squawk of 7500, 7600, or 7700, or a readsb emergency flag other than none, flashes the icon red about once a second and overrides the green outline. A watched aircraft has a cyan ring while the watch list is on. It comes from readsb `dbFlags` bit 0. An optional `data/military-hex-ranges.json` is used only when you add one; the usual compiled table has no license, so it is not included. An optional `data/aircraft-types.json` can map an ICAO type designator to a class when the category is empty. The legend is in the About menu only.

The watch list accepts a US N-number, which converts to the ICAO address offline, another registration matched to readsb's `r` field or `data/registrations.json`, or a 6-digit hex. Hyphens and case are ignored.

## Signed updates

Owner steps are in the [software guide](SOFTWARE.md#6-updates). Internals, keys, and the update channel are in [tokenless-updates.md](tokenless-updates.md).

Updates come from the public GitHub repository `MFG001/flight-tracker`. No account, access key, or token is needed. The device downloads:

`https://github.com/MFG001/flight-tracker/releases/latest/download/manifest.json`

That address is a plain file download, not the GitHub API, so the API rate limit does not apply. Downloads are HTTPS only, send no credentials, and may only be redirected to `github.com`, `release-assets.githubusercontent.com`, or `objects.githubusercontent.com` on port 443. The tarball must be an asset of a release in the same repository, and its size must match the signed size exactly.

`tools/sign_release` is the signer. It refuses a key path inside the repository, runs the personal-data scrub check on the tarball and the notes, and writes `public/manifest.json` (format 2). Upload `flight-tracker-X.Y.Z.tar.gz` and that `manifest.json` as assets on the GitHub release tagged `vX.Y.Z`, and mark it the latest release.

The web server runs as its own system account, `ft-server`, not the desktop login. The code in `/opt/flight-tracker` and the update keys are owned by root.

## Wi-Fi helper and tests

QR codes are drawn on the Pi with the open-source `qrcode` library. No QR image is fetched from the network.

The setup hotspot address is `http://10.42.0.1/`. On that hotspot, `http://flighttracker.local/` also resolves to the unit.

A self-reverting test of the setup hotspot and join QR is documented in [wifi-qr-test.md](wifi-qr-test.md).

TODO: the hotspot, captive-portal redirects, `10.42.0.1`, `iw` station detection, WPA2-PSK/PMF settings, and the two-minute fallback were not run on a Raspberry Pi in this project's test environment. The scripts call Raspberry Pi OS Trixie NetworkManager (`nmcli dev wifi hotspot` on brcmfmac). If the radio is not `wlan0`, edit `scripts/wifi-ctl.sh`.

## Data sources and attribution

No paid API key is embedded. Tiles and radar images are cached on disk so the scope keeps the last view when the network drops. Delete `/var/cache/flight-tracker` (or `data/cache` in a checkout) to force a refresh.

Bundled third-party components (node-qrcode, IBM Plex fonts, and the US Census Bureau ZCTA Gazetteer used for night-dim ZIP centroids) keep their own licenses and attributions; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Map, weather, and aircraft data terms stay with their owners. Credits also appear in the setup page **SOURCES** section and in the About menu.

## Verified here, and not verified on the hardware

Not verified, because this environment has no Pi 4 and no panel:

- The physical 720 × 720 screen, touch alignment, and whether the corners of the framebuffer are fully hidden by the bezel
- Which of the two Waveshare overlays the installed board needs
- Backlight sysfs writes, `gpio-fan`, and real button or encoder wiring
- systemd boot and the Chromium kiosk under Wayland or X11 on Raspberry Pi OS
- Frame rate on a Pi 4 with a live readsb feed
- Avahi at `flighttracker.local`, binding port 80, the setup hotspot, a phone joining from the QR code, and captive-portal detection
- A real over-the-air install on the Pi, including the systemd timer, the health-check restart, and rollback after a failed service start
- The BRT write to the real Waveshare 4inch DSI LCD (C) backlight node on hardware (0–255, device names such as 10-0045 / 11-0045)
- Which backlight node exists if the Pi also has another display
- Sectional coverage outside the United States. The FAA tiles do not cover the whole world

The display math assumes the framebuffer is 720 × 720 and the visible area is the inscribed circle. If a future panel uses a different resolution, the kiosk still scales to the window, but the Pi overlay and the 720 px assumption would need to be revisited.

---

[← Software](SOFTWARE.md) · [README](../README.md) · [Signed updates →](tokenless-updates.md)

Software is under the [Maverick Field Gear Flight Tracker License](../LICENSE). Case print files are [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/).

© 2026 Maverick Field Gear. All rights reserved.
