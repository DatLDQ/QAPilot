import pytest

from app.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "qapilot.db")
    yield s
    s.close()


def _create(store: Store, run_id: str) -> dict:
    return store.create_run(run_id, target_url="http://localhost/shop/", story="As a shopper I can buy a mug",
                            focus=None, control_url=None, max_steps=10, model="claude-opus-5-5")


def test_run_lifecycle(store):
    row = _create(store, "r1")
    assert row["status"] == "queued" and row["result"] is None and row["summary"] is None
    store.mark_started("r1")
    assert store.get_run("r1")["started_at"] is not None

    events = [{"type": "run_start", "seq": 0, "t": 0, "note": "Thử nghiệm"}]
    store.finish_run("r1", status="completed", error=None, model="claude-opus-5-5", summary={"bugs": 2},
                     result={"bugs": [{"id": "BUG-1"}]}, events=events)
    run = store.get_run("r1")
    assert run["status"] == "completed" and run["finished_at"] is not None
    assert run["summary"] == {"bugs": 2} and run["result"] == {"bugs": [{"id": "BUG-1"}]}
    assert store.get_events("r1") == events

    listed = store.list_runs()
    assert [r["id"] for r in listed] == ["r1"] and "result" not in listed[0]

    store.delete_run("r1")
    assert store.get_run("r1") is None and store.get_events("r1") == []


def test_list_is_newest_first(store):
    for run_id in ("a", "b", "c"):
        _create(store, run_id)
    assert [r["id"] for r in store.list_runs()] == ["c", "b", "a"]
    assert [r["id"] for r in store.list_runs(limit=2)] == ["c", "b"]


def test_fail_interrupted(store):
    _create(store, "queued")
    _create(store, "running")
    store.mark_started("running")
    _create(store, "done")
    store.finish_run("done", status="completed", error=None, model="m", summary={}, result=None, events=[])
    assert store.fail_interrupted() == 2
    assert {r["id"]: r["status"] for r in store.list_runs()} == {"queued": "failed", "running": "failed",
                                                                  "done": "completed"}
    assert "server restarted" in store.get_run("running")["error"]
