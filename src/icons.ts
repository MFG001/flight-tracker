import type { AircraftKind } from "./types";
import paths from "./maverick-paths.json";

/** Maverick is the only aircraft icon set. */
export type IconSetId = "maverick";

export type MaverickMark = "light" | "twin" | "bizjet" | "heavy" | "fighter" | "rotor" | "lighter" | "drone" | "unknown";

export const MAVERICK_LEGEND: { mark: MaverickMark; kind: AircraftKind; label: string }[] = [
  { mark: "light", kind: "light", label: "Light" },
  { mark: "twin", kind: "light", label: "Twin" },
  { mark: "bizjet", kind: "jet", label: "Business/Regional" },
  { mark: "heavy", kind: "jet", label: "Airliner/Heavy" },
  { mark: "fighter", kind: "jet", label: "Fighter" },
  { mark: "rotor", kind: "rotor", label: "Helicopter" },
  { mark: "lighter", kind: "lighter", label: "Airship" },
  { mark: "drone", kind: "uav", label: "Drone" },
  { mark: "unknown", kind: "unknown", label: "Unknown" },
];

export const ICON_KINDS: AircraftKind[] = ["jet", "light", "rotor", "uav", "lighter", "unknown"];

const MAVERICK_PATHS: Record<Exclude<MaverickMark, "rotor" | "lighter" | "unknown">, string> = paths;

/** Longest side of the source art is 92. On the glass that side is 28 px. */
const MAVERICK_SCALE = 28 / 92;

/** Helicopter icons are drawn 22% larger than the other kinds. */
export const ROTOR_ICON_SCALE = 1.22;
/** Airborne main-rotor rate, revolutions per second. */
export const ROTOR_RPS_AIR = 1;
/** Grounded helicopters keep a slow idle spin so the rotor still reads as a rotor. */
export const ROTOR_RPS_GROUND = 0.25;

export function rotorAngle(nowMs: number, ground: boolean): number {
  const rps = ground ? ROTOR_RPS_GROUND : ROTOR_RPS_AIR;
  return ((nowMs / 1000) * rps * Math.PI * 2) % (Math.PI * 2);
}

export function iconSetId(_value: string | null | undefined): IconSetId {
  return "maverick";
}

export function paintAircraftIcon(
  ctx: CanvasRenderingContext2D,
  kind: AircraftKind,
  _set: IconSetId,
  options: { fill: string; military: boolean; emergency: boolean; mark?: MaverickMark; rotorRad?: number },
): void {
  const dark = "rgba(10, 16, 22, 0.94)";
  const accent = options.emergency ? "#e10600" : options.military ? "#14944A" : dark;
  const mark = options.mark ?? markFromKind(kind);
  ctx.save();
  if (kind === "rotor" || mark === "rotor") {
    ctx.scale(ROTOR_ICON_SCALE, ROTOR_ICON_SCALE);
  }
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  drawMaverick(ctx, mark);
  ctx.fillStyle = options.fill;
  ctx.fill("nonzero");
  ctx.lineWidth = 1.35;
  ctx.strokeStyle = dark;
  ctx.stroke();
  if (accent !== dark) {
    ctx.lineWidth = 2.15;
    ctx.strokeStyle = accent;
    ctx.stroke();
  }
  if (kind === "rotor" || mark === "rotor") {
    paintRotorBlades(ctx, options.rotorRad ?? 0, accent, dark);
  }
  ctx.restore();
}

function markFromKind(kind: AircraftKind): MaverickMark {
  if (kind === "light") return "light";
  if (kind === "jet") return "heavy";
  if (kind === "rotor") return "rotor";
  if (kind === "uav") return "drone";
  if (kind === "lighter") return "lighter";
  return "unknown";
}

function drawMaverick(ctx: CanvasRenderingContext2D, mark: MaverickMark): void {
  if (mark === "rotor") {
    drawMaverickRotor(ctx);
    return;
  }
  if (mark === "lighter") {
    drawMaverickAirship(ctx);
    return;
  }
  if (mark === "unknown") {
    drawDiamond(ctx);
    return;
  }
  traceMaverickPath(ctx, MAVERICK_PATHS[mark]);
}

function traceMaverickPath(ctx: CanvasRenderingContext2D, d: string): void {
  const tokens = d.match(/[MLCZ]|-?(?:\d+\.\d+|\d+|\.\d+)/gi);
  if (!tokens) return;
  let index = 0;
  let command = "";
  let cx = 0;
  let cy = 0;
  let sx = 0;
  let sy = 0;
  const take = () => parseFloat(tokens[index += 1, index - 1]) * MAVERICK_SCALE;
  while (index < tokens.length) {
    const token = tokens[index];
    if (/^[MLCZ]$/i.test(token)) {
      command = token.toUpperCase();
      index += 1;
      if (command === "Z") {
        ctx.closePath();
        cx = sx;
        cy = sy;
        continue;
      }
    }
    if (command === "M") {
      cx = take();
      cy = take();
      ctx.moveTo(cx, cy);
      sx = cx;
      sy = cy;
      command = "L";
    } else if (command === "L") {
      cx = take();
      cy = take();
      ctx.lineTo(cx, cy);
    } else if (command === "C") {
      const x1 = take();
      const y1 = take();
      const x2 = take();
      const y2 = take();
      const x = take();
      const y = take();
      ctx.bezierCurveTo(x1, y1, x2, y2, x, y);
      cx = x;
      cy = y;
    }
  }
}

/** Helicopter fuselage used by Maverick (unchanged from the previous Linecut body). */
function drawMaverickRotor(ctx: CanvasRenderingContext2D): void {
  ctx.moveTo(0, -7.6);
  ctx.bezierCurveTo(3.3, -7.6, 3.5, -3.2, 3.1, 1.2);
  ctx.lineTo(1.25, 3.2);
  ctx.lineTo(1.05, 11.6);
  ctx.lineTo(3.6, 13);
  ctx.lineTo(3.3, 14.3);
  ctx.lineTo(0, 13.1);
  ctx.lineTo(-3.3, 14.3);
  ctx.lineTo(-3.6, 13);
  ctx.lineTo(-1.05, 11.6);
  ctx.lineTo(-1.25, 3.2);
  ctx.lineTo(-3.1, 1.2);
  ctx.bezierCurveTo(-3.5, -3.2, -3.3, -7.6, 0, -7.6);
  ctx.closePath();
}

/** Airship envelope used by Maverick (unchanged from the previous Linecut body). */
function drawMaverickAirship(ctx: CanvasRenderingContext2D): void {
  ctx.ellipse(0, -1.2, 4.7, 13, 0, 0, Math.PI * 2);
  ctx.moveTo(-1.1, 8.2);
  ctx.lineTo(-6.4, 12.6);
  ctx.lineTo(-1.15, 12.6);
  ctx.closePath();
  ctx.moveTo(1.1, 8.2);
  ctx.lineTo(6.4, 12.6);
  ctx.lineTo(1.15, 12.6);
  ctx.closePath();
}

function drawDiamond(ctx: CanvasRenderingContext2D): void {
  ctx.moveTo(0, -8);
  ctx.lineTo(6.5, 0);
  ctx.lineTo(0, 8);
  ctx.lineTo(-6.5, 0);
  ctx.closePath();
}

/** Main rotor disc (static) and blades (rotated around the hub). The hub is
 *  slightly forward of the icon origin. */
function paintRotorBlades(
  ctx: CanvasRenderingContext2D,
  angle: number,
  accent: string,
  _dark: string,
): void {
  const y = -2.4;
  const r = 11;
  ctx.beginPath();
  ctx.arc(0, y, r, 0, Math.PI * 2);
  ctx.lineWidth = 1.15;
  ctx.strokeStyle = accent;
  ctx.stroke();
  ctx.save();
  ctx.translate(0, y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(-r + 1, 0);
  ctx.lineTo(r - 1, 0);
  ctx.moveTo(0, -r + 1);
  ctx.lineTo(0, r - 1);
  ctx.lineWidth = 1.15;
  ctx.strokeStyle = accent;
  ctx.stroke();
  ctx.restore();
}
