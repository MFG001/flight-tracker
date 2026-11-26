"""Offline US ZIP (ZCTA) centroid lookup from the bundled Census gazetteer table."""

from __future__ import annotations

import gzip
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data" / "zcta-centroids.tsv.gz"
ZIP_RE = re.compile(r"^\d{5}$")


@lru_cache(maxsize=1)
def _rows() -> dict[str, tuple[float, float]]:
    path = TABLE
    if not path.is_file():
        return {}
    opener = gzip.open if path.suffix == ".gz" or path.name.endswith(".gz") else open
    out: dict[str, tuple[float, float]] = {}
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line or line.startswith("#") or line.startswith("zip\t"):
                continue
            zip_code, lat_s, lon_s = line.rstrip("\n").split("\t")
            out[zip_code] = (float(lat_s), float(lon_s))
    return out


def normalize_zip(text: Any) -> str:
    raw = str(text or "").strip()
    if ZIP_RE.fullmatch(raw):
        return raw
    return ""


def lookup_zip(text: Any) -> dict[str, Any] | None:
    """Return {zip, lat, lon, label} for a known 5-digit ZCTA, else None."""
    zip_code = normalize_zip(text)
    if not zip_code:
        return None
    coords = _rows().get(zip_code)
    if coords is None:
        return None
    lat, lon = coords
    return {"zip": zip_code, "lat": lat, "lon": lon, "label": f"ZIP {zip_code}"}


def zip_error(text: Any) -> str:
    """Human-readable reason a ZIP cannot be used, or '' if it is valid."""
    raw = str(text or "").strip()
    if not raw:
        return "Enter your ZIP code to use sunrise/sunset."
    if not ZIP_RE.fullmatch(raw):
        return "Enter a 5-digit US ZIP code."
    if lookup_zip(raw) is None:
        return "That ZIP code was not found."
    return ""
