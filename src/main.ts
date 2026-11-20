import QRCode from "qrcode";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./style.css";

import { RadarView } from "./radar";
import { AlertTracker } from "./alerts";
import { scopeAircraft } from "./scope";
import { PollGate, aircraftUrl } from "./aircraftpoll";
import { wxSummary } from "./wxstatus";
import {
  PROMPT_TIMEOUT_MS,
  installDone,
  installFailed,
  installLine,
  installPercent,
  promptAllowed,
  scheduledLine,
  type UpdateView,
} from "./updatepop";
import { recordTrails as addTrailPoints, trailLines, type TrailPoint } from "./trails";
import { ICON_KINDS, ICON_SETS, MAVERICK_LEGEND, iconSetId, paintAircraftIcon, type IconSetId, type MaverickMark } from "./icons";
import { MAX_RANGE_NM, RANGE_STEPS, ringCount, snapRange } from "./rings";
import { bearingDeg, haversineNm, offsetNm } from "./geo";
import {
  bandLabel,
  formatAltitude,
  formatClockZulu,
  formatDistance,
  formatHeading,
  formatSpeed,
  formatVertical,
  sourceLabel,
} from "./format";
import {
  ALT_BANDS,
  BACKGROUNDS,
  type Aircraft,
  type AircraftResponse,
  type AltitudeBand,
  type AppConfig,
  type BackgroundId,
  type BasemapInfo,
  type BezelKey,
  type MetarReport,
  type TileRequest,
  type WeatherIndex,
} from "./types";

declare global {
  interface Window {
    __ftReady?: boolean;
    __wifiReady?: boolean;
    __splashReady?: boolean;
  }
}

const params = new URLSearchParams(location.search);
const captureMode = params.has("capture");
const kiosk = params.has("kiosk");

const screen = document.querySelector<HTMLElement>("#screen")!;
const canvas = document.querySelector<HTMLCanvasElement>("#radar")!;
const radar = new RadarView(canvas);
const statusEl = document.querySelector<HTMLElement>("#status")!;
const clockEl = document.querySelector<HTMLElement>("#clock")!;
const rangeBtn = document.querySelector<HTMLButtonElement>("#range")!;
const rangeMinus = document.querySelector<HTMLButtonElement>("#range-minus")!;
const rangePlus = document.querySelector<HTMLButtonElement>("#range-plus")!;
const rangePicker = document.querySelector<HTMLElement>("#range-picker")!;
const chipHdg = document.querySelector<HTMLElement>("#chip-hdg")!;
const chipAlt = document.querySelector<HTMLElement>("#chip-alt")!;
const metarEl = document.querySelector<HTMLElement>("#metar")!;
const attrib = document.querySelector<HTMLAnchorElement>("#attrib")!;
const toastEl = document.querySelector<HTMLElement>("#toast")!;
const detail = document.querySelector<HTMLElement>("#detail")!;
const traffic = document.querySelector<HTMLElement>("#traffic")!;
const menu = document.querySelector<HTMLElement>("#menu")!;
const dim = document.querySelector<HTMLElement>("#dim")!;
const splash = document.querySelector<HTMLElement>("#splash")!;
const aboutStatus = document.querySelector<HTMLElement>("#about-status")!;
const sweepBtn = document.querySelector<HTMLButtonElement>("#sweep-toggle")!;
const trafficList = document.querySelector<HTMLElement>("#traffic-list")!;
const detailGrid = document.querySelector<HTMLElement>("#d-grid")!;
const callEl = document.querySelector<HTMLElement>("#d-call")!;

const PRESETS: number[] = [...RANGE_STEPS];
const BRIGHT_STEPS = [100, 80, 60, 40, 20];

let config: AppConfig = {
  home: { name: "KJFK", lat: 40.6399, lon: -73.7787 },
  rangeNm: 20,
  rings: 4,
  showClock: true,
  clockFormat: "24h",
  minimalText: true,
  units: "aviation",
  feed: { mode: "adsbfi", localPath: "/run/readsb/aircraft.json", remoteUrl: "", host: "", port: 8080, fallbackDemo: true },
  background: "dark",
  weather: { enabled: true, opacity: 0.6, animate: true },
  metar: true,
  metarStation: "KJFK",
  orientation: "north",
  facingDeg: 0,
  altitudeBand: "all",
  brightness: 100,
  sweep: { enabled: false, periodSec: 8 },
  watch: { enabled: false, tails: [] },
  alerts: { watch: false, military: false, emergency: false, chime: false },
  trails: { enabled: false, minutes: 5 },
  night: { mode: "off", fromHour: 22, toHour: 6, from: "2200", to: "0600", brightness: 25 },
  icons: "maverick",
  updates: { url: "https://github.com/MFG001/flight-tracker/releases/latest/download/manifest.json", repo: "MFG001/flight-tracker", channel: "stable", auto: false },
  gpio: {
    enabled: false,
    pins: { MAP: 5, TFC: 6, WX: 16, MNU: 17, NAV: 22, HDG: 23, ALT: 24, BRT: 25 },
    encoder: { clk: 12, dt: 13, sw: 20 },
  },
  fan: { gpioControl: false, gpio: 14, onTempC: 60 },
};

let rangeNm = config.rangeNm;
let rangeShown = config.rangeNm;
let savedRange = Number.NaN;
let nightOn = false;
let nightLevel = 25;
const trailHistory = new Map<string, TrailPoint[]>();
let alertsPrimed = false;
let panNorth = 0;
let panEast = 0;
let background: BackgroundId = config.background;
let weatherOn = false;
let opacity = config.weather.opacity;
let orientation = config.orientation;
let band: AltitudeBand = config.altitudeBand;
let brightness = config.brightness;
let sweepOn = false;
let sweepPeriod = 8;
let rings = 4;
// Frame cap for the kiosk: Chromium runs with --disable-gpu on the Pi, so
// every frame is software-rendered. 30 fps keeps the sweep smooth (time-based
// angle) at about half the CPU of 60 fps.
const FRAME_CAP_MS = kiosk && !captureMode ? 1000 / 30 - 4 : 0;
if (FRAME_CAP_MS) radar.liteSweepBelow = 20;
let lastDraw = 0;
let wxDrawnAt = 0;
let wxWantedAt = 0;
let lastMinimal: boolean | null = null;
let selectedId: string | null = null;
let aircraft: Aircraft[] = [];
let fixMs = performance.now();
let source = "demo";
let stale = false;
let feedError: string | null = null;
let basemaps: Record<string, BasemapInfo> = {};
let weather: WeatherIndex | null = null;
let wxFrame = 0;
let metar: MetarReport | null = null;
let booted = false;
let gotAircraft = false;
let fontsDone = false;
let demoLock = false;
let hardwareBacklight = false;
let wifiDismissed = false;
let wifiPinned = false;
let wifiSeen = "";
let connectedTimer = 0;
let mapRequested = false;
let wxRequested = false;
const inflight = { map: 0, weather: 0 };
const images = new Map<string, HTMLImageElement>();
let toastTimer = 0;
let saveTimer = 0;

if (kiosk) document.body.classList.add("kiosk");
if (captureMode) document.body.classList.add("capture");

function $(id: string): HTMLInputElement {
  return document.querySelector<HTMLInputElement>(id)!;
}

/**
 * 1.0.3: no tap keys on the glass. The eight edge tabs (BRT, MAP, TFC, WX,
 * MNU, ALT, NAV, HDG) are gone so the rim of the dial is clean; their
 * settings live on the setup page at flighttracker.local. What stays on the
 * glass: tap an aircraft for its details, the range pill, drag / pinch,
 * double-tap to recenter, and a 2-second press on the clock / status line
 * for the About menu (Wi-Fi QR, touch test, traffic list).
 */
const HOLD_MS = 2000;

function buildChrome(): void {
  const targets = [statusEl, clockEl];
  let holdTimer = 0;
  const cancel = () => {
    window.clearTimeout(holdTimer);
    holdTimer = 0;
    for (const el of targets) el.classList.remove("holding");
  };
  for (const el of targets) {
    el.classList.add("hold-target");
    el.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      cancel();
      for (const item of targets) item.classList.add("holding");
      holdTimer = window.setTimeout(() => {
        cancel();
        openMenu();
      }, HOLD_MS);
    });
    for (const type of ["pointerup", "pointercancel", "pointerleave"]) el.addEventListener(type, cancel);
    el.addEventListener("contextmenu", (event) => event.preventDefault());
  }
}

function openMenu(): void {
  traffic.hidden = true;
  detail.hidden = true;
  selectedId = null;
  menu.hidden = false;
  syncChrome();
}

function recenter(): boolean {
  if (Math.hypot(panNorth, panEast) < 0.05) return false;
  panNorth = 0;
  panEast = 0;
  toast("HOME");
  syncChrome();
  return true;
}

function applyQuery(): void {
  const bg = params.get("bg");
  if (bg && BACKGROUNDS.some((item) => item.id === bg)) background = bg as BackgroundId;
  if (params.has("wx")) weatherOn = params.get("wx") === "1";
  const range = Number(params.get("range"));
  if (Number.isFinite(range) && range >= 2) {
    rangeNm = snapRange(range);
    if (captureMode) rangeShown = rangeNm;
  }
}

function applyConfig(next: AppConfig): void {
  config = next;
  rangeNm = next.rangeNm;
  background = next.background;
  weatherOn = next.weather.enabled;
  opacity = next.weather.opacity;
  orientation = next.orientation;
  band = next.altitudeBand;
  brightness = next.brightness;
  sweepOn = Boolean(next.sweep?.enabled);
  sweepPeriod = next.sweep?.periodSec ?? 8;
  rings = ringCount(next.rings ?? 4);
  const nextRange = snapRange(next.rangeNm);
  if (Number.isNaN(savedRange)) {
    savedRange = nextRange;
    rangeNm = nextRange;
    rangeShown = nextRange;
  } else if (nextRange !== savedRange) {
    savedRange = nextRange;
    rangeNm = nextRange;
  }
  applyQuery();
  noteRangeChange();
  syncChrome();
}

function inBand(item: Aircraft): boolean {
  if (band === "all") return true;
  if (item.ground || item.altFt == null) return band === "low";
  const ft = item.altFt;
  if (band === "low") return ft < 10000;
  if (band === "mid") return ft >= 10000 && ft < 18000;
  if (band === "high") return ft >= 18000 && ft < 35000;
  return ft >= 35000;
}

function placeAircraft(item: Aircraft, now: number): Aircraft {
  if (captureMode || item.ground || item.track == null || item.gsKt == null) return item;
  const dt = Math.min(4, (now - fixMs) / 1000);
  const nm = item.gsKt * (dt / 3600);
  const rad = (item.track * Math.PI) / 180;
  return {
    ...item,
    lat: item.lat + (nm / 60) * Math.cos(rad),
    lon: item.lon + (nm / (60 * Math.max(0.2, Math.cos((item.lat * Math.PI) / 180)))) * Math.sin(rad),
  };
}

function centerOf(): { lat: number; lon: number } {
  return offsetNm(config.home.lat, config.home.lon, panNorth, panEast);
}

function mapUp(): number {
  if (orientation === "north") return 0;
  const selected = aircraft.find((item) => item.id === selectedId);
  if (selected?.track != null) return selected.track;
  return config.facingDeg || 0;
}

/**
 * The aircraft that will be painted inside the outer ring this frame. The
 * same list decides standby (#idle), the track count, and radar.draw, so the
 * screen never wakes for traffic it then clips (see src/scope.ts).
 */
function visible(now: number, beyond?: Aircraft[]): Aircraft[] {
  const center = centerOf();
  return scopeAircraft(aircraft, {
    centerLat: center.lat,
    centerLon: center.lon,
    rangeNm: rangeShown,
    watchOnly: Boolean(config.watch?.enabled),
    inBand,
    place: (item) => placeAircraft(item, now),
  }, beyond);
}

/** Standby shows only while nothing is on the scope; checked every frame. */
function syncIdle(count: number): void {
  const idle = document.querySelector<HTMLElement>("#idle");
  if (!idle) return;
  const forceIdle = captureMode && params.get("idle") === "1";
  const hide = forceIdle ? false : !booted || count > 0;
  if (idle.hidden !== hide) idle.hidden = hide;
}

function syncChrome(): void {
  screen.classList.toggle("scope", background === "scope");
  screen.classList.toggle("bright", background === "light" || background === "satellite");
  const shownRange = Math.abs(rangeShown - rangeNm) < 0.05 ? rangeNm : rangeShown;
  rangeBtn.textContent = formatDistance(shownRange, config.units, shownRange >= 10 ? 0 : 1);
  const step = rangeIndex();
  rangeMinus.disabled = step <= 0;
  rangePlus.disabled = step >= PRESETS.length - 1;
  rangePicker.querySelectorAll<HTMLButtonElement>("button").forEach((button) => {
    button.setAttribute("aria-pressed", String(Number(button.dataset.nm) === snapRange(rangeNm)));
  });
  const watchOn = Boolean(config.watch?.enabled);
  const onScope = visible(performance.now());
  const watchCount = onScope.length;
  const watchChip = document.querySelector<HTMLElement>("#chip-watch");
  if (watchChip) {
    watchChip.hidden = !watchOn;
    watchChip.textContent = `WATCH ${watchCount}`;
  }
  syncIdle(onScope.length);
  const idleAirport = document.querySelector<HTMLElement>("#idle-airport");
  const idleMetar = document.querySelector<HTMLElement>("#idle-metar");
  const idleClock = document.querySelector<HTMLElement>("#idle-clock");
  const idleTitle = document.querySelector<HTMLElement>("#idle-title");
  if (idleTitle) idleTitle.textContent = watchOn ? "No watched aircraft in range" : "No aircraft in range";
  if (idleClock) idleClock.textContent = formatClockZulu(new Date(), config.clockFormat);
  if (idleAirport && !idleAirport.textContent) idleAirport.textContent = config.home.name;
  if (idleMetar) {
    idleMetar.textContent = metar ? shortMetar(metar) : "METAR unavailable";
    idleMetar.classList.toggle("stale", metarStale(metar));
  }
  chipHdg.textContent = orientation === "north" ? "N-UP" : "TRK-UP";
  chipAlt.textContent = bandLabel(band, config.units);
  const shown = onScope.length;
  if (!booted) statusEl.textContent = "ACQUIRING";
  else if (feedError && source !== "demo" && source !== "demo-fallback") statusEl.textContent = "FEED LOST";
  else statusEl.textContent = `FLIGHT TRACKER · ${shown} TRACKS · ${sourceLabel(source, stale)}`;
  clockEl.textContent = formatClockZulu(new Date(), config.clockFormat);
  clockEl.hidden = config.showClock === false;
  applyTextMode(shown);
  const wxChip = document.querySelector<HTMLElement>("#chip-wx");
  showWxChip(wxChip);
  const info = basemaps[background];
  const esri = background === "dark" || background === "light" || background === "satellite";
  const credit = esri ? (info?.attribution || "").trim() : "";
  attrib.hidden = credit.length === 0;
  attrib.textContent = credit;
  attrib.href = info?.attributionUrl || "https://www.esri.com/en-us/legal/terms/data-attributions";
  const dimLevel = nightOn ? Math.min(brightness, nightLevel) : brightness;
  dim.style.opacity = hardwareBacklight && !nightOn ? "0" : String(((100 - dimLevel) / 100) * 0.82);
  sweepBtn.textContent = sweepOn ? "SWEEP ON" : "SWEEP OFF";
  sweepBtn.setAttribute("aria-pressed", String(sweepOn));
  aboutStatus.textContent = statusEl.textContent ?? "";
  paintLegend();
  const holdSplash = params.get("splash") === "1";
  splash.hidden = !holdSplash && booted && gotAircraft;
  if (holdSplash) window.__splashReady = true;
  metarEl.hidden = !config.metar || !metar;
  metarEl.textContent = metar ? shortMetar(metar) : "";
  metarEl.classList.toggle("stale", metarStale(metar));
  if (!detail.hidden) renderDetail();
  document.querySelectorAll<HTMLElement>(".disc, #traffic-list").forEach((el) => {
    el.classList.toggle("can-scroll", el.scrollHeight > el.clientHeight + 6);
  });
}

function toast(text: string): void {
  toastEl.textContent = text;
  toastEl.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastEl.hidden = true;
  }, 1400);
}

function persist(): void {
  if (captureMode || !booted) return;
  config.background = background;
  config.weather.enabled = weatherOn;
  config.weather.opacity = opacity;
  config.orientation = orientation;
  config.altitudeBand = band;
  config.brightness = brightness;
  config.sweep = { enabled: sweepOn, periodSec: sweepPeriod };
  // 1.0.3: the range picked on the glass is saved too.
  config.rangeNm = snapRange(rangeNm);
  savedRange = config.rangeNm;
  localEdits += 1;
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    // Clear the timer id first: pollSharedConfig skips while a save is
    // pending, and a stale id made it skip forever, so setup-page changes
    // only showed after a reload.
    saveTimer = 0;
    saving += 1;
    void fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }).finally(() => {
      saving -= 1;
    });
  }, 400);
}

/** Bumped by every change made on the glass; a config poll that started before it is ignored. */
let localEdits = 0;
let saving = 0;

function rangeIndex(): number {
  return PRESETS.indexOf(snapRange(rangeNm));
}

/** One tap on − or +: the next preset down or up, saved. */
function stepRange(direction: 1 | -1): void {
  const index = Math.max(0, Math.min(PRESETS.length - 1, rangeIndex() + direction));
  pickRange(PRESETS[index]);
}

function pickRange(nm: number): void {
  closeRangePicker();
  setRange(nm);
  toast(formatDistance(rangeNm, config.units, rangeNm >= 10 ? 0 : 1));
  persist();
}

function buildRangePicker(): void {
  rangePicker.replaceChildren();
  for (const nm of PRESETS) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.nm = String(nm);
    button.setAttribute("role", "menuitemradio");
    button.textContent = String(nm);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      pickRange(nm);
    });
    rangePicker.append(button);
  }
}

function openRangePicker(): void {
  rangePicker.hidden = false;
  rangeBtn.setAttribute("aria-expanded", "true");
  syncChrome();
}

function closeRangePicker(): void {
  if (rangePicker.hidden) return;
  rangePicker.hidden = true;
  rangeBtn.setAttribute("aria-expanded", "false");
}

function setRange(nm: number, snap = true): void {
  rangeNm = snap ? snapRange(nm) : Math.max(2, Math.min(MAX_RANGE_NM, nm));
  noteRangeChange();
  syncChrome();
}

/** Fetch traffic for a new range at once; replies for the old range are dropped. */
function noteRangeChange(): void {
  if (!booted || snapRange(rangeNm) === lastPolledRange) return;
  aircraftGate.invalidate();
  void pollAircraft().catch(() => undefined);
}

function nudgeBrightness(delta: number): void {
  brightness = Math.max(0, Math.min(100, Math.round(brightness + delta)));
  toast(`BRT ${brightness}% · ${Math.round((brightness / 100) * 255)}/255`);
  syncChrome();
  persist();
}

function onKey(key: BezelKey): void {
  if (key === "MAP") {
    const order = BACKGROUNDS.map((item) => item.id);
    background = order[(order.indexOf(background) + 1) % order.length];
    toast(BACKGROUNDS.find((item) => item.id === background)?.label ?? background);
  } else if (key === "TFC") {
    const open = traffic.hidden;
    traffic.hidden = !open;
    if (open) {
      menu.hidden = true;
      renderList();
    }
  } else if (key === "WX") {
    weatherOn = !weatherOn;
    toast(weatherOn ? "WEATHER ON" : "WEATHER OFF");
    wxRequested = false;
  } else if (key === "MNU") {
    const open = menu.hidden;
    menu.hidden = !open;
    if (open) traffic.hidden = true;
  } else if (key === "NAV") {
    panNorth = 0;
    panEast = 0;
    selectedId = null;
    detail.hidden = true;
    toast("HOME");
  } else if (key === "HDG") {
    orientation = orientation === "north" ? "track" : "north";
    toast(orientation === "north" ? "NORTH UP" : "TRACK UP");
  } else if (key === "ALT") {
    band = ALT_BANDS[(ALT_BANDS.indexOf(band) + 1) % ALT_BANDS.length];
    toast(bandLabel(band, config.units));
    if (!traffic.hidden) renderList();
  } else if (key === "BRT") {
    const next = BRIGHT_STEPS.find((step) => step < brightness - 0.5) ?? BRIGHT_STEPS[0];
    brightness = next;
    toast(`BRT ${brightness}% · ${Math.round((brightness / 100) * 255)}/255`);
  }
  syncChrome();
  if (key !== "TFC" && key !== "MNU" && key !== "NAV") persist();
  if (key === "NAV") persist();
}

function select(id: string, fromList = false): void {
  selectedId = id;
  if (fromList) traffic.hidden = true;
  detail.hidden = false;
  renderDetail();
  syncChrome();
}

function renderList(): void {
  trafficList.replaceChildren();
  const rows = aircraft
    .filter(inBand)
    .map((item) => ({
      item,
      dist: haversineNm(config.home.lat, config.home.lon, item.lat, item.lon),
      brg: (bearingDeg(config.home.lat, config.home.lon, item.lat, item.lon) + 360) % 360,
    }))
    .sort((a, b) => a.dist - b.dist);
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = aircraft.length ? "Nothing in this altitude filter." : "No aircraft with a position.";
    trafficList.append(empty);
    return;
  }
  for (const row of rows) {
    const li = document.createElement("li");
    if (row.item.id === selectedId) li.classList.add("selected");
    const name = document.createElement("strong");
    name.textContent = row.item.callsign;
    const alt = document.createElement("span");
    alt.textContent = formatAltitude(row.item.altFt, row.item.ground, config.units);
    const meta = document.createElement("em");
    meta.textContent = `${formatSpeed(row.item.gsKt, config.units)}   ${formatDistance(row.dist, config.units)}   ${formatHeading(row.brg)}`;
    li.append(name, alt, meta);
    li.addEventListener("click", () => select(row.item.id, true));
    trafficList.append(li);
  }
}

function renderDetail(): void {
  const item = aircraft.find((row) => row.id === selectedId);
  if (!item) {
    detail.hidden = true;
    return;
  }
  const placed = placeAircraft(item, performance.now());
  const dist = haversineNm(config.home.lat, config.home.lon, placed.lat, placed.lon);
  const brg = (bearingDeg(config.home.lat, config.home.lon, placed.lat, placed.lon) + 360) % 360;
  callEl.textContent = item.callsign;
  const fields: [string, string][] = [
    ["REG", item.registration || "—"],
    ["CLASS", kindLabel(item.kind)],
    ["TYPE", item.typeCode || "—"],
    ["ALTITUDE", formatAltitude(item.altFt, item.ground, config.units)],
    ["SPEED", formatSpeed(item.gsKt, config.units)],
    ["TRACK", formatHeading(item.track)],
    ["SQUAWK", item.squawk ?? "—"],
    ["FROM", `${formatDistance(dist, config.units)} / ${formatHeading(brg)}`],
  ];
  detailGrid.replaceChildren();
  for (const [label, value] of fields) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    wrap.append(dt, dd);
    detailGrid.append(wrap);
  }
}

/**
 * Station, observation time, then the first weather groups. 1.0.2 dropped the
 * time group, so a report that only changes once an hour looked frozen; the
 * time now stays (as HHMMZ) and AUTO/COR make room for it.
 */
function shortMetar(report: MetarReport): string {
  const raw = report.raw.replace(/\s+RMK\b[\s\S]*$/i, "");
  const parts = raw
    .split(/\s+/)
    .filter((part) => part && !/^(AUTO|COR)$/i.test(part))
    .map((part) => (/^\d{6}Z$/i.test(part) ? part.slice(2) : part));
  return parts.slice(0, 6).join(" ");
}

/** True when the METAR on the glass is old: the server kept it after a failed fetch, or it was observed over 90 minutes ago. */
function metarStale(report: MetarReport | null): boolean {
  if (!report) return false;
  if (report.stale) return true;
  if (typeof report.obsTime !== "number") return false;
  return Date.now() / 1000 - report.obsTime > 90 * 60;
}

function activeIconSet(): IconSetId {
  return iconSetId(params.get("icons") || config.icons);
}

function paintLegend(): void {
  const list = document.querySelector<HTMLElement>("#icon-legend");
  if (!list) return;
  const set = activeIconSet();
  list.replaceChildren();
  if (set === "maverick") {
    for (const item of MAVERICK_LEGEND) appendLegendIcon(list, item.kind, set, item.label, item.mark);
    return;
  }
  const names: Record<string, string> = { jet: "Jet", light: "Light", rotor: "Rotor", uav: "UAV", lighter: "Airship", unknown: "Unknown" };
  for (const kind of ICON_KINDS) appendLegendIcon(list, kind, set, names[kind]);
}

function appendLegendIcon(list: HTMLElement, kind: (typeof ICON_KINDS)[number], set: IconSetId, label: string, mark?: MaverickMark): void {
  const li = document.createElement("li");
  const canvas = document.createElement("canvas");
  canvas.width = 36;
  canvas.height = 36;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.translate(18, 18);
    ctx.scale(0.62, 0.62);
    paintAircraftIcon(ctx, kind, set, { fill: "#ffffff", military: false, emergency: false, mark });
  }
  li.append(canvas, document.createTextNode(label));
  list.append(li);
}

function buildSheet(): void {
  document.body.classList.add("sheet");
  const root = document.querySelector<HTMLElement>("#sheet");
  if (!root) return;
  root.hidden = false;
  root.replaceChildren();
  const title = document.createElement("h1");
  title.textContent = "Aircraft icon sets";
  const note = document.createElement("p");
  note.textContent = "Maverick is the default. Linecut, Classic, Planform, and Compact stay available on the setup page. Large icons are above the 28 px size used on the glass. The last icon in each row is a military jet.";
  root.append(title, note);
  const kinds = [...ICON_KINDS, "jet" as const];
  const labels = ["Jet", "Light", "Rotor", "UAV", "Airship", "Unknown", "Military"];
  for (const set of ICON_SETS) {
    const section = document.createElement("section");
    const heading = document.createElement("h2");
    heading.textContent = set.label;
    section.append(heading);
    if (set.id === "maverick") {
      section.append(maverickRow(2.35, "#1a2128", false, "Large"));
      section.append(maverickRow(1, "#24303a", false, "28 px on a dark map"));
      section.append(maverickRow(1, "#e7eef3", true, "28 px on a light map"));
    } else {
      section.append(iconRow(set.id, kinds, labels, 2.35, "#1a2128", false, "Large"));
      section.append(iconRow(set.id, kinds, labels, 1, "#24303a", false, "28 px on a dark map"));
      section.append(iconRow(set.id, kinds, labels, 1, "#e7eef3", true, "28 px on a light map"));
    }
    root.append(section);
  }
  window.__ftReady = true;
}

function maverickRow(scale: number, background: string, light: boolean, caption: string): HTMLElement {
  const row = document.createElement("div");
  row.className = "sheet-row";
  const cap = document.createElement("p");
  cap.textContent = caption;
  row.append(cap);
  const strip = document.createElement("div");
  strip.className = `sheet-strip ${light ? "is-light" : "is-dark"}`;
  strip.style.background = background;
  const shapes = [...MAVERICK_LEGEND, { mark: "heavy" as const, kind: "jet" as const, label: "Military" }];
  for (const shape of shapes) {
    const cell = document.createElement("figure");
    const canvas = document.createElement("canvas");
    const css = scale === 1 ? 56 : 112;
    canvas.width = css * 2;
    canvas.height = css * 2;
    canvas.style.width = `${css}px`;
    canvas.style.height = `${css}px`;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.setTransform(2, 0, 0, 2, canvas.width / 2, canvas.height / 2);
      ctx.scale(scale, scale);
      paintAircraftIcon(ctx, shape.kind, "maverick", {
        fill: "#ffffff",
        military: shape.label === "Military",
        emergency: false,
        mark: shape.mark,
      });
    }
    const name = document.createElement("figcaption");
    name.textContent = shape.label;
    name.style.color = light ? "#1a2128" : "#e7eef4";
    cell.append(canvas, name);
    strip.append(cell);
  }
  row.append(strip);
  return row;
}

function iconRow(
  set: IconSetId,
  kinds: Array<typeof ICON_KINDS[number] | "jet">,
  labels: string[],
  scale: number,
  background: string,
  light: boolean,
  caption: string,
): HTMLElement {
  const row = document.createElement("div");
  row.className = "sheet-row";
  const cap = document.createElement("p");
  cap.textContent = caption;
  row.append(cap);
  const strip = document.createElement("div");
  strip.className = `sheet-strip ${light ? "is-light" : "is-dark"}`;
  strip.style.background = background;
  kinds.forEach((kind, index) => {
    const cell = document.createElement("figure");
    const canvas = document.createElement("canvas");
    const css = scale === 1 ? 44 : 104;
    canvas.width = css * 2;
    canvas.height = css * 2;
    canvas.style.width = `${css}px`;
    canvas.style.height = `${css}px`;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.setTransform(2, 0, 0, 2, canvas.width / 2, canvas.height / 2);
      ctx.scale(scale, scale);
      paintAircraftIcon(ctx, kind, set, {
        fill: "#ffffff",
        military: labels[index] === "Military",
        emergency: false,
      });
    }
    const name = document.createElement("figcaption");
    name.textContent = labels[index];
    name.style.color = light ? "#1a2128" : "#e7eef4";
    cell.append(canvas, name);
    strip.append(cell);
  });
  row.append(strip);
  return row;
}

function kindLabel(kind: Aircraft["kind"]): string {
  if (kind === "jet") return "JET";
  if (kind === "light") return "LIGHT";
  if (kind === "rotor") return "ROTOR";
  if (kind === "uav") return "UAV";
  if (kind === "lighter") return "AIRSHIP";
  return "UNKNOWN";
}

function trailPoints(now: number): { id: string; points: { lat: number; lon: number; age: number }[] }[] {
  const enabled = Boolean(config.trails?.enabled) || (captureMode && params.get("trails") === "1");
  if (!enabled) return [];
  const minutes = config.trails?.minutes || 5;
  const keep = minutes * 60 * 1000;
  const out: { id: string; points: { lat: number; lon: number; age: number }[] }[] = [];
  if (captureMode && params.get("trails") === "1") {
    for (const item of aircraft) {
      if (item.track == null) continue;
      const points = [];
      for (let i = 6; i >= 0; i -= 1) {
        const nm = (item.gsKt ?? 120) * (i * 20 / 3600);
        const rad = (item.track * Math.PI) / 180;
        points.push({
          lat: item.lat - (nm / 60) * Math.cos(rad),
          lon: item.lon - (nm / (60 * Math.max(0.2, Math.cos((item.lat * Math.PI) / 180)))) * Math.sin(rad),
          age: i / 6,
        });
      }
      out.push({ id: item.id, points });
    }
    return out;
  }
  return trailLines(trailHistory, visible(now), now, keep);
}

function recordTrails(list: Aircraft[], now: number): void {
  if (!config.trails?.enabled) {
    trailHistory.clear();
    return;
  }
  addTrailPoints(trailHistory, list, now, (config.trails.minutes || 5) * 60 * 1000);
}

const alertTracker = new AlertTracker();
function noteArrivals(list: Aircraft[]): void {
  if (captureMode && params.get("alert") === "1") {
    if (!alertsPrimed) {
      alertsPrimed = true;
      showAlert("EMERGENCY", list[0]?.callsign || "TRAFFIC");
    }
    return;
  }
  for (const [reason, callsign] of alertTracker.update(list, config.alerts)) showAlert(reason, callsign);
}

function showAlert(reason: string, callsign: string): void {
  const banner = document.querySelector<HTMLElement>("#alert");
  if (!banner) return;
  banner.hidden = false;
  banner.textContent = `${reason} ${callsign}`;
  window.clearTimeout(alertTimer);
  alertTimer = window.setTimeout(() => {
    banner.hidden = true;
  }, 4000);
  if (!config.alerts?.chime) return;
  try {
    const audio = new AudioContext();
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = 880;
    gain.gain.value = 0.04;
    osc.connect(gain);
    gain.connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.12);
    window.setTimeout(() => void audio.close().catch(() => undefined), 400);
  } catch {
    // No audio output is available. The flash still shows.
  }
}

let alertTimer = 0;

function categoryName(cat: string | null): string {
  const names: Record<string, string> = { A1: "LIGHT", A2: "SMALL", A3: "LARGE", A5: "HEAVY", A7: "ROTOR" };
  if (!cat) return "—";
  return names[cat] ?? cat;
}

function getTile(req: TileRequest): HTMLImageElement | null {
  const layer = req.labels ? "?layer=labels" : "";
  const url =
    req.kind === "map"
      ? `/api/tiles/${req.style}/${req.z}/${req.x}/${req.y}.png${layer}`
      : `/api/weather/${req.style}/${req.z}/${req.x}/${req.y}.png`;
  let image = images.get(url);
  // A tile that failed (no network yet at boot, upstream hiccup) is retried
  // after 45 s instead of staying blank until the page reloads.
  if (image && image.dataset.bad === "1" && Date.now() - Number(image.dataset.failedAt || 0) > 45000) {
    images.delete(url);
    image = undefined;
  }
  if (!image) {
    image = new Image();
    image.decoding = "async";
    const bucket = req.kind === "weather" ? "weather" : "map";
    inflight[bucket] += 1;
    const done = () => {
      inflight[bucket] = Math.max(0, inflight[bucket] - 1);
      maybeReady();
    };
    image.onload = done;
    image.onerror = () => {
      image!.dataset.bad = "1";
      image!.dataset.failedAt = String(Date.now());
      done();
    };
    image.src = url;
    images.set(url, image);
  }
  if (image.dataset.bad === "1" || !image.complete || image.naturalWidth === 0) return null;
  return image;
}

function maybeReady(): void {
  if (window.__ftReady) return;
  if (!booted || !gotAircraft || !fontsDone) return;
  if (background !== "scope" && (!mapRequested || inflight.map > 0)) return;
  if (weatherOn) {
    if (!weather) return;
    if (weather.frames.length > 0 && (!wxRequested || inflight.weather > 0)) return;
  }
  window.__ftReady = true;
}

function resize(): void {
  const rect = screen.getBoundingClientRect();
  const dpr = document.body.classList.contains("kiosk") ? 1 : Math.min(window.devicePixelRatio || 1, 2);
  radar.resize(rect.width, rect.height, dpr);
}

let sized = 0;
let lastFrame = 0;
function frame(now: number): void {
  if (FRAME_CAP_MS && lastDraw && now - lastDraw < FRAME_CAP_MS) {
    requestAnimationFrame(frame);
    return;
  }
  lastDraw = now;
  if (screen.clientWidth !== sized) {
    sized = screen.clientWidth;
    resize();
  }
  const dt = lastFrame ? now - lastFrame : 16;
  lastFrame = now;
  const gap = rangeNm - rangeShown;
  if (Math.abs(gap) < 0.03) rangeShown = rangeNm;
  else rangeShown += gap * (1 - Math.exp(-dt / 180));
  const center = centerOf();
  const info = basemaps[background];
  const frameId = weatherOn && weather && weather.frames.length
    ? weather.frames[Math.min(wxFrame, weather.frames.length - 1)].id
    : null;
  if (background !== "scope") mapRequested = true;
  if (weatherOn && frameId) wxRequested = true;
  // One list for standby and drawing: waking and painting happen on this frame.
  const beyond: Aircraft[] = [];
  const onScope = visible(now, beyond);
  syncIdle(onScope.length);
  const stats = radar.draw(
    {
      style: background,
      rangeNm: rangeShown,
      centerLat: center.lat,
      centerLon: center.lon,
      mapUpDeg: mapUp(),
      aircraft: onScope,
      beyond,
      selectedId,
      homeLat: config.home.lat,
      homeLon: config.home.lon,
      homeName: config.home.name,
      weather: {
        enabled: weatherOn,
        opacity,
        frameId,
        maxZoom: weather?.maxZoom ?? 7,
      },
      units: config.units,
      capture: captureMode,
      minZoom: info?.minZoom ?? 0,
      maxZoom: info?.maxZoom ?? 19,
      labels: Boolean(info?.labels),
      sweep: params.get("sweep") === "1" || sweepOn,
      sweepPeriodMs: sweepPeriod * 1000,
      rings,
      trails: trailPoints(now),
      iconSet: activeIconSet(),
      watchOn: Boolean(config.watch?.enabled),
    },
    getTile,
    now,
  );
  if (weatherOn && frameId) {
    if (!wxWantedAt) wxWantedAt = performance.now();
    if (stats.weatherDrawn > 0) wxDrawnAt = performance.now();
    if (stats.weatherEchoes !== null && stats.weatherEchoes !== wxEchoes) {
      wxEchoes = stats.weatherEchoes;
      showWxChip(document.querySelector<HTMLElement>("#chip-wx"));
    }
  } else {
    wxWantedAt = 0;
    wxEchoes = null;
  }
  maybeReady();
  requestAnimationFrame(frame);
}

const aircraftGate = new PollGate();
let lastPolledRange = NaN;

async function pollAircraft(): Promise<void> {
  const ticket = aircraftGate.begin();
  const asked = snapRange(rangeNm);
  lastPolledRange = asked;
  const response = await fetch(aircraftUrl(asked, captureMode));
  const body = (await response.json()) as AircraftResponse;
  // A slow reply from before a range change, or one overtaken by a newer
  // reply, must not replace the traffic on the glass.
  if (!aircraftGate.accept(ticket)) return;
  aircraft = body.aircraft ?? [];
  fixMs = performance.now();
  source = body.source;
  stale = body.stale;
  feedError = body.error;
  gotAircraft = true;
  recordTrails(aircraft, performance.now());
  // Alerts follow what is on the scope, not traffic beyond the outer ring.
  noteArrivals(visible(performance.now()));
  if (selectedId && !aircraft.some((item) => item.id === selectedId)) {
    selectedId = null;
    detail.hidden = true;
  }
  if (!traffic.hidden) renderList();
  if (!detail.hidden) renderDetail();
  syncChrome();
  maybeReady();
}

async function pollWeather(): Promise<void> {
  try {
    weather = (await fetch("/api/weather", { cache: "no-store" }).then((response) => response.json())) as WeatherIndex;
  } catch {
    weather = { provider: "none", attribution: "", attributionUrl: "", maxZoom: 7, frames: [], ok: false, error: "Display link down" };
  }
  if (!Array.isArray(weather.frames)) weather.frames = [];
  // Frames run oldest to newest. Show the newest radar picture (1.0.1 showed
  // frames[0], about two hours old).
  wxFrame = Math.max(0, weather.frames.length - 1);
  wxRequested = false;
  dropOldRadarTiles();
  syncChrome();
}

/**
 * Forget radar tiles from frames no longer on the glass. Each new radar
 * picture has its own URL; without this the kiosk kept every picture since
 * boot in memory.
 */
function dropOldRadarTiles(): void {
  if (!weather || weather.frames.length === 0) return;
  const keep = new Set(weather.frames.slice(-2).map((item) => item.id));
  for (const url of [...images.keys()]) {
    const match = /^\/api\/weather\/([^/]+)\//.exec(url);
    if (match && !keep.has(match[1])) images.delete(url);
  }
}

/** Seconds since the newest radar picture was taken, or null when unknown. */
function radarAgeSec(): number | null {
  const newest = weather?.frames[weather.frames.length - 1];
  if (!newest || typeof newest.time !== "number") return null;
  return Date.now() / 1000 - newest.time;
}

/** True when weather is on and the newest radar picture is over 30 minutes old. */
function weatherStale(): boolean {
  if (!weatherOn || captureMode) return false;
  const age = radarAgeSec();
  return age !== null && age > 30 * 60;
}

/** Share of the ring with radar echoes, from the last complete radar picture. */
let wxEchoes: number | null = null;

function currentWx() {
  const newest = weather?.frames[Math.min(wxFrame, (weather?.frames.length ?? 1) - 1)];
  const shown = Math.abs(rangeShown - rangeNm) < 0.05 ? rangeNm : rangeShown;
  return wxSummary({
    on: weatherOn,
    down: weatherUnavailable(),
    stale: weatherStale(),
    frameTime: newest && typeof newest.time === "number" ? newest.time : null,
    echoes: wxEchoes,
    range: formatDistance(shown, config.units, shown >= 10 ? 0 : 1),
  });
}

function showWxChip(chip: HTMLElement | null): void {
  if (!chip) return;
  const wx = currentWx();
  chip.hidden = wx.chip === null;
  chip.textContent = wx.chip ?? "";
  chip.dataset.tone = wx.tone;
  const idleWx = document.querySelector<HTMLElement>("#idle-wx");
  if (idleWx) {
    idleWx.hidden = !wx.standby;
    idleWx.textContent = wx.standby;
    idleWx.dataset.tone = wx.tone;
  }
}

/** True when weather is switched on but no radar picture is reaching the glass. */
function weatherUnavailable(): boolean {
  if (!weatherOn || captureMode) return false;
  if (weather && (weather.ok === false || weather.frames.length === 0)) return true;
  if (!wxWantedAt) return false;
  return performance.now() - Math.max(wxWantedAt, wxDrawnAt) > 20000 && performance.now() - wxDrawnAt > 20000;
}

/**
 * Minimal text while tracking: with aircraft on the glass, fade the status
 * line, chips, METAR, and map credit; keep the range pill, the clock (if on),
 * alerts, and aircraft labels. CSS does the fade.
 */
function applyTextMode(shown: number): void {
  const minimal = booted && config.minimalText !== false && shown > 0 && !captureMode;
  if (minimal === lastMinimal) return;
  lastMinimal = minimal;
  document.querySelector("#hud")?.classList.toggle("minimal", minimal);
}

async function pollMetar(): Promise<void> {
  if (!config.metar) {
    metar = null;
    syncChrome();
    return;
  }
  const url = `/api/metar?lat=${config.home.lat}&lon=${config.home.lon}`;
  const body = (await fetch(url, { cache: "no-store" }).then((response) => response.json())) as { metar?: MetarReport | null };
  // An error reply (no "metar" key) keeps the last report; a null clears it.
  if (body && "metar" in body) metar = body.metar ?? null;
  syncChrome();
}

async function pollControls(): Promise<void> {
  const body = (await fetch("/api/controls").then((response) => response.json())) as {
    events?: { type: string; key?: BezelKey; delta?: number }[];
  };
  for (const event of body.events ?? []) {
    if (event.type === "button" && event.key) onKey(event.key);
    if (event.type === "encoder" && event.delta) nudgeBrightness(event.delta * 5);
  }
}

/**
 * Touch test: four rings at top, right, bottom, left. A tap draws a dot where
 * the browser received it and marks the ring it landed in, so a rotated or
 * mirrored touch mapping shows at once (tap TOP, see RIGHT light up).
 */
function bindTouchTest(): void {
  const overlay = document.querySelector<HTMLElement>("#touchtest");
  const text = document.querySelector<HTMLElement>("#tt-text");
  const dot = document.querySelector<HTMLElement>("#tt-dot");
  if (!overlay || !text || !dot) return;
  const open = () => {
    overlay.hidden = false;
    menu.hidden = true;
    overlay.querySelectorAll(".tt-target").forEach((target) => target.classList.remove("hit"));
    text.textContent = "Tap each ring: top, right, bottom, left.";
  };
  document.querySelector("#m-touch")?.addEventListener("click", open);
  document.querySelector("#tt-close")?.addEventListener("click", (event) => {
    event.stopPropagation();
    overlay.hidden = true;
  });
  overlay.addEventListener("pointerdown", (event) => {
    if ((event.target as Element).closest("#tt-close")) return;
    const rect = overlay.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    dot.hidden = false;
    dot.style.left = `${x}px`;
    dot.style.top = `${y}px`;
    let hit = "";
    overlay.querySelectorAll<HTMLElement>(".tt-target").forEach((target) => {
      const box = target.getBoundingClientRect();
      const cx = box.left + box.width / 2 - rect.left;
      const cy = box.top + box.height / 2 - rect.top;
      if (Math.hypot(x - cx, y - cy) <= box.width * 0.75) {
        target.classList.add("hit");
        hit = target.dataset.side ?? "";
      }
    });
    const px = Math.round((x / rect.width) * 100);
    const py = Math.round((y / rect.height) * 100);
    text.textContent = hit ? `${hit} ✓  (${px}%, ${py}%)` : `Missed  (${px}%, ${py}%)`;
  });
  if (params.get("touchtest") === "1") open();
}

function bindInput(): void {
  buildRangePicker();
  rangeBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    if (rangePicker.hidden) openRangePicker();
    else closeRangePicker();
  });
  rangeMinus.addEventListener("click", (event) => {
    event.stopPropagation();
    stepRange(-1);
  });
  rangePlus.addEventListener("click", (event) => {
    event.stopPropagation();
    stepRange(1);
  });
  // Tap anywhere else closes the preset picker.
  document.addEventListener("pointerdown", (event) => {
    const target = event.target;
    if (target instanceof Element && (target.closest("#range-picker") || target.closest("#range"))) return;
    closeRangePicker();
  }, true);
  sweepBtn.addEventListener("click", () => {
    sweepOn = !sweepOn;
    toast(sweepOn ? "SWEEP ON" : "SWEEP OFF");
    syncChrome();
    persist();
  });
  document.querySelector("#d-close")!.addEventListener("click", () => {
    selectedId = null;
    detail.hidden = true;
    syncChrome();
  });
  document.querySelector("#t-close")!.addEventListener("click", () => {
    traffic.hidden = true;
    syncChrome();
  });
  document.querySelector("#m-traffic")!.addEventListener("click", () => {
    menu.hidden = true;
    traffic.hidden = false;
    renderList();
    syncChrome();
  });
  document.querySelector("#m-close")!.addEventListener("click", () => {
    menu.hidden = true;
    syncChrome();
  });
  document.querySelector("#m-wifi")!.addEventListener("click", async () => {
    wifiPinned = true;
    wifiDismissed = false;
    menu.hidden = true;
    const info = (await fetch("/api/wifi").then((response) => response.json())) as WifiInfo;
    const view = info.state === "connected" ? "connected" : info.state === "portal" ? "portal" : "hotspot";
    await renderWifi(view, info);
    syncChrome();
  });
  bindTouchTest();
  document.querySelector("#wifi-close")!.addEventListener("click", () => {
    wifiPinned = false;
    wifiDismissed = true;
    wifiPanel.hidden = true;
  });
  screen.addEventListener(
    "wheel",
    (event) => {
      if (!menu.hidden || !traffic.hidden || !detail.hidden) return;
      event.preventDefault();
      const index = PRESETS.findIndex((preset) => preset >= rangeNm - 0.1);
    const next = Math.max(0, Math.min(PRESETS.length - 1, (index < 0 ? 0 : index) + (event.deltaY > 0 ? 1 : -1)));
    setRange(PRESETS[next]);
    persist();
    },
    { passive: false },
  );
  const pointers = new Map<number, { x: number; y: number }>();
  let lastTap = { t: 0, x: 0, y: 0 };
  let drag: { x: number; y: number; north: number; east: number; moved: boolean } | null = null;
  let pinch: { dist: number; range: number } | null = null;
  const distance = () => {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  canvas.addEventListener("pointerdown", (event) => {
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    canvas.setPointerCapture(event.pointerId);
    if (pointers.size >= 2) {
      pinch = { dist: distance(), range: rangeNm };
      drag = null;
    } else {
      drag = { x: event.clientX, y: event.clientY, north: panNorth, east: panEast, moved: false };
    }
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size >= 2 && pinch) {
      const dist = Math.max(20, distance());
      setRange(pinch.range * (pinch.dist / dist), false);
      return;
    }
    if (!drag) return;
    const sx = event.clientX - drag.x;
    const sy = event.clientY - drag.y;
    if (Math.hypot(sx, sy) > 6) drag.moved = true;
    if (!drag.moved) return;
    const angle = (-mapUp() * Math.PI) / 180;
    const dx = sx * Math.cos(angle) + sy * Math.sin(angle);
    const dy = -sx * Math.sin(angle) + sy * Math.cos(angle);
    panEast = drag.east - dx * radar.nmPerPx;
    panNorth = drag.north + dy * radar.nmPerPx;
    panEast = Math.max(-80, Math.min(80, panEast));
    panNorth = Math.max(-80, Math.min(80, panNorth));
    syncChrome();
  });
  const end = (event: PointerEvent) => {
    const was = drag;
    pointers.delete(event.pointerId);
    if (pointers.size < 2) {
      if (pinch) {
        setRange(rangeNm, true);
        persist();
      }
      pinch = null;
    }
    if (pointers.size === 0) {
      if (was && !was.moved) {
        const rect = canvas.getBoundingClientRect();
        const hit = radar.hitTest(event.clientX - rect.left, event.clientY - rect.top);
        const now = performance.now();
        const double = now - lastTap.t < 380 && Math.hypot(event.clientX - lastTap.x, event.clientY - lastTap.y) < 40;
        lastTap = { t: double ? 0 : now, x: event.clientX, y: event.clientY };
        if (hit) select(hit);
        else {
          if (!detail.hidden) {
            selectedId = null;
            detail.hidden = true;
            syncChrome();
          }
          // Double-tap empty map: back to home (the old NAV key).
          if (double) recenter();
        }
      }
      drag = null;
    }
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  window.addEventListener("keydown", (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement) {
      if (event.key === "Escape") target.blur();
      return;
    }
    const keys: Record<string, BezelKey> = {
      m: "MAP",
      t: "TFC",
      w: "WX",
      u: "MNU",
      n: "NAV",
      h: "HDG",
      a: "ALT",
      b: "BRT",
    };
    const key = keys[event.key.toLowerCase()];
    if (key) {
      onKey(key);
      return;
    }
    if (event.key === "Escape") {
      menu.hidden = true;
      traffic.hidden = true;
      detail.hidden = true;
      selectedId = null;
      syncChrome();
    }
    if (event.key === "+" || event.key === "=") {
      const index = PRESETS.findIndex((preset) => preset > rangeNm + 0.1);
      if (index >= 0) pickRange(PRESETS[index]);
    }
    if (event.key === "-" || event.key === "_") {
      const index = PRESETS.findIndex((preset) => preset >= rangeNm - 0.1);
      if (index > 0) pickRange(PRESETS[index - 1]);
    }
  });
}

interface WifiInfo {
  state: string;
  password: string;
  ssid: string;
  joinQr: string;
  setupUrl: string;
  setupQr: string;
  configUrl: string;
  configQr: string;
}

const wifiPanel = document.querySelector<HTMLElement>("#wifi")!;
const wifiTitle = document.querySelector<HTMLElement>("#wifi-title")!;
const wifiKicker = document.querySelector<HTMLElement>("#wifi-kicker")!;
const wifiPass = document.querySelector<HTMLElement>("#wifi-pass")!;
const wifiSteps = document.querySelector<HTMLElement>("#wifi-steps")!;
const wifiQr = document.querySelector<HTMLCanvasElement>("#wifi-qr")!;

async function renderWifi(view: string, info: WifiInfo): Promise<void> {
  wifiPanel.hidden = false;
  let code = info.joinQr;
  let steps: string[] = [];
  if (view === "portal") {
    wifiKicker.textContent = "PHONE JOINED";
    wifiTitle.textContent = "Open setup";
    wifiPass.textContent = info.setupUrl;
    code = info.setupQr;
    steps = ["Stay on FlightTracker-Setup.", "Scan this code.", "Enter your home Wi-Fi and save."];
  } else if (view === "connected") {
    wifiKicker.textContent = "CONNECTED";
    wifiTitle.textContent = "Connected — configure at http://flighttracker.local";
    wifiPass.textContent = info.configUrl;
    code = info.configQr;
    steps = ["Home Wi-Fi is up.", "Scan to open the setup page on your phone."];
  } else {
    wifiKicker.textContent = "NO WI-FI";
    wifiTitle.textContent = "Join FlightTracker-Setup";
    wifiPass.textContent = info.password;
    code = info.joinQr;
    steps = ["Scan with the phone camera.", "It joins the WPA setup network.", "The next code appears when the phone connects."];
  }
  wifiSteps.replaceChildren();
  for (const step of steps) {
    const item = document.createElement("li");
    item.textContent = step;
    wifiSteps.append(item);
  }
  await QRCode.toCanvas(wifiQr, code, {
    width: 280,
    margin: 1,
    color: { dark: "#071016", light: "#f7f4ee" },
  });
}

async function pollWifi(): Promise<void> {
  const info = (await fetch("/api/wifi").then((response) => response.json())) as WifiInfo;
  const forced = params.get("wifi");
  if (forced === "hotspot" || forced === "portal" || forced === "connected" || forced === "failed") {
    await renderWifi(forced === "failed" ? "hotspot" : forced, info);
    window.__wifiReady = true;
    return;
  }
  const state = info.state;
  if ((state === "hotspot" || state === "portal" || state === "failed") && !wifiDismissed) {
    await renderWifi(state === "portal" ? "portal" : "hotspot", info);
  } else if (wifiSeen && ["hotspot", "portal", "failed"].includes(wifiSeen) && state === "connected") {
    await renderWifi("connected", info);
    window.clearTimeout(connectedTimer);
    connectedTimer = window.setTimeout(() => {
      if (!wifiPinned) wifiPanel.hidden = true;
    }, 8000);
  }
  wifiSeen = state;
}

async function pollNight(): Promise<void> {
  if (!config.night || config.night.mode === "off") {
    nightOn = false;
    syncChrome();
    return;
  }
  const response = await fetch("/api/night");
  if (!response.ok) return;
  const body = (await response.json()) as { night?: boolean; brightness?: number };
  nightOn = Boolean(body.night);
  nightLevel = body.brightness ?? 25;
  syncChrome();
}

async function pollNearest(): Promise<void> {
  const response = await fetch(`/api/nearest?lat=${config.home.lat}&lon=${config.home.lon}`);
  if (!response.ok) return;
  const body = (await response.json()) as { airport?: { icao?: string; name?: string; city?: string } | null };
  const airport = body.airport;
  const el = document.querySelector<HTMLElement>("#idle-airport");
  if (el && airport) el.textContent = [airport.icao, airport.city].filter(Boolean).join(" · ");
}

/** Stable text of a config (sorted keys) to tell whether anything changed. */
function configKey(value: unknown): string {
  return JSON.stringify(value, (_key, item) => {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      return Object.fromEntries(Object.entries(item as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)));
    }
    return item;
  });
}

async function pollSharedConfig(): Promise<void> {
  if (saveTimer || saving) return;
  const edits = localEdits;
  const response = await fetch("/api/config");
  if (!response.ok) return;
  const next = (await response.json()) as AppConfig;
  // A change made on the glass while this poll was out (or still being
  // saved) wins; the old reply must not bounce the range back.
  if (edits !== localEdits || saveTimer || saving) return;
  const moved = next.home.lat !== config.home.lat || next.home.lon !== config.home.lon;
  // Any saved change on flighttracker.local applies: 1.0.2 compared a fixed
  // list of fields that left out trails, alerts, watch, night, and
  // brightness, so those only took effect after a restart.
  const changed = configKey(next) !== configKey(config);
  if (!changed) return;
  const keepNorth = panNorth;
  const keepEast = panEast;
  applyConfig(next);
  panNorth = moved ? 0 : keepNorth;
  panEast = moved ? 0 : keepEast;
}

// ---- 1.0.7 prototype: on-screen update prompt ----------------------------

type PopMode = "prompt" | "scheduled" | "installing" | "complete" | "failed";
const pop = {
  root: document.querySelector<HTMLElement>("#update-pop")!,
  kicker: document.querySelector<HTMLElement>("#up-kicker")!,
  title: document.querySelector<HTMLElement>("#up-title")!,
  line: document.querySelector<HTMLElement>("#up-line")!,
  summary: document.querySelector<HTMLElement>("#up-summary")!,
  bar: document.querySelector<HTMLElement>("#up-bar")!,
  fill: document.querySelector<HTMLElement>("#up-bar-fill")!,
  actions: document.querySelector<HTMLElement>("#up-actions")!,
  now: document.querySelector<HTMLButtonElement>("#up-now")!,
  later: document.querySelector<HTMLButtonElement>("#up-later")!,
  hint: document.querySelector<HTMLElement>("#up-hint")!,
  close: document.querySelector<HTMLButtonElement>("#up-close")!,
};
let popMode: PopMode | null = null;
let popVersion = "";
let popTarget = "";
let popTimer = 0;
let popPoll = 0;
let popMisses = 0;

function popShow(mode: PopMode, parts: { kicker?: string; title: string; line: string; summary?: string; hint?: string; percent?: number | null; actions?: boolean; close?: boolean }): void {
  popMode = mode;
  pop.root.dataset.mode = mode;
  pop.kicker.textContent = parts.kicker ?? "SOFTWARE UPDATE";
  pop.title.textContent = parts.title;
  pop.line.textContent = parts.line;
  pop.summary.textContent = parts.summary ?? "";
  pop.summary.hidden = !parts.summary;
  pop.hint.textContent = parts.hint ?? "";
  pop.hint.hidden = !parts.hint;
  pop.bar.hidden = parts.percent == null;
  if (parts.percent != null) pop.fill.style.width = `${Math.max(3, Math.min(100, parts.percent))}%`;
  pop.actions.hidden = !parts.actions;
  pop.close.hidden = !parts.close;
  pop.root.hidden = false;
}

function popHide(): void {
  window.clearTimeout(popTimer);
  popMode = null;
  pop.root.hidden = true;
}

function popPrompt(view: UpdateView): void {
  popVersion = view.prompt?.version || view.latest;
  popShow("prompt", {
    title: "Update available",
    line: `Version ${popVersion} is ready`,
    summary: view.prompt?.summary || "",
    hint: `LATER installs at ${view.laterLabel || "2:00 AM ET"}. Closes by itself in 2 min.`,
    actions: true,
  });
  window.clearTimeout(popTimer);
  if (!captureMode) popTimer = window.setTimeout(() => void popLater("timeout"), PROMPT_TIMEOUT_MS);
}

function popScheduled(label: string, version: string): void {
  popShow("scheduled", { kicker: "LATER", title: scheduledLine(label), line: `Version ${version} installs then by itself.` });
  window.clearTimeout(popTimer);
  if (!captureMode) popTimer = window.setTimeout(popHide, 4000);
}

function popInstalling(view: UpdateView, reconnecting = false): void {
  const line = reconnecting ? "Step 4 of 4 · Restarting Flight Tracker, reconnecting..." : installLine(view);
  popShow("installing", {
    kicker: "INSTALLING",
    title: `Installing Version ${popTarget || view.target}`,
    line,
    hint: "The screen reloads by itself when it is done.",
    percent: reconnecting ? 92 : installPercent(view),
  });
}

function popComplete(version: string): void {
  popShow("complete", { kicker: "SOFTWARE UPDATE", title: "Update complete", line: `Now running Version ${version}` });
  window.clearTimeout(popTimer);
  if (!captureMode) popTimer = window.setTimeout(popHide, 6000);
}

function popFailed(view: UpdateView): void {
  const reason = (view.error || "The update did not finish.").replace(/\s*$/, "");
  popShow("failed", {
    kicker: "SOFTWARE UPDATE",
    title: "Update failed",
    line: `Still running Version ${view.version}`,
    summary: `${/[.!?]$/.test(reason) ? reason : `${reason}.`} Rolled back automatically; your settings are kept.`,
    close: true,
  });
  window.clearTimeout(popTimer);
  if (!captureMode) popTimer = window.setTimeout(popHide, 10000);
}

async function updateView(init?: RequestInit, path = "/api/updates"): Promise<UpdateView> {
  const response = await fetch(path, { cache: "no-store", ...init });
  return (await response.json()) as UpdateView;
}

const postJson = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function popLater(source: "later" | "timeout"): Promise<void> {
  window.clearTimeout(popTimer);
  try {
    const view = await updateView(postJson({ version: popVersion, source }), "/api/updates/later");
    if (view.schedule) popScheduled(view.schedule.label, view.schedule.version);
    else popHide();
  } catch {
    popHide();
  }
}

async function popInstall(): Promise<void> {
  window.clearTimeout(popTimer);
  popTarget = popVersion;
  pop.now.disabled = true;
  try {
    const view = await updateView(postJson({}), "/api/updates/install");
    if (installFailed(view) || (view as UpdateView & { ok?: boolean }).ok === false) {
      popFailed({ ...view, error: view.error || view.detail });
    } else {
      popInstalling(view);
      watchInstall();
    }
  } catch {
    popFailed({ version: "", error: "The display lost its link to the tracker." } as UpdateView);
  } finally {
    pop.now.disabled = false;
  }
}

function watchInstall(): void {
  window.clearInterval(popPoll);
  popMisses = 0;
  const started = Date.now();
  popPoll = window.setInterval(async () => {
    if (Date.now() - started > 4 * 60_000) {
      window.clearInterval(popPoll);
      popFailed({ version: "", error: "The update took too long. Check the Software card at flighttracker.local." } as UpdateView);
      return;
    }
    try {
      const view = await updateView();
      popMisses = 0;
      if (installDone(view, popTarget)) {
        window.clearInterval(popPoll);
        popComplete(popTarget);
        // The updater restarts the kiosk too; this is the fallback.
        window.setTimeout(() => location.reload(), 3000);
      } else if (installFailed(view)) {
        window.clearInterval(popPoll);
        popFailed(view);
      } else {
        popInstalling(view);
      }
    } catch {
      popMisses += 1;
      popInstalling({ stage: "restarting", step: 4 } as UpdateView, true);
    }
  }, 1500);
}

/** Every minute: show the prompt for a newer release, or follow an install that started elsewhere. */
async function pollUpdatePrompt(): Promise<void> {
  if (popMode === "installing" || popMode === "prompt") return;
  const view = await updateView();
  if (view.state === "installing" && view.target) {
    popTarget = view.target;
    popInstalling(view);
    watchInstall();
    return;
  }
  if (popMode) return;
  if (!view.prompt?.show) return;
  const panelOpen = [menu, traffic, detail, document.querySelector<HTMLElement>("#wifi"), document.querySelector<HTMLElement>("#touchtest")]
    .some((el) => el && !el.hidden);
  const banner = document.querySelector<HTMLElement>("#alert");
  const bannerText = banner && !banner.hidden ? banner.textContent : null;
  // Only an emergency holds it back; queued, not dropped (next poll asks again).
  if (panelOpen || !promptAllowed(bannerText, visible(performance.now()))) return;
  popPrompt(view);
}

/** After the kiosk reloads on a new version, say so once. */
async function announceInstalled(): Promise<void> {
  const view = await updateView();
  if (view.state !== "installed" || !view.installedAt) return;
  const age = Date.now() - Date.parse(view.installedAt);
  if (!(age >= 0 && age < 15 * 60_000)) return;
  if (localStorage.getItem("ft-installed-seen") === view.installedAt) return;
  localStorage.setItem("ft-installed-seen", view.installedAt);
  popComplete(view.version);
}

const SAMPLE_NOTES = "Update prompt on the round screen with Update now or Later, and weather radar status on standby.";
function captureUpdatePop(mode: string): void {
  const MB = 1024 * 1024;
  const base = { version: "1.0.6", latest: "1.0.7", available: true, state: "available", stage: "", step: 0, steps: 4, target: "1.0.7", detail: "", error: "", received: 0, total: 0, installedAt: "", laterLabel: "2:00 AM ET" } as UpdateView;
  popVersion = "1.0.7";
  popTarget = "1.0.7";
  if (mode === "prompt") popPrompt({ ...base, prompt: { show: true, version: "1.0.7", summary: SAMPLE_NOTES } });
  else if (mode === "scheduled") popScheduled("2:00 AM ET", "1.0.7");
  else if (mode === "installing") popInstalling({ ...base, state: "installing", stage: "downloading", step: 2, received: 24 * MB, total: 71 * MB, detail: "Downloading Version 1.0.7 (24 / 71 MB)..." });
  else if (mode === "complete") popComplete("1.0.7");
  else if (mode === "failed") popFailed({ ...base, state: "rolled-back", stage: "failed", error: "Update to Version 1.0.7 failed." });
}

async function boot(): Promise<void> {
  if (params.get("sheet") === "1") {
    buildSheet();
    return;
  }
  buildChrome();
  bindInput();
  resize();
  new ResizeObserver(resize).observe(screen);
  window.addEventListener("resize", resize);
  document.fonts.ready.then(() => {
    fontsDone = true;
    maybeReady();
  }).catch(() => {
    fontsDone = true;
  });
  try {
    const [cfgRes, mapRes, healthRes] = await Promise.all([
      fetch("/api/config"),
      fetch("/api/basemaps"),
      fetch("/api/health"),
    ]);
    basemaps = (await mapRes.json()) as Record<string, BasemapInfo>;
    const health = (await healthRes.json()) as { demoLock?: boolean; backlightNodes?: string[] };
    demoLock = Boolean(health.demoLock);
    hardwareBacklight = Array.isArray(health.backlightNodes) && health.backlightNodes.length > 0;
    applyConfig((await cfgRes.json()) as AppConfig);
    booted = true;
    await pollAircraft();
    await pollWeather();
    if (config.metar) await pollMetar();
    syncChrome();
  } catch (error) {
    statusEl.textContent = "DISPLAY LINK DOWN";
    console.error(error);
  }
  requestAnimationFrame(frame);
  let lastActivity = 0;
  screen.addEventListener("pointerdown", () => {
    const now = Date.now();
    if (now - lastActivity < 30000) return;
    lastActivity = now;
    void fetch("/api/activity", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  });
  const refreshUpdateDot = async () => {
    const response = await fetch("/api/updates");
    if (!response.ok) return;
    const body = (await response.json()) as { available?: boolean };
    const dot = document.querySelector<HTMLElement>("#update-dot");
    if (dot) dot.hidden = !body.available;
  };
  void refreshUpdateDot().catch(() => undefined);
  pop.now.addEventListener("click", () => void popInstall());
  pop.later.addEventListener("click", () => void popLater("later"));
  pop.close.addEventListener("click", popHide);
  const popCapture = params.get("updatepop");
  if (captureMode && popCapture) {
    captureUpdatePop(popCapture);
  } else if (!captureMode) {
    void announceInstalled().catch(() => undefined);
    window.setTimeout(() => void pollUpdatePrompt().catch(() => undefined), 20000);
    window.setInterval(() => void pollUpdatePrompt().catch(() => undefined), 60000);
  }
  window.setInterval(() => void refreshUpdateDot().catch(() => undefined), 120000);
  window.setInterval(() => void pollAircraft().catch(() => undefined), 1000);
  window.setInterval(() => void pollSharedConfig().catch(() => undefined), 2000);
  window.setInterval(() => void pollNight().catch(() => undefined), 60000);
  void pollNight();
  void pollNearest();
  screen.addEventListener("pointerdown", (event) => {
    if (detail.hidden) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("#detail") || target.closest("#rangectl") || target.closest("#range-picker") || target.closest(".hold-target")) return;
    selectedId = null;
    detail.hidden = true;
    syncChrome();
  });
  window.setInterval(() => void pollWeather().catch(() => undefined), 60000);
  window.setInterval(() => void pollMetar().catch(() => undefined), 240000);
  window.setInterval(() => void pollControls().catch(() => undefined), 160);
  window.setInterval(() => void pollWifi().catch(() => undefined), 3000);
  void pollWifi().catch(() => undefined);
  window.setInterval(() => {
    clockEl.textContent = formatClockZulu(new Date(), config.clockFormat);
    showWxChip(document.querySelector<HTMLElement>("#chip-wx"));
  }, 1000);
  window.setTimeout(() => {
    window.__ftReady = true;
  }, 15000);
}

void boot();
