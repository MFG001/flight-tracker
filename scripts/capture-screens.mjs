// Capture review screenshots: the round display (720x720) and the setup page
// watch section at phone and desktop widths.
// Usage: node scripts/capture-screens.mjs <baseUrl> <outDir> <prefix>
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

const base = process.argv[2] ?? "http://127.0.0.1:8741";
const outDir = resolve(process.argv[3] ?? "screens");
const prefix = process.argv[4] ?? "shot";
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome";
const sections = (process.env.SECTIONS ?? "watch").split(",");
const deviceShots = process.env.DEVICE !== "0";
await mkdir(outDir, { recursive: true });
const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"] });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 720, height: 720, deviceScaleFactor: 1 });
  const device = [
    ["device-radar-watch", "/?kiosk=1&capture=1&bg=dark", null],
    ["device-idle-watch", "/?kiosk=1&capture=1&bg=dark&idle=1", null],
    ["device-traffic", "/?kiosk=1&capture=1&bg=dark", "t"],
  ];
  for (const [name, path, key] of deviceShots ? device : []) {
    await page.goto(base + path, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForFunction(() => window.__ftReady === true, { timeout: 25000 }).catch(() => undefined);
    if (key) { await page.keyboard.press(key); }
    await wait(1200);
    const file = resolve(outDir, `${prefix}-${name}.png`);
    await page.screenshot({ path: file });
    console.log(file);
  }
  for (const section of sections) for (const [label, width, height] of [["phone", 390, 844], ["desktop", 1280, 900]]) {
    await page.setViewport({ width, height, deviceScaleFactor: 1 });
    await page.goto(base + "/setup", { waitUntil: "networkidle0", timeout: 30000 });
    await wait(800);
    const box = await page.evaluate((id) => {
      const el = document.querySelector("#" + id);
      if (!el) return null;
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
    }, section);
    await wait(300);
    const file = resolve(outDir, `${prefix}-setup-${section}-${label}.png`);
    if (box) {
      const pad = 16;
      await page.screenshot({ path: file, clip: { x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: Math.min(width, box.width + pad * 2), height: box.height + pad * 2 } });
    } else {
      await page.screenshot({ path: file });
    }
    console.log(file);
  }
} finally {
  await browser.close();
}
