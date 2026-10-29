"""The whole pipeline against the seeded shop: a real Chromium, the offline demo agent,
generated suites replayed by pytest on both builds. Needs ``playwright install chromium``.

Run with:  pytest -m e2e
"""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.config import Settings
from app.demo import DemoLLM
from app.main import create_app

pytestmark = pytest.mark.e2e


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    port = free_port()
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", public_url=f"http://127.0.0.1:{port}",
                        demo_mode=True, verify_timeout_s=240)
    app = create_app(settings, llm_factory=lambda _s, url: DemoLLM(url, delay=0))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not srv.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
        yield client
    srv.should_exit = True
    thread.join(timeout=60)


def test_demo_run_finds_and_verifies_every_seeded_bug(server):
    demo = server.get("/api/config").json()["demo"]
    run_id = server.post("/api/runs", json=demo).json()["id"]

    events = []
    with server.stream("GET", f"/api/runs/{run_id}/events", timeout=None) as res:
        for line in res.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] == "done":
                    break
    done = events[-1]
    assert done["status"] == "completed", done["error"]
    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert phases == ["explore", "generate", "verify", "report"]

    run = server.get(f"/api/runs/{run_id}").json()
    result = run["result"]
    bugs = result["bugs"]
    assert len(bugs) == 7 and all(b["reproduced"] is True and b["test"] for b in bugs)
    control = result["verification"]["control"]
    assert control["error"] is None and all(t["verdict"] == "stable" for t in control["tests"])
    streamed = [e for e in events if e["type"] == "verify_test"]
    assert len(streamed) == len(result["verification"]["target"]["tests"]) + len(control["tests"])

    for path in ("report.md", "bugs.json", "session.webm", "trace.zip", "tests/test_qapilot.py",
                 "tests/qapilot.spec.ts"):
        assert server.get(f"/api/runs/{run_id}/artifacts/{path}").status_code == 200, path
    assert server.get(f"/api/runs/{run_id}/suite.zip").status_code == 200
    report = server.get(f"/api/runs/{run_id}/artifacts/report.md").text
    assert "- **Same build**" in report and "- **Known-good build**" in report
