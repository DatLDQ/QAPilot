import copy
from pathlib import Path

import pytest

from app.browser import BrowserError
from app.config import Settings
from app.llm import LLMEvent, LLMTurn
from app.recorder import Recorder

USAGE = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 500, "cache_creation_input_tokens": 0}


class FakeLLM:
    """Scripted stand-in for ClaudeLLM. Each script entry is one model turn:
    ``(content_blocks, stop_reason)``, or an exception instance to raise mid-stream."""

    model = "claude-opus-5-5"

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    async def stream(self, *, system, tools, messages, tool_choice=None):
        self.calls.append({"system": system, "messages": copy.deepcopy(messages), "tool_choice": tool_choice})
        entry = self.script.pop(0) if self.script else ([text("Done.")], "end_turn")
        if isinstance(entry, Exception):
            yield LLMEvent("text_start")
            raise entry
        content, stop_reason = entry
        for block in content:
            if block["type"] == "thinking":
                yield LLMEvent("thinking_start")
                yield LLMEvent("thinking_delta", {"text": block["thinking"]})
            elif block["type"] == "text":
                yield LLMEvent("text_start")
                for word in block["text"].split(" "):
                    yield LLMEvent("text_delta", {"text": word + " "})
            elif block["type"] == "tool_use":
                yield LLMEvent("tool_use_start", {"id": block["id"], "name": block["name"]})
        yield LLMTurn(content=content, stop_reason=stop_reason, model=self.model, usage=dict(USAGE))


def tool_use(id_: str, tool: str, /, **inputs) -> dict:
    return {"type": "tool_use", "id": id_, "name": tool, "input": inputs}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def thinking(t: str) -> dict:
    return {"type": "thinking", "thinking": t, "signature": "sig"}


class FakeSession:
    """The slice of BrowserSession that the run pipeline and the bug/finish tools touch."""

    page = None
    last_signal_seq = 0

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.closed = False

    def errors_since(self, seq: int) -> list:
        return []

    async def capture(self, **_):
        raise BrowserError("No page is open.")

    async def close(self) -> dict[str, str | None]:
        self.closed = True
        return {"video": None, "trace": None}


class FakeBridge:
    """Runs coroutines inline instead of on a Playwright thread; no browser is ever launched."""

    status = "ready"
    version = "fake-1.0"

    def __init__(self, *, fail_open: bool = False):
        self.fail_open = fail_open
        self.sessions: list[FakeSession] = []
        self.stopped = False

    async def call(self, coro):
        return await coro

    async def warmup(self) -> None:
        pass

    async def open_session(self, run_dir: Path, target_url: str) -> FakeSession:
        if self.fail_open:
            raise RuntimeError("Executable doesn't exist at /ms-playwright/chromium\nRun playwright install")
        session = FakeSession(run_dir)
        self.sessions.append(session)
        return session

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        demo_mode=False,
        data_dir=tmp_path / "data",
        public_url="http://testserver",
        max_agent_steps=5,
        verify_timeout_s=60,
    )


@pytest.fixture
def recorder() -> Recorder:
    """A recorded session with one passing and one failing scenario, and a bug on the failing one."""
    rec = Recorder("http://localhost:8100/shop/")
    rec.begin("Search finds products regardless of case", None, 0)
    rec.add_step(0, kind="fill", description="Type mug into search", value="mug",
                 locator=[{"op": "role", "role": "searchbox", "name": "Search products", "exact": True}])
    rec.add_step(0, kind="expect", description="Ceramic Mug is listed", assertion="visible", passed=True,
                 locator=[{"op": "role", "role": "heading", "name": "Ceramic Mug"}])
    rec.begin("Cart subtotal multiplies price by quantity", "http://localhost:8100/shop/#/cart", 0)
    rec.add_step(0, kind="click", description="Add Ceramic Mug to cart",
                 locator=[{"op": "test_id", "value": "card-mug"},
                          {"op": "role", "role": "button", "name": "Add to cart", "exact": True}])
    rec.add_step(0, kind="expect", description='Subtotal is "$36.00"', assertion="text_contains", expected="$36.00",
                 actual="$18.00", passed=False, locator=[{"op": "test_id", "value": "subtotal"}])
    rec.add_step(0, kind="expect", description="No console errors", assertion="no_console_errors", passed=True)
    rec.add_bug(title="Cart subtotal ignores quantities", severity="critical", category="functional",
                steps_to_reproduce=["Add a mug", "Set quantity to 2"], expected="$36.00", actual="$18.00",
                url="http://localhost:8100/shop/#/cart", screenshot=None)
    rec.begin("Empty scenario", None, 0)  # no steps: never becomes a test
    return rec
