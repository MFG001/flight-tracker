/**
 * Render setup-page previews of the saved Wi-Fi list.
 * Usage: node preview-saved-nets.mjs [setupUrl] [outDir]
 */
import fs from "fs";
import path from "path";
import puppeteer from "puppeteer-core";

const base = (process.argv[2] ?? "http://127.0.0.1:8820").replace(/\/$/, "");
const outDir = process.argv[3] ?? path.resolve(".");
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome";
const setupUrl = /setup/i.test(base) ? base : `${base}/setup`;

const SAVED = {
  networks: [
    { uuid: "aaaaaaaa-1111-4111-8111-000000000001", name: "Home", ssid: "Home", active: true, autoconnect: true, priority: 100, preferred: true },
    { uuid: "aaaaaaaa-1111-4111-8111-000000000002", name: "Shop", ssid: "Shop", active: false, autoconnect: true, priority: 0, preferred: false },
    { uuid: "aaaaaaaa-1111-4111-8111-000000000003", name: "Travel", ssid: "Travel", active: false, autoconnect: true, priority: 0, preferred: false },
  ],
  wifi: {
    nmcli: true,
    state: "connected",
    connectedSsid: "Home",
    devices: [{ type: "wifi", ip: "192.0.2.10", connection: "Home" }],
    note: "",
  },
};

async function shotCard(page, dest) {
  const card = await page.$("#wifi");
  if (!card) throw new Error("wifi card missing");
  await card.screenshot({ path: dest });
}

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
});

async function stubPage(page) {
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    const url = req.url();
    const json = (body) =>
      req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (url.includes("/api/wifi/saved")) return json(SAVED);
    if (url.includes("/api/wifi/scan")) return json({ networks: [] });
    if (/\/api\/wifi$/.test(url) || url.endsWith("/api/wifi?")) return json(SAVED.wifi);
    if (url.includes("/api/auth")) return json({ required: false });
    if (url.includes("/api/config")) return json({ wifi: { country: "US" }, home: { lat: 40.64, lon: -73.78 } });
    if (url.includes("/api/updates")) return json({ state: "idle", current: "1.0.20" });
    if (url.includes("/api/weather")) return json({ ok: true, frames: [1], attribution: "demo", error: "" });
    if (url.includes("/api/health")) return json({ ok: true, version: "1.0.20" });
    return req.continue();
  });
}

async function prepare(page, { passwordPanel = false, glass = false, focusPass = true } = {}) {
  await page.goto(setupUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForFunction(() => document.getElementById("saved-nets"), { timeout: 15000 });
  await page.addStyleTag({ content: `
    p.lead, .preview, #login { display: none !important; }
    #app > .card:not(#wifi) { display: none !important; }
    main { padding: 80px 8px 0 !important; }
    #wifi { margin-top: 0 !important; }
  `});
  await page.evaluate(() => {
    document.getElementById("login")?.classList.add("hidden");
    document.getElementById("app")?.classList.remove("hidden");
  });
  // Give loadSavedNets a tick if it raced, then render from the stubbed data.
  await page.evaluate((payload) => {
    if (typeof showWifiState === "function") showWifiState(payload.wifi);
    if (typeof showSavedNets === "function") showSavedNets(payload.networks);
  }, SAVED).catch(async () => {
    // functions are inside a script closure — click-refresh or re-call load path
  });
  // If functions are not on window, the intercepted load() should already have filled the list.
  await page.waitForFunction(() => {
    const items = document.querySelectorAll("#saved-nets li");
    return items.length >= 3 && /Home/.test(document.getElementById("saved-nets")?.innerText || "");
  }, { timeout: 10000 });
  if (passwordPanel) {
    await page.evaluate((focus) => {
      const buttons = [...document.querySelectorAll("#saved-nets button")];
      const btn = buttons.find((el) => el.textContent.includes("CHANGE PASSWORD") && el.closest("li")?.innerText.includes("Shop"));
      btn?.click();
      if (!focus) document.activeElement?.blur();
    }, focusPass);
    await page.waitForFunction(() => !document.getElementById("saved-pass-panel")?.classList.contains("hidden"), { timeout: 5000 });
    if (!focusPass) {
      await page.evaluate(() => {
        document.activeElement?.blur();
        const osk = document.getElementById("ft-osk");
        if (osk) { osk.hidden = true; osk.setAttribute("aria-hidden", "true"); }
        document.body.classList.remove("ft-osk-open");
        for (const id of ["wifi-join", "wifi-saved-save"]) {
          const btn = document.getElementById(id);
          if (!btn) continue;
          btn.classList.remove("osk-pinned");
          btn.style.position = "";
          btn.style.left = "";
          btn.style.top = "";
          btn.style.width = "";
          btn.style.height = "";
          btn.style.zIndex = "";
          btn.style.margin = "";
        }
        const scroller = document.querySelector("#wifi .round-scroll");
        const panel = document.getElementById("saved-pass-panel");
        if (scroller && panel) {
          const s = scroller.getBoundingClientRect();
          const r = panel.getBoundingClientRect();
          scroller.scrollTop = Math.max(0, scroller.scrollTop + (r.top - s.top) - 12);
        }
      });
    }
  }
  await page.evaluate((showPass) => {
    const scroller = document.querySelector("#wifi .round-scroll");
    if (!scroller) return;
    const into = (el, pad) => {
      if (!el) return;
      const s = scroller.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      scroller.scrollTop = Math.max(0, scroller.scrollTop + (r.top - s.top) - pad);
    };
    if (showPass) into(document.getElementById("saved-pass-panel"), 12);
    else into([...scroller.querySelectorAll(".subhead")].find((h) => /SAVED/.test(h.textContent || "")), 8);

  }, passwordPanel && glass);
  await new Promise((r) => setTimeout(r, 200));
}

try {
  // 720 list
  const glass = await browser.newPage();
  await glass.setViewport({ width: 720, height: 720, deviceScaleFactor: 1, hasTouch: true });
  await stubPage(glass);
  await prepare(glass, { passwordPanel: false, glass: true });
  await shotCard(glass, path.join(outDir, "saved-nets-720-raw.png"));
  await glass.close();

  // 720 password form (no keyboard, so the fields stay visible)
  const glassForm = await browser.newPage();
  await glassForm.setViewport({ width: 720, height: 720, deviceScaleFactor: 1, hasTouch: true });
  await stubPage(glassForm);
  await prepare(glassForm, { passwordPanel: true, glass: true, focusPass: false });
  await shotCard(glassForm, path.join(outDir, "saved-nets-720-password-form-raw.png"));
  await glassForm.close();

  // 720 password with on-device keyboard
  const glassPass = await browser.newPage();
  await glassPass.setViewport({ width: 720, height: 720, deviceScaleFactor: 1, hasTouch: true });
  await stubPage(glassPass);
  await prepare(glassPass, { passwordPanel: true, glass: true, focusPass: true });
  await glassPass.screenshot({ path: path.join(outDir, "saved-nets-720-password-raw.png") });
  await glassPass.close();

  // phone list
  const phone = await browser.newPage();
  await phone.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
  await stubPage(phone);
  await prepare(phone, { passwordPanel: false });
  // Crop to the wifi card height rather than empty space: screenshot full phone.
  await phone.screenshot({ path: path.join(outDir, "saved-nets-phone.png") });
  await phone.close();

  const phonePass = await browser.newPage();
  await phonePass.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
  await stubPage(phonePass);
  await prepare(phonePass, { passwordPanel: true });
  await phonePass.evaluate(() => {
    const panel = document.getElementById("saved-pass-panel");
    if (panel) panel.scrollIntoView({ block: "center", inline: "nearest" });
  });
  await phonePass.screenshot({ path: path.join(outDir, "saved-nets-phone-password.png") });
  await phonePass.close();

  console.log("wrote raw screenshots to", outDir);
} finally {
  await browser.close();
}
