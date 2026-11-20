// Capture the 1.0.4 Software card states (phone width, 2x).
// Usage: node scripts/capture-software.mjs <baseUrl> <outDir>
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";
import { SW_STATES } from "./sw-states.mjs";

const base = process.argv[2] ?? "http://127.0.0.1:8741";
const outDir = resolve(process.argv[3] ?? "previews_v104");
await mkdir(outDir, { recursive: true });
const browser = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 430, height: 900, deviceScaleFactor: 2 });
  await page.goto(base + "/setup", { waitUntil: "networkidle0" });
  await page.evaluate(() => {
    document.getElementById("app")?.classList.remove("hidden");
    document.getElementById("login")?.classList.add("hidden");
  });
  for (const [name, state] of Object.entries(SW_STATES)) {
    await page.evaluate((info) => {
      showSoftware(info);
      stopSoftwarePoll();
      const card = document.getElementById("software");
      card.scrollIntoView({ block: "center" });
      card.querySelector(".round-scroll").scrollTop = 0;
    }, state);
    await new Promise((r) => setTimeout(r, 900));
    const card = await page.$("#software");
    const file = resolve(outDir, `v104-sw-${name}.png`);
    await card.screenshot({ path: file });
    console.log(file);
  }
} finally {
  await browser.close();
}
