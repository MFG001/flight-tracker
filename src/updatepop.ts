/**
 * On-screen update prompt (1.0.7 prototype). Pure logic, unit-tested with node.
 */
import type { Aircraft } from "./types";

// Same codes as src/alerts.ts (kept import-free so node can unit-test this file).
const EMERGENCY_SQUAWKS = ["7500", "7600", "7700"];

export interface UpdateView {
  version: string;
  latest: string;
  available: boolean;
  state: string;
  stage: string;
  step: number;
  steps: number;
  target: string;
  detail: string;
  error: string;
  received: number;
  total: number;
  installedAt: string;
  laterLabel?: string;
  schedule?: { version: string; label: string; day?: string } | null;
  prompt?: { show: boolean; version: string; summary: string };
}

/** Auto-dismiss after this long without a touch; counted as LATER. */
export const PROMPT_TIMEOUT_MS = 120_000;

/**
 * The prompt waits only while an EMERGENCY (squawk 7500/7600/7700) is on the
 * glass or its alert banner is showing. Military and watch alerts do not hold
 * it (1.0.7). Queued, not dropped: the next poll asks again.
 */
export function promptAllowed(bannerText: string | null, onScope: Aircraft[]): boolean {
  if (bannerText && /^EMERGENCY\b/.test(bannerText.trim())) return false;
  return !onScope.some((item) => Boolean(item.emergency) || EMERGENCY_SQUAWKS.includes(item.squawk || ""));
}

const STAGE_STEP: Record<string, number> = { starting: 1, checking: 1, downloading: 2, verifying: 3, restarting: 4 };

export function installStep(view: Pick<UpdateView, "stage" | "step">): number {
  return Math.max(1, Math.min(4, view.step || STAGE_STEP[view.stage] || 1));
}

/** Overall progress 0..100 for the bar: each step is a quarter, downloads fill theirs by bytes. */
export function installPercent(view: Pick<UpdateView, "stage" | "step" | "received" | "total">): number {
  const step = installStep(view);
  let within = 0.15;
  if (view.stage === "downloading" && view.total > 0) within = Math.max(0, Math.min(1, view.received / view.total));
  return Math.round(((step - 1 + within) / 4) * 100);
}

export function installLine(view: Pick<UpdateView, "stage" | "step" | "detail" | "target">): string {
  const detail = (view.detail || "").trim() || `Installing Version ${view.target}...`;
  return `Step ${installStep(view)} of 4 · ${detail}`;
}

/** The install we watched has finished on the new version. */
export function installDone(view: UpdateView, target: string): boolean {
  return Boolean(target) && view.version === target && (view.state === "installed" || view.state === "current" || view.state === "");
}

export function installFailed(view: UpdateView): boolean {
  return view.state === "rolled-back" || (view.state === "error" && view.stage === "failed");
}

/** "Update scheduled for 2:00 AM ET". */
export function scheduledLine(label: string): string {
  return `Update scheduled for ${label}`;
}
