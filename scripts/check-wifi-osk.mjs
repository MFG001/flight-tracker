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
  if (!device.labels.includes("q") || !device.labels.includes("p") || !device.labels.includes("space") || !device.labels.includes("connect")) {
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

  // Typing via the on-device keyboard must fill the inputs that CONNECT submits,
  // and CONNECT itself must stay tappable (1.0.16 covered it 100%).
  const posts = [];
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    if (req.url().includes("/api/wifi/connect") && req.method() === "POST") {
      posts.push(req.postData() || "");
      req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, detail: "Connected.", wifi: { state: "connected", devices: [] } }) });
      return;
    }
    req.continue();
  });
  const typeKey = async (key) => {
    const handle = await page.evaluateHandle((k) => {
      const root = document.getElementById("ft-osk");
      return [...(root?.querySelectorAll("button") || [])].find((b) => b.dataset.key === k);
    }, key);
    const el = handle.asElement();
    if (!el) throw new Error("missing key " + key);
    const box = await el.boundingBox();
    await handle.dispose();
    if (!box) throw new Error("no box for key " + key);
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  };
  await page.evaluate(() => {
    document.getElementById("wifi-ssid").value = "";
    document.getElementById("wifi-pass").value = "";
    document.getElementById("wifi-ssid").focus();
  });
  await wait(150);
  for (const ch of "HomeNet") await typeKey(ch.toLowerCase());
  await page.evaluate(() => document.getElementById("wifi-pass").focus());
  await wait(150);
  for (const ch of "secret99") await typeKey(ch);
  const filled = await page.evaluate(() => ({
    ssid: document.getElementById("wifi-ssid").value,
    pass: document.getElementById("wifi-pass").value,
  }));
  if (filled.ssid !== "homenet" || filled.pass !== "secret99") {
    console.error("720x720: OSK did not write into the inputs that CONNECT submits", filled);
    failed = true;
  }
  const coverage = await page.evaluate(() => {
    const osk = document.getElementById("ft-osk");
    const join = document.getElementById("wifi-join");
    const o = osk.getBoundingClientRect();
    const j = join.getBoundingClientRect();
    const overlap = !(j.right < o.left || j.left > o.right || j.bottom < o.top || j.top > o.bottom);
    const area = Math.max(0, Math.min(j.right, o.right) - Math.max(j.left, o.left)) * Math.max(0, Math.min(j.bottom, o.bottom) - Math.max(j.top, o.top));
    const coveredPct = j.width * j.height ? 100 * area / (j.width * j.height) : 0;
    return { overlap, coveredPct: +coveredPct.toFixed(1), joinTop: +j.top.toFixed(1), oskTop: +o.top.toFixed(1) };
  });
  if (coverage.coveredPct >= 40) {
    console.error("720x720: CONNECT is covered by the keyboard", coverage);
    failed = true;
  } else {
    console.log("720x720: CONNECT stays clear of the keyboard", coverage);
  }
  posts.length = 0;
  await typeKey("connect");
  await wait(400);
  let body = {};
  try { body = JSON.parse(posts[0] || "{}"); } catch { body = { raw: posts[0] }; }
  if (posts.length !== 1 || body.ssid !== "homenet" || body.password !== "secret99") {
    console.error("720x720: connect key did not submit the OSK values", { posts, body, filled });
    failed = true;
  } else {
    console.log("720x720: connect key submitted OSK values.");
  }

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
