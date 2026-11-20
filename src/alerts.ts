/** Alert rules for the radar screen (1.0.3). Pure logic, unit-tested with node. */
import type { Aircraft, AppConfig } from "./types";

export const EMERGENCY_SQUAWKS = ["7500", "7600", "7700"];

/** Why an aircraft deserves an alert under the current settings, or "". */
export function alertReason(item: Aircraft, alerts: AppConfig["alerts"] | undefined): string {
  if (!alerts) return "";
  const squawk = item.squawk || "";
  if (alerts.emergency && (item.emergency || EMERGENCY_SQUAWKS.includes(squawk))) return "EMERGENCY";
  if (alerts.military && item.military) return "MILITARY";
  if (alerts.watch && item.watched) return "WATCH";
  return "";
}

/**
 * Raises each alert once per aircraft and reason. 1.0.2 only looked at
 * aircraft the moment they appeared, so a squawk changing to 7700 later, or a
 * setting switched on from the setup page, never alerted; and watch alerts
 * needed "show only watched" on.
 */
export class AlertTracker {
  private primed = false;
  private done = new Set<string>();

  /** Returns the alerts to show now, as [reason, callsign] pairs. */
  update(list: Aircraft[], alerts: AppConfig["alerts"] | undefined): [string, string][] {
    const out: [string, string][] = [];
    const present = new Set(list.map((item) => item.id));
    for (const item of list) {
      const reason = alertReason(item, alerts);
      if (!reason) continue;
      const key = `${item.id}|${reason}`;
      if (this.done.has(key)) continue;
      this.done.add(key);
      // Already on the glass at start: no arrival alert, except emergencies.
      if (!this.primed && reason !== "EMERGENCY") continue;
      out.push([reason, item.callsign]);
    }
    this.primed = true;
    for (const key of [...this.done]) if (!present.has(key.slice(0, key.lastIndexOf("|")))) this.done.delete(key);
    return out;
  }
}
