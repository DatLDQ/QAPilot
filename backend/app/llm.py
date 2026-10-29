"""Thin streaming wrapper around the Claude Messages API.

The agent loop only depends on the ``LLMClient`` protocol, which yields normalised
``LLMEvent``s and finishes with an ``LLMTurn``. The offline demo agent and the tests
implement the same protocol.

A QA session is long: dozens of page outlines and screenshots flow back as tool
results. Server-side context editing clears the oldest tool results once the prompt
grows past a threshold, keeping bug reports and scenario markers, so the agent can
explore for 60 steps without the context (or the bill) running away.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import anthropic

from .config import Settings

EventKind = Literal["thinking_start", "thinking_delta", "text_start", "text_delta", "tool_use_start"]

CONTEXT_EDITING_BETA = "context-management-2025-06-27"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class LLMEvent:
    kind: EventKind
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMTurn:
    content: list[dict[str, Any]]
    stop_reason: str | None
    model: str
    usage: dict[str, int]


class LLMError(RuntimeError):
    """An API failure with a message that is safe to show to the user."""


class LLMClient(Protocol):
    model: str

    def stream(
        self, *, system: str, tools: list[dict], messages: list[dict], tool_choice: dict | None = None
    ) -> AsyncIterator[LLMEvent | LLMTurn]: ...


def _usage_dict(usage: Any) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens or 0,
        "output_tokens": usage.output_tokens or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
    }


def sanitize_assistant_content(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare assistant content for replay after a server-side fallback.

    Blocks the declined model produced before the last ``fallback`` marker must not be
    echoed back (except text), and the marker itself is an ignorable audit block.
    """
    idx = max((i for i, b in enumerate(content) if b.get("type") == "fallback"), default=-1)
    if idx < 0:
        return content
    before = [b for b in content[:idx] if b.get("type") == "text"]
    return before + content[idx + 1 :]


NO_CREDENTIALS = "No Anthropic credentials found. Set ANTHROPIC_API_KEY in backend/.env and restart the backend."


def _map_error(exc: Exception) -> LLMError:
    if isinstance(exc, TypeError) and "authentication" in str(exc).lower():
        # The SDK builds a client without credentials and only fails when a request is made.
        return LLMError(NO_CREDENTIALS)
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMError("Anthropic API key is missing or invalid. Set ANTHROPIC_API_KEY and restart the backend.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return LLMError("This API key does not have access to the configured model.")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("Rate limited by the Anthropic API. Please wait a moment and try again.")
    if isinstance(exc, anthropic.BadRequestError):
        return LLMError(f"The API rejected the request: {exc.message}")
    if isinstance(exc, anthropic.APIStatusError):
        return LLMError(f"Anthropic API error ({exc.status_code}). Please try again.")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("Could not reach the Anthropic API. Check your network connection.")
    return LLMError(f"Unexpected LLM error: {exc}")


# Old page outlines and screenshots are the bulk of a long session and go stale fast.
CONTEXT_MANAGEMENT: dict[str, Any] = {
    "edits": [
        {
            "type": "clear_tool_uses_20250919",
            "trigger": {"type": "input_tokens", "value": 50_000},
            "keep": {"type": "tool_uses", "value": 6},
            "clear_at_least": {"type": "input_tokens", "value": 12_000},
            "exclude_tools": ["begin_scenario", "report_bug", "finish"],
        }
    ]
}


class ClaudeLLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.model
        try:
            self.client = (
                anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
                if settings.anthropic_api_key
                else anthropic.AsyncAnthropic()  # env var or `ant auth login` profile
            )
        except anthropic.AnthropicError as exc:
            raise LLMError(NO_CREDENTIALS) from exc

    def _request_kwargs(self) -> dict[str, Any]:
        betas = [CONTEXT_EDITING_BETA]
        extra: dict[str, Any] = {"context_management": CONTEXT_MANAGEMENT}
        if self.settings.enable_fallbacks:
            # On a safety-classifier refusal, the API retries the request on the recommended fallback model.
            betas.append(FALLBACK_BETA)
            extra["fallbacks"] = "default"
        return {"betas": betas, **extra}

    async def stream(
        self, *, system: str, tools: list[dict], messages: list[dict], tool_choice: dict | None = None
    ) -> AsyncIterator[LLMEvent | LLMTurn]:
        extra = self._request_kwargs()
        if tool_choice is not None:
            extra["tool_choice"] = tool_choice
        try:
            async with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=self.settings.max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": self.settings.effort},
                cache_control={"type": "ephemeral"},  # caches tools + system + history across agent steps
                **extra,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "thinking":
                            yield LLMEvent("thinking_start")
                        elif block.type == "text":
                            yield LLMEvent("text_start")
                        elif block.type == "tool_use":
                            yield LLMEvent("tool_use_start", {"id": block.id, "name": block.name})
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "thinking_delta" and delta.thinking:
                            yield LLMEvent("thinking_delta", {"text": delta.thinking})
                        elif delta.type == "text_delta":
                            yield LLMEvent("text_delta", {"text": delta.text})
                final = await stream.get_final_message()
        except (anthropic.APIError, TypeError) as exc:
            raise _map_error(exc) from exc
        content = [block.to_dict() for block in final.content]
        yield LLMTurn(
            content=sanitize_assistant_content(content),
            stop_reason=final.stop_reason,
            model=final.model,
            usage=_usage_dict(final.usage),
        )
