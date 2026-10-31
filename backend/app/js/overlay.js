// Draws what the agent is doing on top of the page, so the session video reads like a screen recording:
// a cursor that moves to each element, a ripple on click, an outline around the element, a caption, and a
// green or red box when a check passes or fails. Runs as an init script in every document of the run.
// The overlay lives in a closed shadow root under <html> and ignores the pointer, so the page, the
// snapshot (which walks <body>) and Playwright locators never see it.
(() => {
  if (window.top !== window || window.__qaOverlay) return;

  const CSS = `
    :host { all: initial; }
    .cursor { position: fixed; left: 0; top: 0; width: 22px; height: 22px; opacity: 0;
      transform: translate(var(--x, -40px), var(--y, -40px));
      transition: transform 0.32s cubic-bezier(.4, 0, .2, 1), opacity 0.2s;
      filter: drop-shadow(0 1px 2px rgba(0, 0, 0, .55)); }
    .cursor.on { opacity: 1; }
    .ripple { position: fixed; left: 0; top: 0; width: 34px; height: 34px; margin: -17px 0 0 -17px;
      border-radius: 50%; border: 3px solid #f5b400; opacity: 0; transform: scale(.3); }
    .ripple.go { animation: ripple .55s ease-out; }
    @keyframes ripple { 0% { opacity: .95; transform: scale(.3); } 100% { opacity: 0; transform: scale(1.6); } }
    .box { position: fixed; box-sizing: border-box; border: 2px solid #f5b400; border-radius: 6px;
      background: rgba(245, 180, 0, .10); opacity: 0; transition: opacity .25s; }
    .box.on { opacity: 1; }
    .box.pass { border-color: #22c55e; background: rgba(34, 197, 94, .12); }
    .box.fail { border-color: #ef4444; background: rgba(239, 68, 68, .14); border-width: 3px; }
    .tag { position: absolute; left: -2px; bottom: 100%; margin-bottom: 4px; max-width: 520px; padding: 3px 8px;
      border-radius: 5px; font: 600 12px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif; color: #fff;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: none; }
    .box.pass .tag { display: block; background: #16a34a; }
    .box.fail .tag { display: block; background: #dc2626; }
    .box.below .tag { bottom: auto; top: 100%; margin: 4px 0 0; }
    .box.end .tag { left: auto; right: -2px; }
    .caption { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); max-width: 78vw;
      padding: 7px 14px; border-radius: 999px; background: rgba(17, 17, 17, .86); color: #fff;
      font: 500 13px/1.3 system-ui, -apple-system, "Segoe UI", sans-serif; white-space: nowrap; overflow: hidden;
      text-overflow: ellipsis; opacity: 0; transition: opacity .2s; border: 1px solid rgba(255, 255, 255, .14); }
    .caption.on { opacity: 1; }
    .caption.pass { background: rgba(22, 101, 52, .92); }
    .caption.fail { background: rgba(153, 27, 27, .94); }
  `;
  const CURSOR =
    '<svg viewBox="0 0 22 22" width="22" height="22"><path d="M3 2 L3 18 L7.5 13.8 L10.6 20.4 L13.4 19.1 ' +
    'L10.4 12.6 L16.6 12.6 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';

  let host = null;
  let ui = null;
  let boxTimer = 0;
  let pos = { x: -40, y: -40 };

  function ensure() {
    if (host && host.isConnected) return ui;
    if (!document.documentElement) return null;
    host = document.createElement("qapilot-overlay");
    host.setAttribute("aria-hidden", "true");
    host.style.cssText =
      "all: initial !important; position: fixed !important; inset: 0 !important; z-index: 2147483647 !important;" +
      "pointer-events: none !important; display: block !important;";
    const root = host.attachShadow({ mode: "closed" });
    root.innerHTML =
      `<style>${CSS}</style><div class="box"><div class="tag"></div></div><div class="ripple"></div>` +
      `<div class="cursor">${CURSOR}</div><div class="caption"></div>`;
    ui = {
      box: root.querySelector(".box"),
      tag: root.querySelector(".tag"),
      ripple: root.querySelector(".ripple"),
      cursor: root.querySelector(".cursor"),
      caption: root.querySelector(".caption"),
    };
    document.documentElement.appendChild(host);
    return ui;
  }

  function moveCursor(x, y, animate) {
    const u = ensure();
    if (!u) return;
    pos = { x, y };
    if (!animate) u.cursor.style.transition = "none";
    u.cursor.style.setProperty("--x", `${x}px`);
    u.cursor.style.setProperty("--y", `${y}px`);
    u.cursor.classList.add("on");
    if (!animate) {
      void u.cursor.offsetWidth;
      u.cursor.style.transition = "";
    }
  }

  function showBox(box, tone, text) {
    const u = ensure();
    if (!u) return;
    clearTimeout(boxTimer);
    u.box.className = "box";
    if (!box) return;
    const pad = 3;
    Object.assign(u.box.style, {
      left: `${box.x - pad}px`,
      top: `${box.y - pad}px`,
      width: `${box.width + pad * 2}px`,
      height: `${box.height + pad * 2}px`,
    });
    u.tag.textContent = text || "";
    u.box.classList.add("on");
    if (tone) u.box.classList.add(tone);
    if (box.y < 30) u.box.classList.add("below");
    // Grow the label towards the middle of the page so it is not cut off at the right edge.
    if (box.x + box.width / 2 > window.innerWidth / 2) u.box.classList.add("end");
    // A plain highlight fades so it does not linger over a page that has changed; a verdict stays.
    if (!tone) boxTimer = setTimeout(() => u.box.classList.remove("on"), 1600);
  }

  function caption(text, tone) {
    const u = ensure();
    if (!u) return;
    u.caption.textContent = text || "";
    u.caption.className = "caption";
    if (text) u.caption.classList.add("on");
    if (tone) u.caption.classList.add(tone);
  }

  const api = {
    place({ x, y }) {
      moveCursor(x, y, false);
    },
    point({ box, label, from }) {
      if (from) moveCursor(from.x, from.y, false);
      if (box) moveCursor(box.x + box.width / 2, box.y + box.height / 2, true);
      showBox(box, null);
      if (label !== undefined) caption(label, null);
    },
    click() {
      const u = ensure();
      if (!u) return;
      u.ripple.style.left = `${pos.x}px`;
      u.ripple.style.top = `${pos.y}px`;
      u.ripple.classList.remove("go");
      void u.ripple.offsetWidth;
      u.ripple.classList.add("go");
    },
    verdict({ box, passed, text }) {
      const tone = passed ? "pass" : "fail";
      showBox(box, tone, text);
      caption(text, tone);
    },
  };
  Object.defineProperty(window, "__qaOverlay", { value: api, enumerable: false });
})();
