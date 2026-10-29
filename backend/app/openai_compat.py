"""``LLMClient`` for OpenAI-compatible chat endpoints: Google Gemini and local Ollama.

The agent, tools and run history stay Anthropic-shaped (``tool_use`` / ``tool_result``
blocks); this module translates at the edge, so ``ClaudeLLM`` is untouched.

Claude features without an equivalent are handled client-side or dropped:

* Context editing: old tool results (page outlines, screenshots) are cleared locally once the
  estimated prompt passes ``compat_context_tokens``, keeping the newest few and every
  ``begin_scenario`` / ``report_bug`` / ``finish`` result, like ``CONTEXT_MANAGEMENT`` in llm.py.
* Screenshots: OpenAI tool messages are text-only, so images go in a user message right after
  the tool results, or are replaced by a note for models without vision.
* Prompt caching directives, adaptive thinking display and refusal fallbacks are not used.
"""

import asyncio
import copy
import json
import re
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import GEMINI_BASE_URL, Settings
from .llm import CONTEXT_MANAGEMENT, LLMError, LLMEvent, LLMTurn

FINISH_REASONS = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}
EFFORT_TO_REASONING = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
MAX_RATE_LIMIT_RETRIES = 4
# Gemini 3 rejects replayed function calls of the current turn without their thought signature.
# Real signatures are kept in memory; this documented placeholder covers anything else.
GEMINI_SKIP_SIGNATURE = {"google": {"thought_signature": "skip_thought_signature_validator"}}
PROTECTED_TOOLS = frozenset(CONTEXT_MANAGEMENT["edits"][0]["exclude_tools"])
CLEARED = "[Old tool result cleared to save context. Take a fresh snapshot if you need the page again.]"
NO_VISION = "[Screenshot omitted: this model cannot read images. Rely on the page outline instead.]"
IMAGE_TOKENS = 1600  # rough cost of one 1280x800 JPEG


def _tool_id(raw: str | None) -> str:
    # Claude only accepts [A-Za-z0-9_-] ids, so run history stays valid for it too.
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", raw or "")
    return cleaned or f"call_{uuid.uuid4().hex[:24]}"


def _blocks(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content or [])


def _text_of(content: Any) -> str:
    return "\n".join(b.get("text", "") for b in _blocks(content) if b.get("type") == "text")


def _image_part(block: dict) -> dict:
    source = block["source"]
    return {"type": "image_url", "image_url": {"url": f"data:{source['media_type']};base64,{source['data']}"}}


def _estimate_tokens(block: dict) -> int:
    if block.get("type") == "image":
        return IMAGE_TOKENS
    if block.get("type") == "tool_result":
        return 10 + sum(_estimate_tokens(b) for b in _blocks(block.get("content")))
    return len(json.dumps(block, ensure_ascii=False)) // 4


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}}
        for t in tools
    ]


def to_openai_tool_choice(choice: dict | None) -> str | dict | None:
    if choice is None:
        return None
    kind = choice.get("type")
    if kind == "tool":
        return {"type": "function", "function": {"name": choice["name"]}}
    return {"none": "none", "any": "required"}.get(kind, "auto")


def trim_tool_results(messages: list[dict], *, budget: int, keep: int) -> list[dict]:
    """Clear the oldest unprotected tool results until the prompt estimate fits ``budget``.

    Works on a copy; the agent's own history is never modified.
    """
    total = sum(_estimate_tokens(b) for m in messages for b in _blocks(m["content"]))
    if total <= budget:
        return messages
    names = {b["id"]: b["name"] for m in messages if m["role"] == "assistant"
             for b in _blocks(m["content"]) if b.get("type") == "tool_use"}
    results = [(i, j) for i, m in enumerate(messages) if m["role"] == "user" and not isinstance(m["content"], str)
               for j, b in enumerate(m["content"]) if b.get("type") == "tool_result"]
    candidates = [(i, j) for i, j in results[: max(len(results) - keep, 0)]
                  if names.get(messages[i]["content"][j]["tool_use_id"]) not in PROTECTED_TOOLS]
    out = copy.copy(messages)
    target = int(budget * 0.7)  # like clear_at_least: free a real chunk, not a few tokens per step
    for i, j in candidates:
        if total <= target:
            break
        block = out[i]["content"][j]
        if block.get("content") == CLEARED:
            continue
        if out[i] is messages[i]:
            out[i] = {**messages[i], "content": list(messages[i]["content"])}
        cleared = {"type": "tool_result", "tool_use_id": block["tool_use_id"], "content": CLEARED}
        total -= _estimate_tokens(block) - _estimate_tokens(cleared)
        out[i]["content"][j] = cleared
    return out


class OpenAICompatLLM:
    def __init__(self, settings: Settings, provider: str | None = None):
        self.settings = settings
        self.provider = provider or settings.active_provider
        if self.provider == "gemini":
            if not settings.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set. Add it to backend/.env and restart the backend.")
            base_url, api_key, self.model = GEMINI_BASE_URL, settings.gemini_api_key, settings.gemini_model
        else:
            base_url, api_key, self.model = settings.ollama_base_url, "ollama", settings.ollama_model
        self.vision = settings.compat_vision if settings.compat_vision is not None else self.provider == "gemini"
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(settings.compat_timeout_s, connect=10.0),
        )
        self._signatures: OrderedDict[str, dict] = OrderedDict()

    # -- request translation -------------------------------------------------
    def to_openai_messages(self, system: str, messages: list[dict]) -> list[dict]:
        messages = trim_tool_results(
            messages, budget=self.settings.compat_context_tokens, keep=self.settings.compat_keep_tool_results
        )
        out: list[dict] = [{"role": "system", "content": system}]
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                out.append({"role": message["role"], "content": content})
            elif message["role"] == "assistant":
                out.append(self._assistant_message(content))
            else:
                out.extend(self._user_messages(content))
        return out

    def _assistant_message(self, content: list[dict]) -> dict:
        msg: dict[str, Any] = {"role": "assistant", "content": _text_of(content) or None}
        calls = []
        for block in content:
            if block.get("type") != "tool_use":
                continue  # thinking blocks are Claude-specific and are not replayed
            call: dict[str, Any] = {
                "id": block["id"], "type": "function",
                "function": {"name": block["name"], "arguments": json.dumps(block.get("input") or {})},
            }
            extra = self._signatures.get(block["id"])
            if extra is None and self.provider == "gemini":
                extra = GEMINI_SKIP_SIGNATURE
            if extra is not None:
                call["extra_content"] = extra
            calls.append(call)
        if calls:
            msg["tool_calls"] = calls
        return msg

    def _user_messages(self, content: list[dict]) -> list[dict]:
        out: list[dict] = []
        parts: list[dict] = []  # trailing user message: screenshots, then any plain text
        for block in content:
            if block.get("type") == "tool_result":
                texts = []
                for inner in _blocks(block.get("content")):
                    if inner.get("type") == "text":
                        texts.append(inner["text"])
                    elif inner.get("type") == "image":
                        if self.vision:
                            label = f"Screenshot returned by tool call {block['tool_use_id']}:"
                            parts += [{"type": "text", "text": label}, _image_part(inner)]
                            texts.append("[Screenshot attached in the next message.]")
                        else:
                            texts.append(NO_VISION)
                body = "\n".join(texts)
                if block.get("is_error"):
                    body = f"Error: {body}"
                out.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": body})
            elif block.get("type") == "text":
                parts.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "image" and self.vision:
                parts.append(_image_part(block))
        if parts:  # tool messages must directly follow the assistant turn that called them
            if all(p["type"] == "text" for p in parts):
                out.append({"role": "user", "content": "\n\n".join(p["text"] for p in parts)})
            else:
                out.append({"role": "user", "content": parts})
        return out

    def _remember_signature(self, call_id: str, extra: dict) -> None:
        self._signatures[call_id] = extra
        while len(self._signatures) > 500:
            self._signatures.popitem(last=False)

    def _body(self, system: str, tools: list[dict], messages: list[dict], tool_choice: dict | None) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self.to_openai_messages(system, messages),
            "max_tokens": self.settings.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = to_openai_tools(tools)
            choice = to_openai_tool_choice(tool_choice)
            if choice is not None:
                body["tool_choice"] = choice
        if self.provider == "gemini":
            body["reasoning_effort"] = EFFORT_TO_REASONING[self.settings.effort]
        return body

    # -- transport -------------------------------------------------------------
    def _map_status(self, status: int, detail: str) -> LLMError:
        name = "Gemini" if self.provider == "gemini" else "Ollama"
        if status in (401, 403):
            return LLMError(f"{name} rejected the API key. Check GEMINI_API_KEY and restart the backend.")
        if status == 404:
            hint = f" Run `ollama pull {self.model}` first." if self.provider == "ollama" else ""
            return LLMError(f"{name} does not know the model '{self.model}'.{hint}")
        if status == 429:
            return LLMError(f"Rate limited by {name} (free-tier quota). Wait a minute, or lower max steps.")
        if status == 400:
            return LLMError(f"{name} rejected the request: {detail[:300]}")
        return LLMError(f"{name} API error ({status}). Please try again.")

    def _connection_error(self) -> LLMError:
        if self.provider == "ollama":
            return LLMError(f"Could not reach Ollama at {self.settings.ollama_base_url}. Is `ollama serve` running?")
        return LLMError("Could not reach the Gemini API. Check your network connection.")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        try:
            return min(float(response.headers.get("retry-after", "")), 60.0)
        except ValueError:
            return min(4.0 * 2**attempt, 60.0)

    async def _post_stream(self, body: dict) -> AsyncIterator[dict]:
        """Yield parsed SSE chunks, backing off on free-tier rate limits before any output."""
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                async with self.client.stream("POST", "chat/completions", json=body) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode(errors="replace")
                        if response.status_code in (429, 503) and attempt < MAX_RATE_LIMIT_RETRIES:
                            await asyncio.sleep(self._retry_delay(response, attempt))
                            continue
                        raise self._map_status(response.status_code, detail)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        chunk = json.loads(data)
                        if "error" in chunk:
                            err = chunk["error"]
                            message = err.get("message", err) if isinstance(err, dict) else err
                            raise LLMError(f"Provider error: {message}")
                        yield chunk
                    return
            except httpx.ConnectError as exc:
                raise self._connection_error() from exc
            except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ReadTimeout) as exc:
                raise ValueError("stream interrupted") from exc  # the agent retries interrupted streams

    # -- LLMClient ---------------------------------------------------------------
    async def stream(
        self, *, system: str, tools: list[dict], messages: list[dict], tool_choice: dict | None = None
    ) -> AsyncIterator[LLMEvent | LLMTurn]:
        body = self._body(system, tools, messages, tool_choice)
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        calls: list[dict[str, Any]] = []
        by_index: dict[int, int] = {}
        finish: str | None = None
        usage: dict[str, Any] = {}
        model = self.model

        async for chunk in self._post_stream(body):
            model = chunk.get("model") or model
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning:
                    if not thinking_parts:
                        yield LLMEvent("thinking_start")
                    thinking_parts.append(reasoning)
                    yield LLMEvent("thinking_delta", {"text": reasoning})
                if delta.get("content"):
                    if not text_parts:
                        yield LLMEvent("text_start")
                    text_parts.append(delta["content"])
                    yield LLMEvent("text_delta", {"text": delta["content"]})
                for tc in delta.get("tool_calls") or []:
                    index = tc.get("index", len(calls))
                    pos = by_index.get(index)
                    fn = tc.get("function") or {}
                    # Some servers reuse index 0 for every parallel call; a new id means a new call.
                    if pos is None or (tc.get("id") and _tool_id(tc["id"]) != calls[pos]["id"]):
                        call = {"id": _tool_id(tc.get("id")), "name": fn.get("name") or "", "args": ""}
                        calls.append(call)
                        pos = by_index[index] = len(calls) - 1
                        yield LLMEvent("tool_use_start", {"id": call["id"], "name": call["name"]})
                    call = calls[pos]
                    if fn.get("name") and not call["name"]:
                        call["name"] = fn["name"]
                    call["args"] += fn.get("arguments") or ""
                    if tc.get("extra_content"):
                        call["extra"] = tc["extra_content"]
                finish = choice.get("finish_reason") or finish

        content: list[dict[str, Any]] = []
        if text_parts:
            content.append({"type": "text", "text": "".join(text_parts)})
        stop_reason = FINISH_REASONS.get(finish or "stop", "end_turn")
        for call in calls:
            try:
                args = json.loads(call["args"]) if call["args"].strip() else {}
            except json.JSONDecodeError:
                if stop_reason == "max_tokens":
                    args = {}  # the agent never runs tool calls from a truncated turn
                else:
                    raise ValueError("malformed tool arguments") from None  # retried by the agent
            if not isinstance(args, dict):
                raise ValueError("tool arguments are not an object")
            if call.get("extra"):
                self._remember_signature(call["id"], call["extra"])
            content.append({"type": "tool_use", "id": call["id"], "name": call["name"], "input": args})
        if calls and stop_reason == "end_turn":
            stop_reason = "tool_use"  # Gemini reports "stop" even when it called tools
        if not content:
            raise ValueError("empty response")

        cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        yield LLMTurn(
            content=content,
            stop_reason=stop_reason,
            model=model.removeprefix("models/"),
            usage={
                "input_tokens": max((usage.get("prompt_tokens") or 0) - cached, 0),
                "output_tokens": usage.get("completion_tokens") or 0,
                "cache_read_input_tokens": cached,
                "cache_creation_input_tokens": 0,
            },
        )
