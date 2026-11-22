# Test the setup hotspot and join QR on the unit

[Flight Tracker](../README.md) / Wi-Fi QR test

**[README](../README.md)** · [Build guide](BUILD.md) · [Software](SOFTWARE.md) · [Signed updates](tokenless-updates.md) · **Wi-Fi QR test**


This is a short, self-reverting test of the FlightTracker-Setup hotspot and the NO WI-FI join QR card on the round display. It is safe to run while the unit is already on your home Wi-Fi: the test records that profile (spaces in the name are kept exactly), starts the setup hotspot, and then brings the same profile back.

You will need SSH access to the Pi (for example `ssh flighttracker@flighttracker.local`) and Flight Tracker 1.0.10 or later.

## Start the test

1. SSH into the Pi and run:

   ```
   sudo flight-tracker-wifi-test
   ```

   That uses a 10-minute timer. To choose another length (1 to 30 minutes):

   ```
   sudo flight-tracker-wifi-test 15
   ```

2. The command starts a systemd job named `flight-tracker-wifi-test` and returns. The job keeps running if the SSH session drops, which it likely will, because the Pi leaves home Wi-Fi to start the setup hotspot. That is expected.

3. Within a few seconds the round display should show the **NO WI-FI** card, with a QR code to join the `FlightTracker-Setup` network and the setup address. If you had dismissed that card earlier, it should appear again for this test.

## On your phone

4. Scan the QR code (or join `FlightTracker-Setup` from Wi-Fi settings and use the password shown on the display). Open the setup page if it does not open by itself.

5. You can stop there and wait for the timer, or save a network on the setup page. Saving a network also ends the test.

## What happens when it ends

6. The setup hotspot is taken down. The original home Wi-Fi profile is brought back (several retries). The profile itself is not deleted or edited.

7. The NO WI-FI card should go away once the unit is back on home Wi-Fi. SSH to `flighttracker.local` should work again after that.

To end early, if you still have a session (for example a keyboard on the Pi, or Ethernet):

```
sudo flight-tracker-wifi-test --stop
```

Logs are in the journal:

```
journalctl -u flight-tracker-wifi-test
journalctl -t flight-tracker-wifi-test
```

The test does not print the hotspot password in the terminal or the journal. The password is only shown on the display, as usual.

## If the Pi does not come back

1. Wait the full timer you started (10 minutes unless you chose another length). Do not assume it failed after only a minute or two.
2. If it is still off home Wi-Fi after that, power-cycle the Pi.
3. NetworkManager will autoconnect the saved home Wi-Fi profile on boot. It will not start the setup hotspot when a home profile is already saved.

---

[← Signed updates](tokenless-updates.md) · [README](../README.md)

© 2026 Maverick Field Gear. All rights reserved.
