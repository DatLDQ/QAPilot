"""Stable, replayable locators for the generated tests.

The agent acts on snapshot refs (``e12``), which mean nothing outside this browser
session. For every element it touches we derive the locator a careful engineer would
write, in Playwright's recommended priority order (test id, role + name, label,
placeholder, text), and keep the first one that resolves to exactly that element.
Duplicates such as one "Add to cart" button per product card are scoped to their
card; ``nth`` and finally a CSS path are last resorts.

A spec is a list of chained operations that renders to a live Playwright locator,
Python source or TypeScript source, so the agent's run and the test it leaves behind
use the very same selector.
"""

import json
from typing import Any

from playwright.async_api import Locator, Page

Op = dict[str, Any]
LocatorSpec = list[Op]

ROLE_LOCATABLE = {
    "button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox", "spinbutton", "slider",
    "switch", "tab", "menuitem", "option", "listbox", "heading", "img", "dialog", "alert",
}
FIELD_ROLES = {"textbox", "searchbox", "combobox", "spinbutton", "checkbox", "radio", "slider", "switch", "listbox"}

_MATCH_JS = "(els, ref) => [els.length, els.findIndex((e) => e.getAttribute('data-qa-ref') === ref)]"
_CSS_PATH_JS = """(el) => {
  const parts = [];
  for (let node = el; node && node.nodeType === 1 && node !== document.body; node = node.parentElement) {
    if (node.id) { parts.unshift('#' + CSS.escape(node.id)); break; }
    let part = node.tagName.toLowerCase();
    const parent = node.parentElement;
    const same = parent ? [...parent.children].filter((c) => c.tagName === node.tagName) : [];
    if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
    parts.unshift(part);
  }
  return parts.join(' > ');
}"""


def _usable(name: str | None) -> bool:
    # Names the snapshot clipped with an ellipsis would never match exactly.
    return bool(name) and not name.endswith("…")


def candidates(info: dict[str, Any]) -> list[LocatorSpec]:
    role, name = info.get("role"), info.get("name")
    out: list[LocatorSpec] = []
    if info.get("test_id"):
        out.append([{"op": "test_id", "value": info["test_id"]}])
    if role in ROLE_LOCATABLE and _usable(name):
        out.append([{"op": "role", "role": role, "name": name, "exact": True}])
    if role in FIELD_ROLES and info.get("label"):
        out.append([{"op": "label", "value": info["label"], "exact": True}])
    if role in FIELD_ROLES and info.get("placeholder"):
        out.append([{"op": "placeholder", "value": info["placeholder"], "exact": True}])
    if role == "text" and _usable(name):
        out.append([{"op": "text", "value": name, "exact": True}])
    return out


def scope_variants(scope: dict[str, Any] | None) -> list[LocatorSpec]:
    if not scope:
        return []
    variants: list[LocatorSpec] = []
    if scope.get("test_id"):
        variants.append([{"op": "test_id", "value": scope["test_id"]}])
    if scope.get("css") and scope.get("has_text"):
        variants.append([{"op": "css", "value": scope["css"]}, {"op": "filter", "has_text": scope["has_text"]}])
    return variants


def described(*, role: str | None = None, name: str | None = None, text: str | None = None) -> LocatorSpec:
    """A locator for an element the agent expects to exist but that may not be on the page."""
    if text:
        return [{"op": "text", "value": text}]
    op: Op = {"op": "role", "role": role}
    if name:
        op["name"] = name
    return [op]


def to_runtime(page: Page, spec: LocatorSpec) -> Locator:
    loc: Any = page
    for op in spec:
        match op["op"]:
            case "test_id":
                loc = loc.get_by_test_id(op["value"])
            case "role":
                kwargs: dict[str, Any] = {}
                if op.get("name"):
                    kwargs["name"] = op["name"]
                    kwargs["exact"] = bool(op.get("exact"))
                loc = loc.get_by_role(op["role"], **kwargs)
            case "label":
                loc = loc.get_by_label(op["value"], exact=bool(op.get("exact")))
            case "placeholder":
                loc = loc.get_by_placeholder(op["value"], exact=bool(op.get("exact")))
            case "text":
                loc = loc.get_by_text(op["value"], exact=bool(op.get("exact")))
            case "css":
                loc = loc.locator(op["value"])
            case "filter":
                loc = loc.filter(has_text=op["has_text"])
            case "nth":
                loc = loc.nth(op["index"])
            case "first":
                loc = loc.first
            case other:
                raise ValueError(f"Unknown locator op: {other}")
    return loc


async def _match(page: Page, spec: LocatorSpec, ref: str) -> tuple[int, int]:
    count, index = await to_runtime(page, spec).evaluate_all(_MATCH_JS, ref)
    return int(count), int(index)


async def build_spec(page: Page, ref: str, info: dict[str, Any]) -> LocatorSpec:
    """The most readable locator that resolves to exactly the element behind ``ref``."""
    scopes = scope_variants(info.get("scope"))
    fallbacks: list[LocatorSpec] = []
    for cand in candidates(info):
        count, index = await _match(page, cand, ref)
        if count == 1 and index == 0:
            return cand
        if index < 0:
            continue  # our name computation disagreed with Playwright's; try the next strategy
        for scope in scopes:
            scoped = [*scope, *cand]
            s_count, s_index = await _match(page, scoped, ref)
            if s_count == 1 and s_index == 0:
                return scoped
            if s_index >= 0:
                fallbacks.append([*scoped, {"op": "nth", "index": s_index}])
        fallbacks.append([*cand, {"op": "nth", "index": index}])
    if fallbacks:
        return fallbacks[0]
    css = await page.locator(f'[data-qa-ref="{ref}"]').evaluate(_CSS_PATH_JS)
    return [{"op": "css", "value": css}]


# --- source rendering -------------------------------------------------------------


def py_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def ts_str(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
        .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    )
    return f"'{escaped}'"


def render_py(spec: LocatorSpec, root: str = "page") -> str:
    parts = [root]
    for op in spec:
        match op["op"]:
            case "test_id":
                parts.append(f"get_by_test_id({py_str(op['value'])})")
            case "role":
                args = [py_str(op["role"])]
                if op.get("name"):
                    args.append(f"name={py_str(op['name'])}")
                    if op.get("exact"):
                        args.append("exact=True")
                parts.append(f"get_by_role({', '.join(args)})")
            case "label" | "placeholder" | "text":
                method = {"label": "get_by_label", "placeholder": "get_by_placeholder", "text": "get_by_text"}[op["op"]]
                exact = ", exact=True" if op.get("exact") else ""
                parts.append(f"{method}({py_str(op['value'])}{exact})")
            case "css":
                parts.append(f"locator({py_str(op['value'])})")
            case "filter":
                parts.append(f"filter(has_text={py_str(op['has_text'])})")
            case "nth":
                parts.append(f"nth({op['index']})")
            case "first":
                parts.append("first")
    return ".".join(parts)


def render_ts(spec: LocatorSpec, root: str = "page") -> str:
    parts = [root]
    for op in spec:
        match op["op"]:
            case "test_id":
                parts.append(f"getByTestId({ts_str(op['value'])})")
            case "role":
                opts = ""
                if op.get("name"):
                    exact = ", exact: true" if op.get("exact") else ""
                    opts = f", {{ name: {ts_str(op['name'])}{exact} }}"
                parts.append(f"getByRole({ts_str(op['role'])}{opts})")
            case "label" | "placeholder" | "text":
                method = {"label": "getByLabel", "placeholder": "getByPlaceholder", "text": "getByText"}[op["op"]]
                exact = ", { exact: true }" if op.get("exact") else ""
                parts.append(f"{method}({ts_str(op['value'])}{exact})")
            case "css":
                parts.append(f"locator({ts_str(op['value'])})")
            case "filter":
                parts.append(f"filter({{ hasText: {ts_str(op['has_text'])} }})")
            case "nth":
                parts.append(f"nth({op['index']})")
            case "first":
                parts.append("first()")
    return ".".join(parts)
