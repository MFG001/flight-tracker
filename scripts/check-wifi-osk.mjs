/**
 * Assert the device Wi-Fi keyboard at 720×720 sits inside the inscribed
 * circle, and that phones do not show that keyboard.
 * Usage: node scripts/check-wifi-osk.mjs [setupUrl]
 */
import puppeteer from "puppeteer-core";

const base = (process.argv[2] ?? "http://127.0.0.1:8820").replace(/\/$/, "");
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome";
const setupUrl = /setup/i.test(base) ? base : `${base}/setup`;
const MARGIN = 16; // px inside the 720 glass (radius 360)

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
});
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = false;

try {
  const page = await browser.newPage();

  await page.setViewport({ width: 720, height: 720, deviceScaleFactor: 1, hasTouch: true });
  await page.goto(setupUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForFunction(() => document.getElementById("wifi-pass"), { timeout: 10000 });
  await page.evaluate(() => {
    document.getElementById("login")?.classList.add("hidden");
    document.getElementById("app")?.classList.remove("hidden");
    document.getElementById("wifi-pass")?.focus();
  });
  await wait(200);
  const device = await page.evaluate((margin) => {
    const root = document.getElementById("ft-osk");
    const keys = [...(root?.querySelectorAll("button") || [])];
    const cx = 360, cy = 360, limit = 360 - margin;
    const outside = [];
    for (const btn of keys) {
      const r = btn.getBoundingClientRect();
      const corners = [
        [r.left, r.top], [r.right, r.top], [r.left, r.bottom], [r.right, r.bottom],
      ];
      for (const [x, y] of corners) {
        const d = Math.hypot(x - cx, y - cy);
        if (d > limit + 0.5) {
          outside.push({ key: btn.dataset.key || btn.textContent, x: +x.toFixed(1), y: +y.toFixed(1), d: +d.toFixed(1) });
        }
      }
    }
    return {
      open: !root?.hidden && document.body.classList.contains("ft-osk-open"),
      keyCount: keys.length,
      labels: keys.map((b) => (b.dataset.key || b.textContent || "").trim()),
      outside,
      inputmode: document.getElementById("wifi-pass")?.getAttribute("inputmode") || "",
    };
  }, MARGIN);
  if (!device.open) {
    console.error("720x720: keyboard did not open on password focus");
    failed = true;
  }
  if (device.keyCount < 40) {
    console.error("720x720: expected a full key set, got", device.keyCount, device.labels);
    failed = true;
  }
  if (!device.labels.includes("q") || !device.labels.includes("p") || !device.labels.includes("space")) {
    console.error("720x720: missing expected keys", device.labels);
    failed = true;
  }
  if (device.inputmode !== "none") {
    console.error("720x720: expected inputmode=none to suppress the OS keyboard, got", device.inputmode);
    failed = true;
  }
  if (device.outside.length) {
    console.error("720x720: keys extend outside the glass:", JSON.stringify(device.outside.slice(0, 8)));
    failed = true;
  }
  if (!failed) console.log("720x720: all", device.keyCount, "keys sit inside the circle.");

  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  await page.goto(setupUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForFunction(() => document.getElementById("wifi-pass"), { timeout: 10000 });
  await page.evaluate(() => {
    document.getElementById("login")?.classList.add("hidden");
    document.getElementById("app")?.classList.remove("hidden");
    document.getElementById("wifi-pass")?.focus();
  });
  await wait(200);
  const phone = await page.evaluate(() => {
    const root = document.getElementById("ft-osk");
    return {
      hidden: !root || root.hidden || !document.body.classList.contains("ft-osk-open"),
      inputmode: document.getElementById("wifi-pass")?.getAttribute("inputmode") || "",
    };
  });
  if (!phone.hidden) {
    console.error("phone: custom keyboard should stay hidden so the OS keyboard can be used");
    failed = true;
  }
  if (phone.inputmode === "none") {
    console.error("phone: must not set inputmode=none");
    failed = true;
  }
  if (!failed) console.log("phone: custom keyboard hidden.");
} finally {
  await browser.close();
}
process.exit(failed ? 1 : 0);
