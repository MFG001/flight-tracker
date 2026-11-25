/**
 * Automated overflow / overlap / clip checks for the setup page at phone
 * and tablet widths. Exit 0 when every required viewport passes.
 *
 * Usage: node scripts/check-setup-responsive.mjs [baseUrl]
 *   baseUrl may be the setup origin (http://127.0.0.1:8820) or a static
 *   file server rooted at the repo (http://127.0.0.1:PORT/setup/index.html).
 */
import puppeteer from "puppeteer-core";

const base = (process.argv[2] ?? "http://127.0.0.1:8820").replace(/\/$/, "");
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome";
const setupUrl = /setup/i.test(base) ? base : `${base}/setup`;

const VIEWPORTS = [
  ["320-portrait", 320, 720],
  ["360-portrait", 360, 800],
  ["375-portrait", 375, 812],
  ["390-portrait", 390, 844],
  ["414-portrait", 414, 896],
  ["430-portrait", 430, 932],
  ["landscape-phone", 844, 390],
  ["ipad", 768, 1024],
];

const SECTIONS = [
  "login", "wifi", "background", "display-screen", "location", "form",
  "weather", "watch", "alerts", "trails", "night", "health", "software", "sources",
];

const LONG_NOTES = [
  "Flight Tracker 1.0.13 by Maverick Field Gear.",
  "",
  "- Daily update check moved to 9:00 AM so the update prompt shows while you're awake.",
  "- Setup is now responsive on phones: https://github.com/MFG001/flight-tracker/releases/tag/v1.0.13",
].join("\n");

const LONG_URL = "https://github.com/MFG001/flight-tracker/releases/latest/download/manifest.json";

async function applyFixtures(page) {
  await page.evaluate((notes, url) => {
    const show = (id) => {
      const el = document.getElementById(id);
      if (el) el.classList.remove("hidden");
    };
    const hide = (id) => {
      const el = document.getElementById(id);
      if (el) el.classList.add("hidden");
    };
    hide("login");
    show("app");

    const wifiText = document.getElementById("wifi-text");
    if (wifiText) {
      wifiText.textContent = "Connected to Harbor-View-Guest-Network-5GHz. Reopen http://flighttracker.local/ after the Pi switches.";
    }
    const wifiIps = document.getElementById("wifi-ips");
    if (wifiIps) wifiIps.textContent = "Wi-Fi (Harbor-View-Guest-Network-5GHz) · Ethernet connected";

    const nets = document.getElementById("nets");
    if (nets) {
      nets.replaceChildren();
      for (const net of [
        { ssid: "Harbor-View-Guest-Network-5GHz", signal: 72, secured: true, security: "WPA2" },
        { ssid: "A very long SSID name that should wrap not truncate", signal: 41, secured: true, security: "WPA3" },
      ]) {
        const li = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        const name = document.createElement("span");
        name.className = "net-name";
        name.textContent = net.ssid;
        name.style.whiteSpace = "pre";
        const sig = document.createElement("span");
        sig.className = "net-bars";
        sig.textContent = "▂▄▆█";
        const meta = document.createElement("span");
        meta.className = "net-meta";
        meta.textContent = net.signal + "% · Secured (" + net.security + ")";
        button.append(name, sig, meta);
        li.append(button);
        nets.append(li);
      }
    }

    const loc = document.getElementById("loc-match");
    if (loc) {
      loc.textContent = "John F. Kennedy International Airport · New York · 40.6399, -73.7787";
    }

    const health = document.getElementById("health-text");
    if (health) health.textContent = "Receiver OK · 19 aircraft · 100 messages";

    if (typeof showSoftware === "function") {
      showSoftware({
        version: "1.0.13",
        latest: "1.0.17",
        available: true,
        url,
        notes,
        state: "",
        auto: false,
        laterAt: "02:00",
        laterTz: "America/New_York",
        source: "github.com/MFG001/flight-tracker",
        keyFingerprints: ["2D7C 0580 0B69 E5EA"],
      });
    } else {
      const banner = document.getElementById("sw-banner");
      const title = document.getElementById("sw-banner-title");
      const detail = document.getElementById("sw-banner-detail");
      const notesEl = document.getElementById("sw-notes");
      const urlEl = document.getElementById("sw-url");
      if (banner) { banner.hidden = false; banner.dataset.tone = "ready"; }
      if (title) title.textContent = "Update ready: Version 1.0.17";
      if (detail) detail.textContent = "Tap INSTALL UPDATE below.";
      if (notesEl) { notesEl.hidden = false; notesEl.textContent = notes; }
      if (urlEl) urlEl.textContent = url;
    }
  }, LONG_NOTES, LONG_URL);
}

function auditVisible(sectionIds, requireTap) {
  const issues = { overflow: [], clipped: [], overlap: [], tap: [] };
  const visible = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 2) {
    issues.overflow.push({ el: "html", scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth });
  }
  if (document.body.scrollWidth > document.body.clientWidth + 2) {
    issues.overflow.push({ el: "body", scrollWidth: document.body.scrollWidth, clientWidth: document.body.clientWidth });
  }

  const skipOverflowTags = new Set(["INPUT", "TEXTAREA", "SELECT"]);
  for (const el of document.querySelectorAll("main, .card, form, .round-scroll, h1, p, button, label, a, li, #sw-url, #sw-notes, #wifi-text, #sources")) {
    if (!visible(el)) continue;
    if (skipOverflowTags.has(el.tagName)) continue;
    if (el.scrollWidth > el.clientWidth + 2) {
      issues.overflow.push({
        el: el.id ? "#" + el.id : el.tagName + (el.className ? "." + String(el.className).toString().replace(/\s+/g, ".") : ""),
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        text: (el.innerText || "").trim().slice(0, 80),
      });
    }
  }

  const isVisibleRect = (r) => {
    if (r.width < 1 || r.height < 1) return false;
    // Intersect the viewport (page overflow is already flagged separately).
    return r.right > 0 && r.left < window.innerWidth && r.bottom > 0 && r.top < window.innerHeight;
  };

  const clippedByAncestor = (parent, r) => {
    let anc = parent;
    while (anc && anc !== document.body) {
      const acs = getComputedStyle(anc);
      const canScrollY = acs.overflowY === "auto" || acs.overflowY === "scroll";
      const canScrollX = acs.overflowX === "auto" || acs.overflowX === "scroll";
      const clips = acs.overflow !== "visible" || acs.overflowX !== "visible" || acs.overflowY !== "visible";
      if (clips) {
        const ar = anc.getBoundingClientRect();
        const pad = 0.75;
        const outsideX = r.left < ar.left - pad || r.right > ar.right + pad;
        const outsideY = r.top < ar.top - pad || r.bottom > ar.bottom + pad;
        // Scrolled-out content in an intentional scroller is not a defect.
        if (outsideY && canScrollY && !outsideX) { anc = anc.parentElement; continue; }
        if (outsideX && canScrollX && !outsideY) { anc = anc.parentElement; continue; }
        let outsideCircle = false;
        const radius = parseFloat(acs.borderRadius);
        if ((acs.borderRadius.includes("%") && ar.width > 80) || radius > ar.width * 0.4) {
          const cx = ar.left + ar.width / 2;
          const cy = ar.top + ar.height / 2;
          const rad = Math.min(ar.width, ar.height) / 2;
          const pts = [
            [r.left, r.top], [r.right, r.top], [r.left, r.bottom], [r.right, r.bottom],
            [(r.left + r.right) / 2, r.top], [(r.left + r.right) / 2, r.bottom],
          ];
          outsideCircle = pts.some(([x, y]) => Math.hypot(x - cx, y - cy) > rad + 0.5);
        }
        if (outsideX || (outsideY && !canScrollY) || outsideCircle) {
          return {
            el: anc.id ? "#" + anc.id : String(anc.className || anc.tagName),
            reason: outsideCircle ? "clipped by round card" : "clipped by overflow hidden",
          };
        }
        break;
      }
      anc = anc.parentElement;
    }
    return null;
  };

  const textRects = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (!node.textContent || !node.textContent.trim()) continue;
    const parent = node.parentElement;
    if (!parent || !visible(parent)) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    for (const r of range.getClientRects()) {
      if (!isVisibleRect(r)) continue;
      // Ignore text that is in a scrollport but currently out of that scrollport.
      let hiddenInScroll = false;
      let anc = parent;
      while (anc && anc !== document.body) {
        const acs = getComputedStyle(anc);
        if (acs.overflowY === "auto" || acs.overflowY === "scroll" || acs.overflowX === "auto" || acs.overflowX === "scroll") {
          const ar = anc.getBoundingClientRect();
          if (r.bottom <= ar.top + 0.5 || r.top >= ar.bottom - 0.5 || r.right <= ar.left + 0.5 || r.left >= ar.right - 0.5) {
            hiddenInScroll = true;
          }
          break;
        }
        anc = anc.parentElement;
      }
      if (hiddenInScroll) continue;

      textRects.push({ r, text: node.textContent.trim().slice(0, 70), el: parent });

      const cs = getComputedStyle(parent);
      const ellipsis = cs.textOverflow === "ellipsis" && (cs.whiteSpace === "nowrap" || cs.whiteSpace === "pre");
      if (ellipsis && parent.scrollWidth > parent.clientWidth + 1) {
        issues.clipped.push({
          el: parent.id ? "#" + parent.id : String(parent.className || parent.tagName),
          reason: "ellipsis/nowrap truncation",
          text: node.textContent.trim().slice(0, 70),
        });
      }
      const clip = clippedByAncestor(parent, r);
      if (clip) issues.clipped.push({ ...clip, text: node.textContent.trim().slice(0, 70) });
    }
  }

  for (let i = 0; i < textRects.length; i++) {
    for (let j = i + 1; j < textRects.length; j++) {
      const a = textRects[i], b = textRects[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const ar = a.r, br = b.r;
      const ix = Math.max(0, Math.min(ar.right, br.right) - Math.max(ar.left, br.left));
      const iy = Math.max(0, Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top));
      const area = ix * iy;
      if (ix > 1.5 && iy > 1.5 && area > 6) {
        issues.overlap.push({ a: a.text, b: b.text, ix: +ix.toFixed(1), iy: +iy.toFixed(1), area: +area.toFixed(1) });
      }
    }
  }

  if (requireTap) {
    for (const el of document.querySelectorAll("button, input, select, textarea")) {
      if (!visible(el)) continue;
      const type = (el.type || "").toLowerCase();
      if (type === "checkbox" || type === "range" || type === "hidden") continue;
      const r = el.getBoundingClientRect();
      if (r.height + 0.5 < 44) {
        issues.tap.push({
          el: el.id ? "#" + el.id : (el.className && String(el.className).slice(0, 40)) || el.tagName,
          h: +r.height.toFixed(1),
          text: (el.value || el.textContent || "").trim().slice(0, 40),
        });
      }
    }
  }

  const missing = sectionIds.filter((id) => !document.getElementById(id));
  return {
    vw: window.innerWidth,
    vh: window.innerHeight,
    overflow: issues.overflow,
    clipped: issues.clipped,
    overlap: issues.overlap,
    tap: issues.tap,
    missing,
  };
}

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
});
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const results = {};
let failed = false;

try {
  const page = await browser.newPage();
  for (const [name, width, height] of VIEWPORTS) {
    const isPhone = name !== "ipad";
    await page.setViewport({ width, height, deviceScaleFactor: 1, isMobile: isPhone && width <= 430, hasTouch: true });
    await page.goto(setupUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForFunction(() => document.getElementById("app"), { timeout: 10000 });
    await wait(600);
    await applyFixtures(page);
    await wait(200);

    // Walk every section into view so inner-scroll cards expose their content.
    for (const id of SECTIONS) {
      await page.evaluate((sid) => {
        const el = document.getElementById(sid);
        if (!el) return;
        el.classList.remove("hidden");
        el.scrollIntoView({ block: "center" });
        const scroller = el.querySelector(".round-scroll") || el;
        if (scroller.scrollHeight > scroller.clientHeight + 4) {
          const step = Math.max(40, scroller.clientHeight - 24);
          for (let y = 0; y <= scroller.scrollHeight - scroller.clientHeight; y += step) scroller.scrollTop = y;
          scroller.scrollTop = 0;
        }
      }, id);
    }

    // Software: update-ready (already applied), then install progress, then back.
    const reports = [];
    const collect = async (label) => {
      // Recheck after scrolling each section to the first screen, then mid-scroll for long cards.
      for (const id of SECTIONS) {
        await page.evaluate((sid) => {
          const el = document.getElementById(sid);
          if (!el) return;
          el.scrollIntoView({ block: "nearest" });
          const scroller = el.querySelector(".round-scroll");
          if (scroller) scroller.scrollTop = 0;
        }, id);
      }
      const first = await page.evaluate(auditVisible, SECTIONS, isPhone);
      first.label = label + ":top";
      reports.push(first);
      await page.evaluate(() => {
        for (const el of document.querySelectorAll(".round-scroll, form.card, section.card")) {
          if (el.scrollHeight > el.clientHeight + 4) el.scrollTop = Math.min(el.scrollHeight, el.clientHeight * 0.8);
        }
      });
      const mid = await page.evaluate(auditVisible, SECTIONS, isPhone);
      mid.label = label + ":mid";
      reports.push(mid);
    };

    await collect("ready");

    await page.evaluate(() => {
      if (typeof showSoftware === "function") {
        showSoftware({
          version: "1.0.13",
          latest: "1.0.17",
          available: true,
          target: "1.0.17",
          state: "installing",
          step: 2,
          steps: 4,
          detail: "Copying files…",
          percent: 45,
          url: document.getElementById("sw-url")?.textContent || "",
        });
      } else {
        const banner = document.getElementById("sw-banner");
        const title = document.getElementById("sw-banner-title");
        const detail = document.getElementById("sw-banner-detail");
        const prog = document.getElementById("sw-progress");
        const bar = document.getElementById("sw-progress-bar");
        if (banner) { banner.hidden = false; banner.dataset.tone = "busy"; }
        if (title) title.textContent = "Installing Version 1.0.17…";
        if (detail) detail.textContent = "Step 2 of 4 · Copying files…";
        if (prog) prog.hidden = false;
        if (bar) bar.style.width = "45%";
      }
    });
    await page.evaluate(() => document.getElementById("software")?.scrollIntoView({ block: "center" }));
    await collect("installing");

    // Location lat/long mode and the sign-in card.
    await page.evaluate(() => {
      if (typeof setLocMode === "function") setLocMode("ll");
      const login = document.getElementById("login");
      if (login) login.classList.remove("hidden");
    });
    await page.evaluate(() => document.getElementById("location")?.scrollIntoView({ block: "center" }));
    await collect("latlon+login");
    await page.evaluate(() => document.getElementById("login")?.classList.add("hidden"));

    const merged = {
      overflow: [], clipped: [], overlap: [], tap: [], missing: [],
    };
    for (const r of reports) {
      for (const key of ["overflow", "clipped", "overlap", "tap"]) {
        for (const item of r[key]) merged[key].push({ ...item, at: r.label });
      }
      for (const m of r.missing || []) if (!merged.missing.includes(m)) merged.missing.push(m);
    }
    results[name] = {
      width, height,
      overflow: merged.overflow.length,
      clipped: merged.clipped.length,
      overlap: merged.overlap.length,
      tap: merged.tap.length,
      missing: merged.missing,
      samples: {
        overflow: merged.overflow.slice(0, 6),
        clipped: merged.clipped.slice(0, 6),
        overlap: merged.overlap.slice(0, 6),
        tap: merged.tap.slice(0, 6),
      },
    };
    const ok = merged.overflow.length === 0 && merged.clipped.length === 0 && merged.overlap.length === 0
      && merged.tap.length === 0 && merged.missing.length === 0;
    if (!ok) failed = true;
    console.log((ok ? "PASS " : "FAIL ") + name + " " + width + "x" + height
      + " overflow=" + merged.overflow.length
      + " clipped=" + merged.clipped.length
      + " overlap=" + merged.overlap.length
      + " tap=" + merged.tap.length
      + (merged.missing.length ? " missing=" + merged.missing.join(",") : ""));
    if (!ok) console.log(JSON.stringify(results[name].samples, null, 2));
  }
} finally {
  await browser.close();
}

console.log("SUMMARY " + JSON.stringify(Object.fromEntries(Object.entries(results).map(([k, v]) => [k, {
  overflow: v.overflow, clipped: v.clipped, overlap: v.overlap, tap: v.tap,
}])), null, 2));
if (failed) process.exit(1);
console.log("setup responsive ok");
