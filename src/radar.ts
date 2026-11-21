import { trailAlpha } from "./trails";
import { bearingDeg, chooseZoom, haversineNm, NM_TO_M, project } from "./geo";
import { dataBlockLine } from "./format";
import { leaderAnchor, placeLabels, type Box, type LabelMemory } from "./labelplace";
import { paintAircraftIcon, type IconSetId, type MaverickMark } from "./icons";
import { formatRing, ringDistances, ringLabelMask } from "./rings";
import type { Aircraft, BackgroundId, TileRequest, Units } from "./types";

export interface RadarWeather {
  enabled: boolean;
  opacity: number;
  frameId: string | null;
  maxZoom: number;
}

export interface RadarScene {
  style: BackgroundId;
  rangeNm: number;
  centerLat: number;
  centerLon: number;
  mapUpDeg: number;
  aircraft: Aircraft[];
  selectedId: string | null;
  homeLat: number;
  homeLon: number;
  homeName: string;
  weather: RadarWeather;
  units: Units;
  capture: boolean;
  minZoom: number;
  maxZoom: number;
  labels: boolean;
  sweep: boolean;
  sweepPeriodMs: number;
  rings?: number;
  trails: { id: string; points: { lat: number; lon: number; age: number }[] }[];
  iconSet: IconSetId;
  watchOn: boolean;
  /** Traffic just outside the ring: edge ticks only, never icons or a wake. */
  beyond?: Aircraft[];
}

export type TileGetter = (req: TileRequest) => HTMLImageElement | null;

interface Spot {
  id: string;
  x: number;
  y: number;
}

const SCOPE = "#04140e";

export interface PlateStats {
  mapDrawn: number;
  weatherDrawn: number;
  /** Share of the ring with radar echoes (0..1), or null when not measured. */
  weatherEchoes: number | null;
}

/** Share of pixels inside a centred circle whose alpha shows a real echo. */
export function echoFraction(rgba: Uint8ClampedArray, size: number, ringPx: number, minAlpha = 90): number {
  const c = size / 2;
  let inside = 0;
  let wet = 0;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      if (Math.hypot(x + 0.5 - c, y + 0.5 - c) > ringPx) continue;
      inside += 1;
      if (rgba[(y * size + x) * 4 + 3] >= minAlpha) wet += 1;
    }
  }
  return inside ? wet / inside : 0;
}

export class RadarView {
  readonly canvas: HTMLCanvasElement;
  nmPerPx = 0.1;
  private w = 720;
  private h = 720;
  private dpr = 1;
  private spots: Spot[] = [];
  private plate: HTMLCanvasElement | null = null;
  private plateKey = "";
  private plateStats: PlateStats = { mapDrawn: 0, weatherDrawn: 0, weatherEchoes: null };
  private labelMemory = new Map<string, LabelMemory>();
  private fps = 60;
  /** Drop the sweep glow below this frame rate. main.ts lowers it when frames are capped. */
  liteSweepBelow = 28;
  private fpsStamp = 0;
  private fpsCount = 0;
  private liteSweep = false;
  private outerRing = 200;
  private plateIncomplete = false;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }

  resize(cssW: number, cssH: number, dpr: number): void {
    this.w = cssW;
    this.h = cssH;
    this.dpr = dpr;
    this.canvas.width = Math.max(1, Math.round(cssW * dpr));
    this.canvas.height = Math.max(1, Math.round(cssH * dpr));
    this.canvas.style.width = `${cssW}px`;
    this.canvas.style.height = `${cssH}px`;
  }

  hitTest(x: number, y: number): string | null {
    let best: string | null = null;
    let bestD = 28;
    for (const spot of this.spots) {
      const d = Math.hypot(spot.x - x, spot.y - y);
      if (d < bestD) {
        bestD = d;
        best = spot.id;
      }
    }
    return best;
  }

  draw(scene: RadarScene, tiles: TileGetter, now: number): PlateStats {
    const ctx = this.canvas.getContext("2d");
    if (!ctx) return { mapDrawn: 0, weatherDrawn: 0, weatherEchoes: null };
    const w = this.w;
    const h = this.h;
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(w, h) / 2;
    const safeR = radius * 0.9;
    const ringR = Math.max(40, safeR - 28);
    this.outerRing = ringR;
    this.nmPerPx = scene.rangeNm / ringR;
    const screenPxPerMeter = ringR / (scene.rangeNm * NM_TO_M);
    const scope = scene.style === "scope";
    const zoom = chooseZoom(
      scene.centerLat,
      screenPxPerMeter,
      scope ? 0 : scene.minZoom,
      scope ? 19 : scene.maxZoom,
    );

    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius - 0.5, 0, Math.PI * 2);
    ctx.clip();

    // 1.0.7: the map scale is in the key. Before, only the tile zoom level
    // was, so after a range change the map and weather radar stayed drawn at
    // the scale of the first animation frame (wrong place, and weather beyond
    // the old range missing) until a new radar frame or a pan rebuilt it.
    const plateKey = [
      w, h, this.dpr, scene.style, zoom.z, zoom.pxPerWorldPx.toFixed(5), scene.mapUpDeg.toFixed(2),
      scene.centerLat.toFixed(4), scene.centerLon.toFixed(4),
      scene.weather.enabled ? scene.weather.frameId : "",
      scene.weather.opacity, scene.labels,
    ].join("|");
    const plate = this.ensurePlate(plateKey, ctx, scene, tiles, scope, zoom.z, zoom.pxPerWorldPx, cx, cy, radius, ringR);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(plate, 0, 0);
    ctx.restore();
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius - 0.5, 0, Math.PI * 2);
    ctx.clip();

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((-scene.mapUpDeg * Math.PI) / 180);
    this.drawTrails(ctx, scene, zoom.z, zoom.pxPerWorldPx);
    this.drawAircraftIcons(ctx, scene, zoom.z, zoom.pxPerWorldPx, now, false);
    ctx.restore();

    this.drawRings(ctx, cx, cy, ringR, scene);
    this.drawCompass(ctx, cx, cy, ringR, scene.mapUpDeg, scope);
    this.drawHome(ctx, scene, zoom.z, zoom.pxPerWorldPx, cx, cy);
    this.spots = [];
    this.drawSelectionLine(ctx, scene, zoom.z, zoom.pxPerWorldPx, cx, cy);
    this.drawLabelsAndHits(ctx, scene, zoom.z, zoom.pxPerWorldPx, cx, cy, ringR, now);
    if (scene.sweep) this.paintSweep(ctx, scene, now, cx, cy, ringR, zoom.z, zoom.pxPerWorldPx);
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((-scene.mapUpDeg * Math.PI) / 180);
    this.drawAircraftIcons(ctx, scene, zoom.z, zoom.pxPerWorldPx, now, true);
    ctx.restore();
    ctx.restore();
    ctx.restore();
    return this.plateStats;
  }

  private ensurePlate(
    key: string,
    _ctx: CanvasRenderingContext2D,
    scene: RadarScene,
    tiles: TileGetter,
    scope: boolean,
    z: number,
    pxPerWorld: number,
    cx: number,
    cy: number,
    radius: number,
    ringR: number,
  ): HTMLCanvasElement {
    if (this.plate && this.plateKey === key && this.plate.width === this.canvas.width && this.plate.height === this.canvas.height) {
      return this.plate;
    }
    const plate = document.createElement("canvas");
    plate.width = this.canvas.width;
    plate.height = this.canvas.height;
    const paint = plate.getContext("2d");
    if (!paint) return plate;
    paint.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.plateIncomplete = false;
    paint.beginPath();
    paint.arc(cx, cy, radius - 0.5, 0, Math.PI * 2);
    paint.clip();
    if (scope) {
      const glow = paint.createRadialGradient(cx, cy, ringR * 0.2, cx, cy, radius);
      glow.addColorStop(0, "#12171c");
      glow.addColorStop(1, "#050607");
      paint.fillStyle = glow;
    } else {
      paint.fillStyle = scene.style === "light" ? "#d5dde4" : "#070b10";
    }
    paint.fillRect(0, 0, this.w, this.h);
    paint.save();
    paint.translate(cx, cy);
    paint.rotate((-scene.mapUpDeg * Math.PI) / 180);
    let mapDrawn = 0;
    let weatherDrawn = 0;
    if (!scope) {
      mapDrawn = this.drawTiles(paint, tiles, "map", scene.style, z, pxPerWorld, scene.centerLat, scene.centerLon, radius, false);
      if (scene.labels) {
        this.drawTiles(paint, tiles, "map", scene.style, z, pxPerWorld, scene.centerLat, scene.centerLon, radius, true);
      }
    }
    if (scene.weather.enabled && scene.weather.frameId) {
      const screenPxPerMeter = ringR / (scene.rangeNm * NM_TO_M);
      const wz = chooseZoom(scene.centerLat, screenPxPerMeter, 2, scene.weather.maxZoom);
      paint.save();
      paint.globalAlpha = scene.weather.opacity;
      weatherDrawn = this.drawTiles(
        paint, tiles, "weather", scene.weather.frameId, wz.z, wz.pxPerWorldPx,
        scene.centerLat, scene.centerLon, radius, false,
      );
      paint.restore();
    }
    paint.restore();
    this.plate = plate;
    this.plateKey = this.plateIncomplete ? "" : key;
    // 1.0.7: how much of the ring has radar echoes, so the screen can say
    // "no rain in range" instead of looking like weather is broken. Only
    // measured once the picture is complete (cheap: a 96 px probe).
    const echoes = scene.weather.enabled && scene.weather.frameId && !this.plateIncomplete
      ? this.probeEchoes(scene, tiles, cx, cy, radius, ringR)
      : null;
    this.plateStats = { mapDrawn, weatherDrawn, weatherEchoes: echoes };
    return plate;
  }

  /** Fraction (0..1) of the area inside the outer ring that shows radar echoes. */
  private probeEchoes(scene: RadarScene, tiles: TileGetter, cx: number, cy: number, radius: number, ringR: number): number | null {
    const size = 96;
    const k = size / Math.max(1, this.w);
    const probe = document.createElement("canvas");
    probe.width = size;
    probe.height = size;
    const paint = probe.getContext("2d", { willReadFrequently: true });
    if (!paint) return null;
    paint.setTransform(k, 0, 0, k, 0, 0);
    paint.translate(cx, cy);
    paint.rotate((-scene.mapUpDeg * Math.PI) / 180);
    const screenPxPerMeter = ringR / (scene.rangeNm * NM_TO_M);
    const wz = chooseZoom(scene.centerLat, screenPxPerMeter, 2, scene.weather.maxZoom);
    const drawn = this.drawTiles(
      paint, tiles, "weather", scene.weather.frameId ?? "", wz.z, wz.pxPerWorldPx,
      scene.centerLat, scene.centerLon, radius, false,
    );
    if (drawn === 0) return null;
    let data: Uint8ClampedArray;
    try {
      data = paint.getImageData(0, 0, size, size).data;
    } catch {
      return null;
    }
    return echoFraction(data, size, (ringR * k));
  }

  private noteFps(now: number): void {
    this.fpsCount += 1;
    if (this.fpsStamp === 0) this.fpsStamp = now;
    if (now - this.fpsStamp < 1000) return;
    this.fps = this.fpsCount;
    this.fpsCount = 0;
    this.fpsStamp = now;
    this.liteSweep = this.fps > 0 && this.fps < this.liteSweepBelow;
  }

  private paintSweep(
    ctx: CanvasRenderingContext2D,
    scene: RadarScene,
    now: number,
    cx: number,
    cy: number,
    ringR: number,
    z: number,
    pxPerWorld: number,
  ): void {
    const period = Math.max(2000, scene.sweepPeriodMs);
    const head = scene.capture ? 0.85 : ((now % period) / period) * Math.PI * 2;
    if (!scene.capture) this.noteFps(now);
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, ringR + 6, 0, Math.PI * 2);
    ctx.clip();
    const trail = ctx.createConicGradient(head, cx, cy);
    trail.addColorStop(0, "rgba(51, 255, 102, 0.5)");
    trail.addColorStop(0.01, "rgba(51, 255, 102, 0)");
    trail.addColorStop(0.88, "rgba(51, 255, 102, 0)");
    trail.addColorStop(0.95, "rgba(51, 255, 102, 0.1)");
    trail.addColorStop(0.99, "rgba(51, 255, 102, 0.28)");
    trail.addColorStop(1, "rgba(51, 255, 102, 0.5)");
    ctx.fillStyle = trail;
    ctx.fillRect(cx - ringR - 4, cy - ringR - 4, (ringR + 4) * 2, (ringR + 4) * 2);
    ctx.translate(cx, cy);
    ctx.rotate(head);
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(ringR, 0);
    ctx.strokeStyle = "rgba(0, 0, 0, 0.78)";
    ctx.lineWidth = 5;
    ctx.stroke();
    ctx.strokeStyle = "#33FF66";
    ctx.lineWidth = 2.2;
    if (!this.liteSweep) {
      ctx.shadowColor = "rgba(0, 0, 0, 0.65)";
      ctx.shadowBlur = 3;
    }
    ctx.stroke();
    ctx.restore();
    if (this.liteSweep) return;
    for (const aircraft of scene.aircraft) {
      const { dx, dy } = this.worldDelta(aircraft.lat, aircraft.lon, scene.centerLat, scene.centerLon, z, pxPerWorld);
      const spot = this.toScreen(dx, dy, scene.mapUpDeg, cx, cy);
      if (Math.hypot(spot.x - cx, spot.y - cy) > ringR) continue;
      const bearing = Math.atan2(spot.y - cy, spot.x - cx);
      let behind = (head - bearing) % (Math.PI * 2);
      if (behind < 0) behind += Math.PI * 2;
      const flash = Math.exp(-behind / 0.65);
      if (flash < 0.08) continue;
      const glow = ctx.createRadialGradient(spot.x, spot.y, 0, spot.x, spot.y, 18);
      glow.addColorStop(0, `rgba(51, 255, 102, ${0.9 * flash})`);
      glow.addColorStop(1, "rgba(51, 255, 102, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(spot.x, spot.y, 18, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  private drawTiles(
    ctx: CanvasRenderingContext2D,
    tiles: TileGetter,
    kind: "map" | "weather",
    style: string,
    z: number,
    pxPerWorld: number,
    lat: number,
    lon: number,
    radius: number,
    labels: boolean,
  ): number {
    if (pxPerWorld <= 0) return 0;
    const world = 256 * 2 ** z;
    const center = project(lat, lon);
    const cpx = center.x * world;
    const cpy = center.y * world;
    const reach = radius / pxPerWorld + 4;
    const minX = Math.floor((cpx - reach) / 256);
    const maxX = Math.floor((cpx + reach) / 256);
    const minY = Math.max(0, Math.floor((cpy - reach) / 256));
    const maxY = Math.min(2 ** z - 1, Math.floor((cpy + reach) / 256));
    const span = 2 ** z;
    const size = 256 * pxPerWorld + 0.6;
    let drawn = 0;
    let requested = 0;
    for (let ty = minY; ty <= maxY; ty += 1) {
      for (let tx = minX; tx <= maxX; tx += 1) {
        requested += 1;
        if (requested > 64) return drawn;
        const wrapped = ((tx % span) + span) % span;
        const image = tiles({ kind, style, z, x: wrapped, y: ty, labels });
        if (!image) {
          this.plateIncomplete = true;
          continue;
        }
        const dx = (tx * 256 - cpx) * pxPerWorld;
        const dy = (ty * 256 - cpy) * pxPerWorld;
        ctx.drawImage(image, dx, dy, size, size);
        drawn += 1;
      }
    }
    return drawn;
  }

  private worldDelta(lat: number, lon: number, centerLat: number, centerLon: number, z: number, pxPerWorld: number): { dx: number; dy: number } {
    const world = 256 * 2 ** z;
    const c = project(centerLat, centerLon);
    const p = project(lat, lon);
    return {
      dx: (p.x - c.x) * world * pxPerWorld,
      dy: (p.y - c.y) * world * pxPerWorld,
    };
  }

  private toScreen(dx: number, dy: number, mapUp: number, cx: number, cy: number): { x: number; y: number } {
    const a = (-mapUp * Math.PI) / 180;
    return {
      x: cx + dx * Math.cos(a) - dy * Math.sin(a),
      y: cy + dx * Math.sin(a) + dy * Math.cos(a),
    };
  }

  private drawTrails(ctx: CanvasRenderingContext2D, scene: RadarScene, z: number, pxPerWorld: number): void {
    if (!scene.trails.length) return;
    ctx.save();
    ctx.lineCap = "round";
    for (const trail of scene.trails) {
      for (let index = 1; index < trail.points.length; index += 1) {
        const prev = trail.points[index - 1];
        const point = trail.points[index];
        const a = this.worldDelta(prev.lat, prev.lon, scene.centerLat, scene.centerLon, z, pxPerWorld);
        const b = this.worldDelta(point.lat, point.lon, scene.centerLat, scene.centerLon, z, pxPerWorld);
        ctx.beginPath();
        ctx.moveTo(a.dx, a.dy);
        ctx.lineTo(b.dx, b.dy);
        // Fades from the aircraft back to the oldest point. 1.0.3: wider and
        // brighter so it reads on the 720 px glass at arm's length.
        const alpha = trailAlpha(point.age).toFixed(3);
        ctx.strokeStyle = scene.style === "light" ? `rgba(20, 50, 40, ${alpha})` : `rgba(150, 255, 200, ${alpha})`;
        ctx.lineWidth = 2.2;
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  private drawAircraftIcons(ctx: CanvasRenderingContext2D, scene: RadarScene, z: number, pxPerWorld: number, now: number, emergencyOnly: boolean): void {
    for (const aircraft of scene.aircraft) {
      const emergency = Boolean(aircraft.emergency);
      if (emergencyOnly !== emergency) continue;
      const { dx, dy } = this.worldDelta(aircraft.lat, aircraft.lon, scene.centerLat, scene.centerLon, z, pxPerWorld);
      const dist = Math.hypot(dx, dy);
      if (!Number.isFinite(dist) || dist > this.outerRing) continue;
      ctx.save();
      ctx.translate(dx, dy);
      // A missing or junk track draws nose-up instead of a NaN transform (which paints nothing).
      const track = typeof aircraft.track === "number" && Number.isFinite(aircraft.track) ? aircraft.track : 0;
      ctx.rotate((track * Math.PI) / 180);
      const selected = aircraft.id === scene.selectedId;
      const flashOn = emergency && (scene.capture || Math.floor(now / 500) % 2 === 0);
      if (selected) {
        ctx.beginPath();
        ctx.arc(0, 0, 16, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(232, 162, 58, 0.95)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      } else if (scene.watchOn && !emergency) {
        ctx.beginPath();
        ctx.arc(0, 0, 15, 0, Math.PI * 2);
        ctx.strokeStyle = "#3DDCFF";
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }
      paintAircraftIcon(ctx, aircraft.kind ?? "unknown", scene.iconSet, {
        fill: flashOn ? "#e10600" : "#ffffff",
        military: Boolean(aircraft.military) && !emergency,
        emergency: flashOn,
        mark: aircraft.mark as MaverickMark | undefined,
      });
      ctx.restore();
    }
  }

  private drawRings(ctx: CanvasRenderingContext2D, cx: number, cy: number, ringR: number, scene: RadarScene): void {
    const scope = scene.style === "scope";
    ctx.save();
    ctx.font = '600 11px "IBM Plex Mono", ui-monospace, monospace';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const distances = ringDistances(scene.rangeNm, scene.rings ?? 4);
    const showLabel = ringLabelMask(distances.length, ringR);
    distances.forEach((nm, index) => {
      const r = (ringR * (index + 1)) / distances.length;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      const outer = index === distances.length - 1;
      if (scope) {
        ctx.strokeStyle = outer ? "rgba(130, 255, 190, 0.85)" : "rgba(80, 255, 170, 0.38)";
        ctx.lineWidth = outer ? 1.6 : 1;
        ctx.stroke();
      } else {
        ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
        ctx.lineWidth = 2.4;
        ctx.stroke();
        ctx.strokeStyle = scene.style === "light" ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.78)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      if (!showLabel[index]) return;
      const label = formatRing(nm);
      const ang = (-55 * Math.PI) / 180;
      const labelR = Math.max(12, r - 12);
      const x = cx + labelR * Math.sin(ang);
      const y = cy - labelR * Math.cos(ang);
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(0,0,0,0.72)";
      ctx.strokeText(label, x, y);
      ctx.fillStyle = scope ? "#b8ffd4" : "#f4f7fb";
      ctx.fillText(label, x, y);
    });
    ctx.restore();
  }

  private drawCompass(ctx: CanvasRenderingContext2D, cx: number, cy: number, ringR: number, mapUp: number, scope: boolean): void {
    const names: Record<number, string> = { 0: "N", 90: "E", 180: "S", 270: "W" };
    ctx.save();
    ctx.font = '600 13px "IBM Plex Sans", sans-serif';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    for (let deg = 0; deg < 360; deg += 10) {
      const screen = (deg - mapUp) * (Math.PI / 180);
      const inner = deg % 90 === 0 ? ringR + 1 : deg % 30 === 0 ? ringR + 4 : ringR + 6;
      const outer = Math.min(ringR + 10, ringR + (Math.min(this.w, this.h) / 2) * 0.9 - ringR - 4);
      ctx.beginPath();
      ctx.moveTo(cx + inner * Math.sin(screen), cy - inner * Math.cos(screen));
      ctx.lineTo(cx + outer * Math.sin(screen), cy - outer * Math.cos(screen));
      ctx.strokeStyle = deg === 0 ? "#e8a23a" : scope ? "rgba(150,255,200,0.55)" : "rgba(255,255,255,0.72)";
      ctx.stroke();
      const name = names[deg];
      if (!name) continue;
      // 1.0.3: the − / range / + selector sits at 12 o'clock; a cardinal letter
      // there would peek out behind the pill, so it is left off (the amber
      // north tick above the ring still marks north).
      if (Math.abs(angleFromTop(deg - mapUp)) < TOP_PILL_HALF_DEG) continue;
      const lx = cx + (ringR - 18) * Math.sin(screen);
      const ly = cy - (ringR - 18) * Math.cos(screen);
      ctx.strokeStyle = "rgba(0,0,0,0.75)";
      ctx.strokeText(name, lx, ly);
      ctx.fillStyle = deg === 0 ? "#ffcc6a" : scope ? "#d8ffe8" : "#f7fbff";
      ctx.fillText(name, lx, ly);
    }
    ctx.restore();
  }

  private drawHome(
    ctx: CanvasRenderingContext2D,
    scene: RadarScene,
    z: number,
    pxPerWorld: number,
    cx: number,
    cy: number,
  ): void {
    const { dx, dy } = this.worldDelta(scene.homeLat, scene.homeLon, scene.centerLat, scene.centerLon, z, pxPerWorld);
    const p = this.toScreen(dx, dy, scene.mapUpDeg, cx, cy);
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(Math.PI / 4);
    ctx.fillStyle = "#e8a23a";
    ctx.strokeStyle = "rgba(0,0,0,0.8)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.rect(-5, -5, 10, 10);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    ctx.font = '600 11px "IBM Plex Sans", sans-serif';
    ctx.textAlign = "center";
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(0,0,0,0.75)";
    ctx.strokeText(fitText(ctx, scene.homeName, 72), p.x, p.y + 16);
    ctx.fillStyle = "#ffcc6a";
    ctx.fillText(fitText(ctx, scene.homeName, 72), p.x, p.y + 16);
  }

  private drawLabelsAndHits(
    ctx: CanvasRenderingContext2D,
    scene: RadarScene,
    z: number,
    pxPerWorld: number,
    cx: number,
    cy: number,
    ringR: number,
    now: number,
  ): void {
    const hud = this.bottomHudBox();
    type LabelDraft = {
      id: string;
      x: number;
      y: number;
      w: number;
      h: number;
      selected: boolean;
      emergency: boolean;
      distNm: number;
      line1: string;
      line2: string;
      stale: boolean;
    };
    const drafts: LabelDraft[] = [];
    const ranked = [...scene.aircraft, ...(scene.beyond ?? [])].sort((a, b) => {
      const da = haversineNm(scene.centerLat, scene.centerLon, a.lat, a.lon);
      const db = haversineNm(scene.centerLat, scene.centerLon, b.lat, b.lon);
      return da - db;
    });
    for (const aircraft of ranked) {
      const { dx, dy } = this.worldDelta(aircraft.lat, aircraft.lon, scene.centerLat, scene.centerLon, z, pxPerWorld);
      const screen = this.toScreen(dx, dy, scene.mapUpDeg, cx, cy);
      const distPx = Math.hypot(dx, dy);
      const distNm = haversineNm(scene.centerLat, scene.centerLon, aircraft.lat, aircraft.lon);
      if (distNm > scene.rangeNm && distNm < scene.rangeNm * 1.45) {
        const brg = bearingDeg(scene.centerLat, scene.centerLon, aircraft.lat, aircraft.lon);
        const ang = ((brg - scene.mapUpDeg) * Math.PI) / 180;
        const emergency = Boolean(aircraft.emergency) && (scene.capture || Math.floor(now / 500) % 2 === 0);
        this.drawOutsideTick(ctx, cx, cy, ringR, ang, emergency ? "#e10600" : "#ffffff");
        continue;
      }
      if (distPx > ringR) continue;
      this.spots.push({ id: aircraft.id, x: screen.x, y: screen.y });
      const selected = aircraft.id === scene.selectedId;
      const stale = (aircraft.seenSec ?? 0) > 25;
      const line1 = aircraft.callsign;
      // 1.0.3: altitude always in the block ("3,400 ft", "FL340", "GND"), with
      // the climb/descent arrow and ground speed after it.
      const line2 = dataBlockLine(aircraft.altFt, aircraft.ground, aircraft.vsFpm, aircraft.gsKt, scene.units);
      ctx.font = '500 11px "IBM Plex Mono", ui-monospace, monospace';
      const boxW = Math.min(118, Math.max(86, Math.ceil(ctx.measureText(line2).width) + 14));
      const boxH = 30;
      drafts.push({
        id: aircraft.id,
        x: screen.x,
        y: screen.y,
        w: boxW,
        h: boxH,
        selected,
        emergency: Boolean(aircraft.emergency),
        distNm,
        line1,
        line2,
        stale,
      });
    }
    const placed = placeLabels(drafts, {
      cx,
      cy,
      radius: ringR - 4,
      obstacles: hud ? [hud] : [],
      memory: this.labelMemory,
    });
    const byId = new Map(placed.map((item) => [item.id, item]));
    for (const draft of drafts) {
      const result = byId.get(draft.id);
      if (!result) continue;
      const box = result.box;
      ctx.save();
      if (result.leader) {
        const tip = leaderAnchor(draft.x, draft.y, box);
        ctx.beginPath();
        ctx.moveTo(draft.x, draft.y);
        ctx.lineTo(tip.x, tip.y);
        ctx.strokeStyle = draft.selected ? "rgba(232, 162, 58, 0.7)" : "rgba(255, 255, 255, 0.35)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.globalAlpha = draft.stale ? 0.45 : 1;
      roundRect(ctx, box.x, box.y, box.w, box.h, 6);
      ctx.fillStyle = draft.selected ? "rgba(42, 28, 8, 0.92)" : "rgba(6, 10, 14, 0.82)";
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = draft.selected ? "#e8a23a" : "rgba(255,255,255,0.14)";
      ctx.stroke();
      ctx.font = '600 12px "IBM Plex Sans", sans-serif';
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillStyle = "#f4f7fb";
      ctx.fillText(fitText(ctx, draft.line1, box.w - 10), box.x + 6, box.y + 3);
      ctx.font = '500 11px "IBM Plex Mono", ui-monospace, monospace';
      ctx.fillStyle = "#ffffff";
      ctx.fillText(fitText(ctx, draft.line2, box.w - 10), box.x + 6, box.y + 16);
      ctx.restore();
    }
  }

  private bottomHudBox(): Box | null {
    const canvas = this.canvas.getBoundingClientRect();
    if (canvas.width < 2 || canvas.height < 2) return null;
    const scaleX = this.w / canvas.width;
    const scaleY = this.h / canvas.height;
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    let any = false;
    for (const id of ["status", "clock", "metar"]) {
      const el = document.getElementById(id);
      if (!el || el.hidden) continue;
      const style = getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const rect = el.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) continue;
      any = true;
      left = Math.min(left, rect.left);
      top = Math.min(top, rect.top);
      right = Math.max(right, rect.right);
      bottom = Math.max(bottom, rect.bottom);
    }
    if (!any) return null;
    const pad = 4;
    return {
      x: (left - canvas.left) * scaleX - pad,
      y: (top - canvas.top) * scaleY - pad,
      w: (right - left) * scaleX + pad * 2,
      h: (bottom - top) * scaleY + pad * 2,
    };
  }

  private drawSelectionLine(
    ctx: CanvasRenderingContext2D,
    scene: RadarScene,
    z: number,
    pxPerWorld: number,
    cx: number,
    cy: number,
  ): void {
    if (!scene.selectedId) return;
    const selected = scene.aircraft.find((item) => item.id === scene.selectedId);
    if (!selected) return;
    const { dx, dy } = this.worldDelta(selected.lat, selected.lon, scene.centerLat, scene.centerLon, z, pxPerWorld);
    const screen = this.toScreen(dx, dy, scene.mapUpDeg, cx, cy);
    ctx.save();
    ctx.setLineDash([3, 4]);
    ctx.strokeStyle = "rgba(232, 162, 58, 0.85)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(screen.x, screen.y);
    ctx.stroke();
    ctx.restore();
  }

  private drawOutsideTick(ctx: CanvasRenderingContext2D, cx: number, cy: number, ringR: number, ang: number, color: string): void {
    const x = cx + ringR * Math.sin(ang);
    const y = cy - ringR * Math.cos(ang);
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(ang);
    ctx.beginPath();
    ctx.moveTo(0, -7);
    ctx.lineTo(4, 4);
    ctx.lineTo(-4, 4);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.restore();
  }
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function fitText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let trimmed = text;
  while (trimmed.length > 1 && ctx.measureText(`${trimmed}…`).width > maxWidth) trimmed = trimmed.slice(0, -1);
  return `${trimmed}…`;
}

/** Half-width, in degrees either side of 12 o'clock, of the top range selector over the compass letters. */
export const TOP_PILL_HALF_DEG = 22;

/** Screen angle from 12 o'clock in -180..180 degrees. */
export function angleFromTop(screenDeg: number): number {
  return ((((screenDeg % 360) + 540) % 360) - 180);
}
