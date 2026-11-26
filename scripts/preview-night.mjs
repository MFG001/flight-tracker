/**
 * Render setup-page previews of the NIGHT card (sunrise/sunset vs fixed hours).
 * Usage: node scripts/preview-night.mjs [setupUrl] [outDir]
 * Uses the live demo server for /api/solar; sample ZIP 10001 only.
 */
import path from "path";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] ?? "http://127.0.0.1:8832").replace(/\/$/, "");
const outDir = process.argv[3] ?? path.resolve(".");
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome";
const setupUrl = /setup/i.test(base) ? base : `${base}/setup`;

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
});

async function prepare(page, state) {
  await page.goto(setupUrl, { waitUntil: "networkidle0", timeout: 30000 });
  await page.waitForFunction(() => document.getElementById("night-mode"), { timeout: 15000 });
  await page.addStyleTag({ content: `
    p.lead, .preview, #login { display: none !important; }
    #app > .card:not(#night) { display: none !important; }
    main { padding: 80px 8px 0 !important; }
  `});
  await page.evaluate(() => {
    document.getElementById("login")?.classList.add("hidden");
    document.getElementById("app")?.classList.remove("hidden");
  });
  await page.evaluate((s) => {
    const set = (id, v) => { const el = document.getElementById(id); if (el) { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); } };
    document.getElementById(s.loc === "ll" ? "night-loc-ll" : "night-loc-zip")?.click();
    set("night-zip", s.zip ?? "");
    set("night-lat", s.lat ?? "");
    set("night-lon", s.lon ?? "");
    set("night-from", "2200");
    set("night-to", "0600");
    const mode = document.getElementById("night-mode");
    mode.value = s.mode;
    mode.dispatchEvent(new Event("change", { bubbles: true }));
  }, state);
  if (state.mode === "sun" && state.expect) {
    await page.waitForFunction((re) => new RegExp(re).test(document.getElementById("night-sun-times")?.textContent || ""), { timeout: 10000 }, state.expect);
  }
  await page.evaluate((mode) => {
    const scroller = document.querySelector("#night .round-scroll");
    if (!scroller) return;
    if (mode !== "sun") { scroller.scrollTop = 0; return; }
    const times = document.getElementById("night-sun-times");
    if (!times) return;
    // Keep the heading and the computed-times line in the inscribed area.
    const s = scroller.getBoundingClientRect();
    const r = times.getBoundingClientRect();
    const overflow = r.bottom - (s.top + s.height * 0.86);
    if (overflow > 0) scroller.scrollTop += overflow;
  }, state.mode);
  await new Promise((r) => setTimeout(r, 250));
}

const SHOTS = [
  { name: "night-sun-zip", mode: "sun", loc: "zip", zip: "10001", expect: "dim at sunset \\d\\d:\\d\\d" },
  { name: "night-sun-nozip", mode: "sun", loc: "zip", zip: "", expect: "Enter your ZIP code" },
  { name: "night-sun-coords", mode: "sun", loc: "ll", lat: "51.5000", lon: "-0.1200", expect: "dim at sunset" },
  { name: "night-schedule", mode: "schedule", loc: "zip", zip: "" },
];

try {
  for (const shot of SHOTS) {
    const glass = await browser.newPage();
    await glass.setViewport({ width: 720, height: 720, deviceScaleFactor: 1, hasTouch: true });
    await prepare(glass, shot);
    const card = await glass.$("#night");
    await card.screenshot({ path: path.join(outDir, `${shot.name}-720-raw.png`) });
    await glass.close();

    const phone = await browser.newPage();
    await phone.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
    await prepare(phone, shot);
    await phone.evaluate(() => document.getElementById("night")?.scrollIntoView({ block: "start" }));
    await phone.screenshot({ path: path.join(outDir, `${shot.name}-phone.png`) });
    await phone.close();
  }
  console.log("wrote night previews to", outDir);
} finally {
  await browser.close();
}
