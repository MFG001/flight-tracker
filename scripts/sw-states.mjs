// Software card states for 1.0.4 previews and the safe-circle check.
const MB = 1024 * 1024;
const base = {
  version: "1.0.3", auto: false,
  url: "https://github.com/MFG001/flight-tracker/releases/latest/download/manifest.json",
  repo: "MFG001/flight-tracker", source: "github.com/MFG001/flight-tracker", keyFingerprints: ["2D7C 0580 0B69 E5EA"],
  checkedAt: "2026-11-20T04:50:00Z", error: "", detail: "", stage: "", step: 0, steps: 0,
  target: "", received: 0, total: 0, installedAt: "",
};
export const SW_STATES = {
  available: { ...base, state: "available", available: true, latest: "1.0.4",
    notes: "Software updates now show each step live, and the saved key stays saved." },
  installing: { ...base, state: "installing", stage: "downloading", step: 2, steps: 4, target: "1.0.4",
    latest: "1.0.4", available: true, received: 24 * MB, total: 71 * MB,
    detail: "Downloading Version 1.0.4 (24 / 71 MB)..." },
  complete: { ...base, version: "1.0.4", state: "installed", stage: "complete", latest: "1.0.4",
    available: false, installedAt: "2026-11-20T04:53:10Z", detail: "Update complete. Now running Version 1.0.4." },
  // 1.0.7 prototype: LATER was tapped on the round screen.
  scheduled: { ...base, version: "1.0.6", state: "available", available: true, latest: "1.0.7",
    notes: "Update prompt on the round screen with Update now or Later, and weather radar status on standby.",
    laterAt: "02:00", laterTz: "America/New_York", laterZone: "ET", laterLabel: "2:00 AM ET",
    schedule: { version: "1.0.7", label: "2:00 AM ET", day: "tomorrow", zone: "America/New_York", source: "later" } },
  failed: { ...base, state: "rolled-back", stage: "failed", latest: "1.0.4", available: true,
    error: "Update to Version 1.0.4 failed.", detail: "Update failed and rolled back to Version 1.0.3." },
};
