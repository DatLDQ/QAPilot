"""Offline demo agent: a scripted QA session that needs no API key.

``DemoLLM`` implements the same ``LLMClient`` protocol as ``ClaudeLLM``, so the whole
pipeline (real browser, recorder, generated tests, verification, reports) runs for
real. Only the decisions are scripted: each playbook step reads refs out of the
latest page outline, and it reports a bug only when a check actually failed. Point it
at ``/shop-fixed/`` and every check passes; at ``/shop/`` it finds the seeded bugs.
"""

import asyncio
import itertools
import re
from collections.abc import AsyncIterator, Generator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .llm import LLMEvent, LLMTurn

DEMO_MODEL = "demo-offline"
_ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
_LINE = re.compile(r'^(\s*)- ([a-z]+)(?: "((?:[^"\\]|\\.)*)")?(.*?)(?: \[ref=(e\d+)\])?$')


@dataclass
class Entry:
    role: str
    name: str
    ref: str | None
    attrs: str


@dataclass
class Act:
    """One scripted assistant turn: some reasoning, a line of narration and tool calls."""

    thinking: str
    text: str
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


class Missing(LookupError):
    """The page does not look the way the playbook expected."""


class Observation:
    """What the agent saw last: the tool results of the previous turn.

    Assertions return no outline, so the latest page outline carries over from earlier
    turns, just as a model remembers the last snapshot it read.
    """

    def __init__(self, text: str, previous: "Observation | None" = None):
        self.text = text
        idx = text.rfind("Page: ")
        self.entries: list[Entry] = []
        if idx < 0:
            self.entries = previous.entries if previous else []
            return
        for line in text[idx:].splitlines()[1:]:
            m = _LINE.match(line)
            if m:
                name = m.group(3) or ""
                self.entries.append(Entry(m.group(2), name.replace('\\"', '"'), m.group(5), m.group(4)))

    @property
    def failed(self) -> bool:
        return "✗ FAILED" in self.text

    @property
    def errored(self) -> bool:
        return "✗ " in self.text and not self.failed

    def find(self, role: str, name: str | None = None, *, after: tuple[str, str] | None = None,
             contains: bool = False) -> str:
        start = 0
        if after is not None:
            start = next((i + 1 for i, e in enumerate(self.entries) if e.role == after[0] and e.name == after[1]), -1)
            if start < 0:
                raise Missing(f"{after[0]} {after[1]!r}")
        for e in self.entries[start:]:
            if e.role != role or e.ref is None:
                continue
            if name is None or e.name == name or (contains and name.lower() in e.name.lower()):
                return e.ref
        raise Missing(f"{role} {name!r}" if name else role)

    def has(self, role: str, name: str) -> bool:
        return any(e.role == role and e.name == name for e in self.entries)

    def links(self) -> list[Entry]:
        return [e for e in self.entries if e.role == "link" and e.ref and e.name]


Playbook = Generator[Act, Observation, None]


def _expect(assertion: str, description: str, **target: str) -> tuple[str, dict[str, Any]]:
    return "expect", {"assertion": assertion, "description": description, **target}


def _fail_note(obs: Observation) -> str:
    m = re.search(r"Actual: (.+)", obs.text)
    return m.group(1).strip("'\"") if m else "the check failed"


# --- Larkspur Goods (the bundled demo shop) ---------------------------------------------


def shop_playbook(base: str) -> Playbook:
    bugs: list[str] = []
    skipped: list[str] = []

    def add_and_open_cart(obs: Observation, *products: str) -> Act:
        calls = [("click", {"ref": obs.find("button", "Add to cart", after=("heading", p)),
                            "description": f"Add {p} to cart"}) for p in products]
        calls.append(("click", {"ref": obs.find("link", "Cart", contains=True), "description": "Open the cart"}))
        return Act("Product cards don't re-render when I add items, so these refs stay valid for the whole batch.",
                   f"Adding {', '.join(products)} and opening the cart.", calls)

    def search() -> Playbook:
        obs = yield Act(
            "The user story starts with finding a product. Shoppers rarely match capitalisation, so lower-case "
            "search is the first thing to try.",
            "Scenario 1: search should ignore letter case.",
            [("begin_scenario", {"name": "Search finds products regardless of letter case"})],
        )
        obs = yield Act(
            "There is one product named Ceramic Mug, so searching 'mug' should leave exactly one card.",
            "Searching for “mug” in lower case.",
            [("fill", {"ref": obs.find("searchbox", "Search products"), "value": "mug",
                       "description": "Search for 'mug'"})],
        )
        obs = yield Act(
            "Assert the correct outcome, not what I see: one result.",
            "",
            [_expect("text_equals", "Result count shows 1 product", ref=obs.find("text", "product", contains=True),
                     expected="1 product")],
        )
        if obs.failed:
            yield Act(
                f"The count reads {_fail_note(obs)}: lower-case 'mug' does not match 'Ceramic Mug'. That's a real "
                "defect; search is the main way into the catalogue.",
                "Search is case-sensitive. Filing it.",
                [("report_bug", {
                    "title": "Product search is case-sensitive",
                    "severity": "high", "category": "functional",
                    "steps_to_reproduce": ["Open the shop", "Type 'mug' in Search products"],
                    "expected": "Ceramic Mug is listed (1 product)",
                    "actual": f"No products match ({_fail_note(obs)})",
                })],
            )
            bugs.append("search")

    def cart_math() -> Playbook:
        obs = yield Act(
            "Next, the cart. Quantities greater than one are where totals usually go wrong.",
            "Scenario 2: cart totals should account for quantity.",
            [("begin_scenario", {"name": "Cart subtotal multiplies price by quantity"})],
        )
        obs = yield add_and_open_cart(obs, "Ceramic Mug", "Ceramic Mug", "Canvas Tote")
        obs = yield Act(
            "2 × $18.00 + $24.00 = $60.00. The mug line should be $36.00, and with no coupon the total equals the "
            "subtotal.",
            "Checking line total, subtotal and total against hand-computed values.",
            [
                _expect("text_equals", "Ceramic Mug line total is $36.00",
                        ref=obs.find("text", after=("button", "Increase quantity of Ceramic Mug")), expected="$36.00"),
                _expect("text_equals", "Subtotal is $60.00", ref=obs.find("text", after=("text", "Subtotal")),
                        expected="$60.00"),
                _expect("text_equals", "Total is $60.00", ref=obs.find("text", after=("text", "Total")),
                        expected="$60.00"),
            ],
        )
        if obs.failed:
            yield Act(
                "The line total is right but the subtotal isn't: it looks like each product's price is counted once, "
                "whatever the quantity. Customers would be undercharged.",
                "The subtotal ignores quantities. Filing a critical bug.",
                [("report_bug", {
                    "title": "Cart subtotal ignores item quantities",
                    "severity": "critical", "category": "functional",
                    "steps_to_reproduce": ["Add Ceramic Mug to the cart twice", "Add Canvas Tote", "Open the cart"],
                    "expected": "Subtotal and total are $60.00 (2 × $18.00 + $24.00)",
                    "actual": f"Subtotal shows {_fail_note(obs)}",
                    "evidence": "Line totals are correct, so only the summary calculation is wrong.",
                })],
            )
            bugs.append("subtotal")

    def coupon() -> Playbook:
        obs = yield Act(
            "Coupons are a classic place for stacking bugs: apply the same code twice and watch the discount.",
            "Scenario 3: SAVE10 should only apply once.",
            [("begin_scenario", {"name": "Coupon SAVE10 applies 10% once"})],
        )
        obs = yield add_and_open_cart(obs, "Pour-Over Kettle")
        obs = yield Act(
            "Kettle is $54.00, so 10% off is $5.40.",
            "Applying SAVE10.",
            [("fill", {"ref": obs.find("textbox", "Coupon code"), "value": "SAVE10",
                       "description": "Enter coupon SAVE10"}),
             ("click", {"ref": obs.find("button", "Apply"), "description": "Apply the coupon"})],
        )
        obs = yield Act(
            "", "",
            [_expect("text_equals", "Discount is -$5.40", ref=obs.find("text", after=("text", "Discount")),
                     expected="-$5.40")],
        )
        obs = yield Act(
            "First application looks right. Now the same code again.",
            "Applying SAVE10 a second time.",
            [("fill", {"ref": obs.find("textbox", "Coupon code"), "value": "SAVE10",
                       "description": "Enter coupon SAVE10 again"}),
             ("click", {"ref": obs.find("button", "Apply"), "description": "Apply the coupon again"})],
        )
        obs = yield Act(
            "The discount must not grow: still -$5.40, total $48.60.",
            "",
            [_expect("text_equals", "Discount is still -$5.40", ref=obs.find("text", after=("text", "Discount")),
                     expected="-$5.40"),
             _expect("text_equals", "Total is $48.60", ref=obs.find("text", after=("text", "Total")),
                     expected="$48.60")],
        )
        if obs.failed:
            yield Act(
                "Each Apply adds another 10%. Repeat it ten times and the order is free.",
                "The coupon stacks. Filing it.",
                [("report_bug", {
                    "title": "Re-applying coupon SAVE10 stacks the discount",
                    "severity": "high", "category": "functional",
                    "steps_to_reproduce": ["Add Pour-Over Kettle to the cart", "Open the cart",
                                           "Apply coupon SAVE10", "Apply coupon SAVE10 again"],
                    "expected": "The discount stays at 10% (-$5.40); the second attempt is rejected",
                    "actual": f"The discount grows with every apply ({_fail_note(obs)})",
                })],
            )
            bugs.append("coupon")

    def remove_a11y() -> Playbook:
        obs = yield Act(
            "Icon-only buttons often ship without an accessible name. Screen-reader users need to know which item a "
            "remove button removes.",
            "Scenario 4: cart controls should have accessible names.",
            [("begin_scenario", {"name": "Remove button has an accessible name"})],
        )
        obs = yield add_and_open_cart(obs, "Ceramic Mug")
        unnamed = any(e.role == "button" and not e.name for e in obs.entries)
        obs = yield Act(
            "The outline shows a button with no accessible name next to the quantity controls."
            if unnamed else "Checking the remove control is announced properly.",
            "",
            [_expect("visible", "A 'Remove Ceramic Mug' button is available", role="button",
                     name="Remove Ceramic Mug")],
        )
        if obs.failed:
            yield Act(
                "Confirmed: the trash icon is an unlabeled button. Assistive tech announces just 'button'.",
                "Filing an accessibility bug.",
                [("report_bug", {
                    "title": "Remove-item button has no accessible name",
                    "severity": "medium", "category": "accessibility",
                    "steps_to_reproduce": ["Add Ceramic Mug to the cart", "Open the cart",
                                           "Inspect the trash-icon button with a screen reader"],
                    "expected": "The button is announced as 'Remove Ceramic Mug'",
                    "actual": "The button has no accessible name (WCAG 4.1.2 Name, Role, Value)",
                })],
            )
            bugs.append("a11y")

    def checkout_form(obs: Observation, email: str) -> Act:
        return Act(
            "Using obviously fake test data. Filling the form doesn't re-render it, so one batch is safe.",
            f"Filling the checkout form with email “{email}”.",
            [("fill", {"ref": obs.find("textbox", "Full name"), "value": "Test Shopper", "description": "Enter name"}),
             ("fill", {"ref": obs.find("textbox", "Email"), "value": email, "description": "Enter email"}),
             ("fill", {"ref": obs.find("textbox", "Shipping address"), "value": "1 Test Street, Springfield",
                       "description": "Enter shipping address"})],
        )

    def email_validation() -> Playbook:
        obs = yield Act(
            "Form validation: an address without a domain must be rejected before an order is placed.",
            "Scenario 5: checkout should reject an invalid email.",
            [("begin_scenario", {"name": "Checkout rejects an email without a domain"})],
        )
        obs = yield add_and_open_cart(obs, "Dot Grid Notebook")
        obs = yield Act("", "Going to checkout.",
                        [("click", {"ref": obs.find("link", "Checkout"), "description": "Go to checkout"})])
        obs = yield checkout_form(obs, "test.shopper@")
        obs = yield Act(
            "", "Submitting.",
            [("click", {"ref": obs.find("button", "Place order"), "description": "Place the order"})],
        )
        obs = yield Act(
            "The right behaviour is an inline error and no order.",
            "",
            [_expect("visible", "An 'Enter a valid email address.' error is shown",
                     text="Enter a valid email address."),
             _expect("url_contains", "The shopper stays on checkout", expected="#/checkout")],
        )
        if obs.failed:
            yield Act(
                "The order went through with 'test.shopper@'. The confirmation email can never arrive.",
                "Invalid email accepted. Filing it.",
                [("report_bug", {
                    "title": "Checkout accepts an email address without a domain",
                    "severity": "high", "category": "validation",
                    "steps_to_reproduce": ["Add Dot Grid Notebook to the cart", "Open checkout",
                                           "Fill name and address, enter email 'test.shopper@'", "Click Place order"],
                    "expected": "An inline 'Enter a valid email address.' error; no order is created",
                    "actual": "The order is placed and the confirmation page is shown",
                })],
            )
            bugs.append("email")

    def express_shipping() -> Playbook:
        obs = yield Act(
            "Every shipping option should be purchasable. Standard is the default path; Express is the one that "
            "tends to be forgotten.",
            "Scenario 6: an order with Express shipping should go through.",
            [("begin_scenario", {"name": "Order with Express shipping can be placed"})],
        )
        obs = yield add_and_open_cart(obs, "Desk Plant")
        obs = yield Act("", "Going to checkout.",
                        [("click", {"ref": obs.find("link", "Checkout"), "description": "Go to checkout"})])
        act = checkout_form(obs, "test.shopper@example.com")
        act.calls.append(("select_option", {"ref": obs.find("combobox", "Shipping"), "option": "Express",
                                            "description": "Choose Express shipping"}))
        obs = yield act
        obs = yield Act(
            "$32.50 + $15.00 Express = $47.50.",
            "",
            [_expect("text_equals", "Total with Express shipping is $47.50",
                     ref=obs.find("text", after=("text", "Total")), expected="$47.50")],
        )
        obs = yield Act(
            "", "Placing the order.",
            [("click", {"ref": obs.find("button", "Place order"), "description": "Place the order"}),
             _expect("url_contains", "The order confirmation page opens", expected="#/order/")],
        )
        if obs.failed:
            obs = yield Act(
                "Still on checkout. Let me see what the API said.",
                "Checking the network log for the failed request.",
                [("inspect_network", {"url_contains": "api/checkout", "only_failed": True})],
            )
            status = re.search(r"→ (\d{3})", obs.text)
            yield Act(
                "The checkout request failed on the server. The client shows a generic retry banner, but retrying "
                "can never succeed.",
                "Express orders fail server-side. Filing a critical bug.",
                [("report_bug", {
                    "title": "Placing an order with Express shipping fails with HTTP 500",
                    "severity": "critical", "category": "network",
                    "steps_to_reproduce": ["Add Desk Plant to the cart", "Open checkout", "Fill in valid details",
                                           "Choose Express shipping", "Click Place order"],
                    "expected": "The order is placed and the confirmation page opens",
                    "actual": "An error banner appears and no order is created",
                    "evidence": f"POST api/checkout → {status.group(1) if status else 'error'}",
                })],
            )
            bugs.append("express")

    def details_dialog() -> Playbook:
        obs = yield Act(
            "Product details are data-driven; an item with missing data is a good edge case. Wool Socks has no "
            "rating shown anywhere yet.",
            "Scenario 7: details should open for every product, including one without reviews.",
            [("begin_scenario", {"name": "Details dialog opens for a product without reviews"})],
        )
        obs = yield Act(
            "", "Opening Wool Socks details.",
            [("click", {"ref": obs.find("button", "Details", after=("heading", "Wool Socks")),
                        "description": "Open Wool Socks details"})],
        )
        obs = yield Act(
            "A dialog should open and nothing should throw.",
            "",
            [_expect("visible", "The Wool Socks details dialog opens", role="dialog", name="Wool Socks"),
             _expect("no_console_errors", "No console errors or uncaught exceptions")],
        )
        if obs.failed:
            yield Act(
                "Nothing opened and an uncaught TypeError was logged: the dialog code assumes every product has a "
                "reviews list.",
                "Details crash for products without reviews. Filing it.",
                [("report_bug", {
                    "title": "Details for a product without reviews throws a TypeError",
                    "severity": "medium", "category": "console",
                    "steps_to_reproduce": ["Open the shop", "Click Details on Wool Socks"],
                    "expected": "The details dialog opens and shows 'No reviews yet'",
                    "actual": "Nothing opens; an uncaught TypeError is thrown",
                })],
            )
            bugs.append("details")

    for scenario in (search, cart_math, coupon, remove_a11y, email_validation, express_shipping, details_dialog):
        try:
            yield from scenario()
        except Missing as exc:
            skipped.append(f"{scenario.__name__.replace('_', ' ')} (could not find {exc})")

    if bugs:
        summary = (f"Browsing, search, cart, coupon and checkout were exercised in 7 scenarios. Found {len(bugs)} "
                   "defects: the most serious are wrong cart totals and Express orders failing on the server, both "
                   "of which block or corrupt purchases. Risk is high until those two are fixed.")
    else:
        summary = ("Browsing, search, cart, coupon and checkout were exercised in 7 scenarios and every check passed. "
                   "No defects found in the covered flows.")
    untested = "; ".join(skipped) if skipped else "Payment providers, accounts and mobile layouts are out of scope."
    yield Act("Coverage is complete for the story. Wrapping up.", "Done. Writing the summary.",
              [("finish", {"summary": summary, "untested": untested})])


# --- any other site: a generic smoke test ---------------------------------------------------


def smoke_playbook(base: str) -> Playbook:
    obs = yield Act(
        "No site-specific script for this target, so I'll run a smoke test: the home page and a few internal links "
        "should render without errors.",
        "Scenario 1: the start page should load cleanly.",
        [("begin_scenario", {"name": "Start page loads without errors"})],
    )
    host = urlparse(base).netloc
    links = [e for e in obs.links() if not e.attrs or "href=\"http" not in e.attrs or host in e.attrs][:3]
    headings = [e for e in obs.entries if e.role == "heading" and e.ref]
    calls = [_expect("no_console_errors", "No console errors on load")]
    if headings:
        calls.insert(0, _expect("visible", f"Heading '{headings[0].name}' is visible", ref=headings[0].ref))
    obs = yield Act("", "", calls)
    found = 0
    if obs.failed:
        found += 1
        yield Act("The start page logs errors on load.", "Filing it.", [("report_bug", {
            "title": "Start page logs console errors on load", "severity": "medium", "category": "console",
            "steps_to_reproduce": [f"Open {base}"], "expected": "No console errors",
            "actual": _fail_note(obs)})])
    for link in links:
        obs = yield Act("", f"Following the “{link.name}” link.",
                        [("begin_scenario", {"name": f"'{link.name}' link opens without errors"})])
        try:
            ref = obs.find("link", link.name)
        except Missing:
            continue
        obs = yield Act("", "", [("click", {"ref": ref, "description": f"Click the '{link.name}' link"})])
        if obs.errored:
            continue
        obs = yield Act("", "", [_expect("no_console_errors", f"No console errors after opening '{link.name}'")])
        if obs.failed:
            found += 1
            yield Act("", "Filing it.", [("report_bug", {
                "title": f"Console errors after opening '{link.name}'", "severity": "medium", "category": "console",
                "steps_to_reproduce": [f"Open {base}", f"Click '{link.name}'"], "expected": "No console errors",
                "actual": _fail_note(obs)})])
    summary = (f"Smoke-tested the start page and {len(links)} internal link(s). "
               + (f"Found {found} issue(s)." if found else "No errors were observed."))
    yield Act("", "Done.", [("finish", {
        "summary": summary,
        "untested": "Offline demo mode runs a generic smoke test on unknown sites. Set ANTHROPIC_API_KEY "
                    "(or GEMINI_API_KEY) for a full exploratory session."})])


def pick_playbook(target_url: str) -> Playbook:
    path = urlparse(target_url).path
    if re.search(r"/shop(-fixed)?/?$", path):
        return shop_playbook(target_url)
    return smoke_playbook(target_url)


# --- the client --------------------------------------------------------------------------


def _last_observation(messages: list[dict[str, Any]], previous: Observation | None) -> Observation:
    last = messages[-1] if messages else {}
    parts: list[str] = []
    for block in last.get("content", []):
        if block.get("type") != "tool_result":
            continue
        content = block.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(b.get("text", "") for b in content if b.get("type") == "text")
    return Observation("\n".join(parts), previous)


def _chunks(text: str, size: int = 18) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


class DemoLLM:
    """Plays a scripted QA session through the ``LLMClient`` protocol."""

    model = DEMO_MODEL

    def __init__(self, target_url: str, *, delay: float = 0.012):
        self._playbook = pick_playbook(target_url)
        self._started = False
        self._seen: Observation | None = None
        self._ids = itertools.count(1)
        self._delay = delay

    def _next(self, messages: list[dict[str, Any]]) -> Act | None:
        try:
            if not self._started:
                self._started = True
                return next(self._playbook)
            self._seen = _last_observation(messages, self._seen)
            return self._playbook.send(self._seen)
        except StopIteration:
            return None

    async def stream(
        self, *, system: str, tools: list[dict], messages: list[dict], tool_choice: dict | None = None
    ) -> AsyncIterator[LLMEvent | LLMTurn]:
        act = None if tool_choice == {"type": "none"} else self._next(messages)
        if act is None:
            act = Act("", "Session complete.")
        content: list[dict[str, Any]] = []
        if act.thinking:
            yield LLMEvent("thinking_start")
            for piece in _chunks(act.thinking):
                yield LLMEvent("thinking_delta", {"text": piece})
                await asyncio.sleep(self._delay)
            content.append({"type": "thinking", "thinking": act.thinking, "signature": ""})
        if act.text:
            yield LLMEvent("text_start")
            for piece in _chunks(act.text):
                yield LLMEvent("text_delta", {"text": piece})
                await asyncio.sleep(self._delay)
            content.append({"type": "text", "text": act.text})
        for name, data in act.calls:
            block_id = f"toolu_demo_{next(self._ids):03d}"
            yield LLMEvent("tool_use_start", {"id": block_id, "name": name})
            await asyncio.sleep(self._delay * 4)
            content.append({"type": "tool_use", "id": block_id, "name": name, "input": data})
        yield LLMTurn(
            content=content,
            stop_reason="tool_use" if act.calls else "end_turn",
            model=DEMO_MODEL,
            usage=dict(_ZERO_USAGE),
        )
