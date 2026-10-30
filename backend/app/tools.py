"""The QA agent's tools: browser actions, assertions, evidence and bug reports.

Every successful action is recorded as a test step, so the run itself becomes the
regression suite. Tool inputs stream eagerly, which means the API no longer validates
them for us: ``validate_input`` checks each one against its schema before it runs.
"""

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .browser import ActionResult, BrowserBridge, BrowserError, BrowserSession, CheckResult, Signal
from .locators import described, render_ts
from .recorder import CATEGORIES, SEVERITIES, Recorder

ASSERTIONS = (
    "visible", "hidden", "text_equals", "text_contains", "value_equals", "checked", "unchecked",
    "enabled", "disabled", "count_equals", "url_contains", "title_contains", "no_console_errors",
)
NEEDS_EXPECTED = {"text_equals", "text_contains", "value_equals", "count_equals", "url_contains", "title_contains"}
PAGE_LEVEL = {"url_contains", "title_contains", "no_console_errors"}

_REF = {"type": "string", "description": "Element ref from the latest snapshot, e.g. e12."}
_DESC = {
    "type": "string",
    "description": "Short imperative description of the step as a user would say it, e.g. 'Add Ceramic Mug to cart'. "
    "Becomes the step label in the generated test.",
}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": properties, "required": required},
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool(
        "begin_scenario",
        "Start a new, independent test scenario: clears cookies and storage, then opens start_url (default: the "
        "target URL) and returns the page outline. Later steps belong to it until the next begin_scenario. Name it "
        "after the behaviour it verifies, e.g. 'Coupon can only be applied once'. Each scenario becomes one test.",
        {
            "name": {"type": "string", "description": "Behaviour under test, phrased as the expected outcome."},
            "start_url": {"type": "string", "description": "Optional absolute URL on the target host."},
        },
        ["name"],
    ),
    _tool(
        "navigate",
        "Open a URL in the current tab (only the target host is allowed). Returns the page outline.",
        {"url": {"type": "string", "description": "Absolute http(s) URL."}},
        ["url"],
    ),
    _tool("click", "Click an element. Returns the updated page outline and new signals.",
          {"ref": _REF, "description": _DESC}, ["ref", "description"]),
    _tool(
        "fill",
        "Replace the contents of a text field (input, textarea, contenteditable) with value.",
        {"ref": _REF, "value": {"type": "string"}, "description": _DESC},
        ["ref", "value", "description"],
    ),
    _tool(
        "select_option",
        "Choose an option of a <select> by its visible label (or value).",
        {"ref": _REF, "option": {"type": "string"}, "description": _DESC},
        ["ref", "option", "description"],
    ),
    _tool(
        "set_checked",
        "Check or uncheck a checkbox, radio button or switch.",
        {"ref": _REF, "checked": {"type": "boolean"}, "description": _DESC},
        ["ref", "checked", "description"],
    ),
    _tool(
        "press_key",
        "Press a key such as Enter, Tab, Escape or ArrowDown, optionally focused on an element first.",
        {"key": {"type": "string"}, "ref": _REF, "description": _DESC},
        ["key", "description"],
    ),
    _tool("hover", "Move the mouse over an element (menus, tooltips).", {"ref": _REF, "description": _DESC},
          ["ref", "description"]),
    _tool(
        "snapshot",
        "Return a fresh page outline, optionally after waiting (for loading states or animations).",
        {"wait_seconds": {"type": "number", "description": "0 to 5 seconds."}},
        [],
    ),
    _tool(
        "screenshot",
        "Look at the page, or one element, as an image. Use it for layout, overlap, styling and rendering issues the "
        "outline cannot show. It costs more than the outline, so use it deliberately.",
        {"ref": _REF, "full_page": {"type": "boolean"}},
        [],
    ),
    _tool(
        "expect",
        "Record an assertion of the correct, expected behaviour and evaluate it now (auto-waits about 2.5s). "
        "Target an element with ref, or describe one that should exist with role (+ optional name) or text. "
        "Page-level assertions (url_contains, title_contains, no_console_errors) need no target. "
        "A failure is recorded as a failing check in the generated test: state what SHOULD happen, never the buggy "
        "value you observe. The replay may run it before a navigation or update finishes, so assert something only the "
        "expected state shows (url_contains, the destination's heading by role), never text the previous page also "
        "had. no_console_errors checks console errors and uncaught exceptions since the scenario began.",
        {
            "assertion": {"type": "string", "enum": list(ASSERTIONS)},
            "ref": _REF,
            "role": {"type": "string", "description": "ARIA role, e.g. heading, button, alert, dialog, article."},
            "name": {"type": "string", "description": "Accessible name to match (substring, case-insensitive)."},
            "text": {"type": "string", "description": "Visible text to match (substring, case-insensitive)."},
            "expected": {"type": "string", "description": "Expected text, value, URL/title fragment, or count."},
            "description": {"type": "string", "description": "What should be true, e.g. 'Subtotal is $36.00'."},
        },
        ["assertion", "description"],
    ),
    _tool(
        "inspect_network",
        "List recent document/fetch/XHR requests with status codes and truncated request/response bodies.",
        {
            "url_contains": {"type": "string"},
            "only_failed": {"type": "boolean", "description": "Only HTTP status >= 400."},
        },
        [],
    ),
    _tool(
        "report_bug",
        "File one distinct defect you have confirmed, with exact reproduction steps. It needs a failing `expect` in "
        "the current scenario that captures the defect, so the generated regression test fails on it: assert the "
        "correct behaviour first, then report. Those failing checks are linked to the bug, and a screenshot of the "
        "current page is attached automatically.",
        {
            "title": {
                "type": "string", "description": "Specific and searchable, e.g. 'Cart subtotal ignores quantity'."
            },
            "severity": {"type": "string", "enum": list(SEVERITIES)},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "steps_to_reproduce": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "expected": {"type": "string"},
            "actual": {"type": "string"},
            "evidence": {"type": "string", "description": "Signals, requests or observations that support it."},
            "untestable_reason": {
                "type": "string",
                "description": "Only when no expect assertion can capture the defect (e.g. a wrong product image "
                "or broken layout): say why. The bug is then filed without a regression test.",
            },
        },
        ["title", "severity", "category", "steps_to_reproduce", "expected", "actual"],
    ),
    _tool(
        "finish",
        "End the session once the story is covered (or the budget is nearly spent).",
        {
            "summary": {"type": "string", "description": "2-5 sentences: what works, what is broken, overall risk."},
            "untested": {"type": "string", "description": "Anything you could not cover and why."},
        },
        ["summary"],
    ),
]

_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOL_DEFINITIONS}
_PY_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "boolean": (bool,),
    "number": (int, float),
    "integer": (int,),
    "array": (list,),
}


def validate_input(name: str, data: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Check a (possibly truncated) streamed tool input against the tool's schema."""
    schema = _SCHEMAS.get(name)
    if schema is None:
        return None, f"Unknown tool {name!r}."
    if not isinstance(data, dict):
        return None, "Tool input must be a JSON object."
    props: dict[str, Any] = schema["properties"]
    clean: dict[str, Any] = {}
    for key, value in data.items():
        spec = props.get(key)
        if spec is None or value is None:
            continue  # ignore unknown keys rather than failing the whole call
        types = _PY_TYPES[spec["type"]]
        if not isinstance(value, types) or (spec["type"] in ("number", "integer") and isinstance(value, bool)):
            return None, f"'{key}' must be of type {spec['type']}."
        if "enum" in spec and value not in spec["enum"]:
            return None, f"'{key}' must be one of: {', '.join(spec['enum'])}."
        if spec["type"] == "array":
            if not all(isinstance(v, str) and v.strip() for v in value):
                return None, f"'{key}' must be a list of non-empty strings."
            if len(value) < spec.get("minItems", 0):
                return None, f"'{key}' needs at least {spec['minItems']} item(s)."
        clean[key] = value.strip() if isinstance(value, str) and key not in ("value",) else value
    for key in schema["required"]:
        if key not in clean or (isinstance(clean[key], str) and not clean[key] and key != "value"):
            return None, f"Missing required field '{key}'."
    return clean, None


@dataclass
class ToolOutcome:
    content: str | list[dict[str, Any]]
    is_error: bool = False
    summary: str = ""
    ui: dict[str, Any] = field(default_factory=dict)
    finished: bool = False


def _signals_text(signals: list[Signal]) -> str:
    if not signals:
        return ""
    return "Signals:\n" + "\n".join(f"  {s.format()}" for s in signals[:12]) + "\n"


class QAToolExecutor:
    """Runs tool calls against one browser session and records them as test steps."""

    def __init__(self, bridge: BrowserBridge, session: BrowserSession, recorder: Recorder):
        self.bridge = bridge
        self.session = session
        self.recorder = recorder
        self._handlers: dict[str, Callable[..., Any]] = {
            "begin_scenario": self._begin_scenario,
            "navigate": self._navigate,
            "click": self._click,
            "fill": self._fill,
            "select_option": self._select_option,
            "set_checked": self._set_checked,
            "press_key": self._press_key,
            "hover": self._hover,
            "snapshot": self._snapshot,
            "screenshot": self._screenshot,
            "expect": self._expect,
            "inspect_network": self._inspect_network,
            "report_bug": self._report_bug,
            "finish": self._finish,
        }

    async def execute(self, name: str, raw_input: Any) -> ToolOutcome:
        data, error = validate_input(name, raw_input)
        if error is not None or data is None:
            return ToolOutcome(content=f"Invalid input for {name}: {error}", is_error=True, summary=error or "")
        try:
            return await self._handlers[name](**data)
        except BrowserError as exc:
            text = f"✗ {name} failed: {exc}"
            if exc.snapshot is not None:
                text += "\n\n" + exc.snapshot.render()
            ui: dict[str, Any] = {"kind": "error"}
            if exc.snapshot is not None:
                ui["url"] = exc.snapshot.url
            return ToolOutcome(content=text, is_error=True, summary=str(exc).splitlines()[0], ui=ui)

    # --- helpers ----------------------------------------------------------------------

    @property
    def _signal_start(self) -> int:
        current = self.recorder.current
        return current.signal_start if current else 0

    def _action_outcome(self, headline: str, result: ActionResult, step_kind: str | None, description: str,
                        value: Any = None) -> ToolOutcome:
        step = None
        if step_kind is not None:
            step = self.recorder.add_step(
                self.session.last_signal_seq, kind=step_kind, description=description, locator=result.spec,
                value=value, screenshot=result.screenshot, url=result.snapshot.url,
            )
        locator = f"Locator: {render_ts(result.spec)}\n" if result.spec else ""
        status = f"HTTP status: {result.status}\n" if result.status and result.status >= 400 else ""
        text = f"✓ {headline}\n{locator}{status}{_signals_text(result.signals)}\n{result.snapshot.render()}"
        return ToolOutcome(
            content=text,
            summary=headline,
            ui={
                "kind": "action",
                "step": step.to_dict() if step else None,
                "scenario_id": self.recorder.current.id if self.recorder.current else None,
                "screenshot": result.screenshot,
                "url": result.snapshot.url,
                "title": result.snapshot.title,
                "signals": [s.to_dict() for s in result.signals],
            },
        )

    # --- tools ------------------------------------------------------------------------

    async def _begin_scenario(self, name: str, start_url: str | None = None) -> ToolOutcome:
        url = start_url or self.recorder.target_url
        signal_start = self.session.last_signal_seq
        result = await self.bridge.call(self.session.reset(url))
        scenario = self.recorder.begin(name, url, signal_start)
        outcome = self._action_outcome(f"Scenario {scenario.id} started: {scenario.name} (fresh storage)", result,
                                       None, "")
        outcome.ui.update({"kind": "scenario", "scenario": {"id": scenario.id, "name": scenario.name, "start_url": url},
                           "scenario_id": scenario.id})
        return outcome

    async def _navigate(self, url: str) -> ToolOutcome:
        result = await self.bridge.call(self.session.goto(url))
        return self._action_outcome(f"Opened {result.snapshot.url}", result, "goto", f"Open {url}", url)

    async def _click(self, ref: str, description: str) -> ToolOutcome:
        result = await self.bridge.call(self.session.act("click", ref))
        return self._action_outcome(f"click: {description}", result, "click", description)

    async def _fill(self, ref: str, value: str, description: str) -> ToolOutcome:
        result = await self.bridge.call(self.session.act("fill", ref, value))
        return self._action_outcome(f"fill {value!r}: {description}", result, "fill", description, value)

    async def _select_option(self, ref: str, option: str, description: str) -> ToolOutcome:
        result = await self.bridge.call(self.session.act("select", ref, option))
        return self._action_outcome(f"selected {result.value!r}: {description}", result, "select", description,
                                    result.value)

    async def _set_checked(self, ref: str, checked: bool, description: str) -> ToolOutcome:
        result = await self.bridge.call(self.session.act("check", ref, checked))
        verb = "checked" if checked else "unchecked"
        return self._action_outcome(f"{verb}: {description}", result, "check", description, checked)

    async def _press_key(self, key: str, description: str, ref: str | None = None) -> ToolOutcome:
        if ref:
            result = await self.bridge.call(self.session.act("press", ref, key))
        else:
            result = await self.bridge.call(self.session.press_page(key))
        return self._action_outcome(f"pressed {key}: {description}", result, "press", description, key)

    async def _hover(self, ref: str, description: str) -> ToolOutcome:
        result = await self.bridge.call(self.session.act("hover", ref))
        return self._action_outcome(f"hover: {description}", result, "hover", description)

    async def _snapshot(self, wait_seconds: float = 0.0) -> ToolOutcome:
        result = await self.bridge.call(self.session.wait(float(wait_seconds)))
        outcome = self._action_outcome("Fresh snapshot", result, None, "")
        outcome.ui["kind"] = "snapshot"
        return outcome

    async def _screenshot(self, ref: str | None = None, full_page: bool = False) -> ToolOutcome:
        rel, data = await self.bridge.call(self.session.capture(ref=ref, full_page=full_page))
        what = f"element {ref}" if ref else ("full page" if full_page else "viewport")
        content = [
            {"type": "text", "text": f"Screenshot of the {what}:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(data).decode()}},
        ]
        return ToolOutcome(content=content, summary=f"Captured {what}", ui={"kind": "screenshot", "screenshot": rel})

    async def _expect(
        self,
        assertion: str,
        description: str,
        ref: str | None = None,
        role: str | None = None,
        name: str | None = None,
        text: str | None = None,
        expected: str | None = None,
    ) -> ToolOutcome:
        if assertion in NEEDS_EXPECTED and not expected:
            return ToolOutcome(content=f"'{assertion}' needs an 'expected' value.", is_error=True,
                               summary="missing expected")
        if assertion == "count_equals" and not (expected or "").strip().isdigit():
            return ToolOutcome(content="count_equals needs a whole number in 'expected'.", is_error=True,
                               summary="bad count")
        target = None
        if assertion not in PAGE_LEVEL and ref is None:
            if not (role or text):
                return ToolOutcome(content="Give a ref, or describe the element with role (+ name) or text.",
                                   is_error=True, summary="missing target")
            target = described(role=role, name=name, text=text)
        if assertion == "count_equals" and ref is not None:
            return ToolOutcome(content="count_equals counts matches: describe the elements with role or text.",
                               is_error=True, summary="count needs a description")
        self.recorder.ensure_scenario(self.session.last_signal_seq)
        result: CheckResult = await self.bridge.call(
            self.session.check(assertion, ref=ref, target=target, expected=expected, since_seq=self._signal_start)
        )
        step = self.recorder.add_step(
            self.session.last_signal_seq, kind="expect", description=description, locator=result.spec,
            assertion=assertion, expected=expected, actual=result.actual, passed=result.passed,
            screenshot=result.screenshot, url=result.url,
        )
        exp = f" {expected!r}" if expected else ""
        if result.passed:
            text_out = f"✓ PASSED expect {assertion}{exp}: {description}"
        else:
            text_out = (
                f"✗ FAILED expect {assertion}{exp}: {description}\nActual: {result.actual!r}\n"
                "Recorded as a failing check. If this is a defect, confirm it and call report_bug."
            )
        text_out += "\n" + _signals_text(result.signals)
        return ToolOutcome(
            content=text_out.rstrip(),
            summary=("passed" if result.passed else "failed") + f": {description}",
            ui={
                "kind": "check",
                "step": step.to_dict(),
                "scenario_id": self.recorder.current.id if self.recorder.current else None,
                "screenshot": result.screenshot,
                "url": result.url,
                "signals": [s.to_dict() for s in result.signals],
            },
        )

    async def _inspect_network(self, url_contains: str | None = None, only_failed: bool = False) -> ToolOutcome:
        entries = await self.bridge.call(self.session.network_log(url_contains, only_failed))
        if not entries:
            return ToolOutcome(content="No matching requests recorded.", summary="no requests",
                               ui={"kind": "network", "entries": []})
        lines = []
        for e in entries:
            lines.append(f"{e['method']} {e['url']} → {e['status']} ({e['type']})")
            if e.get("request_body"):
                lines.append(f"    request: {e['request_body']}")
            if e.get("response_body"):
                lines.append(f"    response: {e['response_body']}")
        return ToolOutcome(content="\n".join(lines), summary=f"{len(entries)} request(s)",
                           ui={"kind": "network", "entries": entries})

    async def _report_bug(
        self,
        title: str,
        severity: str,
        category: str,
        steps_to_reproduce: list[str],
        expected: str,
        actual: str,
        evidence: str | None = None,
        untestable_reason: str | None = None,
    ) -> ToolOutcome:
        duplicate = next((b for b in self.recorder.bugs if b.title.lower() == title.lower()), None)
        if duplicate is not None:
            return ToolOutcome(content=f"{duplicate.id} already covers this ({duplicate.title}). Not filed again.",
                               summary=f"duplicate of {duplicate.id}")
        current = self.recorder.current
        if current is not None and current.unlinked_failed_checks:
            untestable_reason = None  # a failing check backs the bug, so it gets a real regression test
        elif not untestable_reason:
            # Without a failing check the generated test passes on this build and can never catch the bug.
            return ToolOutcome(
                content="Not filed: no failing check in the current scenario captures this defect, so its regression "
                "test would pass. Call expect to assert the correct behaviour (it should fail on this build), then "
                "call report_bug again. If no assertion can capture it, call report_bug again with untestable_reason.",
                is_error=True, summary="needs a failing check",
            )
        try:
            rel, _ = await self.bridge.call(self.session.capture())
        except BrowserError:
            rel = None
        signals = [s.format() for s in self.session.errors_since(current.signal_start if current else 0)][:8]
        bug = self.recorder.add_bug(
            title=title, severity=severity, category=category, steps_to_reproduce=steps_to_reproduce,
            expected=expected, actual=actual, url=self.session.page.url if self.session.page else "",
            screenshot=rel, evidence=evidence, signals=signals, untestable_reason=untestable_reason,
        )
        checks = ", ".join(f"#{i}" for i in bug.check_steps)
        linked = f" Linked to failing check(s) {checks}." if bug.check_steps else " Filed without a regression test."
        return ToolOutcome(
            content=f"Filed {bug.id} ({severity}): {title}.{linked}",
            summary=f"{bug.id} · {severity} · {title}",
            ui={"kind": "bug", "bug": bug.to_dict(), "screenshot": rel},
        )

    async def _finish(self, summary: str, untested: str | None = None) -> ToolOutcome:
        self.recorder.summary = summary
        self.recorder.untested = untested
        return ToolOutcome(content="Session finished.", summary="Session finished", finished=True,
                           ui={"kind": "finish", "summary": summary, "untested": untested})
