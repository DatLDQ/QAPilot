import asyncio
import json
import time

import pytest
from conftest import FakeBridge, FakeLLM, text, tool_use
from fastapi.testclient import TestClient

from app.llm import LLMEvent
from app.main import create_app
from app.store import Store

STORY = "As a shopper I can add a mug to my cart and check out."
BUG = {
    "title": "Checkout button does nothing",
    "severity": "high",
    "category": "functional",
    "steps_to_reproduce": ["Open the cart", "Click Checkout"],
    "expected": "The checkout form opens",
    "actual": "Nothing happens",
}


def parse_sse(body: str) -> list[dict]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def script() -> list:
    return [
        ([text("Checking the checkout."), tool_use("t1", "report_bug", **BUG)], "tool_use"),
        ([tool_use("t2", "finish", summary="Checkout is broken.", untested="Payments")], "tool_use"),
    ]


class HangingLLM(FakeLLM):
    async def stream(self, **kwargs):
        yield LLMEvent("text_start")
        await asyncio.sleep(60)


@pytest.fixture
def bridge():
    return FakeBridge()


@pytest.fixture
def llms():
    return []


@pytest.fixture
def client(settings, bridge, llms):
    def factory(_settings, _target_url):
        llm = llms.pop(0) if llms else FakeLLM(script())
        return llm

    app = create_app(settings, llm_factory=factory, bridge=bridge, warmup=False)  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c


def start(client, **overrides) -> dict:
    res = client.post("/api/runs", json={"target_url": "http://localhost:8100/shop/", "story": STORY, **overrides})
    assert res.status_code == 201, res.text
    return res.json()


def wait_for_status(client, run_id: str, *statuses: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never reached {statuses}")


def test_health_and_config(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["model"] == "claude-opus-5-5" and health["demo_mode"] is False
    assert health["browser"] == {"status": "ready", "version": "fake-1.0"} and health["active_runs"] == 0
    config = client.get("/api/config").json()
    assert config["demo"]["target_url"] == "http://testserver/shop/"
    assert config["demo"]["control_url"] == "http://testserver/shop-fixed/"
    assert config["max_steps"] == 5


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"target_url": "ftp://example.com", "story": STORY}, "Enter a full http:// or https:// URL."),
        ({"target_url": "   ", "story": STORY}, "Enter the URL of the app to test."),
        ({"target_url": "http://localhost/", "story": "  too short  "}, "at least 10 characters"),
        ({"target_url": "http://localhost/", "story": STORY, "control_url": "nope"}, "Enter a full http://"),
        ({"target_url": "http://localhost/", "story": STORY, "max_steps": 1}, "greater than or equal to 3"),
    ],
)
def test_run_validation(client, body, message):
    res = client.post("/api/runs", json=body)
    assert res.status_code == 422
    assert message in json.dumps(res.json())


def test_run_lifecycle(client, bridge):
    row = start(client, focus="  ", control_url="", max_steps=8)
    assert row["status"] == "queued" and row["live"] is True and row["max_steps"] == 8
    assert row["focus"] is None and row["control_url"] is None
    run_id = row["id"]

    events = parse_sse(client.get(f"/api/runs/{run_id}/events").text)
    types = [e["type"] for e in events]
    assert types[:3] == ["run_queued", "run_start", "phase"] and types[-1] == "done"
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert [e["phase"] for e in events if e["type"] == "phase"] == ["explore", "report"]
    done = events[-1]
    assert done["status"] == "completed" and done["error"] is None
    assert done["summary"]["bugs_by_severity"]["high"] == 1 and done["summary"]["tests"] == 0
    assert bridge.sessions[0].closed
    # The report is announced on the stream, so a live viewer can show it without refetching.
    assert [e for e in events if e["type"] == "artifacts"][-1]["report"] == "report.md"

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "completed" and run["live"] is False
    result = run["result"]
    assert result["summary"] == "Checkout is broken." and result["untested"] == "Payments"
    assert result["bugs"][0]["title"] == BUG["title"] and result["bugs"][0]["test"] is None
    assert result["artifacts"]["report"] == "report.md" and result["finished"] is True
    assert [r["id"] for r in client.get("/api/runs").json()] == [run_id]

    # Resuming after an event id only sends what came later.
    tail = parse_sse(client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(done["seq"] - 1)}).text)
    assert [e["type"] for e in tail] == ["done"]

    report = client.get(f"/api/runs/{run_id}/artifacts/report.md")
    assert report.status_code == 200 and report.headers["content-type"].startswith("text/markdown")
    assert BUG["title"] in report.text
    download = client.get(f"/api/runs/{run_id}/artifacts/bugs.json", params={"download": True})
    assert "attachment" in download.headers["content-disposition"]
    for path in ("..%2Fqapilot.db", "../../qapilot.db", "missing.png"):
        assert client.get(f"/api/runs/{run_id}/artifacts/{path}").status_code == 404
    assert client.get(f"/api/runs/{run_id}/suite.zip").status_code == 404  # no scenarios, so no tests

    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get(f"/api/runs/{run_id}/events").status_code == 404


def test_browser_failure_fails_the_run(settings, llms):
    app = create_app(settings, llm_factory=lambda *_: FakeLLM(script()), bridge=FakeBridge(fail_open=True),
                     warmup=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        run_id = start(client)["id"]
        events = parse_sse(client.get(f"/api/runs/{run_id}/events").text)
        assert [e["type"] for e in events][-2:] == ["error", "done"]
        run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error"] == "Could not start the browser: Executable doesn't exist at /ms-playwright/chromium"


def test_cancel_a_live_run(client, llms, bridge):
    llms.append(HangingLLM([]))
    run_id = start(client)["id"]
    wait_for_status(client, run_id, "running")
    assert client.delete(f"/api/runs/{run_id}").status_code == 409
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    events = parse_sse(client.get(f"/api/runs/{run_id}/events").text)
    assert events[-1]["type"] == "done" and events[-1]["status"] == "cancelled"
    run = wait_for_status(client, run_id, "cancelled")
    assert run["error"] == "Cancelled by the user." and bridge.sessions[0].closed
    assert client.post("/api/runs/unknown/cancel").status_code == 404


def test_interrupted_runs_are_failed_on_startup(settings):
    store = Store(settings.data_dir / "qapilot.db")
    store.create_run("stale", target_url="http://localhost/", story=STORY, focus=None, control_url=None,
                     max_steps=5, model="claude-opus-5-5")
    store.mark_started("stale")
    store.close()
    app = create_app(settings, llm_factory=lambda *_: FakeLLM([]), bridge=FakeBridge(), warmup=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        run = client.get("/api/runs/stale").json()
        assert run["status"] == "failed" and "server restarted" in run["error"]
        # A stored run with no events replays as an empty stream.
        assert parse_sse(client.get("/api/runs/stale/events").text) == []
