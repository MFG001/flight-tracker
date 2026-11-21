export type BackgroundId = "dark" | "light" | "satellite" | "sectional" | "scope";
export type Units = "aviation" | "imperial" | "metric";
export type FeedMode = "adsbfi" | "demo" | "local" | "remote";
export type Orientation = "north" | "track";
export type AltitudeBand = "all" | "low" | "mid" | "high" | "upper";
export type ClockFormat = "24h" | "12h" | "utc";
export type BezelKey = "MAP" | "TFC" | "WX" | "MNU" | "NAV" | "HDG" | "ALT" | "BRT";

export interface Home {
  name: string;
  lat: number;
  lon: number;
}

export interface AppConfig {
  schema?: number;
  home: Home;
  rangeNm: number;
  rings: number;
  showClock: boolean;
  clockFormat: ClockFormat;
  minimalText: boolean;
  units: Units;
  feed: {
    mode: FeedMode;
    localPath: string;
    remoteUrl: string;
    host: string;
    port: number;
    fallbackDemo: boolean;
  };
  background: BackgroundId;
  weather: {
    enabled: boolean;
    opacity: number;
    animate: boolean;
  };
  metar: boolean;
  metarStation: string;
  orientation: Orientation;
  facingDeg: number;
  altitudeBand: AltitudeBand;
  brightness: number;
  sweep: { enabled: boolean; periodSec: number };
  watch: { enabled: boolean; tails: string[] };
  alerts: { watch: boolean; military: boolean; emergency: boolean; chime: boolean };
  trails: { enabled: boolean; minutes: number };
  night: { mode: "off" | "sun" | "schedule"; fromHour: number; toHour: number; from?: string; to?: string; brightness: number };
  display?: { rotation: number; output: string; touchDevice: string; touchMatrix: boolean };
  wifi?: { country: string };
  icons: "classic" | "planform" | "compact" | "linecut" | "maverick";
  updates: { url: string; repo?: string; channel?: string; auto: boolean };
  gpio: {
    enabled: boolean;
    pins: Record<BezelKey, number>;
    encoder: { clk: number; dt: number; sw: number };
  };
  fan: {
    gpioControl: boolean;
    gpio: number;
    onTempC: number;
  };
}

export type AircraftKind = "jet" | "light" | "rotor" | "uav" | "lighter" | "unknown";

export interface Aircraft {
  id: string;
  hex?: string | null;
  callsign: string;
  registration?: string | null;
  typeCode?: string | null;
  /** Registered owner/operator (adsb.fi ownOp, or the same field on a local readsb feed). */
  owner?: string | null;
  lat: number;
  lon: number;
  altFt: number | null;
  ground: boolean;
  gsKt: number | null;
  track: number | null;
  vsFpm: number | null;
  squawk: string | null;
  category: string | null;
  kind?: AircraftKind;
  mark?: string;
  military?: boolean;
  emergency?: boolean;
  /** Server: matches the watch list (set whether or not "show only watched" is on). */
  watched?: boolean;
  seenSec: number | null;
}

export interface AircraftResponse {
  now: number;
  source: string;
  stale: boolean;
  error: string | null;
  aircraft: Aircraft[];
}

export interface BasemapInfo {
  minZoom: number;
  maxZoom: number;
  attribution: string;
  attributionUrl: string;
  labels?: boolean;
}

export interface WeatherFrame {
  id: string;
  time: number | null;
}

export interface WeatherIndex {
  provider: string;
  attribution: string;
  attributionUrl: string;
  maxZoom: number;
  frames: WeatherFrame[];
  ok?: boolean;
  error?: string;
}

export interface MetarReport {
  icao: string | null;
  name: string | null;
  raw: string;
  lat: number;
  lon: number;
  distanceNm: number;
  tempC: number | null;
  windDir: number | string | null;
  windKt: number | null;
  obsTime: number | null;
  /** Set by the server when it kept the last good report after a failed fetch. */
  stale?: boolean;
}

export interface TileRequest {
  kind: "map" | "weather";
  style: string;
  z: number;
  x: number;
  y: number;
  labels?: boolean;
}

export const BACKGROUNDS: { id: BackgroundId; label: string }[] = [
  { id: "dark", label: "DARK MAP" },
  { id: "light", label: "LIGHT MAP" },
  { id: "satellite", label: "SATELLITE" },
  { id: "sectional", label: "SECTIONAL" },
  { id: "scope", label: "RADAR SCOPE" },
];

export const ALT_BANDS: AltitudeBand[] = ["all", "low", "mid", "high", "upper"];

export const BEZEL: { key: BezelKey; angle: number }[] = [
  { key: "BRT", angle: 0 },
  { key: "MAP", angle: 45 },
  { key: "TFC", angle: 90 },
  { key: "WX", angle: 135 },
  { key: "MNU", angle: 180 },
  { key: "ALT", angle: 225 },
  { key: "NAV", angle: 270 },
  { key: "HDG", angle: 315 },
];
