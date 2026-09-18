"""SQLite persistence for check results (stdlib sqlite3, no ORM)."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager

from .checker import Diagnostic

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    file_count       INTEGER NOT NULL,
    diagnostic_count INTEGER NOT NULL,
    summary          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnostics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id   TEXT NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    source     TEXT NOT NULL,
    line       INTEGER NOT NULL,
    link       TEXT NOT NULL,
    resolved   TEXT,
    message    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnostics_check_id ON diagnostics(check_id);
"""


class Store:
    """A small SQLite-backed repository for check results."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_check(
        self,
        check_id: str,
        created_at: str,
        file_count: int,
        summary: dict[str, int],
        diagnostics: Iterable[Diagnostic],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO checks (id, created_at, file_count, diagnostic_count, summary)"
                " VALUES (?, ?, ?, ?, ?)",
                (check_id, created_at, file_count, len(diagnostics), json.dumps(summary)),
            )
            conn.executemany(
                "INSERT INTO diagnostics"
                " (check_id, type, source, line, link, resolved, message)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (check_id, d.type, d.source, d.line, d.link, d.resolved, d.message)
                    for d in diagnostics
                ],
            )

    def get_check(self, check_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
            if row is None:
                return None
            diags = conn.execute(
                "SELECT type, source, line, link, resolved, message FROM diagnostics"
                " WHERE check_id = ? ORDER BY id",
                (check_id,),
            ).fetchall()
        return {
            "check_id": row["id"],
            "created_at": row["created_at"],
            "file_count": row["file_count"],
            "diagnostic_count": row["diagnostic_count"],
            "summary": json.loads(row["summary"]),
            "diagnostics": [dict(d) for d in diags],
        }

    def list_checks(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM checks ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "check_id": r["id"],
                "created_at": r["created_at"],
                "file_count": r["file_count"],
                "diagnostic_count": r["diagnostic_count"],
                "summary": json.loads(r["summary"]),
            }
            for r in rows
        ]
