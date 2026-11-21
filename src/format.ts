import type { Units } from "./types";

export function distanceParts(nm: number, units: Units): { value: number; unit: string } {
  if (units === "metric") return { value: nm * 1.852, unit: "KM" };
  if (units === "imperial") return { value: nm * 1.15078, unit: "MI" };
  return { value: nm, unit: "NM" };
}

export function formatDistance(nm: number, units: Units, digits = 1): string {
  const { value, unit } = distanceParts(nm, units);
  return `${value.toFixed(digits)} ${unit}`;
}

export function formatSpeed(kt: number | null, units: Units): string {
  if (kt == null || !Number.isFinite(kt)) return "—";
  if (units === "metric") return `${Math.round(kt * 1.852)} KM/H`;
  if (units === "imperial") return `${Math.round(kt * 1.15078)} MPH`;
  return `${Math.round(kt)} KT`;
}

export function formatAltitude(ft: number | null, ground: boolean, units: Units): string {
  if (ground) return "GROUND";
  if (ft == null || !Number.isFinite(ft)) return "—";
  if (units === "metric") return `${Math.round(ft * 0.3048).toLocaleString("en-US")} M`;
  return `${Math.round(ft).toLocaleString("en-US")} FT`;
}

/** Traffic-list altitude: the number only (or GROUND / —). Metric still
 *  carries "M". The selected-aircraft card uses formatAltitude, which keeps "FT". */
export function listAltitude(ft: number | null, ground: boolean, units: Units): string {
  if (ground) return "GROUND";
  if (ft == null || !Number.isFinite(ft)) return "—";
  if (units === "metric") return `${Math.round(ft * 0.3048).toLocaleString("en-US")} M`;
  return Math.round(ft).toLocaleString("en-US");
}

export function formatVertical(fpm: number | null, units: Units): string {
  if (fpm == null || !Number.isFinite(fpm) || Math.abs(fpm) < 50) return "LEVEL";
  const sign = fpm > 0 ? "+" : "−";
  if (units === "metric") return `${sign}${Math.abs(fpm * 0.00508).toFixed(1)} M/S`;
  return `${sign}${Math.abs(Math.round(fpm)).toLocaleString("en-US")} FPM`;
}

/** Short tag used beside the icon: flight level, or meters when metric. */
export function shortAltitude(ft: number | null, ground: boolean, units: Units): string {
  if (ground) return "GND";
  if (ft == null || !Number.isFinite(ft)) return "----";
  if (units === "metric") return `${Math.round(ft * 0.3048)}`;
  return String(Math.round(ft / 100)).padStart(3, "0");
}

/** Below this, altitude reads in feet; at or above, as a flight level (US transition altitude). */
export const TRANSITION_FT = 18000;

/**
 * Altitude for the on-screen data block: "GND", "3,400", "FL340",
 * or "1,040 m" for metric. 1.0.10 drops "ft" from feet values; the
 * selected-aircraft card still uses formatAltitude, which keeps "FT".
 */
export function blockAltitude(ft: number | null, ground: boolean, units: Units): string {
  if (ground) return "GND";
  if (ft == null || !Number.isFinite(ft)) return "ALT ---";
  if (units === "metric") return `${Math.round(Math.max(0, ft) * 0.3048).toLocaleString("en-US")} m`;
  if (ft >= TRANSITION_FT) return `FL${String(Math.round(ft / 100)).padStart(3, "0")}`;
  return `${(Math.round(Math.max(0, ft) / 100) * 100).toLocaleString("en-US")}`;
}

/** Line 2 of the data block: altitude, climb/descent arrow, ground speed. */
export function dataBlockLine(ft: number | null, ground: boolean, vsFpm: number | null | undefined, kt: number | null, units: Units): string {
  const arrow = ground || vsFpm == null || !Number.isFinite(vsFpm) ? "" : vsFpm >= 200 ? "▲" : vsFpm <= -200 ? "▼" : "";
  return `${blockAltitude(ft, ground, units)}${arrow} ${shortSpeed(kt, units)}`.trim();
}

export function shortSpeed(kt: number | null, units: Units): string {
  if (kt == null || !Number.isFinite(kt)) return "";
  if (units === "metric") return String(Math.round(kt * 1.852));
  if (units === "imperial") return String(Math.round(kt * 1.15078));
  return String(Math.round(kt));
}

export function formatHeading(track: number | null): string {
  if (track == null || !Number.isFinite(track)) return "—";
  return `${String(Math.round(((track % 360) + 360) % 360)).padStart(3, "0")}°`;
}

/**
 * Clock text in the Pi's local time zone.
 * "24h" (default): four digits, aviation style, e.g. 1319.
 * "12h": 1:19 PM.  "utc": 1819Z.
 */
export function formatClock(date: Date, format: string = "24h"): string {
  if (format === "utc") {
    return `${String(date.getUTCHours()).padStart(2, "0")}${String(date.getUTCMinutes()).padStart(2, "0")}Z`;
  }
  const hours = date.getHours();
  const mm = String(date.getMinutes()).padStart(2, "0");
  if (format === "12h") {
    const h12 = hours % 12 === 0 ? 12 : hours % 12;
    return `${h12}:${mm} ${hours < 12 ? "AM" : "PM"}`;
  }
  return `${String(hours).padStart(2, "0")}${mm}`;
}

/**
 * Screen clock (1.0.3): local time with Zulu (UTC) beside it, the way an
 * avionics clock shows both, e.g. "1853 · 2353Z" or "6:53 PM · 2353Z".
 * A UTC clock shows Zulu once.
 */
export function formatClockZulu(date: Date, format: string = "24h"): string {
  const zulu = formatClock(date, "utc");
  if (format === "utc") return zulu;
  return `${formatClock(date, format)} · ${zulu}`;
}

export function bandLabel(band: string, units: Units): string {
  if (units === "metric") {
    return (
      {
        all: "ALL ALT",
        low: "< 3,000 M",
        mid: "3–5.5 KM",
        high: "5.5–10.7 KM",
        upper: "> 10.7 KM",
      }[band] ?? "ALL ALT"
    );
  }
  return (
    {
      all: "ALL ALT",
      low: "< 10,000",
      mid: "10–18,000",
      high: "18–35,000",
      upper: "> 35,000",
    }[band] ?? "ALL ALT"
  );
}

export function sourceLabel(source: string, stale: boolean): string {
  if (source === "demo") return "DEMO";
  if (source === "demo-fallback") return "DEMO · NO FEED";
  if (stale) return "STALE";
  return "LIVE";
}
