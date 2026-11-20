import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = resolve(root, "docs/screenshots");
const base = process.env.FLIGHT_TRACKER_URL ?? "http://127.0.0.1:8741";
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome-stable";
const backgrounds = ["dark", "light", "satellite", "sectional", "scope"];

await mkdir(outDir, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 848, height: 848, deviceScaleFactor: 2 });
  for (const background of backgrounds) {
    for (const wx of [0, 1]) {
      const name = wx ? `${background}-wx` : background;
      const url = `${base}/?capture=1&bg=${background}&wx=${wx}`;
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForFunction(() => window.__ftReady === true, { timeout: 25000 });
      await new Promise((resolveWait) => setTimeout(resolveWait, 400));
      const file = resolve(outDir, `${name}.png`);
      await page.screenshot({ path: file, type: "png" });
      console.log(file);
    }
  }
} finally {
  await browser.close();
}
