// Touch check for the round display in headless Chromium with software
// rendering (--disable-gpu), 720x720, touch emulation.
// Usage: node scripts/touch-check.mjs <baseUrl> <outDir> <prefix>
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

const base = process.argv[2] ?? "http://127.0.0.1:8741";
const outDir = resolve(process.argv[3] ?? "screens");
const prefix = process.argv[4] ?? "touch";
await mkdir(outDir, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME ?? "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-gpu-compositing", "--touch-events=enabled"],
});
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const result = {};
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 720, height: 720, hasTouch: true, isMobile: false });
  await page.goto(base + "/?kiosk=1", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__ftReady === true, { timeout: 25000 }).catch(() => undefined);
  await wait(2500);
  // 1.0.3: the rim has no tap keys; this must stay 0.
  result.edgeKeys = await page.evaluate(() => document.querySelectorAll("#screen .key, #keys").length);
  await page.screenshot({ path: resolve(outDir, `${prefix}-device-radar.png`) });
  // Hold the status line for 2 s to open the About menu.
  const sbox = await page.evaluate(() => {
    const r = document.querySelector("#status").getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.touchscreen.touchStart(sbox.x, sbox.y);
  await wait(2300);
  await page.touchscreen.touchEnd();
  await wait(500);
  result.menuOpen = await page.evaluate(() => !document.querySelector("#menu").hidden);
  await page.screenshot({ path: resolve(outDir, `${prefix}-device-menu.png`) });
  const disc = await page.evaluate(() => {
    const d = document.querySelector("#menu .disc");
    const r = d.getBoundingClientRect();
    return { top: d.scrollTop, max: d.scrollHeight - d.clientHeight, x: r.x + r.width / 2, y: r.y + r.height / 2, h: r.height };
  });
  result.menuScrollable = disc.max;
  await page.touchscreen.touchStart(disc.x, disc.y + disc.h * 0.3);
  for (let i = 1; i <= 10; i += 1) {
    await page.touchscreen.touchMove(disc.x, disc.y + disc.h * 0.3 - i * 18);
    await wait(16);
  }
  await page.touchscreen.touchEnd();
  await wait(600);
  result.menuScrollTopAfterSwipe = await page.evaluate(() => document.querySelector("#menu .disc").scrollTop);
  await page.screenshot({ path: resolve(outDir, `${prefix}-device-menu-scrolled.png`) });
  // Tap the SWEEP toggle inside the panel and see that it changes.
  const sweep = await page.evaluate(() => {
    const b = document.querySelector("#sweep-toggle");
    b.scrollIntoView({ block: "center" });
    const r = b.getBoundingClientRect();
    return { before: b.textContent, x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await wait(300);
  await page.touchscreen.tap(sweep.x, sweep.y);
  await wait(400);
  result.sweepTapBefore = sweep.before;
  result.sweepTapAfter = await page.evaluate(() => document.querySelector("#sweep-toggle").textContent);
  const touchBtn = await page.evaluate(() => {
    const b = document.querySelector("#m-touch");
    if (!b) return null;
    b.scrollIntoView({ block: "center" });
    const r = b.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  if (touchBtn) {
    await wait(300);
    await page.touchscreen.tap(touchBtn.x, touchBtn.y);
    await wait(400);
    result.touchTestOpen = await page.evaluate(() => !document.querySelector("#touchtest").hidden);
    await page.touchscreen.tap(360, 0.14 * 720);
    await wait(300);
    result.touchTestText = await page.evaluate(() => document.querySelector("#tt-text").textContent);
    await page.screenshot({ path: resolve(outDir, `${prefix}-device-touchtest.png`) });
  }
  // Close button on the menu.
  await page.goto(base + "/?kiosk=1", { waitUntil: "domcontentloaded" });
  await wait(2500);
  await page.touchscreen.tap(360, 360 + 0.445 * 720);
  await wait(400);
  const close = await page.evaluate(() => {
    const b = document.querySelector("#m-close");
    b.scrollIntoView({ block: "center" });
    const r = b.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await wait(300);
  await page.touchscreen.tap(close.x, close.y);
  await wait(400);
  result.menuClosedByCloseTap = await page.evaluate(() => document.querySelector("#menu").hidden);
} finally {
  await browser.close();
}
console.log(JSON.stringify(result, null, 1));
