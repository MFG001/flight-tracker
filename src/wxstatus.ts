/**
 * What the screen says about the weather radar (1.0.7). Pure logic, unit-tested.
 *
 * 1.0.6 only spoke up when radar was broken. With radar on and working but no
 * rain inside the ring, the glass looked exactly like radar was off, which read
 * as "no weather". Now there is always a short, honest line.
 */
export interface WxInput {
  on: boolean;
  down: boolean;
  stale: boolean;
  /** Unix seconds of the radar picture on the glass, if known. */
  frameTime: number | null;
  /** Share of the ring with echoes (0..1), or null while not measured yet. */
  echoes: number | null;
  /** e.g. "20 NM". */
  range: string;
}

export interface WxSummary {
  /** Chip text, or null to hide the chip. */
  chip: string | null;
  tone: "ok" | "warn" | "bad";
  /** One line for the standby screen ("" to hide). */
  standby: string;
}

/** "1200Z" from unix seconds. */
export function zulu(seconds: number): string {
  const d = new Date(seconds * 1000);
  return `${String(d.getUTCHours()).padStart(2, "0")}${String(d.getUTCMinutes()).padStart(2, "0")}Z`;
}

export const ECHO_THRESHOLD = 0.002;

export function wxSummary(input: WxInput): WxSummary {
  if (!input.on) return { chip: null, tone: "ok", standby: "" };
  if (input.down) return { chip: "WX UNAVAILABLE", tone: "bad", standby: "Weather radar unavailable" };
  const when = input.frameTime ? zulu(input.frameTime) : "";
  if (input.stale) return { chip: "WX STALE", tone: "warn", standby: `Weather radar stale${when ? ` · ${when}` : ""}` };
  if (input.echoes === null) return { chip: when ? `WX ${when}` : "WX", tone: "ok", standby: `Weather radar on${when ? ` · ${when}` : ""}` };
  if (input.echoes < ECHO_THRESHOLD) {
    return { chip: "WX CLEAR", tone: "ok", standby: `Radar ${when ? `${when} · ` : ""}no rain within ${input.range}` };
  }
  return { chip: when ? `WX ${when}` : "WX", tone: "ok", standby: `Radar ${when ? `${when} · ` : ""}rain within ${input.range}` };
}
