from dataclasses import dataclass, field

from conftest import FakeLLM, text, thinking, tool_use

from app.agent import SKIPPED, QAAgent, compact_events, estimate_cost
from app.recorder import Recorder
from app.tools import ToolOutcome


@dataclass
class FakeExecutor:
    """Answers tool calls from a table; ``finish`` ends the session like the real executor."""

    fail: set[str] = field(default_factory=set)
    calls: list[tuple[str, dict]] = field(default_factory=list)
    recorder: Recorder = field(default_factory=lambda: Recorder("http://localhost/shop/"))

    async def execute(self, name, raw_input):
        self.calls.append((name, raw_input))
        if name in self.fail:
            return ToolOutcome(content=f"✗ {name} failed", is_error=True, summary="failed", ui={"kind": "error"})
        if name == "finish":
            self.recorder.summary = raw_input["summary"]
            return ToolOutcome(content="Session finished.", finished=True, ui={"kind": "finish"})
        return ToolOutcome(content=f"ok {name}", summary=f"ok {name}", ui={"kind": "action"})


async def collect(agent: QAAgent, story: str = "As a shopper I can buy a mug") -> list[dict]:
    return [e async for e in agent.run("http://localhost/shop/", story, "Pricing")]


async def test_happy_path(settings):
    llm = FakeLLM([
        ([thinking("Start with search."), text("Opening the shop."),
          tool_use("t1", "begin_scenario", name="Search works")], "tool_use"),
        ([tool_use("t2", "click", ref="e4", description="Search")], "tool_use"),
        ([tool_use("t3", "finish", summary="Search works; checkout untested.")], "tool_use"),
    ])
    executor = FakeExecutor()
    agent = QAAgent(llm, executor, settings)  # type: ignore[arg-type]
    events = await collect(agent)

    types = [e["type"] for e in events]
    assert types[0] == "agent_start" and types[-1] == "agent_done"
    assert {"thinking_start", "thinking_delta", "text_start", "text_delta", "tool_start", "tool_call",
            "tool_result"} <= set(types)
    assert [n for n, _ in executor.calls] == ["begin_scenario", "click", "finish"]
    done = events[-1]
    assert done["ok"] and done["finished"] and done["steps"] == 3
    assert done["summary"] == "Search works; checkout untested."
    assert done["usage"]["input_tokens"] == 3000 and done["usage"]["cost_usd"] > 0
    # The story and focus reach the model, and every tool result goes back to it.
    first = llm.calls[0]["messages"][0]["content"][0]["text"]
    assert "As a shopper I can buy a mug" in first and "Pricing" in first
    assert llm.calls[2]["messages"][-1]["content"][0] == {"type": "tool_result", "tool_use_id": "t2",
                                                          "content": "ok click"}


async def test_failed_call_skips_the_rest_of_the_turn(settings):
    llm = FakeLLM([
        ([tool_use("t1", "click", ref="e1", description="a"), tool_use("t2", "fill", ref="e2", value="x",
                                                                         description="b")], "tool_use"),
        ([text("The page changed; stopping here.")], "end_turn"),
    ])
    executor = FakeExecutor(fail={"click"})
    agent = QAAgent(llm, executor, settings)  # type: ignore[arg-type]
    events = await collect(agent)

    assert [n for n, _ in executor.calls] == ["click"]
    results = llm.calls[1]["messages"][-1]["content"]
    assert results[0]["is_error"] and results[1] == {"type": "tool_result", "tool_use_id": "t2", "content": SKIPPED,
                                                     "is_error": True}
    skipped = [e for e in events if e["type"] == "tool_result" and e["ui"].get("kind") == "skipped"]
    assert len(skipped) == 1
    # Wrapping up in prose counts as finishing; the prose becomes the summary.
    assert agent.finished and executor.recorder.summary == "The page changed; stopping here."


async def test_step_limit_forces_a_final_answer(settings):
    settings.max_agent_steps = 2
    llm = FakeLLM([([tool_use(f"t{i}", "snapshot")], "tool_use") for i in range(5)])
    agent = QAAgent(llm, FakeExecutor(), settings)  # type: ignore[arg-type]
    await collect(agent)
    assert [c["tool_choice"] for c in llm.calls] == [None, None, {"type": "none"}]
    notice = llm.calls[2]["messages"][-1]["content"][-1]
    assert notice["type"] == "text" and "step" in notice["text"].lower()


async def test_truncated_turn_never_runs_tools(settings):
    llm = FakeLLM([([tool_use("t1", "click", ref="e1", description="a")], "max_tokens")])
    executor = FakeExecutor()
    agent = QAAgent(llm, executor, settings)  # type: ignore[arg-type]
    events = await collect(agent)
    assert executor.calls == [] and agent.error and "token limit" in agent.error
    assert events[-1]["ok"] is False


async def test_refusal_stops_the_session(settings):
    agent = QAAgent(FakeLLM([([], "refusal")]), FakeExecutor(), settings)  # type: ignore[arg-type]
    events = await collect(agent)
    assert any(e["type"] == "error" for e in events) and agent.error == "The model declined to continue this session."


async def test_broken_stream_is_retried(settings):
    llm = FakeLLM([ValueError("stream cut"), ([text("All good.")], "end_turn")])
    agent = QAAgent(llm, FakeExecutor(), settings)  # type: ignore[arg-type]
    events = await collect(agent)
    assert [e["attempt"] for e in events if e["type"] == "retry"] == [1]
    assert agent.finished and agent.error is None and len(llm.calls) == 2


async def test_stream_that_keeps_breaking_fails_cleanly(settings):
    llm = FakeLLM([ValueError("cut")] * 3)
    agent = QAAgent(llm, FakeExecutor(), settings)  # type: ignore[arg-type]
    events = await collect(agent)
    assert "interrupted repeatedly" in (agent.error or "")
    assert events[-1]["type"] == "agent_done" and events[-1]["ok"] is False


def test_compact_events_merges_deltas_per_step():
    events = [
        {"type": "text_delta", "step": 1, "text": "Hel", "seq": 0},
        {"type": "text_delta", "step": 1, "text": "lo", "seq": 1},
        {"type": "text_delta", "step": 2, "text": "!", "seq": 2},
        {"type": "tool_call", "step": 2, "seq": 3},
        {"type": "thinking_delta", "step": 2, "text": "a", "seq": 4},
        {"type": "thinking_delta", "step": 2, "text": "b", "seq": 5},
    ]
    assert compact_events(events) == [
        {"type": "text_delta", "step": 1, "text": "Hello", "seq": 0},
        {"type": "text_delta", "step": 2, "text": "!", "seq": 2},
        {"type": "tool_call", "step": 2, "seq": 3},
        {"type": "thinking_delta", "step": 2, "text": "ab", "seq": 4},
    ]


def test_estimate_cost():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0}
    assert estimate_cost("claude-opus-5-5", usage) == 6.0
    assert estimate_cost("demo-offline", usage) == 0.0
    assert estimate_cost("unknown-model", usage) is None
