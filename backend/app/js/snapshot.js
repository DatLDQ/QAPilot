// Builds a compact, indented accessibility outline of the page for the agent.
// Every element the agent can act on or assert against gets a short ref (e1, e2, ...)
// stored in a data-qa-ref attribute, plus the facts needed to build a stable locator.
(opts) => {
  const maxLines = opts.maxLines;
  document.querySelectorAll("[data-qa-ref]").forEach((el) => el.removeAttribute("data-qa-ref"));

  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "PATH", "META", "LINK", "HEAD"]);
  const INLINE = new Set(["SPAN", "STRONG", "EM", "B", "I", "SMALL", "CODE", "MARK", "SUB", "SUP", "BR", "ABBR", "TIME", "S", "U"]);
  const CONTAINERS = {
    HEADER: "banner", NAV: "navigation", MAIN: "main", FOOTER: "contentinfo", FORM: "form",
    ARTICLE: "article", SECTION: "region", ASIDE: "complementary", DIALOG: "dialog", TABLE: "table",
    TR: "row", FIELDSET: "group", UL: "list", OL: "list",
  };
  const CONTAINER_ROLES = new Set([
    "banner", "navigation", "main", "contentinfo", "form", "article", "region", "complementary", "dialog",
    "alertdialog", "table", "row", "group", "list", "tablist", "tabpanel", "alert", "status", "listitem",
  ]);
  const INTERACTIVE_ROLES = new Set([
    "button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox", "spinbutton", "slider",
    "switch", "tab", "menuitem", "option", "listbox",
  ]);

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const quote = (s) => '"' + s.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';

  function isVisible(el) {
    if (el.getAttribute("aria-hidden") === "true" || el.hidden) return false;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function implicitRole(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit.split(" ")[0];
    const tag = el.tagName;
    if (tag === "A") return el.hasAttribute("href") ? "link" : null;
    if (tag === "BUTTON" || tag === "SUMMARY") return "button";
    if (tag === "SELECT") return el.multiple ? "listbox" : "combobox";
    if (tag === "TEXTAREA") return "textbox";
    if (tag === "IMG") return el.getAttribute("alt") === "" ? null : "img";
    if (/^H[1-6]$/.test(tag)) return "heading";
    if (tag === "INPUT") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset", "image"].includes(t)) return "button";
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      if (t === "range") return "slider";
      if (t === "number") return "spinbutton";
      if (t === "search") return "searchbox";
      if (t === "hidden") return null;
      return "textbox";
    }
    if (tag === "SECTION") return el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby") ? "region" : null;
    return CONTAINERS[tag] || null;
  }

  function labelFor(el) {
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl) return clean(lbl.innerText);
    }
    const wrap = el.closest("label");
    if (wrap) return clean(wrap.innerText);
    return "";
  }

  function accessibleName(el, role) {
    const aria = el.getAttribute("aria-label");
    if (aria) return clean(aria);
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const text = by.split(/\s+/).map((id) => document.getElementById(id)?.innerText || "").join(" ");
      if (clean(text)) return clean(text);
    }
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
      const t = (el.getAttribute("type") || "").toLowerCase();
      if (["button", "submit", "reset"].includes(t)) return clean(el.value);
      return labelFor(el) || clean(el.getAttribute("placeholder")) || clean(el.getAttribute("title"));
    }
    if (tag === "IMG") return clean(el.getAttribute("alt")) || clean(el.getAttribute("title"));
    if (role === "img") return clean(el.getAttribute("title"));
    if (CONTAINER_ROLES.has(role)) return "";
    let text = clean(el.innerText);
    if (!text) {
      const img = el.querySelector("img[alt]");
      if (img) text = clean(img.getAttribute("alt"));
    }
    return text || clean(el.getAttribute("title"));
  }

  function containerName(el, role) {
    const aria = el.getAttribute("aria-label");
    if (aria) return clean(aria);
    if (["article", "region", "form", "dialog", "group", "row", "listitem"].includes(role)) {
      const h = el.querySelector("h1,h2,h3,h4,h5,h6,legend,caption");
      if (h) return clip(clean(h.innerText), 60);
    }
    return "";
  }

  // The nearest card-like ancestor with a recognisable label, used to scope duplicate locators.
  function scopeOf(el) {
    const box = el.parentElement && el.parentElement.closest("article, li, tr, fieldset, [data-testid]");
    if (!box) return null;
    if (box.dataset.testid) return { test_id: box.dataset.testid };
    const h = box.querySelector("h1,h2,h3,h4,h5,h6,legend,strong,td,a");
    const text = h ? clean(h.innerText) : "";
    return text ? { css: box.tagName.toLowerCase(), has_text: clip(text, 50) } : null;
  }

  const lines = [];
  const refs = {};
  let counter = 0;
  let truncated = 0;

  function addRef(el, info) {
    const ref = "e" + ++counter;
    el.setAttribute("data-qa-ref", ref);
    refs[ref] = {
      ...info,
      tag: el.tagName.toLowerCase(),
      test_id: el.dataset.testid || null,
      label: labelFor(el) || null,
      placeholder: el.getAttribute("placeholder") || null,
      scope: scopeOf(el),
    };
    return ref;
  }

  function emit(depth, text) {
    if (lines.length >= maxLines) {
      truncated += 1;
      return;
    }
    lines.push("  ".repeat(depth) + "- " + text);
  }

  function ownText(el) {
    let t = "";
    for (const node of el.childNodes) if (node.nodeType === Node.TEXT_NODE) t += node.textContent;
    return clean(t);
  }

  function isTextLeaf(el) {
    if (ownText(el)) return true;
    if (!el.children.length) return false;
    return [...el.children].every((c) => INLINE.has(c.tagName) && !c.querySelector("a,button,input,select,textarea"));
  }

  function states(el, role) {
    const out = [];
    if (role === "heading") out.push(`level=${el.tagName[1] || el.getAttribute("aria-level") || 2}`);
    if ("value" in el && ["textbox", "searchbox", "spinbutton", "combobox", "slider"].includes(role)) {
      if (el.tagName === "SELECT") {
        const opts = [...el.options].map((o) => clean(o.text));
        out.push(`selected=${quote(clean(el.options[el.selectedIndex]?.text || ""))}`);
        out.push(`options=[${opts.slice(0, 12).map(quote).join(", ")}${opts.length > 12 ? ", …" : ""}]`);
      } else {
        out.push(`value=${quote(clip(el.value || "", 60))}`);
      }
    }
    if (role === "checkbox" || role === "radio" || role === "switch") out.push(el.checked ? "checked" : "unchecked");
    if (el.getAttribute("aria-selected") === "true") out.push("selected");
    if (el.getAttribute("aria-expanded")) out.push(`expanded=${el.getAttribute("aria-expanded")}`);
    if (el.disabled || el.getAttribute("aria-disabled") === "true") out.push("disabled");
    if (el.required) out.push("required");
    if (el.getAttribute("aria-invalid") === "true") out.push("invalid");
    if (role === "link") {
      const href = el.getAttribute("href") || "";
      if (href && !href.startsWith("javascript:")) out.push(`href=${quote(clip(href, 60))}`);
    }
    return out.length ? " [" + out.join("] [") + "]" : "";
  }

  function walk(el, depth) {
    if (SKIP.has(el.tagName.toUpperCase()) || !isVisible(el)) return;
    const role = implicitRole(el);

    if (role && (INTERACTIVE_ROLES.has(role) || role === "heading" || role === "img")) {
      const name = clip(accessibleName(el, role), 80);
      const ref = addRef(el, { role, name });
      const label = name ? ` ${quote(name)}` : role === "img" ? " (no alt text)" : " (no accessible name)";
      emit(depth, `${role}${label}${states(el, role)} [ref=${ref}]`);
      if (role !== "listbox") return;
    }

    const textLeaf = (d) => {
      const text = clip(clean(el.innerText), 120);
      if (text) emit(d, `text ${quote(text)} [ref=${addRef(el, { role: "text", name: text })}]`);
    };

    let childDepth = depth;
    if (role && CONTAINER_ROLES.has(role) && role !== "listitem" && role !== "list") {
      const name = containerName(el, role);
      emit(depth, role + (name ? " " + quote(name) : ""));
      childDepth = depth + 1;
      // Alerts, status lines and footers often hold their message as direct text.
      if (isTextLeaf(el)) return textLeaf(childDepth);
      const own = ownText(el);
      if (own) emit(childDepth, `text ${quote(clip(own, 120))}`);
    } else if (!role && isTextLeaf(el)) {
      return textLeaf(depth);
    }
    for (const child of el.children) walk(child, childDepth);
  }

  walk(document.body, 0);
  if (truncated) lines.push(`- … ${truncated} more elements not shown (page is long; scroll-independent refs above are complete)`);
  return { lines, refs, title: document.title, url: location.href };
}
