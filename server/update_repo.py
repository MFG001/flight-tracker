"""Where signed updates come from.

1.0.7: anonymously from the public repo (no token). The private releases repo
still receives each release in the old format so units on 1.0.6 or older can
reach 1.0.7; nothing in 1.0.7 reads it.
"""
from __future__ import annotations

UPDATE_REPO = "MFG001/flight-tracker"
UPDATE_URL = f"https://github.com/{UPDATE_REPO}/releases/latest/download/manifest.json"
PRIVATE_REPO = "MFG001/flight-tracker-updates"
PRIVATE_URL = f"https://api.github.com/repos/{PRIVATE_REPO}/releases/latest"
