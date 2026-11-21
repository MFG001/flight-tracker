import type { AircraftKind } from "./types";
import paths from "./maverick-paths.json";

/** Maverick is the set on the glass. Linecut, Classic, Planform, and Compact stay selectable. */
export type IconSetId = "classic" | "planform" | "compact" | "linecut" | "maverick";

export type MaverickMark = "light" | "twin" | "bizjet" | "heavy" | "fighter" | "rotor" | "lighter" | "drone" | "unknown";

export const ICON_SETS: { id: IconSetId; label: string }[] = [
  { id: "maverick", label: "Maverick (default)" },
  { id: "linecut", label: "Linecut" },
  { id: "classic", label: "Classic" },
  { id: "planform", label: "Planform" },
  { id: "compact", label: "Compact" },
];

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

/** Helicopter icons are drawn 22% larger than the other kinds, in every set. */
export const ROTOR_ICON_SCALE = 1.22;

export function iconSetId(value: string | null | undefined): IconSetId {
  if (value === "silhouette") return "linecut";
  if (value === "planform" || value === "compact" || value === "linecut" || value === "classic" || value === "maverick") return value;
  return "maverick";
}

export function paintAircraftIcon(
  ctx: CanvasRenderingContext2D,
  kind: AircraftKind,
  set: IconSetId,
  options: { fill: string; military: boolean; emergency: boolean; mark?: MaverickMark },
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
  if (set === "maverick") drawMaverick(ctx, mark);
  else if (set === "classic") drawClassic(ctx, kind);
  else if (set === "compact") drawCompact(ctx, kind);
  else drawPlanform(ctx, kind, set === "linecut");
  ctx.fillStyle = options.fill;
  ctx.fill(set === "linecut" && (kind === "jet" || kind === "light") ? "evenodd" : "nonzero");
  ctx.lineWidth = 1.35;
  ctx.strokeStyle = dark;
  ctx.stroke();
  if (accent !== dark) {
    ctx.lineWidth = 2.15;
    ctx.strokeStyle = accent;
    ctx.stroke();
  }
  if (set === "maverick" && mark === "rotor") {
    ctx.beginPath();
    drawDetail(ctx, "linecut", "rotor");
    ctx.lineWidth = 1.15;
    ctx.strokeStyle = accent;
    ctx.stroke();
  } else if (set !== "classic" && set !== "maverick") {
    ctx.beginPath();
    drawDetail(ctx, set, kind);
    ctx.lineWidth = 1.15;
    ctx.strokeStyle = accent;
    ctx.stroke();
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
    drawPlanform(ctx, "rotor", true);
    return;
  }
  if (mark === "lighter") {
    drawPlanform(ctx, "lighter", true);
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

function drawClassic(ctx: CanvasRenderingContext2D, kind: AircraftKind): void {
  if (kind === "rotor") {
    ctx.ellipse(0, 1, 3.2, 6.5, 0, 0, Math.PI * 2);
    ctx.moveTo(-11, -1);
    ctx.lineTo(11, -1);
    ctx.moveTo(0, -8);
    ctx.lineTo(0, 9);
    return;
  }
  if (kind === "uav") {
    ctx.arc(0, 0, 2.2, 0, Math.PI * 2);
    for (const [x, y] of [[-7, -7], [7, -7], [-7, 7], [7, 7]] as const) {
      ctx.moveTo(0, 0);
      ctx.lineTo(x, y);
      ctx.moveTo(x + 2.2, y);
      ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    }
    return;
  }
  if (kind === "lighter") {
    ctx.ellipse(0, -3, 7, 9, 0, 0, Math.PI * 2);
    ctx.moveTo(-2, 6);
    ctx.lineTo(-3.5, 11);
    ctx.lineTo(3.5, 11);
    ctx.lineTo(2, 6);
    return;
  }
  if (kind === "unknown") {
    drawDiamond(ctx);
    return;
  }
  const light = kind === "light";
  const wing = light ? 11 : 14;
  ctx.moveTo(0, light ? -11 : -14);
  ctx.lineTo(2.4, -4);
  ctx.lineTo(wing, light ? 1 : -2);
  ctx.lineTo(wing * 0.72, light ? 3 : 1);
  ctx.lineTo(2.2, 2);
  ctx.lineTo(1.6, 8);
  ctx.lineTo(light ? 4 : 6, 11);
  ctx.lineTo(0, 8);
  ctx.lineTo(light ? -4 : -6, 11);
  ctx.lineTo(-1.6, 8);
  ctx.lineTo(-2.2, 2);
  ctx.lineTo(-wing * 0.72, light ? 3 : 1);
  ctx.lineTo(-wing, light ? 1 : -2);
  ctx.lineTo(-2.4, -4);
  ctx.closePath();
  if (light) {
    ctx.moveTo(-2.5, -11);
    ctx.arc(0, -11, 2.5, Math.PI, 0);
  }
}

function drawPlanform(ctx: CanvasRenderingContext2D, kind: AircraftKind, cut: boolean): void {
  if (kind === "jet") {
    ctx.moveTo(0, -15);
    ctx.bezierCurveTo(1.6, -14.2, 2.35, -9.5, 2.35, -4.5);
    ctx.lineTo(13.6, 1.2);
    ctx.lineTo(11.5, 5.6);
    ctx.lineTo(2.25, 1.5);
    ctx.lineTo(1.7, 7.2);
    ctx.lineTo(6.5, 10.5);
    ctx.lineTo(5.3, 12.7);
    ctx.lineTo(0, 10.5);
    ctx.lineTo(-5.3, 12.7);
    ctx.lineTo(-6.5, 10.5);
    ctx.lineTo(-1.7, 7.2);
    ctx.lineTo(-2.25, 1.5);
    ctx.lineTo(-11.5, 5.6);
    ctx.lineTo(-13.6, 1.2);
    ctx.lineTo(-2.35, -4.5);
    ctx.bezierCurveTo(-2.35, -9.5, -1.6, -14.2, 0, -15);
    ctx.closePath();
  } else if (kind === "light") {
    ctx.moveTo(0, -12.5);
    ctx.lineTo(1.55, -7.5);
    ctx.lineTo(1.55, -1.4);
    ctx.lineTo(12.6, -1.4);
    ctx.lineTo(12.6, 2.7);
    ctx.lineTo(1.5, 2.7);
    ctx.lineTo(1.35, 7.4);
    ctx.lineTo(4.8, 9.7);
    ctx.lineTo(3.9, 11.5);
    ctx.lineTo(0, 9.8);
    ctx.lineTo(-3.9, 11.5);
    ctx.lineTo(-4.8, 9.7);
    ctx.lineTo(-1.35, 7.4);
    ctx.lineTo(-1.5, 2.7);
    ctx.lineTo(-12.6, 2.7);
    ctx.lineTo(-12.6, -1.4);
    ctx.lineTo(-1.55, -1.4);
    ctx.lineTo(-1.55, -7.5);
    ctx.closePath();
  } else if (kind === "rotor") {
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
  } else if (kind === "uav") {
    ctx.moveTo(0, -4.4);
    ctx.lineTo(2.5, 1.8);
    ctx.lineTo(-2.5, 1.8);
    ctx.closePath();
    for (const [x, y] of [[-7.4, -7.2], [7.4, -7.2], [-7.4, 7.4], [7.4, 7.4]] as const) {
      ctx.moveTo(x + 3.1, y);
      ctx.arc(x, y, 3.1, 0, Math.PI * 2);
    }
  } else if (kind === "lighter") {
    ctx.ellipse(0, -1.2, 4.7, 13, 0, 0, Math.PI * 2);
    ctx.moveTo(-1.1, 8.2);
    ctx.lineTo(-6.4, 12.6);
    ctx.lineTo(-1.15, 12.6);
    ctx.closePath();
    ctx.moveTo(1.1, 8.2);
    ctx.lineTo(6.4, 12.6);
    ctx.lineTo(1.15, 12.6);
    ctx.closePath();
  } else {
    drawDiamond(ctx);
  }
  if (cut && (kind === "jet" || kind === "light")) {
    ctx.moveTo(1.05, -8.2);
    ctx.ellipse(0, kind === "jet" ? -6.4 : -5.6, 1.05, 2.15, 0, 0, Math.PI * 2);
  }
}

function drawCompact(ctx: CanvasRenderingContext2D, kind: AircraftKind): void {
  if (kind === "jet") {
    ctx.moveTo(0, -11.5);
    ctx.lineTo(2.8, -6);
    ctx.lineTo(12.2, -0.4);
    ctx.lineTo(10.4, 4.8);
    ctx.lineTo(2.6, 1.4);
    ctx.lineTo(2.1, 6.2);
    ctx.lineTo(6.2, 8.6);
    ctx.lineTo(5, 10.6);
    ctx.lineTo(0, 8.4);
    ctx.lineTo(-5, 10.6);
    ctx.lineTo(-6.2, 8.6);
    ctx.lineTo(-2.1, 6.2);
    ctx.lineTo(-2.6, 1.4);
    ctx.lineTo(-10.4, 4.8);
    ctx.lineTo(-12.2, -0.4);
    ctx.lineTo(-2.8, -6);
    ctx.closePath();
  } else if (kind === "light") {
    ctx.moveTo(0, -9.5);
    ctx.lineTo(2, -5);
    ctx.lineTo(2, -1.6);
    ctx.lineTo(11.4, -2.2);
    ctx.lineTo(11.4, 2.4);
    ctx.lineTo(2, 1.8);
    ctx.lineTo(1.7, 6.2);
    ctx.lineTo(4.4, 8);
    ctx.lineTo(3.6, 9.8);
    ctx.lineTo(0, 8.2);
    ctx.lineTo(-3.6, 9.8);
    ctx.lineTo(-4.4, 8);
    ctx.lineTo(-1.7, 6.2);
    ctx.lineTo(-2, 1.8);
    ctx.lineTo(-11.4, 2.4);
    ctx.lineTo(-11.4, -2.2);
    ctx.lineTo(-2, -1.6);
    ctx.lineTo(-2, -5);
    ctx.closePath();
  } else if (kind === "rotor") {
    ctx.moveTo(0, -6.2);
    ctx.bezierCurveTo(3.6, -6.2, 3.8, -2, 3.2, 1.6);
    ctx.lineTo(1.4, 3);
    ctx.lineTo(1.2, 8.6);
    ctx.lineTo(3.8, 10);
    ctx.lineTo(3.4, 11.4);
    ctx.lineTo(0, 10.2);
    ctx.lineTo(-3.4, 11.4);
    ctx.lineTo(-3.8, 10);
    ctx.lineTo(-1.2, 8.6);
    ctx.lineTo(-1.4, 3);
    ctx.lineTo(-3.2, 1.6);
    ctx.bezierCurveTo(-3.8, -2, -3.6, -6.2, 0, -6.2);
    ctx.closePath();
  } else if (kind === "uav") {
    ctx.arc(0, 0, 2.6, 0, Math.PI * 2);
    for (const [x, y] of [[-5.6, -5.6], [5.6, -5.6], [-5.6, 5.6], [5.6, 5.6]] as const) {
      ctx.moveTo(x + 3.4, y);
      ctx.arc(x, y, 3.4, 0, Math.PI * 2);
    }
  } else if (kind === "lighter") {
    ctx.ellipse(0, -0.4, 6.3, 10.4, 0, 0, Math.PI * 2);
    ctx.moveTo(-1.4, 6.4);
    ctx.lineTo(-7.2, 10.6);
    ctx.lineTo(-1.3, 10.8);
    ctx.closePath();
    ctx.moveTo(1.4, 6.4);
    ctx.lineTo(7.2, 10.6);
    ctx.lineTo(1.3, 10.8);
    ctx.closePath();
  } else {
    drawDiamond(ctx);
  }
}

function drawDiamond(ctx: CanvasRenderingContext2D): void {
  ctx.moveTo(0, -8);
  ctx.lineTo(6.5, 0);
  ctx.lineTo(0, 8);
  ctx.lineTo(-6.5, 0);
  ctx.closePath();
}

function drawDetail(ctx: CanvasRenderingContext2D, set: IconSetId, kind: AircraftKind): void {
  if (kind === "light" && set === "compact") {
    ctx.moveTo(3.1, -9.6);
    ctx.arc(0, -9.6, 3.1, 0, Math.PI * 2);
    return;
  }
  if (kind === "rotor") {
    const y = set === "compact" ? -1.6 : -2.4;
    const r = set === "compact" ? 9.2 : 11;
    ctx.moveTo(r, y);
    ctx.arc(0, y, r, 0, Math.PI * 2);
    ctx.moveTo(-r + 1, y);
    ctx.lineTo(r - 1, y);
    ctx.moveTo(0, y - r + 1);
    ctx.lineTo(0, y + r - 1);
    return;
  }
  if (kind === "uav") {
    const arms = set === "compact"
      ? ([[-5.6, -5.6], [5.6, -5.6], [-5.6, 5.6], [5.6, 5.6]] as const)
      : ([[-7.4, -7.2], [7.4, -7.2], [-7.4, 7.4], [7.4, 7.4]] as const);
    for (const [x, y] of arms) {
      ctx.moveTo(0, 0);
      ctx.lineTo(x, y);
    }
  }
}
