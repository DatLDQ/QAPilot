"""The exploration loop: Claude drives the browser until the story is covered.

``QAAgent.run`` is an async generator of UI events (plain dicts) that the run manager
fans out to the browser as SSE. Every event carries the agent ``step`` it belongs to.

Event types:
    agent_start, thinking_start, thinking_delta, text_start, text_delta, tool_start,
    tool_call, tool_result, retry, error, agent_done
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from .config import PRICING, Settings
from .llm import LLMClient, LLMError, LLMEvent, LLMTurn
from .prompts import SYSTEM_PROMPT, initial_message, step_limit_notice
from .tools import TOOL_DEFINITIONS, QAToolExecutor

MAX_STREAM_RETRIES = 2
SKIPPED = "Skipped: an earlier tool call in this turn failed, so the page may not be in the state you assumed."

_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def estimate_cost(model: str, usage: dict[str, int]) -> float | None:
    price = PRICING.get(model)
    if price is None:
        return None
    cost = (
        usage["input_tokens"] * price["input"]
        + usage["output_tokens"] * price["output"]
        + usage["cache_read_input_tokens"] * price["cache_read"]
        + usage["cache_creation_input_tokens"] * price["cache_write"]
    ) / 1_000_000
    return round(cost, 6)


def compact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive text/thinking deltas so the stored replay log stays small."""
    out: list[dict[str, Any]] = []
    for ev in events:
        prev = out[-1] if out else None
        if (
            prev is not None
            and ev["type"] in ("text_delta", "thinking_delta")
            and prev["type"] == ev["type"]
            and prev.get("step") == ev.get("step")
        ):
            prev = out[-1] = {**prev, "text": prev["text"] + ev["text"]}
        else:
            out.append(dict(ev))
    return out


class QAAgent:
    def __init__(self, llm: LLMClient, executor: QAToolExecutor, settings: Settings):
        self.llm = llm
        self.executor = executor
        self.settings = settings
        self.step = 0
        self.usage = dict.fromkeys(_USAGE_KEYS, 0)
        self.model = llm.model
        self.stop_reason: str | None = None
        self.finished = False  # the agent called `finish` or wrapped up on its own
        self.error: str | None = None
        self._final_text: list[str] = []

    async def run(self, target_url: str, story: str, focus: str | None = None) -> AsyncIterator[dict[str, Any]]:
        started = time.perf_counter()
        yield {"type": "agent_start", "step": 0, "model": self.model}
        try:
            async for event in self._loop(target_url, story, focus):
                yield event
        except LLMError as exc:
            self.error = str(exc)
            yield {"type": "error", "step": self.step, "message": str(exc)}
        recorder = self.executor.recorder
        if recorder.summary is None and self._final_text:
            recorder.summary = "".join(self._final_text).strip() or None
        yield {
            "type": "agent_done",
            "step": self.step,
            "ok": self.error is None,
            "finished": self.finished,
            "stop_reason": self.stop_reason,
            "steps": self.step,
            "model": self.model,
            "summary": recorder.summary,
            "stats": recorder.stats(),
            "usage": {**self.usage, "cost_usd": estimate_cost(self.model, self.usage)},
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    async def _loop(self, target_url: str, story: str, focus: str | None) -> AsyncIterator[dict[str, Any]]:
        system = SYSTEM_PROMPT.replace("{max_steps}", str(self.settings.max_agent_steps))
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": initial_message(target_url, story, focus)}]}
        ]
        force_finish = False
        while True:
            self.step += 1
            turn: LLMTurn | None = None
            async for item in self._call(self.step, system, messages, force_finish):
                if isinstance(item, LLMTurn):
                    turn = item
                else:
                    yield item
            assert turn is not None
            self.stop_reason = turn.stop_reason
            self.model = turn.model

            if turn.stop_reason == "refusal":
                self.error = "The model declined to continue this session."
                yield {"type": "error", "step": self.step, "message": self.error}
                return
            if turn.stop_reason == "max_tokens":
                # Never run a tool call that may have been truncated.
                self.error = "The response hit the output token limit and was cut off."
                yield {"type": "error", "step": self.step, "message": self.error}
                return

            messages.append({"role": "assistant", "content": turn.content})
            if turn.stop_reason == "pause_turn":
                continue  # the server paused a long turn; resend so it can resume
            tool_uses = [b for b in turn.content if b.get("type") == "tool_use"]
            if turn.stop_reason != "tool_use" or not tool_uses:
                # The agent wrapped up in prose (or was told to): its last words are the summary.
                self._final_text = [b.get("text", "") for b in turn.content if b.get("type") == "text"]
                self.finished = True
                return

            for b in tool_uses:
                yield {"type": "tool_call", "step": self.step, "id": b["id"], "name": b["name"],
                       "input": b.get("input")}
            blocks: list[dict[str, Any]] = []
            failed = False
            for b in tool_uses:
                if failed:
                    blocks.append({"type": "tool_result", "tool_use_id": b["id"], "content": SKIPPED,
                                   "is_error": True})
                    yield self._result_event(b, SKIPPED, True, {"kind": "skipped"})
                    continue
                outcome = await self.executor.execute(b["name"], b.get("input"))
                result: dict[str, Any] = {"type": "tool_result", "tool_use_id": b["id"], "content": outcome.content}
                if outcome.is_error:
                    result["is_error"] = True
                    failed = True
                blocks.append(result)
                yield self._result_event(b, outcome.summary, outcome.is_error, outcome.ui)
                if outcome.finished:
                    self.finished = True
                    return
            if force_finish:
                return  # tool_choice=none should prevent this; stop rather than loop
            if self.step >= self.settings.max_agent_steps:
                force_finish = True
                blocks = [*blocks, {"type": "text", "text": step_limit_notice(story, focus)}]
            messages.append({"role": "user", "content": blocks})

    def _result_event(self, block: dict[str, Any], summary: str, is_error: bool, ui: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "step": self.step,
            "id": block["id"],
            "name": block["name"],
            "is_error": is_error,
            "summary": summary,
            "ui": ui,
            "stats": self.executor.recorder.stats(),
        }

    async def _call(
        self, step: int, system: str, messages: list[dict], force_finish: bool
    ) -> AsyncIterator[dict[str, Any] | LLMTurn]:
        """One model call with retries for streams that break mid-way."""
        for attempt in range(MAX_STREAM_RETRIES + 1):
            try:
                async for item in self.llm.stream(
                    system=system,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                    tool_choice={"type": "none"} if force_finish else None,
                ):
                    if isinstance(item, LLMTurn):
                        for key in _USAGE_KEYS:
                            self.usage[key] += item.usage.get(key, 0)
                        yield item
                        return
                    yield self._ui_event(step, item)
            except ValueError:
                if attempt == MAX_STREAM_RETRIES:
                    raise LLMError("The response stream was interrupted repeatedly. Please try again.") from None
                yield {"type": "retry", "step": step, "attempt": attempt + 1}
                await asyncio.sleep(0.5 * (attempt + 1))
        raise LLMError("The model returned no response.")

    @staticmethod
    def _ui_event(step: int, event: LLMEvent) -> dict[str, Any]:
        if event.kind == "tool_use_start":
            return {"type": "tool_start", "step": step, "id": event.data["id"], "name": event.data["name"]}
        return {"type": event.kind, "step": step, **event.data}
