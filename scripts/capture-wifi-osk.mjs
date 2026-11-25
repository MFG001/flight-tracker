/**
 * Before/after screenshots of the Wi-Fi keyboard at the 720×720 panel size.
 * Usage: node scripts/capture-wifi-osk.mjs [setupUrl] [outDir]
 */
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] ?? "http://127.0.0.1:8820").replace(/\/$/, "");
const outDir = resolve(process.argv[3] ?? "previews-keyboard");
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome";
const setupUrl = /setup/i.test(base) ? base : `${base}/setup`;
await mkdir(outDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
});
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function openWifi(page) {
  await page.goto(setupUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForFunction(() => document.getElementById("wifi-pass"), { timeout: 10000 });
  await page.evaluate(() => {
    document.documentElement.style.background = "#07090c";
    document.body.style.background = "#07090c";
    document.getElementById("login")?.classList.add("hidden");
    document.getElementById("app")?.classList.remove("hidden");
    const wifi = document.getElementById("wifi");
    if (wifi) wifi.scrollIntoView({ block: "center" });
    const pass = document.getElementById("wifi-pass");
    if (pass) {
      pass.type = "text";
      pass.value = "";
      pass.focus();
    }
  });
  await wait(250);
}

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 720, height: 720, deviceScaleFactor: 1, hasTouch: true });

  await openWifi(page);
  // Before: hide the fitted keyboard and draw a typical full-width OS keyboard
  // docked to the bottom of the 720×720 framebuffer — the keys at the lower
  // corners fall outside the round glass.
  await page.evaluate(() => {
    const osk = document.getElementById("ft-osk");
    if (osk) { osk.hidden = true; document.body.classList.remove("ft-osk-open"); }
    document.getElementById("wifi-pass")?.blur();
    const fake = document.createElement("div");
    fake.id = "ft-osk-before";
    fake.style.cssText = "position:fixed;left:0;right:0;bottom:0;height:280px;z-index:90;background:#1c1c1e;display:flex;flex-direction:column;gap:6px;padding:8px 4px 12px;box-sizing:border-box;";
    const rows = [
      "q w e r t y u i o p".split(" "),
      "a s d f g h j k l".split(" "),
      ["shift","z","x","c","v","b","n","m","delete"],
      ["?123","space","return"],
    ];
    for (const keys of rows) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;gap:5px;flex:1;";
      for (const key of keys) {
        const btn = document.createElement("div");
        const wide = key === "space" ? 5 : (key === "shift" || key === "delete" || key === "?123" || key === "return") ? 2 : 1;
        btn.textContent = key;
        btn.style.cssText = `flex:${wide};display:flex;align-items:center;justify-content:center;background:#3a3a3c;color:#fff;border-radius:6px;font:600 16px/1 sans-serif;text-transform:${key.length===1?"uppercase":"none"};font-size:${key.length===1?"18px":"13px"};`;
        row.append(btn);
      }
      fake.append(row);
    }
    document.body.append(fake);
  });
  const before = resolve(outDir, "wifi-osk-before.png");
  await page.screenshot({ path: before, type: "png" });
  console.log(before);

  await openWifi(page);
  await page.evaluate(() => document.getElementById("wifi-pass")?.focus());
  await wait(200);
  const after = resolve(outDir, "wifi-osk-after.png");
  await page.screenshot({ path: after, type: "png" });
  console.log(after);
} finally {
  await browser.close();
}

const mask = spawnSync("python3", [
  resolve(new URL(".", import.meta.url).pathname, "round-mask.py"),
  resolve(outDir, "wifi-osk-before.png"),
  resolve(outDir, "wifi-osk-after.png"),
], { stdio: "inherit" });
if (mask.status !== 0) process.exit(mask.status || 1);
