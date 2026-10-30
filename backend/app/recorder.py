"""What the agent did, in a form the test generator and the bug report can replay."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .locators import LocatorSpec, render_py, render_ts

Severity = Literal["critical", "high", "medium", "low"]
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
CATEGORIES: tuple[str, ...] = (
    "functional", "validation", "ui", "accessibility", "console", "network", "performance", "security", "content",
)


@dataclass
class Step:
    index: int
    kind: str  # goto | click | fill | select | check | press | hover | expect
    description: str
    locator: LocatorSpec | None = None
    value: Any = None
    assertion: str | None = None
    expected: str | None = None
    actual: str | None = None
    passed: bool | None = None
    bug_ids: list[str] = field(default_factory=list)
    screenshot: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["locator_ts"] = render_ts(self.locator) if self.locator else None
        data["locator_py"] = render_py(self.locator) if self.locator else None
        return data


@dataclass
class Scenario:
    id: int
    name: str
    start_url: str | None
    signal_start: int = 0
    steps: list[Step] = field(default_factory=list)

    @property
    def checks(self) -> list[Step]:
        return [s for s in self.steps if s.kind == "expect"]

    @property
    def failed_checks(self) -> list[Step]:
        return [s for s in self.checks if s.passed is False]

    @property
    def unlinked_failed_checks(self) -> list[Step]:
        """Failing checks no bug has claimed yet: the evidence a new bug report can link to."""
        return [s for s in self.failed_checks if not s.bug_ids]

    @property
    def expected_outcome(self) -> Literal["pass", "fail"]:
        """How the generated test should behave against the build the agent explored."""
        return "fail" if self.failed_checks else "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "start_url": self.start_url,
            "expected_outcome": self.expected_outcome,
            "checks": len(self.checks),
            "failed_checks": len(self.failed_checks),
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass
class Bug:
    id: str
    title: str
    severity: str
    category: str
    scenario_id: int | None
    steps_to_reproduce: list[str]
    expected: str
    actual: str
    url: str
    screenshot: str | None
    evidence: str | None = None
    signals: list[str] = field(default_factory=list)
    check_steps: list[int] = field(default_factory=list)
    # Why no assertion could capture this bug, when the agent filed it without a failing check.
    untestable_reason: str | None = None
    # Filled in by verification: did the generated test fail the same way on a fresh browser?
    reproduced: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Recorder:
    def __init__(self, target_url: str):
        self.target_url = target_url
        self.scenarios: list[Scenario] = []
        self.bugs: list[Bug] = []
        self.summary: str | None = None
        self.untested: str | None = None
        self._step_index = 0

    @property
    def current(self) -> Scenario | None:
        return self.scenarios[-1] if self.scenarios else None

    def begin(self, name: str, start_url: str | None, signal_start: int) -> Scenario:
        scenario = Scenario(
            id=len(self.scenarios) + 1, name=name.strip(), start_url=start_url, signal_start=signal_start
        )
        self.scenarios.append(scenario)
        return scenario

    def ensure_scenario(self, signal_start: int) -> Scenario:
        """Steps taken before any begin_scenario still belong to a (replayable) test."""
        return self.current or self.begin("Exploratory session", None, signal_start)

    def add_step(self, signal_start: int, **fields: Any) -> Step:
        scenario = self.ensure_scenario(signal_start)
        self._step_index += 1
        step = Step(index=self._step_index, **fields)
        scenario.steps.append(step)
        return step

    def add_bug(self, **fields: Any) -> Bug:
        scenario = self.current
        bug = Bug(id=f"BUG-{len(self.bugs) + 1}", scenario_id=scenario.id if scenario else None, **fields)
        if scenario is not None:
            # Tie the failing assertions that motivated this report to it, so the test names the bug.
            for step in scenario.unlinked_failed_checks:
                step.bug_ids.append(bug.id)
                bug.check_steps.append(step.index)
        self.bugs.append(bug)
        return bug

    def stats(self) -> dict[str, int]:
        checks = [c for s in self.scenarios for c in s.checks]
        return {
            "scenarios": len(self.scenarios),
            "actions": sum(len(s.steps) for s in self.scenarios) - len(checks),
            "checks": len(checks),
            "failed_checks": sum(1 for c in checks if c.passed is False),
            "bugs": len(self.bugs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_url": self.target_url,
            "summary": self.summary,
            "untested": self.untested,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "bugs": [b.to_dict() for b in self.bugs],
            "stats": self.stats(),
        }
