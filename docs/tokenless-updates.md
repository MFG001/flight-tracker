# Tokenless signed updates (1.0.7)

## Channel
- Public repo `MFG001/flight-tracker` (source + releases). Each release has
  `flight-tracker-X.Y.Z.tar.gz` and `manifest.json` (format 2).
- Device checks `https://github.com/<repo>/releases/latest/download/manifest.json` anonymously.
  github.com 302s to `release-assets.githubusercontent.com`; this is not the REST API, so the
  60/hour/IP anonymous API limit does not apply. Checks: 90 s after boot, then every 6 h, plus the
  03:10 nightly run and manual CHECK NOW (about 5/day/unit).
- Hosts allowed (HTTPS:443 only, no credentials, every redirect checked): github.com,
  release-assets.githubusercontent.com, objects.githubusercontent.com. Tarball URL must be under
  `github.com/<pinned repo>/releases/download/v…`. No Authorization header is ever sent.

## Trust (server/update_trust.py)
- Ed25519 over `flight-tracker-update-v2\n` + canonical JSON of every manifest field except
  `signatures`: format, product, channel, version, url, sha256, size, published, expires,
  minVersion, notes, keys.
- Pinned keys: `/etc/flight-tracker-keys/{release,root}-<keyId>.pem` (root-owned). Until that folder
  has a key, the legacy `/etc/flight-tracker/update-public.pem` is used (counts as release+root).
  keyId = sha256 of the public key DER. Current key fingerprint: `2D7C 0580 0B69 E5EA`
  (full 2d7c05800b69e5ea9c356933856435ce37f6f7e879de6a0ab7e0956b4d5c25c0).
- Refused: unsigned / unknown key / revoked key; product or channel mismatch; version <= running;
  version < signed floor (max minVersion seen); published older than last seen (replay);
  expired (only if `expires` set and the clock is sane); non-allowlisted URL; size missing, > 200 MB,
  or download size != signed size; sha256 mismatch; tar with absolute/.. paths, links, devices,
  FIFOs, setuid bits, > 20 000 files or > 400 MB unpacked; VERSION inside != manifest.
- Expiry: optional, off by default. A hard window needs regular re-signing with the offline key and
  a Pi 4 has no RTC. The replay mark + anti-rollback already stop downgrades; a "freeze" (old manifest
  served forever) would need GitHub or the maintainer's account compromised and only withholds updates.
- Key changes (`keys.add` / `keys.revoke`) must also be signed by the offline root key; applied only
  after the install is healthy.

## Privilege
- Before 1.0.7 the web server ran as the desktop login, which owned /opt/flight-tracker and
  /etc/flight-tracker while sudo ran /opt/flight-tracker/current/server/updater.py as root, so that
  login could edit the root-run updater or swap the pinned key.
- 1.0.7 (`server/harden.py`, `install.sh`): the server runs as the system account `ft-server`
  (never the desktop login, which keeps the kiosk). /opt/flight-tracker, /etc/flight-tracker-keys
  and /var/lib/flight-tracker (trust state, config backup) are root-owned; ft-server owns only
  /etc/flight-tracker (config, status; mode 0755 so the kiosk can read it) and the cache. The sudo
  helpers are granted to ft-server. Root-run code reads with O_NOFOLLOW and writes with
  mkstemp + rename, so links planted in ft-server's folders are not followed.
- Units updated from 1.0.6: `migrate.py` schedules `updater.py --harden` 5 minutes after the
  install (a transient systemd timer). By then the 1.0.6 updater has finished its health check;
  if it rolled back to 1.0.6, that updater has no `--harden` and nothing changes. `--harden` adds
  a drop-in `User=ft-server`, restarts and waits for /api/health with the running version; on any
  failure it restores the previous user, sudoers and ownership and restarts as before. It deletes
  the old token file only after success. The nightly `--auto` run retries a unit never hardened.

## Migration from 1.0.6 (token + private MFG001/flight-tracker-updates)
1. 1.0.7 is published to the PRIVATE repo exactly like 1.0.6 (v1 manifest) so 1.0.6 units can
   fetch it with their token, and to the public repo with a v2 manifest.
2. 1.0.7's migrate.py rewrites updates.url to the public manifest URL and sets
   updates.repo = MFG001/flight-tracker; the saved home location and other settings are kept.
3. `--harden` (above) pins update-public.pem into /etc/flight-tracker-keys, fixes ownership and
   deletes /etc/flight-tracker/update-token.
4. From 1.0.7 on, only v2 manifests from the public repo are accepted. Token code is removed
   (no fallback). The private repo can be archived after every unit reports 1.0.7.

## Personal data (hard requirement)
- `scripts/scrub_check.py` (`npm run scrub`) fails on: personal/account/Wi-Fi words (stored only as
  SHA-256), private LAN addresses (except the hotspot 10.42.0.1), e-mail addresses outside
  example/noreply domains, phone numbers, personal home folders; scans PNG text chunks too.
- Runs in the test suite (tree + freshly packed tarball) and in `scripts/release.py` /
  `tools/sign_release` (tarball + release notes) before anything is signed.
- Public repo gets fresh history: one commit from the scrubbed tree, author "Maverick Field Gear"
  with a GitHub noreply address; `scrub_check.py --git-log` must pass before pushing.
