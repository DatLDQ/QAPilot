"""The human-readable outcome of a run: a Markdown report and a machine-readable bug list."""

import json
from pathlib import Path
from typing import Any

from .recorder import Bug, Recorder
from .verify import VERDICT_LABELS, SuiteRun

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _reproduced_label(bug: Bug) -> str:
    if bug.reproduced is True:
        return "reproduced by its regression test"
    if bug.reproduced is False:
        return "did not reproduce on replay"
    return "not covered by an automated check"


def issue_markdown(bug: Bug, test_name: str | None = None) -> str:
    """One bug as a ready-to-paste issue body."""
    lines = [
        f"**Severity:** {bug.severity} · **Category:** {bug.category}",
        f"**URL:** {bug.url}",
        "",
        "### Steps to reproduce",
        *[f"{i}. {step}" for i, step in enumerate(bug.steps_to_reproduce, 1)],
        "",
        "### Expected",
        bug.expected,
        "",
        "### Actual",
        bug.actual,
    ]
    if bug.evidence:
        lines += ["", "### Evidence", bug.evidence]
    if bug.signals:
        lines += ["", "```", *bug.signals, "```"]
    if test_name:
        lines += ["", f"Regression test: `{test_name}` ({_reproduced_label(bug)})."]
    elif bug.untestable_reason:
        lines += ["", f"No regression test: {bug.untestable_reason}"]
    return "\n".join(lines)


def _verification_section(target: SuiteRun | None, control: SuiteRun | None) -> list[str]:
    if target is None:
        return ["_Verification was skipped._"]
    lines: list[str] = []
    for run in (target, control):
        if run is None:
            continue
        title = "Same build" if run.label == "target" else "Known-good build"
        lines.append(f"- **{title}** (`{run.base_url}`): {run.passed} passed, {run.failed} failed in {run.duration_s}s")
        if run.error:
            lines += [f"  > {line}" for line in run.error.splitlines()]
    lines += ["", "| Test | Expected | Result | Verdict |", "| --- | --- | --- | --- |"]
    control_by_id = {t.scenario_id: t for t in control.tests} if control else {}
    for t in target.tests:
        verdict = VERDICT_LABELS[t.verdict]
        if t.scenario_id in control_by_id:
            verdict += f" · known-good build: {control_by_id[t.scenario_id].actual}"
        lines.append(f"| `{t.name}` | {t.expected} | {t.actual} | {verdict} |")
    return lines


def render_markdown(
    meta: dict[str, Any],
    recorder: Recorder,
    tests: dict[int, str],
    target: SuiteRun | None,
    control: SuiteRun | None,
) -> str:
    stats = recorder.stats()
    usage = meta.get("usage") or {}
    cost = usage.get("cost_usd")
    lines = [
        f"# QA report: {recorder.target_url}",
        "",
        f"Run `{meta['id']}` · {meta.get('created_at', '')} · model `{meta.get('model', '')}` · "
        f"{meta.get('steps', 0)} agent steps" + (f" · ${cost:.2f}" if cost else ""),
        "",
        "## User story",
        "",
        meta.get("story", "").strip(),
        "",
        "## Summary",
        "",
        recorder.summary or "_The agent did not write a summary._",
        "",
        f"{stats['scenarios']} scenarios · {stats['actions']} actions · {stats['checks']} checks "
        f"({stats['failed_checks']} failed) · **{stats['bugs']} bugs**",
        "",
        "## Verification",
        "",
        *_verification_section(target, control),
        "",
        f"## Bugs ({len(recorder.bugs)})",
    ]
    bugs = sorted(recorder.bugs, key=lambda b: (SEVERITY_ORDER.get(b.severity, 9), b.id))
    if not bugs:
        lines += ["", "No bugs were reported."]
    for bug in bugs:
        lines += ["", f"### {bug.id} · {bug.severity.upper()} · {bug.title}", ""]
        lines.append(issue_markdown(bug, tests.get(bug.scenario_id or -1)))
        if bug.screenshot:
            lines += ["", f"![{bug.id} screenshot]({bug.screenshot})"]
    lines += ["", "## Scenarios", "", "| # | Scenario | Steps | Checks | Failed |", "| --- | --- | --- | --- | --- |"]
    for s in recorder.scenarios:
        lines.append(f"| {s.id} | {s.name} | {len(s.steps)} | {len(s.checks)} | {len(s.failed_checks)} |")
    if recorder.untested:
        lines += ["", "## Not tested", "", recorder.untested]
    lines += [
        "",
        "## Artifacts",
        "",
        "- `tests/test_qapilot.py` and `tests/qapilot.spec.ts`: the regression suite",
        "- `session.webm`: video of the whole session",
        "- `trace.zip`: Playwright trace (`npx playwright show-trace trace.zip`)",
        "- `bugs.json`: machine-readable bug list",
    ]
    return "\n".join(lines) + "\n"


def write_report(
    run_dir: Path,
    meta: dict[str, Any],
    recorder: Recorder,
    tests: dict[int, str],
    target: SuiteRun | None,
    control: SuiteRun | None,
) -> None:
    (run_dir / "report.md").write_text(render_markdown(meta, recorder, tests, target, control), encoding="utf-8")
    bugs = [{**b.to_dict(), "test": tests.get(b.scenario_id or -1)} for b in recorder.bugs]
    (run_dir / "bugs.json").write_text(json.dumps(bugs, indent=2, ensure_ascii=False), encoding="utf-8")
