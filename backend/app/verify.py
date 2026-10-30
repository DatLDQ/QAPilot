"""Prove the findings: replay the generated suite in a fresh browser with pytest.

A test the agent expected to fail (it holds a failed check) must fail again on the
same build: that bug *reproduced*. Optionally the suite also runs against a known-good
build (``control_url``), where every test should pass, which shows the tests detect
the bugs rather than break on their own.
"""

import asyncio
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .codegen import PY_FILE, GeneratedTest
from .recorder import Recorder

VERDICT_LABELS = {
    "reproduced": "Bug reproduced",
    "stable": "Passes as expected",
    "not_reproduced": "Did not reproduce",
    "flaky": "Unexpected failure",
    "error": "Could not run",
}
_PARAM_ID = re.compile(r"\[[^\]]*\]$")
# One line per test in verbose mode: "test_qapilot.py::test_01_x[chromium] FAILED   [ 14%]"
_PROGRESS = re.compile(r"::(test_\w+)(?:\[[^\]]*\])? (PASSED|FAILED|ERROR|SKIPPED)\b")
# One line per failed soft check, "- #24 Cart badge shows 1 item: ...", possibly behind pytest's "E   " prefix.
_FAILED_CHECK = re.compile(r"^(?:E\s+)?- #(\d+) ", re.MULTILINE)


@dataclass
class TestOutcome:
    scenario_id: int
    name: str
    expected: str  # pass | fail
    actual: str  # passed | failed | error | skipped | missing
    duration_s: float
    message: str | None
    verdict: str
    failed_checks: list[int] = field(default_factory=list)  # step indices of the checks that failed


@dataclass
class SuiteRun:
    label: str  # target | control
    base_url: str
    ok: bool  # pytest ran and produced a report (regardless of test results)
    duration_s: float
    passed: int = 0
    failed: int = 0
    tests: list[TestOutcome] = field(default_factory=list)
    error: str | None = None
    output_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_junit(path: Path) -> dict[str, tuple[str, float, str | None, list[int]]]:
    results: dict[str, tuple[str, float, str | None, list[int]]] = {}
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        name = _PARAM_ID.sub("", case.get("name", ""))  # pytest-playwright appends "[chromium]"
        duration = float(case.get("time") or 0)
        outcome, message, failed_checks = "passed", None, []
        for tag, label in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
            node = case.find(tag)
            if node is not None:
                outcome = label
                raw = node.get("message") or node.text or ""
                message = "\n".join(line for line in raw.strip().splitlines()[:6])[:800] or None
                # Read the untruncated text: a test with many failed checks overflows the message above.
                full = f"{node.get('message') or ''}\n{node.text or ''}"
                failed_checks = sorted({int(n) for n in _FAILED_CHECK.findall(full)})
                break
        results[name] = (outcome, duration, message, failed_checks)
    return results


def _verdict(expected: str, actual: str, control: bool) -> str:
    if actual in ("error", "missing", "skipped"):
        return "error"
    if control:
        return "stable" if actual == "passed" else "flaky"
    if expected == "fail":
        return "reproduced" if actual == "failed" else "not_reproduced"
    return "stable" if actual == "passed" else "flaky"


def _start_pytest(tests_dir: Path, base_url: str, label: str) -> subprocess.Popen[str]:
    env = {**os.environ, "BASE_URL": base_url, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [
        sys.executable, "-m", "pytest", PY_FILE, "-v", "-rN", "--color=no", "--no-header",
        "-p", "no:cacheprovider", "-p", "no:asyncio", "--browser", "chromium",
        f"--junitxml=results-{label}.xml", "-o", "junit_family=xunit2",
    ]
    return subprocess.Popen(
        cmd, cwd=tests_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1,
    )


def _drain(proc: subprocess.Popen[str], on_line: Callable[[str], None]) -> str:
    assert proc.stdout is not None
    lines: list[str] = []
    for line in proc.stdout:
        lines.append(line)
        on_line(line)
    proc.wait()
    return "".join(lines)


async def run_suite(
    tests_dir: Path,
    tests: list[GeneratedTest],
    base_url: str,
    *,
    label: str,
    timeout_s: float,
    on_test: Callable[[str, str], None] | None = None,
) -> SuiteRun:
    """Run the generated Python suite; ``on_test(name, outcome)`` fires as each test finishes."""
    started = time.perf_counter()
    report = tests_dir / f"results-{label}.xml"
    report.unlink(missing_ok=True)
    control = label == "control"
    loop = asyncio.get_running_loop()

    def elapsed() -> float:
        return round(time.perf_counter() - started, 2)

    def on_line(line: str) -> None:
        if on_test is not None and (m := _PROGRESS.search(line)):
            loop.call_soon_threadsafe(on_test, m.group(1), m.group(2).lower())

    try:
        proc = _start_pytest(tests_dir, base_url, label)
    except OSError as exc:
        return SuiteRun(label, base_url, False, elapsed(), error=str(exc))
    try:
        # A thread reads the output so the event loop stays free; a timeout or cancellation kills pytest,
        # which closes the pipe and ends the thread.
        output = await asyncio.wait_for(asyncio.to_thread(_drain, proc, on_line), timeout_s)
    except TimeoutError:
        proc.kill()
        return SuiteRun(label, base_url, False, elapsed(), error=f"The suite did not finish within {int(timeout_s)}s.")
    except asyncio.CancelledError:
        proc.kill()
        raise
    output = output or ""
    run = SuiteRun(label, base_url, report.exists(), elapsed(), output_tail=output[-3000:])
    if not report.exists():
        run.error = "pytest did not produce a report. See the output for details."
        return run
    results = _parse_junit(report)
    for test in tests:
        actual, duration, message, failed_checks = results.get(test.name, ("missing", 0.0, None, []))
        expected = "pass" if control else test.expected_outcome
        run.tests.append(TestOutcome(
            scenario_id=test.scenario_id, name=test.name, expected=expected, actual=actual,
            duration_s=round(duration, 2), message=message, verdict=_verdict(expected, actual, control),
            failed_checks=failed_checks,
        ))
    run.passed = sum(1 for t in run.tests if t.actual == "passed")
    run.failed = sum(1 for t in run.tests if t.actual != "passed")
    return run


def apply_to_bugs(recorder: Recorder, target_run: SuiteRun) -> None:
    """A bug counts as reproduced when a failing check that exposed it failed again.

    One test can hold several bugs, so the test failing is not enough: only the bugs whose own
    checks are among its failed checks reproduced.
    """
    by_scenario = {t.scenario_id: t for t in target_run.tests}
    for bug in recorder.bugs:
        outcome = by_scenario.get(bug.scenario_id) if bug.scenario_id is not None else None
        if outcome is None or not bug.check_steps or outcome.verdict == "error":
            bug.reproduced = None  # no assertion encodes this bug, so the replay cannot prove it
        elif outcome.actual == "passed":
            bug.reproduced = False
        elif outcome.failed_checks:
            bug.reproduced = not set(bug.check_steps).isdisjoint(outcome.failed_checks)
        else:
            bug.reproduced = None  # an action broke before the checks were reported, so this proves nothing
