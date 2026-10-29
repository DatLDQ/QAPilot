import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Provider = Literal["claude", "gemini", "ollama"]

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# USD per million tokens. Used only for the cost estimate shown in the UI.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.5},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "demo-offline": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
}


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_prefix="QAPILOT_", extra="ignore", env_ignore_empty=True
    )

    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    model: str = "claude-opus-5-5"
    effort: Effort = "medium"
    max_tokens: int = 32000
    max_agent_steps: int = 60
    enable_fallbacks: bool = True
    # Offline rule-based agent instead of Claude. None = on only when no API key is configured.
    demo_mode: bool | None = None

    # Alternative providers through their OpenAI-compatible endpoints (see README, "Other LLM providers").
    # None = auto: Claude when ANTHROPIC_API_KEY is set, else Gemini when GEMINI_API_KEY is set, else demo.
    provider: Provider | None = None
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = "gemini-3.5-flash-lite"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:14b"
    compat_timeout_s: float = 300.0
    # Send screenshots as images. None = on for Gemini, off for Ollama (most local models have no vision).
    compat_vision: bool | None = None
    # Client-side stand-in for Claude's context editing: past this estimated prompt size, old tool results
    # are cleared, keeping the newest few and every scenario / bug / finish record.
    compat_context_tokens: int = 50_000
    compat_keep_tool_results: int = 6

    data_dir: Path = BACKEND_DIR / "data"
    # Public origin of this API, used to build the demo-shop URL the agent opens.
    public_url: str = "http://localhost:8100"

    # Browser sandbox
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 800
    action_timeout_ms: int = 8000
    navigation_timeout_ms: int = 20000
    # Hosts the agent may navigate to, in addition to the run's target host.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    record_video: bool = True
    max_concurrent_runs: int = 2

    snapshot_max_lines: int = 220
    verify_timeout_s: float = 120.0

    cors_origins: list[str] = ["http://localhost:5180", "http://127.0.0.1:5180"]

    @property
    def anthropic_key_configured(self) -> bool:
        return bool(self.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))

    @property
    def active_provider(self) -> Provider:
        if self.provider is not None:
            return self.provider
        if not self.anthropic_key_configured and self.gemini_api_key:
            return "gemini"
        return "claude"

    @property
    def api_key_configured(self) -> bool:
        """Credentials for the active provider are present (Ollama needs none)."""
        provider = self.active_provider
        if provider == "gemini":
            return bool(self.gemini_api_key)
        return provider == "ollama" or self.anthropic_key_configured

    @property
    def active_model(self) -> str:
        return {"claude": self.model, "gemini": self.gemini_model, "ollama": self.ollama_model}[self.active_provider]

    @property
    def use_demo(self) -> bool:
        return self.demo_mode if self.demo_mode is not None else not self.api_key_configured

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
