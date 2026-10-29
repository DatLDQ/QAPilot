import json

import httpx
import pytest
from conftest import FakeBridge
from fastapi.testclient import TestClient

from app.config import Settings
from app.demo import DemoLLM
from app.llm import ClaudeLLM, LLMError, LLMTurn
from app.main import create_app, make_llm
from app.openai_compat import CLEARED, GEMINI_SKIP_SIGNATURE, NO_VISION, OpenAICompatLLM, trim_tool_results
from app.tools import TOOL_DEFINITIONS

URL = "http://localhost:8100/shop/"
BUG = {"title": "Checkout button does nothing", "severity": "high", "category": "functional",
       "steps_to_reproduce": ["Open the cart", "Click Checkout"], "expected": "The form opens",
       "actual": "Nothing happens"}


def sse(*chunks: dict) -> str:
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


def delta(**d) -> dict:
    return {"model": "gemini-test", "choices": [{"index": 0, "delta": d, "finish_reason": None}]}


def finish(reason: str) -> dict:
    return {"model": "gemini-test", "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 40}}


def call(id_: str, name: str, **args) -> dict:
    return delta(tool_calls=[{"index": 0, "id": id_, "function": {"name": name, "arguments": json.dumps(args)}}])


class Server:
    """Scripted OpenAI-compatible endpoint behind httpx.MockTransport."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        item = self.responses.pop(0)
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, text=item, headers={"content-type": "text/event-stream"})


def make(settings: Settings, server: Server, provider: str = "gemini") -> OpenAICompatLLM:
    llm = OpenAICompatLLM(settings, provider)
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(server.handler), base_url="http://llm.test/v1/")
    return llm


@pytest.fixture
def gemini_settings(settings) -> Settings:
    return settings.model_copy(update={"anthropic_api_key": None, "gemini_api_key": "g-key", "demo_mode": None})


async def collect(llm, **kwargs):
    events, turn = [], None
    async for item in llm.stream(**kwargs):
        if isinstance(item, LLMTurn):
            turn = item
        else:
            events.append(item)
    return events, turn


def screenshot_result(id_: str) -> dict:
    return {"type": "tool_result", "tool_use_id": id_, "content": [
        {"type": "text", "text": "Screenshot of the viewport:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
    ]}


def test_provider_selection(settings, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    auto = settings.model_copy(update={"demo_mode": None})
    # Claude key present: exactly the pre-existing behaviour, whatever else is set.
    claude = auto.model_copy(update={"gemini_api_key": "g-key"})
    assert claude.active_provider == "claude" and isinstance(make_llm(claude, URL), ClaudeLLM)
    gemini = auto.model_copy(update={"anthropic_api_key": None, "gemini_api_key": "g-key"})
    llm = make_llm(gemini, URL)
    assert isinstance(llm, OpenAICompatLLM) and llm.model == "gemini-3.5-flash-lite" and llm.vision
    ollama = auto.model_copy(update={"anthropic_api_key": None, "provider": "ollama"})
    llm = make_llm(ollama, URL)
    assert llm.model == "qwen3:14b" and not llm.vision
    assert isinstance(make_llm(auto.model_copy(update={"anthropic_api_key": None}), URL), DemoLLM)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        OpenAICompatLLM(auto.model_copy(update={"provider": "gemini"}))


def test_health_and_config_report_provider(gemini_settings):
    app = create_app(gemini_settings, bridge=FakeBridge(), warmup=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        config = client.get("/api/config").json()
    assert health["provider"] == config["provider"] == "gemini"
    assert health["model"] == "gemini-3.5-flash-lite" and health["demo_mode"] is False


def test_screenshots_follow_tool_messages(gemini_settings):
    history = [
        {"role": "user", "content": [{"type": "text", "text": "Test the shop."}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "plan", "signature": "s"},
            {"type": "tool_use", "id": "s1", "name": "screenshot", "input": {}},
            {"type": "tool_use", "id": "c1", "name": "click", "input": {"ref": "e3"}},
        ]},
        {"role": "user", "content": [
            screenshot_result("s1"),
            {"type": "tool_result", "tool_use_id": "c1", "content": "No element e3", "is_error": True},
        ]},
    ]
    out = OpenAICompatLLM(gemini_settings).to_openai_messages("SYS", history)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "tool", "user"]
    assert out[2]["tool_calls"][0]["extra_content"] == GEMINI_SKIP_SIGNATURE
    assert out[3]["content"].endswith("[Screenshot attached in the next message.]")
    assert out[4]["content"] == "Error: No element e3"
    image = out[5]["content"][1]
    assert image == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}

    blind = OpenAICompatLLM(gemini_settings, "ollama").to_openai_messages("SYS", history)
    assert [m["role"] for m in blind] == ["system", "user", "assistant", "tool", "tool"]
    assert NO_VISION in blind[3]["content"] and "extra_content" not in blind[2]["tool_calls"][0]


def test_trim_keeps_recent_and_protected_results():
    big = "x" * 8000  # ~2000 tokens each
    history: list[dict] = [{"role": "user", "content": [{"type": "text", "text": "Go"}]}]
    names = ["begin_scenario", "snapshot", "report_bug", "snapshot", "screenshot", "snapshot", "snapshot",
             "snapshot", "snapshot", "snapshot", "snapshot"]
    for n, name in enumerate(names):
        history.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"t{n}", "name": name,
                                                           "input": {}}]})
        result = screenshot_result(f"t{n}") if name == "screenshot" else {
            "type": "tool_result", "tool_use_id": f"t{n}", "content": big}
        history.append({"role": "user", "content": [result]})
    before = json.dumps(history)

    trimmed = trim_tool_results(history, budget=12_000, keep=6)
    assert json.dumps(history) == before  # the agent's history is never modified
    contents = {m["content"][0]["tool_use_id"]: m["content"][0]["content"] for m in trimmed[2::2]}
    assert contents["t0"] == big and contents["t2"] == big  # begin_scenario / report_bug survive
    assert contents["t1"] == CLEARED and contents["t3"] == CLEARED and contents["t4"] == CLEARED
    assert all(contents[f"t{n}"] == big for n in range(5, 11))  # the newest six are kept
    assert trim_tool_results(history, budget=1_000_000, keep=6) is history


async def test_stream_tool_calls_and_signatures(gemini_settings):
    signature = {"google": {"thought_signature": "abc"}}
    server = Server([sse(
        delta(content="Opening the cart."),
        delta(tool_calls=[{"index": 0, "id": "fc-1", "extra_content": signature,
                           "function": {"name": "click", "arguments": '{"ref": '}}]),
        delta(tool_calls=[{"index": 0, "function": {"arguments": '"e7"}'}}]),
        finish("stop"),
    )])
    llm = make(gemini_settings, server)
    events, turn = await collect(llm, system="SYS", tools=TOOL_DEFINITIONS, messages=[
        {"role": "user", "content": "go"}], tool_choice={"type": "tool", "name": "finish"})
    assert [e.kind for e in events] == ["text_start", "text_delta", "tool_use_start"]
    assert turn.stop_reason == "tool_use"
    assert turn.content[1] == {"type": "tool_use", "id": "fc-1", "name": "click", "input": {"ref": "e7"}}
    assert turn.usage["input_tokens"] == 900 and turn.usage["output_tokens"] == 40
    request = server.requests[0]
    assert request["tool_choice"] == {"type": "function", "function": {"name": "finish"}}
    assert "eager_input_streaming" not in json.dumps(request["tools"])
    assert llm._assistant_message(turn.content)["tool_calls"][0]["extra_content"] == signature


async def test_rate_limit_and_errors(gemini_settings):
    server = Server([httpx.Response(429, headers={"retry-after": "0"}), sse(delta(content="ok"), finish("stop"))])
    _, turn = await collect(make(gemini_settings, server), system="S", tools=[], messages=[])
    assert turn.content == [{"type": "text", "text": "ok"}]
    with pytest.raises(LLMError, match="ollama pull qwen3:14b"):
        await collect(make(gemini_settings, Server([httpx.Response(404)]), "ollama"), system="S", tools=[],
                      messages=[])
    with pytest.raises(LLMError, match="rejected the API key"):
        await collect(make(gemini_settings, Server([httpx.Response(401)])), system="S", tools=[], messages=[])


def test_full_run_over_api(gemini_settings):
    """The real QA agent loop, recorder and report driven by an OpenAI-compatible provider."""
    server = Server([
        sse(delta(content="Checking the checkout."), call("b1", "report_bug", **BUG), finish("tool_calls")),
        sse(call("f1", "finish", summary="Checkout is broken.", untested="Payments"), finish("tool_calls")),
    ])
    app = create_app(gemini_settings, llm_factory=lambda s, _url: make(s, server), bridge=FakeBridge(),
                     warmup=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        res = client.post("/api/runs", json={"target_url": URL, "story": "As a shopper I can check out."})
        run_id = res.json()["id"]
        events = [json.loads(line[6:]) for line in client.get(f"/api/runs/{run_id}/events").text.splitlines()
                  if line.startswith("data: ")]
        run = client.get(f"/api/runs/{run_id}").json()
    assert events[-1]["type"] == "done" and events[-1]["status"] == "completed", events[-1]
    assert run["result"]["bugs"][0]["title"] == BUG["title"] and run["model"] == "gemini-test"
    second = server.requests[1]["messages"]
    assert [m["role"] for m in second][-2:] == ["assistant", "tool"] and second[-1]["tool_call_id"] == "b1"
