"""Sandboxed Chromium for the QA agent.

Playwright runs on a dedicated thread with its own event loop (a Proactor loop on
Windows, which Chromium's subprocess pipes need). The API only ever awaits
``BrowserBridge.call``, so a slow page never stalls request handling.

A ``BrowserSession`` is one isolated browser context per run. It records a video and
a Playwright trace, collects console and network signals, restricts top-level
navigation to allowlisted hosts, and turns snapshot refs into replayable locators.
"""

import asyncio
import re
import shutil
import sys
import threading
import time
from collections import deque
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Dialog,
    Locator,
    Page,
    Playwright,
    Request,
    Response,
    Route,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import expect as pw_expect

from .config import Settings
from .locators import LocatorSpec, build_spec, to_runtime

T = TypeVar("T")

REF_RE = re.compile(r"^e\d+$")
EXPECT_TIMEOUT_MS = 2500
SETTLE_MAX_S = 3.0
SETTLE_QUIET_S = 0.25


def _load_js(name: str) -> str:
    text = (Path(__file__).parent / "js" / name).read_text(encoding="utf-8")
    # Drop the file-level comment header so Playwright sees a bare function expression.
    return "\n".join(line for line in text.splitlines() if not line.startswith("//")).strip()


SNAPSHOT_JS = _load_js("snapshot.js")


class BrowserError(RuntimeError):
    """An action failed in a way the agent should hear about. Carries a fresh snapshot when available."""

    def __init__(self, message: str, snapshot: "Snapshot | None" = None):
        super().__init__(message)
        self.snapshot = snapshot


def _brief(exc: PlaywrightError) -> str:
    """Playwright errors carry a long call log; keep the headline and the last few hints."""
    lines = [line.strip() for line in str(exc.message).splitlines() if line.strip()]
    if not lines:
        return "Browser action failed."
    hints = [line for line in lines[1:] if line.startswith("-")][-4:]
    return "\n".join([lines[0], *hints])[:700]


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


@dataclass
class Signal:
    seq: int
    kind: str  # console | pageerror | network | dialog | blocked | popup
    level: str  # error | warning | info
    text: str
    url: str | None = None

    def format(self) -> str:
        label = f"{self.kind}.{self.level}" if self.kind == "console" else self.kind
        return f"[{label}] {self.text}"

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "kind": self.kind, "level": self.level, "text": self.text, "url": self.url}


@dataclass
class Snapshot:
    url: str
    title: str
    text: str
    ref_count: int

    def render(self) -> str:
        return f"Page: {self.title or '(untitled)'} — {self.url}\n{self.text}"


@dataclass
class ActionResult:
    snapshot: Snapshot
    signals: list[Signal]
    screenshot: str | None
    spec: LocatorSpec | None = None
    value: Any = None
    status: int | None = None


@dataclass
class CheckResult:
    passed: bool
    actual: str
    spec: LocatorSpec | None
    signals: list[Signal]
    screenshot: str | None
    url: str


@dataclass
class _ContextState:
    signals: list[Signal] = field(default_factory=list)
    network: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=200))


class BrowserBridge:
    """Owns the Playwright thread and the shared Chromium instance."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._launch_lock: asyncio.Lock | None = None
        self.status = "idle"  # idle | starting | ready | error: ...
        self.version: str | None = None

    def _ensure_thread(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                ready = threading.Event()

                def target() -> None:
                    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    self._loop = loop
                    ready.set()
                    loop.run_forever()
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()

                self._thread = threading.Thread(target=target, name="qapilot-browser", daemon=True)
                self._thread.start()
                ready.wait()
            assert self._loop is not None
            return self._loop

    async def call(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run ``coro`` on the browser loop and await its result from any other loop."""
        loop = self._ensure_thread()
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop))

    async def _get_browser(self) -> Browser:
        if self._launch_lock is None:
            self._launch_lock = asyncio.Lock()
        async with self._launch_lock:
            if self._browser is None or not self._browser.is_connected():
                self.status = "starting"
                try:
                    if self._playwright is None:
                        self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(headless=self.settings.headless)
                except Exception as exc:
                    self.status = f"error: {str(exc).splitlines()[0]}"
                    raise
                self.version = self._browser.version
                self.status = "ready"
            return self._browser

    async def warmup(self) -> None:
        try:
            await self.call(self._get_browser())
        except Exception:  # noqa: BLE001 - status already records the failure for /api/health
            pass

    async def open_session(self, run_dir: Path, target_url: str) -> "BrowserSession":
        async def _open() -> BrowserSession:
            return await BrowserSession.create(await self._get_browser(), self.settings, run_dir, target_url)

        return await self.call(_open())

    async def _shutdown(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    def stop(self) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result(timeout=15)
        except Exception:  # noqa: BLE001 - best effort on shutdown
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


class BrowserSession:
    """One run's isolated browser context. All coroutines must run on the bridge loop."""

    def __init__(self, context: BrowserContext, settings: Settings, run_dir: Path, target_url: str):
        self.context = context
        self.settings = settings
        self.run_dir = run_dir
        self.target_url = target_url
        self.allowed_hosts = {host_of(target_url), *(h.lower() for h in settings.allowed_hosts)}
        self.page: Page | None = None
        self.refs: dict[str, dict[str, Any]] = {}
        self._state = _ContextState()
        self._seq = 0
        self._drained = 0
        self._inflight = 0
        self._shots = 0
        self._video_page: Page | None = None
        self._attached: list[Page] = []
        self._closed = False

    @classmethod
    async def create(cls, browser: Browser, settings: Settings, run_dir: Path, target_url: str) -> "BrowserSession":
        (run_dir / "shots").mkdir(parents=True, exist_ok=True)
        viewport = {"width": settings.viewport_width, "height": settings.viewport_height}
        kwargs: dict[str, Any] = {"viewport": viewport, "locale": "en-US", "timezone_id": "UTC"}
        if settings.record_video:
            kwargs["record_video_dir"] = str(run_dir / "video")
            kwargs["record_video_size"] = viewport
        context = await browser.new_context(**kwargs)
        context.set_default_timeout(settings.action_timeout_ms)
        context.set_default_navigation_timeout(settings.navigation_timeout_ms)
        session = cls(context, settings, run_dir, target_url)
        await context.tracing.start(screenshots=True, snapshots=True)
        await context.route("**/*", session._guard)
        context.on("page", session._on_page)
        page = await context.new_page()
        session._on_page(page)  # the "page" event may land later; _on_page ignores repeats
        session._video_page = page
        return session

    # --- signals ---------------------------------------------------------------------

    def _signal(self, kind: str, level: str, text: str, url: str | None = None) -> None:
        self._seq += 1
        self._state.signals.append(Signal(self._seq, kind, level, _clip(text, 400), url))

    @property
    def last_signal_seq(self) -> int:
        return self._seq

    def drain_signals(self) -> list[Signal]:
        fresh = [s for s in self._state.signals if s.seq > self._drained]
        self._drained = self._seq
        return fresh

    def errors_since(self, seq: int) -> list[Signal]:
        return [s for s in self._state.signals if s.seq > seq and s.kind in ("console", "pageerror")]

    def _on_page(self, page: Page) -> None:
        if any(p is page for p in self._attached):
            return
        self._attached.append(page)
        if self.page is not None:
            opened = page.url or "about:blank"
            self._signal("popup", "info", f"A new tab opened ({opened}); the session switched to it.")
        self.page = page
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("dialog", self._on_dialog)
        page.on("request", self._on_request)
        page.on("requestfinished", self._on_request_done)
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)

    def _on_console(self, msg: ConsoleMessage) -> None:
        if msg.type == "error":
            self._signal("console", "error", msg.text, (msg.location or {}).get("url"))

    def _on_pageerror(self, error: PlaywrightError) -> None:
        name = getattr(error, "name", None) or "Error"
        self._signal("pageerror", "error", f"Uncaught {name}: {error.message}")

    async def _on_dialog(self, dialog: Dialog) -> None:
        self._signal("dialog", "info", f"{dialog.type} dialog: {dialog.message!r} (accepted)")
        try:
            await dialog.accept()
        except PlaywrightError:
            pass

    def _on_request(self, request: Request) -> None:
        self._inflight += 1

    def _on_request_done(self, request: Request) -> None:
        self._inflight = max(0, self._inflight - 1)

    def _on_request_failed(self, request: Request) -> None:
        self._inflight = max(0, self._inflight - 1)
        failure = request.failure or "failed"
        if "ERR_BLOCKED_BY_CLIENT" in failure or "ERR_ABORTED" in failure:
            return
        self._signal("network", "error", f"{request.method} {request.url} failed: {failure}", request.url)

    async def _on_response(self, response: Response) -> None:
        request = response.request
        entry: dict[str, Any] = {
            "method": request.method,
            "url": response.url,
            "status": response.status,
            "type": request.resource_type,
            "at": round(time.time(), 3),
        }
        if request.resource_type in ("xhr", "fetch"):
            if request.post_data:
                entry["request_body"] = _clip(request.post_data, 600)
            try:
                entry["response_body"] = _clip(await response.text(), 1200)
            except PlaywrightError:
                pass
        self._state.network.append(entry)
        if response.status >= 400 and not response.url.endswith("/favicon.ico"):
            self._signal("network", "error", f"{request.method} {response.url} → HTTP {response.status}", response.url)

    # --- navigation guard -------------------------------------------------------------

    def url_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme in ("about", "data", "blob"):
            return True
        return parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in self.allowed_hosts

    async def _guard(self, route: Route) -> None:
        request = route.request
        try:
            top_level = request.is_navigation_request() and request.frame.parent_frame is None
        except PlaywrightError:
            top_level = False
        if top_level and not self.url_allowed(request.url):
            self._signal("blocked", "warning", f"Blocked navigation to a host outside the allowlist: {request.url}")
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    # --- page state -------------------------------------------------------------------

    @property
    def _page(self) -> Page:
        assert self.page is not None, "session has no page"
        return self.page

    async def _settle(self) -> None:
        """Wait for the DOM and for in-flight requests to go quiet (bounded)."""
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=self.settings.navigation_timeout_ms)
        except PlaywrightError:
            pass
        deadline = time.monotonic() + SETTLE_MAX_S
        quiet_since: float | None = None
        await asyncio.sleep(0.05)
        while time.monotonic() < deadline:
            if self._inflight == 0:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= SETTLE_QUIET_S:
                    break
            else:
                quiet_since = None
            await asyncio.sleep(0.05)

    async def snapshot(self) -> Snapshot:
        page = self._page
        for attempt in range(3):
            try:
                data = await page.evaluate(SNAPSHOT_JS, {"maxLines": self.settings.snapshot_max_lines})
                break
            except PlaywrightError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.3)  # the page was mid-navigation
        self.refs = data["refs"]
        return Snapshot(url=data["url"], title=data["title"], text="\n".join(data["lines"]), ref_count=len(self.refs))

    async def _safe_snapshot(self) -> Snapshot | None:
        try:
            return await self.snapshot()
        except PlaywrightError:
            return None

    async def _step_screenshot(self) -> str | None:
        self._shots += 1
        rel = f"shots/{self._shots:03d}.jpg"
        try:
            data = await self._page.screenshot(
                type="jpeg", quality=60, timeout=5000, animations="disabled", caret="hide"
            )
        except PlaywrightError:
            return None
        (self.run_dir / rel).write_bytes(data)
        return rel

    async def _after_action(self, *, spec: LocatorSpec | None = None, value: Any = None) -> ActionResult:
        await self._settle()
        snap = await self.snapshot()
        shot = await self._step_screenshot()
        return ActionResult(snapshot=snap, signals=self.drain_signals(), screenshot=shot, spec=spec, value=value)

    async def _resolve(self, ref: str) -> dict[str, Any]:
        if not REF_RE.match(ref):
            raise BrowserError(f"'{ref}' is not a ref. Refs look like e12 and come from the latest snapshot.")
        info = self.refs.get(ref)
        if info is None:
            raise BrowserError(f"Unknown ref '{ref}'. Use a ref from the latest snapshot.", await self._safe_snapshot())
        if await self._page.locator(f'[data-qa-ref="{ref}"]').count() == 0:
            raise BrowserError(
                f"Element {ref} is no longer on the page (it re-rendered). Here is a fresh snapshot; use the new ref.",
                await self._safe_snapshot(),
            )
        return info

    # --- actions ----------------------------------------------------------------------

    def _check_url(self, url: str) -> None:
        if not self.url_allowed(url) or urlparse(url).scheme not in ("http", "https"):
            allowed = ", ".join(sorted(self.allowed_hosts))
            raise BrowserError(f"Navigation to {url} is not allowed. Allowed hosts: {allowed}.")

    async def goto(self, url: str) -> ActionResult:
        self._check_url(url)
        try:
            response = await self._page.goto(url, wait_until="domcontentloaded")
        except PlaywrightError as exc:
            raise BrowserError(_brief(exc), await self._safe_snapshot()) from None
        result = await self._after_action()
        result.status = response.status if response else None
        return result

    async def reset(self, start_url: str) -> ActionResult:
        """Fresh cookies and storage, then open ``start_url``: every scenario replays on its own."""
        self._check_url(start_url)
        try:
            await self._page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        except PlaywrightError:
            pass  # about:blank or a different origin has no storage to clear
        try:
            # Leave the app first: a hash-only change would keep the old in-memory state alive.
            await self._page.goto("about:blank")
        except PlaywrightError:
            pass
        await self.context.clear_cookies()
        return await self.goto(start_url)

    async def act(self, kind: str, ref: str, value: Any = None) -> ActionResult:
        info = await self._resolve(ref)
        try:
            spec = await build_spec(self._page, ref, info)
            loc = to_runtime(self._page, spec)
            match kind:
                case "click":
                    await loc.click()
                case "fill":
                    await loc.fill(value)
                case "select":
                    value = await self._select(loc, value)
                case "check":
                    await loc.set_checked(bool(value))
                case "hover":
                    await loc.hover()
                case "press":
                    await loc.press(value)
                case _:
                    raise BrowserError(f"Unsupported action {kind}.")
        except PlaywrightError as exc:
            raise BrowserError(_brief(exc), await self._safe_snapshot()) from None
        return await self._after_action(spec=spec, value=value)

    async def press_page(self, key: str) -> ActionResult:
        try:
            await self._page.keyboard.press(key)
        except PlaywrightError as exc:
            raise BrowserError(_brief(exc), await self._safe_snapshot()) from None
        return await self._after_action(value=key)

    async def _select(self, loc: Locator, wanted: str) -> str:
        options: list[dict[str, str]] = await loc.evaluate(
            "(el) => el.options ? [...el.options].map((o) => ({ label: o.label.trim(), value: o.value })) : []"
        )
        if not options:
            raise BrowserError("That element is not a <select>; click it and pick an option instead.")
        key = wanted.strip().lower()
        match = next((o for o in options if key in (o["label"].lower(), o["value"].lower())), None)
        match = match or next((o for o in options if o["label"].lower().startswith(key)), None)
        if match is None:
            labels = ", ".join(repr(o["label"]) for o in options)
            raise BrowserError(f"No option matches {wanted!r}. Options: {labels}.")
        await loc.select_option(value=match["value"])
        return match["label"]

    async def wait(self, seconds: float) -> ActionResult:
        await asyncio.sleep(max(0.0, min(seconds, 5.0)))
        return await self._after_action()

    # --- assertions -------------------------------------------------------------------

    async def check(
        self,
        assertion: str,
        *,
        ref: str | None = None,
        target: LocatorSpec | None = None,
        expected: str | None = None,
        since_seq: int = 0,
    ) -> CheckResult:
        page = self._page
        spec: LocatorSpec | None = None
        await self._settle()
        if assertion == "no_console_errors":
            errors = self.errors_since(since_seq)
            passed = not errors
            actual = "no errors" if passed else " | ".join(s.text for s in errors[:5])
        elif assertion in ("url_contains", "title_contains"):
            pattern = re.compile(re.escape(expected or ""))
            try:
                if assertion == "url_contains":
                    await pw_expect(page).to_have_url(pattern, timeout=EXPECT_TIMEOUT_MS)
                else:
                    await pw_expect(page).to_have_title(pattern, timeout=EXPECT_TIMEOUT_MS)
                passed = True
            except AssertionError:
                passed = False
            actual = page.url if assertion == "url_contains" else await page.title()
        else:
            if ref is not None:
                spec = await build_spec(page, ref, await self._resolve(ref))
            elif target is not None:
                spec = target if assertion == "count_equals" else [*target, {"op": "first"}]
            else:
                raise BrowserError("This assertion needs a ref, or a role/name or text describing the element.")
            loc = to_runtime(page, spec)
            try:
                await _expect(loc, assertion, expected)
                passed = True
            except AssertionError:
                passed = False
            except PlaywrightError as exc:
                raise BrowserError(_brief(exc)) from None
            actual = await _actual(loc, assertion)
        shot = await self._step_screenshot()
        return CheckResult(passed, actual, spec, self.drain_signals(), shot, page.url)

    # --- evidence ---------------------------------------------------------------------

    async def capture(self, *, ref: str | None = None, full_page: bool = False) -> tuple[str, bytes]:
        self._shots += 1
        rel = f"shots/{self._shots:03d}-capture.jpg"
        try:
            if ref is not None:
                await self._resolve(ref)
                data = await self._page.locator(f'[data-qa-ref="{ref}"]').screenshot(type="jpeg", quality=80)
            else:
                data = await self._page.screenshot(type="jpeg", quality=80, full_page=full_page, animations="disabled")
        except PlaywrightError as exc:
            raise BrowserError(_brief(exc)) from None
        (self.run_dir / rel).write_bytes(data)
        return rel, data

    async def network_log(self, url_contains: str | None, only_failed: bool, limit: int = 12) -> list[dict[str, Any]]:
        entries = [e for e in self._state.network if e["type"] in ("xhr", "fetch", "document")]
        if url_contains:
            entries = [e for e in entries if url_contains.lower() in e["url"].lower()]
        if only_failed:
            entries = [e for e in entries if e["status"] >= 400]
        return entries[-limit:]

    async def close(self) -> dict[str, str | None]:
        artifacts: dict[str, str | None] = {"video": None, "trace": None}
        if self._closed:
            return artifacts
        self._closed = True
        try:
            await self.context.tracing.stop(path=str(self.run_dir / "trace.zip"))
            artifacts["trace"] = "trace.zip"
        except PlaywrightError:
            pass
        video = self._video_page.video if self._video_page is not None else None
        try:
            await self.context.close()
        except PlaywrightError:
            pass
        if video is not None:
            try:
                src = Path(await video.path())
                shutil.move(str(src), self.run_dir / "session.webm")
                artifacts["video"] = "session.webm"
            except (PlaywrightError, OSError):
                pass
            shutil.rmtree(self.run_dir / "video", ignore_errors=True)
        return artifacts


async def _expect(loc: Locator, assertion: str, expected: str | None) -> None:
    e = pw_expect(loc)
    t = EXPECT_TIMEOUT_MS
    match assertion:
        case "visible":
            await e.to_be_visible(timeout=t)
        case "hidden":
            await e.to_be_hidden(timeout=t)
        case "text_equals":
            await e.to_have_text(expected or "", timeout=t)
        case "text_contains":
            await e.to_contain_text(expected or "", timeout=t)
        case "value_equals":
            await e.to_have_value(expected or "", timeout=t)
        case "checked":
            await e.to_be_checked(timeout=t)
        case "unchecked":
            await e.to_be_checked(checked=False, timeout=t)
        case "enabled":
            await e.to_be_enabled(timeout=t)
        case "disabled":
            await e.to_be_disabled(timeout=t)
        case "count_equals":
            await e.to_have_count(int(expected or "0"), timeout=t)
        case _:
            raise BrowserError(f"Unknown assertion {assertion}.")


async def _actual(loc: Locator, assertion: str) -> str:
    try:
        count = await loc.count()
        if assertion == "count_equals":
            return str(count)
        if count == 0:
            return "no matching element"
        first = loc.first
        match assertion:
            case "visible" | "hidden":
                return "visible" if await first.is_visible() else "hidden"
            case "value_equals":
                return _clip(await first.input_value(timeout=1000), 300)
            case "checked" | "unchecked":
                return "checked" if await first.is_checked(timeout=1000) else "unchecked"
            case "enabled" | "disabled":
                return "enabled" if await first.is_enabled(timeout=1000) else "disabled"
            case _:
                return _clip(await first.inner_text(timeout=1000), 300)
    except PlaywrightError:
        return "unavailable"
