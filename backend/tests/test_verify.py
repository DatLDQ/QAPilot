import textwrap

import pytest

from app import verify
from app.codegen import PY_FILE, GeneratedTest
from app.recorder import Recorder
from app.verify import _PROGRESS, SuiteRun, _parse_junit, _verdict, apply_to_bugs, run_suite

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="test_qapilot" name="test_01_ok[chromium]" time="1.20"/>
  <testcase classname="test_qapilot" name="test_02_broken[chromium]" time="2.5">
    <failure message="AssertionError: 2 check(s) failed:&#10;- #4 Subtotal is $36.00: Locator">page = &lt;Page&gt;
E       AssertionError: 2 check(s) failed:
E       - #4 Subtotal is $36.00: Locator expected to have text '$36.00'
E       - #12 Badge shows 1: Locator expected to contain text '1'</failure>
  </testcase>
  <testcase classname="test_qapilot" name="test_03_setup" time="0"><error message="no fixture"/></testcase>
  <testcase classname="test_qapilot" name="test_04_skip" time="0"><skipped message="later"/></testcase>
</testsuite></testsuites>
"""


def test_parse_junit_strips_the_browser_param(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text(JUNIT, encoding="utf-8")
    results = _parse_junit(path)
    assert results["test_01_ok"] == ("passed", 1.2, None, [])
    assert results["test_02_broken"][0] == "failed"
    assert results["test_02_broken"][2].startswith("AssertionError: 2 check(s) failed:")
    # Failed checks come from the full text, which also lists the one cut from the message.
    assert results["test_02_broken"][3] == [4, 12]
    assert results["test_03_setup"][0] == "error"
    assert results["test_04_skip"][0] == "skipped"


@pytest.mark.parametrize(
    ("expected", "actual", "control", "verdict"),
    [
        ("fail", "failed", False, "reproduced"),
        ("fail", "passed", False, "not_reproduced"),
        ("pass", "passed", False, "stable"),
        ("pass", "failed", False, "flaky"),
        ("pass", "passed", True, "stable"),
        ("pass", "failed", True, "flaky"),
        ("fail", "error", False, "error"),
        ("fail", "missing", True, "error"),
    ],
)
def test_verdict(expected, actual, control, verdict):
    assert _verdict(expected, actual, control) == verdict


def test_progress_lines():
    assert _PROGRESS.search("test_qapilot.py::test_01_a[chromium] FAILED   [ 14%]").groups() == ("test_01_a", "FAILED")
    assert _PROGRESS.search("test_qapilot.py::test_02_b PASSED [100%]").groups() == ("test_02_b", "PASSED")
    assert _PROGRESS.search("collected 2 items") is None


def _outcome(scenario_id: int, actual: str, verdict: str, failed_checks: list[int] | None = None) -> verify.TestOutcome:
    return verify.TestOutcome(scenario_id, f"test_{scenario_id:02d}", "fail", actual, 1.0, None, verdict,
                              failed_checks or [])


def _bug(rec: Recorder, title: str) -> None:
    rec.add_bug(title=title, severity="high", category="functional", steps_to_reproduce=["x"],
                expected="y", actual="z", url="", screenshot=None)


def test_apply_to_bugs():
    rec = Recorder("http://localhost/shop/")
    rec.begin("two bugs in one test", None, 0)
    for name in ("badge", "detail page"):
        rec.add_step(0, kind="expect", description=name, assertion="visible", passed=False)
        _bug(rec, f"Bug in {name}")
    for name in ("passes on replay", "cannot run", "action broke"):
        rec.begin(name, None, 0)
        rec.add_step(0, kind="expect", description=name, assertion="visible", passed=False)
        _bug(rec, f"Bug {name}")
    rec.begin("prose only", None, 0)
    _bug(rec, "No check behind it")
    run = SuiteRun("target", "http://localhost/shop/", True, 3.0, tests=[
        # Only the badge check failed again, so the detail-page bug did not reproduce.
        _outcome(1, "failed", "reproduced", [1]),
        _outcome(2, "passed", "not_reproduced"),
        _outcome(3, "error", "error"),
        _outcome(4, "failed", "reproduced"),
    ])
    apply_to_bugs(rec, run)
    assert [b.check_steps for b in rec.bugs[:2]] == [[1], [2]]
    assert [b.reproduced for b in rec.bugs] == [True, False, False, None, None, None]


SUITE = '''
import time


def test_01_passes():
    assert True


def test_02_fails():
    assert 1 + 1 == 3, "maths is broken"


def test_03_sleeps():
    time.sleep(float(__import__("os").environ.get("SLEEP", "0")))
'''


def _tests(*rows: tuple[int, str, str]) -> list[GeneratedTest]:
    return [GeneratedTest(sid, name, name, expected, []) for sid, name, expected in rows]


async def test_run_suite_replays_and_streams_progress(tmp_path):
    (tmp_path / PY_FILE).write_text(textwrap.dedent(SUITE), encoding="utf-8")
    seen: list[tuple[str, str]] = []
    tests = _tests((1, "test_01_passes", "pass"), (2, "test_02_fails", "fail"), (3, "test_03_sleeps", "pass"),
                   (4, "test_04_vanished", "pass"))
    run = await run_suite(tmp_path, tests, "http://localhost/shop/", label="target", timeout_s=60,
                          on_test=lambda name, outcome: seen.append((name, outcome)))
    assert run.ok and run.error is None
    assert [(t.name, t.actual, t.verdict) for t in run.tests] == [
        ("test_01_passes", "passed", "stable"),
        ("test_02_fails", "failed", "reproduced"),
        ("test_03_sleeps", "passed", "stable"),
        ("test_04_vanished", "missing", "error"),
    ]
    assert "maths is broken" in (run.tests[1].message or "")
    assert (run.passed, run.failed) == (2, 2)
    assert seen == [("test_01_passes", "passed"), ("test_02_fails", "failed"), ("test_03_sleeps", "passed")]


async def test_run_suite_times_out(tmp_path, monkeypatch):
    (tmp_path / PY_FILE).write_text(textwrap.dedent(SUITE), encoding="utf-8")
    monkeypatch.setenv("SLEEP", "30")
    run = await run_suite(tmp_path, _tests((3, "test_03_sleeps", "pass")), "http://localhost/", label="control",
                          timeout_s=3)
    assert not run.ok and run.error == "The suite did not finish within 3s."
