/**
 * 1.0.12: keep the kiosk on the local display. Taps must not open a legal
 * page, a weather site, or any other origin in the Chromium window (there
 * is no back button on the glass).
 */

export function isLocalHref(href: string, baseHref: string): boolean {
  const raw = (href ?? "").trim();
  if (!raw) return false;
  try {
    const base = new URL(baseHref);
    const target = new URL(raw, base);
    if (target.origin !== base.origin) return false;
    return target.protocol === "http:" || target.protocol === "https:";
  } catch {
    return false;
  }
}

/** True when window.open would leave the local origin (or is not a URL). */
export function shouldBlockWindowOpen(url: string | URL | null | undefined, baseHref: string): boolean {
  if (url == null || url === "") return true;
  return !isLocalHref(String(url), baseHref);
}

/** Turn off-origin anchors into plain text, keeping the exact wording. */
export function neutralizeExternalAnchors(root: ParentNode, baseHref: string): void {
  const doc = root instanceof Document ? root : (root as Element).ownerDocument;
  if (!doc) return;
  for (const el of Array.from(root.querySelectorAll("a[href]"))) {
    const href = el.getAttribute("href") || "";
    if (isLocalHref(href, baseHref)) continue;
    const span = doc.createElement("span");
    if (el.id) span.id = el.id;
    if (el.className) span.className = el.className;
    while (el.firstChild) span.appendChild(el.firstChild);
    el.replaceWith(span);
  }
}

export function installKioskGuards(win: Window): void {
  neutralizeExternalAnchors(win.document, win.location.href);
  win.document.addEventListener(
    "click",
    (event) => {
      const node = event.target;
      const el = node instanceof Element ? node.closest("a[href]") : null;
      if (!el) return;
      const href = el.getAttribute("href") || "";
      if (!isLocalHref(href, win.location.href)) {
        event.preventDefault();
        event.stopPropagation();
      }
    },
    true,
  );
  const original = win.open.bind(win);
  win.open = (url?: string | URL, target?: string, features?: string) => {
    if (!shouldBlockWindowOpen(url, win.location.href)) {
      return original(url, target, features);
    }
    return null;
  };
}
