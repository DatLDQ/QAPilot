"""FastAPI application: start QA runs, follow them live over SSE, fetch results and artifacts.

Run with:  uvicorn app.main:create_app --factory --port 8100 --reload

The seeded demo storefront is served by the same app at /shop/ (buggy) and
/shop-fixed/ (the known-good control build).
"""

import asyncio
import io
import json
import logging
import mimetypes
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .browser import BrowserBridge
from .config import Settings, get_settings
from .demo import DEMO_MODEL, DemoLLM
from .llm import ClaudeLLM, LLMClient
from .openai_compat import OpenAICompatLLM
from .runs import LLMFactory, RunManager, RunSpec
from .shop import build_shop_router
from .store import Store

logger = logging.getLogger("qapilot")

DEMO_STORY = (
    "As a shopper I can search the catalogue, open product details, add items to my cart and change "
    "quantities, apply the SAVE10 coupon, and check out with standard or express shipping."
)
DEMO_FOCUS = "Pricing maths, form validation, accessibility of the cart controls, and console or network errors."
MEDIA_TYPES = {".py": "text/plain", ".ts": "text/plain", ".md": "text/markdown", ".ini": "text/plain",
               ".json": "application/json", ".xml": "application/xml", ".zip": "application/zip",
               ".webm": "video/webm", ".jpg": "image/jpeg", ".png": "image/png"}


def _http_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter a full http:// or https:// URL.")
    return value


class RunRequest(BaseModel):
    target_url: str = Field(max_length=2000)
    story: str = Field(min_length=10, max_length=4000)
    focus: str | None = Field(default=None, max_length=1000)
    control_url: str | None = Field(default=None, max_length=2000)
    max_steps: int | None = Field(default=None, ge=3, le=150)
    verify: bool = True

    @field_validator("target_url")
    @classmethod
    def _target(cls, v: str) -> str:
        url = _http_url(v)
        if url is None:
            raise ValueError("Enter the URL of the app to test.")
        return url

    @field_validator("control_url")
    @classmethod
    def _control(cls, v: str | None) -> str | None:
        return _http_url(v)

    @field_validator("story")
    @classmethod
    def _story(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("Describe the user story in at least 10 characters.")
        return v.strip()

    @field_validator("focus")
    @classmethod
    def _focus(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


def make_llm(settings: Settings, target_url: str) -> LLMClient:
    if settings.use_demo:
        return DemoLLM(target_url)
    if settings.active_provider == "claude":
        return ClaudeLLM(settings)
    return OpenAICompatLLM(settings)


def sse(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _suite_zip(tests_dir: Path, prefix: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(tests_dir.rglob("*")):
            rel = path.relative_to(tests_dir)
            if not path.is_file() or path.name.startswith("results-") or {"__pycache__", "test-results"} & set(
                rel.parts
            ):
                continue
            zf.write(path, f"{prefix}/{rel.as_posix()}")
    return buf.getvalue()


def create_app(
    settings: Settings | None = None,
    llm_factory: LLMFactory = make_llm,
    bridge: BrowserBridge | None = None,
    *,
    warmup: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    model = DEMO_MODEL if settings.use_demo else settings.active_model
    provider = "demo" if settings.use_demo else settings.active_provider
    store = Store(settings.data_dir / "qapilot.db")
    bridge = bridge or BrowserBridge(settings)
    runs = RunManager(settings, store, bridge, llm_factory, model)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if interrupted := store.fail_interrupted():
            logger.warning("Marked %d interrupted run(s) as failed", interrupted)
        warm = asyncio.create_task(bridge.warmup()) if warmup else None
        yield
        if warm is not None:
            warm.cancel()
        await runs.shutdown()
        await asyncio.to_thread(bridge.stop)
        store.close()

    app = FastAPI(title="QAPilot API", version="1.0.0", lifespan=lifespan)
    app.state.qapilot = runs
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(build_shop_router())

    def get_run_or_404(run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Run not found.")
        return run

    def demo_target() -> dict[str, str]:
        base = settings.public_url.rstrip("/")
        return {"target_url": f"{base}/shop/", "control_url": f"{base}/shop-fixed/", "story": DEMO_STORY,
                "focus": DEMO_FOCUS}

    # -- meta ------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": provider,
            "model": model,
            "effort": settings.effort,
            "demo_mode": settings.use_demo,
            "api_key_configured": settings.api_key_configured,
            "browser": {"status": bridge.status, "version": bridge.version},
            "active_runs": runs.active_count(),
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "provider": provider,
            "model": model,
            "effort": settings.effort,
            "demo_mode": settings.use_demo,
            "max_steps": settings.max_agent_steps,
            "max_concurrent_runs": settings.max_concurrent_runs,
            "allowed_hosts": settings.allowed_hosts,
            "demo": demo_target(),
        }

    # -- runs ------------------------------------------------------------------------
    @app.post("/api/runs", status_code=201)
    async def create_run(body: RunRequest) -> dict[str, Any]:
        spec = RunSpec(
            target_url=body.target_url, story=body.story, focus=body.focus, control_url=body.control_url,
            max_steps=body.max_steps or settings.max_agent_steps, verify=body.verify,
        )
        return {**runs.start(spec), "live": True}

    @app.get("/api/runs")
    def list_runs(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return [{**r, "live": runs.is_active(r["id"])} for r in store.list_runs(limit)]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return {**get_run_or_404(run_id), "live": runs.is_active(run_id)}

    @app.get("/api/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        after: int = Query(-1, ge=-1),
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> StreamingResponse:
        if last_event_id and last_event_id.isdigit():
            after = max(after, int(last_event_id))  # EventSource resumes after a dropped connection
        live = runs.live.get(run_id)
        if live is None:
            get_run_or_404(run_id)
            stored = store.get_events(run_id)

            async def replay() -> AsyncIterator[str]:
                for event in stored:
                    if event.get("seq", 0) > after:
                        yield sse(event)

            stream: AsyncIterator[str] = replay()
        else:

            async def follow() -> AsyncIterator[str]:
                yield "retry: 2000\n\n"
                async for event in live.follow(after):
                    yield ": ping\n\n" if event is None else sse(event)

            stream = follow()
        return StreamingResponse(
            stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: str) -> dict[str, bool]:
        get_run_or_404(run_id)
        if not runs.cancel(run_id):
            raise HTTPException(409, "This run is not running.")
        return {"cancelled": True}

    @app.delete("/api/runs/{run_id}", status_code=204)
    async def delete_run(run_id: str) -> None:
        get_run_or_404(run_id)
        if runs.is_active(run_id):
            raise HTTPException(409, "Cancel the run before deleting it.")
        await asyncio.to_thread(runs.delete, run_id)

    @app.get("/api/runs/{run_id}/artifacts/{path:path}")
    def artifact(run_id: str, path: str, download: bool = False) -> FileResponse:
        get_run_or_404(run_id)
        root = runs.run_dir(run_id).resolve()
        file = (root / path).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise HTTPException(404, "Artifact not found.")
        media = MEDIA_TYPES.get(file.suffix.lower()) or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if media.startswith("text/"):
            media += "; charset=utf-8"
        return FileResponse(file, media_type=media, filename=file.name if download else None)

    @app.get("/api/runs/{run_id}/suite.zip")
    async def suite_zip(run_id: str) -> Response:
        get_run_or_404(run_id)
        tests_dir = runs.run_dir(run_id) / "tests"
        if not tests_dir.is_dir():
            raise HTTPException(404, "This run has no generated tests.")
        name = f"qapilot-{run_id}-tests"
        data = await asyncio.to_thread(_suite_zip, tests_dir, name)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})

    return app
