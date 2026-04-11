"""SQLite-backed state store for mock services.

Replaces in-memory dict state with SQLite for deterministic snapshot/restore.
Each service table stores rows as JSON blobs. Snapshots are full DB copies
(serialize to bytes), making reset between episodes O(1) regardless of state size.

The in-memory dict interface (emails, tasks, etc.) is preserved via property
accessors backed by SQLite queries, so the FastAPI endpoints don't change.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Tables and their fixture source keys
_TABLES = {
    "emails":          "inbox",
    "sent_emails":     None,  # no fixture source, starts empty
    "slack_channels":  "slack_channels",
    "tasks":           "tasks",
    "calendar_events": "calendar",
    "gitea_issues":    "gitea_issues",
    "gitea_prs":       "gitea_prs",
    "gitea_comments":  None,
    "gitea_refs":      "gitea_refs",
    "gitea_files":     "gitea_files",
    "gitea_commits":   "gitea_commits",
    "action_log":      None,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    tbl   TEXT NOT NULL,
    key   TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (tbl, key)
);
"""


class SQLiteStateStore:
    """SQLite-backed state store with snapshot/restore.

    Stores each service's data as JSON rows in a single `kv` table.
    Snapshot serializes the entire DB to bytes; restore replaces it.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        self._snapshot: bytes | None = None

    # -- Fixture loading --

    def load_fixtures_from_dict(self, fixtures: dict[str, Any]) -> None:
        """Load fixtures and take a snapshot for future resets."""
        self._clear_all()
        for table, fixture_key in _TABLES.items():
            if fixture_key is None:
                continue
            data = fixtures.get(fixture_key)
            if data is None:
                continue
            if isinstance(data, dict):
                # slack_channels: {id: {name, messages}} → store each channel
                for k, v in data.items():
                    self._put(table, k, v)
            elif isinstance(data, list):
                for item in data:
                    key = item.get("id") or item.get("number") or str(uuid.uuid4())
                    self._put(table, str(key), item)
        self._conn.commit()
        self.snapshot()

    def load_fixtures(self, fixtures_dir: str) -> None:
        """Load from a directory of JSON files."""
        fixtures = {}
        if os.path.isdir(fixtures_dir):
            for fn in os.listdir(fixtures_dir):
                if fn.endswith(".json"):
                    with open(os.path.join(fixtures_dir, fn)) as f:
                        fixtures[fn.rsplit(".", 1)[0]] = json.load(f)
        self.load_fixtures_from_dict(fixtures)

    # -- Snapshot / Restore --

    def snapshot(self) -> str:
        """Serialize entire DB to SQL text."""
        self._snapshot = "\n".join(self._conn.iterdump())
        return self._snapshot

    def restore(self) -> None:
        """Restore DB from last snapshot."""
        if self._snapshot is None:
            self._clear_all()
            return
        self._conn.close()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript("DROP TABLE IF EXISTS kv;")
        self._conn.executescript(self._snapshot)
        self._conn.commit()

    def reset(self) -> None:
        """Alias for restore — reset to last-loaded fixtures."""
        self.restore()

    # -- CRUD operations --

    def get_all(self, table: str) -> list[dict]:
        """Get all rows from a table as dicts."""
        rows = self._conn.execute(
            "SELECT key, value FROM kv WHERE tbl = ? ORDER BY rowid", (table,)
        ).fetchall()
        return [json.loads(r[1]) for r in rows]

    def get_map(self, table: str) -> dict[str, dict]:
        """Get all rows as a {key: value} map (for slack_channels)."""
        rows = self._conn.execute(
            "SELECT key, value FROM kv WHERE tbl = ? ORDER BY rowid", (table,)
        ).fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}

    def get_one(self, table: str, key: str) -> dict | None:
        """Get a single row by key."""
        row = self._conn.execute(
            "SELECT value FROM kv WHERE tbl = ? AND key = ?", (table, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, table: str, key: str, value: dict) -> None:
        """Insert or update a row."""
        self._put(table, key, value)
        self._conn.commit()

    def append(self, table: str, value: dict, key: str | None = None) -> str:
        """Append a new row, auto-generating key if needed."""
        key = key or value.get("id") or str(uuid.uuid4())
        value.setdefault("id", key)
        self._put(table, str(key), value)
        self._conn.commit()
        return key

    def delete(self, table: str, key: str) -> bool:
        """Delete a row. Returns True if found."""
        cursor = self._conn.execute(
            "DELETE FROM kv WHERE tbl = ? AND key = ?", (table, key)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def update(self, table: str, key: str, updates: dict) -> dict | None:
        """Update fields on an existing row. Returns updated row or None."""
        existing = self.get_one(table, key)
        if existing is None:
            return None
        existing.update(updates)
        self._put(table, key, existing)
        self._conn.commit()
        return existing

    def count(self, table: str) -> int:
        """Count rows in a table."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM kv WHERE tbl = ?", (table,)
        ).fetchone()
        return row[0]

    def log_action(self, service: str, action: str, data: Any) -> None:
        """Append to action_log."""
        entry = {
            "id": str(uuid.uuid4()),
            "service": service,
            "action": action,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._put("action_log", entry["id"], entry)
        self._conn.commit()

    def dump(self) -> dict[str, Any]:
        """Dump all state for scoring."""
        return {
            "emails": self.get_all("emails"),
            "sent_emails": self.get_all("sent_emails"),
            "slack_channels": self.get_map("slack_channels"),
            "tasks": self.get_all("tasks"),
            "calendar_events": self.get_all("calendar_events"),
            "gitea_issues": self.get_all("gitea_issues"),
            "gitea_prs": self.get_all("gitea_prs"),
            "gitea_comments": self.get_all("gitea_comments"),
            "gitea_refs": self.get_all("gitea_refs"),
            "gitea_files": self.get_all("gitea_files"),
            "gitea_commits": self.get_all("gitea_commits"),
            "action_log": self.get_all("action_log"),
        }

    # -- Internal --

    def _put(self, table: str, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO kv (tbl, key, value) VALUES (?, ?, ?)",
            (table, str(key), json.dumps(value, default=str)),
        )

    def _clear_all(self) -> None:
        self._conn.execute("DELETE FROM kv")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
