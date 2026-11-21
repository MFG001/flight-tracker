/**
 * Fails if a visible non-map control sits outside the safe circle
 * (90 percent of the glass radius).
 */
import puppeteer from "puppeteer-core";

const base = process.env.FLIGHT_TRACKER_URL || "http://127.0.0.1:8741";
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/usr/bin/google-chrome-stable",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 720, height: 720, deviceScaleFactor: 1 });

async function open(url) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__ftReady === true, { timeout: 25000 });
  await new Promise((r) => setTimeout(r, 300));
}

function offenders() {
  const screen = document.querySelector("#screen").getBoundingClientRect();
  const cx = screen.left + screen.width / 2;
  const cy = screen.top + screen.height / 2;
  const safe = (screen.width / 2) * 0.9;
  const skip = new Set(["screen", "radar", "hud", "vignette", "keys", "dim", "splash", "fit", "device"]);
  const bad = [];
  function clipped(el) {
    let box = el.getBoundingClientRect();
    let node = el.parentElement;
    while (node) {
      const style = getComputedStyle(node);
      const clips = style.overflow !== "visible" || node.id === "screen";
      if (clips) {
        const parent = node.getBoundingClientRect();
        const left = Math.max(box.left, parent.left);
        const top = Math.max(box.top, parent.top);
        const right = Math.min(box.right, parent.right);
        const bottom = Math.min(box.bottom, parent.bottom);
        if (right - left < 2 || bottom - top < 2) return null;
        box = { left, top, right, bottom, width: right - left, height: bottom - top };
      }
      if (node.id === "screen") break;
      node = node.parentElement;
    }
    return box;
  }
  for (const el of document.querySelectorAll("#screen *")) {
    if (skip.has(el.id)) continue;
    if (el.closest("canvas#radar")) continue;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || el.hidden || el.closest("[hidden]")) continue;
    const box = clipped(el);
    if (!box) continue;
    const radius = Math.min(box.width, box.height) / 2;
    const rawRadius = style.borderTopLeftRadius;
    const round = (rawRadius.endsWith("%") ? parseFloat(rawRadius) >= 40 : parseFloat(rawRadius) >= radius * 0.8) && box.width > 40;
    if (round) {
      const dist = Math.hypot(box.left + box.width / 2 - cx, box.top + box.height / 2 - cy) + radius;
      if (dist > safe + 2) bad.push(`${el.id || el.className || el.tagName}`.slice(0, 60));
      continue;
    }
    const corners = [[box.left, box.top], [box.right, box.top], [box.left, box.bottom], [box.right, box.bottom]];
    if (corners.some(([x, y]) => Math.hypot(x - cx, y - cy) > safe + 2)) {
      bad.push(`${el.id || el.tagName}.${el.className}`.slice(0, 60));
    }
  }
  return bad;
}

function textOffenders(rootSelector) {
  const root = document.querySelector(rootSelector);
  if (!root || root.hidden) return [`missing ${rootSelector}`];
  const screen = document.querySelector("#screen");
  const glass = screen ? screen.getBoundingClientRect() : null;
  const safe = glass ? (glass.width / 2) * 0.9 : null;
  const gcx = glass ? glass.left + glass.width / 2 : 0;
  const gcy = glass ? glass.top + glass.height / 2 : 0;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (walker.currentNode.textContent.trim()) nodes.push(walker.currentNode);
  }
  const bad = [];
  function centerLine(el, range, index) {
    for (let pass = 0; pass < 5; pass += 1) {
      const rects = [...range.getClientRects()];
      const rect = rects[index];
      if (!rect) return null;
      let node = el.parentElement;
      let moved = false;
      while (node) {
        const style = getComputedStyle(node);
        if ((style.overflowY === "auto" || style.overflowY === "scroll") && node.scrollHeight > node.clientHeight + 2) {
          const parent = node.getBoundingClientRect();
          const delta = (rect.top + rect.height / 2) - (parent.top + parent.height / 2);
          if (Math.abs(delta) > 1) {
            const before = node.scrollTop;
            node.scrollTop += delta;
            if (Math.abs(node.scrollTop - before) > 0.5) moved = true;
          }
        }
        node = node.parentElement;
      }
      if (!moved) return [...range.getClientRects()][index] || null;
    }
    return [...range.getClientRects()][index] || null;
  }
  function lineProblem(rect, el) {
    if (!rect || rect.width < 1 || rect.height < 1) return null;
    let node = el.parentElement;
    while (node && node !== document.documentElement) {
      const style = getComputedStyle(node);
      const parent = node.getBoundingClientRect();
      const raw = style.borderTopLeftRadius;
      const round = parent.width > 40 && (raw.endsWith("%") ? parseFloat(raw) >= 40 : parseFloat(raw) >= Math.min(parent.width, parent.height) * 0.4);
      if (round) {
        const cx = parent.left + parent.width / 2;
        const cy = parent.top + parent.height / 2;
        const radius = Math.min(parent.width, parent.height) / 2 - 1;
        const corners = [[rect.left, rect.top], [rect.right, rect.top], [rect.left, rect.bottom], [rect.right, rect.bottom]];
        if (corners.some(([x, y]) => Math.hypot(x - cx, y - cy) > radius + 1.5)) return "cut by circle";
      } else {
        const clipsX = ["hidden", "clip", "auto", "scroll"].includes(style.overflowX);
        const clipsY = ["hidden", "clip", "auto", "scroll"].includes(style.overflowY);
        if (clipsX && (rect.left < parent.left - 1.5 || rect.right > parent.right + 1.5)) return "clipped sideways";
        if (clipsY && (rect.top < parent.top - 1.5 || rect.bottom > parent.bottom + 1.5)) return "clipped vertically";
      }
      node = node.parentElement;
    }
    if (safe != null) {
      const corners = [[rect.left, rect.top], [rect.right, rect.top], [rect.left, rect.bottom], [rect.right, rect.bottom]];
      if (corners.some(([x, y]) => Math.hypot(x - gcx, y - gcy) > safe + 2)) return "outside safe circle";
    }
    return null;
  }
  for (const node of nodes) {
    const el = node.parentElement;
    if (!el) continue;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || el.closest("[hidden]")) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const count = range.getClientRects().length;
    for (let index = 0; index < count; index += 1) {
      const rect = centerLine(el, range, index);
      const why = lineProblem(rect, el);
      if (why) {
        bad.push(`${why}: ${node.textContent.trim().replace(/\s+/g, " ").slice(0, 48)}`);
        break;
      }
    }
  }
  return bad;
}

const failures = [];
async function check(name) {
  const bad = await page.evaluate(offenders);
  if (bad.length) failures.push(`${name}: ${[...new Set(bad)].join(", ")}`);
  else console.log("ok", name);
}

async function checkText(name, rootSelector) {
  const bad = await page.evaluate(textOffenders, rootSelector);
  if (bad.length) failures.push(`${name}: ${[...new Set(bad)].slice(0, 8).join(" | ")}`);
  else console.log("ok", name);
}

await open(`${base}/?capture=1&bg=dark&wx=0`);
await check("main");
// 1.0.8 range control: − / current range / + only (no preset bar).
await check("rangectl");
await checkText("rangectl-text", "#rangectl");
await page.click("#range-plus");
await check("rangectl-stepped");
await open(`${base}/?capture=1&bg=light&wx=0`);
await check("light");
await open(`${base}/?capture=1&bg=sectional&wx=0`);
await check("sectional");
await open(`${base}/?capture=1&bg=dark&wx=0&range=40`);
await check("range-40");
await open(`${base}/?capture=1&bg=scope&sweep=1`);
await check("sweep");
await open(`${base}/?capture=1&splash=1`);
await page.waitForFunction(() => window.__splashReady === true);
await check("splash");
await checkText("splash-text", "#splash");
await open(`${base}/?capture=1&bg=dark&icons=maverick`);
// 1.0.3: no tap keys on the rim. Fail if any come back.
const keyCount = await page.evaluate(() => document.querySelectorAll("#screen .key, #keys").length);
if (keyCount) {
  failures.push(`edge-keys: ${keyCount} key elements on the glass`);
} else {
  console.log("ok no-edge-keys");
}
// About menu: 2-second press on the status line.
const status = await page.$("#status");
const sbox = await status.boundingBox();
await page.mouse.move(sbox.x + sbox.width / 2, sbox.y + sbox.height / 2);
await page.mouse.down();
await new Promise((r) => setTimeout(r, 2300));
await page.mouse.up();
await page.waitForSelector("#menu:not([hidden])", { timeout: 5000 });
await check("menu");
await checkText("about-text", "#menu");
await page.click("#m-traffic");
await check("traffic");
await checkText("traffic-text", "#traffic");
await page.evaluate(() => document.querySelector("#traffic-list li")?.click());
await page.waitForSelector("#detail:not([hidden])", { timeout: 5000 });
await check("detail");
await checkText("detail-text", "#detail");
await open(`${base}/?capture=1&wifi=hotspot`);
await page.waitForFunction(() => window.__wifiReady === true);
await check("wifi");
await checkText("wifi-text", "#wifi");
await open(`${base}/?capture=1&alert=1`);
await page.waitForSelector("#alert:not([hidden])");
await check("alert");
await checkText("alert-text", "#alert");
// 1.0.7 prototype: the update prompt and its follow-up screens.
for (const mode of ["prompt", "scheduled", "installing", "complete", "failed"]) {
  await open(`${base}/?capture=1&bg=dark&wx=0&updatepop=${mode}`);
  await page.waitForSelector("#update-pop:not([hidden])", { timeout: 5000 });
  await check(`update-${mode}`);
  await checkText(`update-${mode}-text`, "#update-pop");
}
await open(`${base}/?capture=1&idle=1`);
await page.waitForSelector("#idle:not([hidden])");
await checkText("idle-text", "#idle");
await page.goto(`${base}/setup`, { waitUntil: "networkidle0" });
await page.evaluate(() => {
  const app = document.getElementById("app");
  const login = document.getElementById("login");
  if (app) app.classList.remove("hidden");
  if (login) login.classList.add("hidden");
});
const setupCards = await page.$$eval("section.card, form.card", (cards) => cards.map((card) => card.id || card.tagName));
for (const id of setupCards) {
  if (!id || id === "login") continue;
  await checkText(`setup-${id}`, `#${id}`);
}
// 1.0.4 Software card: every update state stays inside the round card.
const { SW_STATES } = await import("./sw-states.mjs");
for (const [name, state] of Object.entries(SW_STATES)) {
  await page.evaluate((info) => { showSoftware(info); stopSoftwarePoll(); }, state);
  await checkText(`setup-software-${name}`, "#software");
}

await browser.close();
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("safe circle ok");
