"""SQLite persistence for runs: request, status, final result and the replayable event log."""

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    target_url TEXT NOT NULL,
    story TEXT NOT NULL,
    focus TEXT,
    control_url TEXT,
    max_steps INTEGER NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    summary_json TEXT,
    result_json TEXT,
    events_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
"""

ACTIVE = ("queued", "running")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @staticmethod
    def _row(row: sqlite3.Row, *, full: bool) -> dict[str, Any]:
        out = {k: row[k] for k in ("id", "target_url", "story", "focus", "control_url", "max_steps", "model",
                                   "status", "error", "created_at", "started_at", "finished_at")}
        out["summary"] = _load(row["summary_json"])
        if full:
            out["result"] = _load(row["result_json"])
        return out

    def create_run(self, run_id: str, *, target_url: str, story: str, focus: str | None, control_url: str | None,
                   max_steps: int, model: str) -> dict[str, Any]:
        self._exec(
            "INSERT INTO runs (id, target_url, story, focus, control_url, max_steps, model, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
            (run_id, target_url, story, focus, control_url, max_steps, model, now()),
        )
        return self.get_run(run_id)  # type: ignore[return-value]

    def mark_started(self, run_id: str) -> None:
        self._exec("UPDATE runs SET status = 'running', started_at = ? WHERE id = ?", (now(), run_id))

    def finish_run(self, run_id: str, *, status: str, error: str | None, model: str, summary: dict[str, Any],
                   result: dict[str, Any] | None, events: list[dict[str, Any]]) -> None:
        self._exec(
            "UPDATE runs SET status = ?, error = ?, model = ?, finished_at = ?, summary_json = ?, result_json = ?,"
            " events_json = ? WHERE id = ?",
            (status, error, model, now(), json.dumps(summary),
             json.dumps(result, ensure_ascii=False) if result else None, json.dumps(events, ensure_ascii=False),
             run_id),
        )

    def fail_interrupted(self) -> int:
        """Runs that were active when the server stopped can never finish."""
        cur = self._exec(
            "UPDATE runs SET status = 'failed', error = 'Interrupted: the server restarted during this run.',"
            f" finished_at = ? WHERE status IN {ACTIVE}",
            (now(),),
        )
        return cur.rowcount

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM runs WHERE id = ?", (run_id,))
        return self._row(rows[0], full=True) if rows else None

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
        return [self._row(r, full=False) for r in rows]

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._query("SELECT events_json FROM runs WHERE id = ?", (run_id,))
        return (_load(rows[0]["events_json"]) or []) if rows else []

    def delete_run(self, run_id: str) -> None:
        self._exec("DELETE FROM runs WHERE id = ?", (run_id,))
