import pytest
from conftest import FakeBridge, FakeSession

from app.recorder import Recorder
from app.tools import TOOL_DEFINITIONS, QAToolExecutor, validate_input

BUG = {
    "title": "Cart subtotal ignores quantities",
    "severity": "critical",
    "category": "functional",
    "steps_to_reproduce": ["Add a mug", "Set quantity to 2"],
    "expected": "$36.00",
    "actual": "$18.00",
}


def test_every_tool_streams_eagerly_and_has_a_valid_schema():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names))
    for tool in TOOL_DEFINITIONS:
        assert tool["eager_input_streaming"] is True
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert set(schema["required"]) <= set(schema["properties"])


@pytest.mark.parametrize(
    ("name", "data", "error"),
    [
        ("teleport", {}, "Unknown tool 'teleport'."),
        ("click", "e1", "Tool input must be a JSON object."),
        ("click", {"ref": "e1"}, "Missing required field 'description'."),
        ("click", {"ref": "e1", "description": "   "}, "Missing required field 'description'."),
        ("set_checked", {"ref": "e1", "checked": "yes", "description": "x"}, "'checked' must be of type boolean."),
        ("snapshot", {"wait_seconds": True}, "'wait_seconds' must be of type number."),
        ("expect", {"assertion": "looks_nice", "description": "x"}, "'assertion' must be one of"),
        ("report_bug", {**BUG, "severity": "blocker"}, "'severity' must be one of"),
        ("report_bug", {**BUG, "steps_to_reproduce": []}, "'steps_to_reproduce' needs at least 1 item(s)."),
        ("report_bug", {**BUG, "steps_to_reproduce": ["ok", ""]}, "'steps_to_reproduce' must be a list of"),
    ],
)
def test_validate_input_rejects(name, data, error):
    clean, message = validate_input(name, data)
    assert clean is None
    assert message is not None and message.startswith(error)


def test_validate_input_cleans():
    clean, error = validate_input(
        "fill", {"ref": " e3 ", "value": "  spaced  ", "description": " Type ", "bogus": 1, "note": None}
    )
    assert error is None
    # Unknown keys are dropped, strings are stripped, but a fill value is typed exactly as given.
    assert clean == {"ref": "e3", "value": "  spaced  ", "description": "Type"}
    assert validate_input("fill", {"ref": "e3", "value": "", "description": "Clear the field"})[1] is None
    assert validate_input("snapshot", {"wait_seconds": 1})[0] == {"wait_seconds": 1}


@pytest.fixture
def executor(tmp_path) -> QAToolExecutor:
    return QAToolExecutor(FakeBridge(), FakeSession(tmp_path), Recorder("http://localhost:8100/shop/"))  # type: ignore[arg-type]


async def test_invalid_input_becomes_an_error_result(executor):
    outcome = await executor.execute("click", {"ref": "e1"})
    assert outcome.is_error and "Missing required field 'description'" in outcome.content


async def test_expect_needs_a_target_or_expected_value(executor):
    missing = await executor.execute("expect", {"assertion": "text_equals", "ref": "e1", "description": "x"})
    assert missing.is_error and "needs an 'expected' value" in missing.content
    count = await executor.execute("expect", {"assertion": "count_equals", "expected": "two", "role": "row",
                                              "description": "x"})
    assert count.is_error and "whole number" in count.content
    target = await executor.execute("expect", {"assertion": "visible", "description": "x"})
    assert target.is_error and "Give a ref" in target.content


async def test_report_bug_links_failing_checks_and_dedupes(executor):
    rec = executor.recorder
    rec.begin("Cart maths", None, 0)
    rec.add_step(0, kind="expect", description="Subtotal is $36", assertion="text_contains", expected="$36.00",
                 actual="$18.00", passed=False)
    filed = await executor.execute("report_bug", BUG)
    assert not filed.is_error
    assert filed.summary == "BUG-1 · critical · Cart subtotal ignores quantities"
    assert "Linked to failing check(s) #1" in filed.content
    assert filed.ui["kind"] == "bug" and filed.ui["bug"]["check_steps"] == [1]
    assert rec.scenarios[0].steps[0].bug_ids == ["BUG-1"]

    again = await executor.execute("report_bug", {**BUG, "title": BUG["title"].upper()})
    assert "already covers this" in again.content and len(rec.bugs) == 1


async def test_finish_ends_the_session(executor):
    outcome = await executor.execute("finish", {"summary": "Checkout is broken.", "untested": "Payments"})
    assert outcome.finished and outcome.ui == {"kind": "finish", "summary": "Checkout is broken.",
                                               "untested": "Payments"}
    assert executor.recorder.summary == "Checkout is broken."
