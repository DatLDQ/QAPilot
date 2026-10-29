"""Run lifecycle: queue a QA session, stream its events live and persist the outcome.

Each run goes through four phases, all reported on the run's event stream:

    explore   Claude drives an isolated browser context through the user story
    generate  the recorded scenarios become Playwright suites (Python and TypeScript)
    verify    the Python suite replays in a fresh browser, then on the control build
    report    report.md and bugs.json are written and the run is stored

Live events are kept in memory so any number of viewers can follow (and resume) a
run over SSE. Finished runs are replayed from SQLite.
"""

import asyncio
import logging
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import QAAgent, compact_events, estimate_cost
from .browser import BrowserBridge, BrowserSession
from .codegen import app_base, plan_tests, write_suite
from .config import Settings
from .llm import LLMClient, LLMError
from .recorder import SEVERITIES, Recorder
from .report import write_report
from .store import Store, now
from .tools import QAToolExecutor
from .verify import SuiteRun, apply_to_bugs, run_suite

logger = logging.getLogger("qapilot")

LLMFactory = Callable[[Settings, str], LLMClient]
PING_S = 15.0
KEEP_FINISHED_S = 600.0  # finished runs stay in memory this long so open streams can drain


class RunError(RuntimeError):
    """A pipeline failure with a message that is safe to show to the user."""


@dataclass
class RunSpec:
    target_url: str
    story: str
    max_steps: int
    focus: str | None = None
    control_url: str | None = None
    verify: bool = True


class LiveRun:
    """The in-memory event log of a run that is queued, running or recently finished."""

    def __init__(self, run_id: str):
        self.id = run_id
        self.events: list[dict[str, Any]] = []
        self.done = False
        self.task: asyncio.Task[None] | None = None
        self._started = time.perf_counter()
        self._changed = asyncio.Event()

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append({**event, "seq": len(self.events), "t": int((time.perf_counter() - self._started) * 1000)})
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def close(self) -> None:
        self.done = True
        self._changed.set()

    async def follow(self, after: int = -1) -> AsyncIterator[dict[str, Any] | None]:
        """Yield events with ``seq > after`` as they arrive; ``None`` is a keep-alive tick."""
        idx = max(after + 1, 0)
        while True:
            changed = self._changed
            while idx < len(self.events):
                yield self.events[idx]
                idx += 1
            if self.done:
                return
            try:
                await asyncio.wait_for(changed.wait(), PING_S)
            except TimeoutError:
                yield None


@dataclass
class _Progress:
    """Everything a run produced so far, so a failed or cancelled run still keeps its evidence."""

    run_dir: Path
    recorder: Recorder | None = None
    agent: QAAgent | None = None
    session: BrowserSession | None = None
    manifest: dict[str, Any] | None = None
    target: SuiteRun | None = None
    control: SuiteRun | None = None
    artifacts: dict[str, str | None] = field(default_factory=dict)
    warning: str | None = None


class RunManager:
    def __init__(self, settings: Settings, store: Store, bridge: BrowserBridge, llm_factory: LLMFactory, model: str):
        self.settings = settings
        self.store = store
        self.bridge = bridge
        self.llm_factory = llm_factory
        self.model = model
        self.live: dict[str, LiveRun] = {}
        self._slots = asyncio.Semaphore(settings.max_concurrent_runs)
        self._closing = False

    # -- public API ----------------------------------------------------------------

    def start(self, spec: RunSpec) -> dict[str, Any]:
        run_id = uuid.uuid4().hex[:12]
        row = self.store.create_run(
            run_id, target_url=spec.target_url, story=spec.story, focus=spec.focus, control_url=spec.control_url,
            max_steps=spec.max_steps, model=self.model,
        )
        live = LiveRun(run_id)
        self.live[run_id] = live
        live.emit({"type": "run_queued", "step": 0, "position": self.active_count()})
        live.task = asyncio.create_task(self._run(live, spec), name=f"qapilot-run-{run_id}")
        return row

    def active_count(self) -> int:
        return sum(1 for r in self.live.values() if not r.done)

    def is_active(self, run_id: str) -> bool:
        live = self.live.get(run_id)
        return live is not None and not live.done

    def cancel(self, run_id: str) -> bool:
        live = self.live.get(run_id)
        if live is None or live.done or live.task is None:
            return False
        live.task.cancel()
        return True

    async def shutdown(self) -> None:
        self._closing = True
        tasks = [r.task for r in self.live.values() if r.task is not None and not r.done]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=30)

    def delete(self, run_id: str) -> None:
        self.live.pop(run_id, None)
        self.store.delete_run(run_id)
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def run_dir(self, run_id: str) -> Path:
        return self.settings.runs_dir / run_id

    # -- pipeline ------------------------------------------------------------------

    async def _run(self, live: LiveRun, spec: RunSpec) -> None:
        progress = _Progress(run_dir=self.run_dir(live.id))
        status, error = "failed", None
        try:
            async with self._slots:
                self.store.mark_started(live.id)
                live.emit({
                    "type": "run_start", "step": 0, "run_id": live.id, "target_url": spec.target_url,
                    "story": spec.story, "focus": spec.focus, "control_url": spec.control_url,
                    "max_steps": spec.max_steps, "verify": spec.verify, "model": self.model,
                    "started_at": now(),
                })
                await self._pipeline(live, spec, progress)
                status, error = "completed", progress.warning
        except asyncio.CancelledError:
            status = "cancelled"
            error = "The server shut down during this run." if self._closing else "Cancelled by the user."
        except (RunError, LLMError) as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - a run must always end with a stored outcome
            logger.exception("Run %s failed", live.id)
            error = f"Unexpected error: {type(exc).__name__}: {exc}"
        finally:
            await self._finalize(live, spec, progress, status, error)

    async def _pipeline(self, live: LiveRun, spec: RunSpec, progress: _Progress) -> None:
        run_dir = progress.run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        settings = self.settings.model_copy(update={"max_agent_steps": spec.max_steps})
        llm = self.llm_factory(settings, spec.target_url)

        # 1. explore
        live.emit({"type": "phase", "step": 0, "phase": "explore"})
        try:
            session = await self.bridge.open_session(run_dir, spec.target_url)
        except Exception as exc:  # noqa: BLE001 - Playwright raises plain Errors for launch failures
            raise RunError(f"Could not start the browser: {str(exc).splitlines()[0]}") from exc
        progress.session = session
        recorder = progress.recorder = Recorder(spec.target_url)
        agent = progress.agent = QAAgent(llm, QAToolExecutor(self.bridge, session, recorder), settings)
        async for event in agent.run(spec.target_url, spec.story, spec.focus):
            live.emit(event)
        await self._close_session(live, progress)
        if agent.error:
            if not recorder.scenarios:
                raise RunError(agent.error)
            progress.warning = f"The session ended early: {agent.error}"

        # 2. generate
        step = agent.step
        tests = plan_tests(recorder)
        if not tests:
            live.emit({"type": "phase", "step": step, "phase": "report"})
            self._write_report(live, spec, progress)
            return
        live.emit({"type": "phase", "step": step, "phase": "generate"})
        progress.manifest = write_suite(recorder, run_dir, live.id, spec.story)
        live.emit({"type": "suite", "step": step, **progress.manifest})

        # 3. verify
        if spec.verify:
            live.emit({"type": "phase", "step": step, "phase": "verify"})
            progress.target = await self._verify(live, progress, "target", progress.manifest["base_url"])
            apply_to_bugs(recorder, progress.target)
            live.emit({"type": "bugs_verified", "step": step,
                       "bugs": [{"id": b.id, "reproduced": b.reproduced} for b in recorder.bugs]})
            if spec.control_url:
                progress.control = await self._verify(live, progress, "control", app_base(spec.control_url))

        # 4. report
        live.emit({"type": "phase", "step": step, "phase": "report"})
        self._write_report(live, spec, progress)

    async def _verify(self, live: LiveRun, progress: _Progress, label: str, base_url: str) -> SuiteRun:
        assert progress.recorder is not None and progress.agent is not None
        tests = plan_tests(progress.recorder)
        step = progress.agent.step
        live.emit({"type": "verify_start", "step": step, "label": label, "base_url": base_url,
                   "tests": [t.name for t in tests]})

        def on_test(name: str, outcome: str) -> None:
            live.emit({"type": "verify_test", "step": step, "label": label, "name": name, "actual": outcome})

        result = await run_suite(progress.run_dir / "tests", tests, base_url, label=label,
                                 timeout_s=self.settings.verify_timeout_s, on_test=on_test)
        live.emit({"type": "verify_done", "step": step, **result.to_dict()})
        return result

    async def _close_session(self, live: LiveRun, progress: _Progress) -> None:
        session, progress.session = progress.session, None
        if session is None:
            return
        try:
            progress.artifacts.update(await self.bridge.call(session.close()))
        except Exception:  # noqa: BLE001 - losing the video must not lose the run
            logger.exception("Could not close the browser session of run %s", live.id)
        live.emit({"type": "artifacts", "step": progress.agent.step if progress.agent else 0, **progress.artifacts})

    def _write_report(self, live: LiveRun, spec: RunSpec, progress: _Progress) -> None:
        if progress.recorder is None:
            return
        agent = progress.agent
        meta = {
            "id": live.id, "created_at": now(), "model": agent.model if agent else self.model,
            "steps": agent.step if agent else 0, "story": spec.story,
            "usage": {**agent.usage, "cost_usd": self._cost(agent)} if agent else {},
        }
        write_report(progress.run_dir, meta, progress.recorder, self._test_names(progress), progress.target,
                     progress.control)
        progress.artifacts.update({"report": "report.md", "bugs": "bugs.json"})
        live.emit({"type": "artifacts", "step": agent.step if agent else 0, **progress.artifacts})

    # -- results -------------------------------------------------------------------

    @staticmethod
    def _cost(agent: QAAgent | None) -> float | None:
        return estimate_cost(agent.model, agent.usage) if agent else None

    @staticmethod
    def _test_names(progress: _Progress) -> dict[int, str]:
        return {t.scenario_id: t.name for t in plan_tests(progress.recorder)} if progress.recorder else {}

    def _summary(self, progress: _Progress, elapsed_ms: int) -> dict[str, Any]:
        recorder, agent = progress.recorder, progress.agent
        bugs = recorder.bugs if recorder else []
        return {
            "stats": recorder.stats() if recorder else None,
            "bugs_by_severity": {s: sum(1 for b in bugs if b.severity == s) for s in SEVERITIES},
            "reproduced": sum(1 for b in bugs if b.reproduced is True),
            "not_reproduced": sum(1 for b in bugs if b.reproduced is False),
            "tests": len(progress.manifest["tests"]) if progress.manifest else 0,
            "control": {"passed": progress.control.passed, "failed": progress.control.failed}
            if progress.control else None,
            "steps": agent.step if agent else 0,
            "cost_usd": self._cost(agent),
            "elapsed_ms": elapsed_ms,
        }

    def _result(self, progress: _Progress) -> dict[str, Any] | None:
        recorder, agent = progress.recorder, progress.agent
        if recorder is None:
            return None
        names = self._test_names(progress)
        data = recorder.to_dict()
        data["bugs"] = [{**b, "test": names.get(b["scenario_id"] or -1)} for b in data["bugs"]]
        return {
            **data,
            "usage": {**agent.usage, "cost_usd": self._cost(agent)} if agent else None,
            "steps": agent.step if agent else 0,
            "finished": agent.finished if agent else False,
            "stop_reason": agent.stop_reason if agent else None,
            "suite": progress.manifest,
            "verification": {
                "target": progress.target.to_dict() if progress.target else None,
                "control": progress.control.to_dict() if progress.control else None,
            },
            "artifacts": progress.artifacts,
        }

    async def _finalize(self, live: LiveRun, spec: RunSpec, progress: _Progress, status: str,
                        error: str | None) -> None:
        if progress.session is not None:
            await self._close_session(live, progress)
        if status != "completed" and progress.recorder is not None and "report" not in progress.artifacts:
            try:
                self._write_report(live, spec, progress)
            except Exception:  # noqa: BLE001 - a partial report is best effort
                logger.exception("Could not write the partial report of run %s", live.id)
        elapsed_ms = live.events[-1]["t"] if live.events else 0
        summary = self._summary(progress, elapsed_ms)
        if error and status != "completed":
            live.emit({"type": "error", "step": progress.agent.step if progress.agent else 0, "message": error})
        live.emit({"type": "done", "step": progress.agent.step if progress.agent else 0, "status": status,
                   "error": error, "summary": summary})
        try:
            self.store.finish_run(
                live.id, status=status, error=error, model=progress.agent.model if progress.agent else self.model,
                summary=summary, result=self._result(progress), events=compact_events(live.events),
            )
        except Exception:  # noqa: BLE001 - e.g. the run was deleted while it ran
            logger.exception("Could not store run %s", live.id)
        live.close()
        asyncio.get_running_loop().call_later(KEEP_FINISHED_S, self._forget, live)

    def _forget(self, live: LiveRun) -> None:
        if self.live.get(live.id) is live:
            del self.live[live.id]
