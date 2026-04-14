"""
Workflow Engine — simple state machine for ontology action runs.

Persists workflow state to the SQLite/PostgreSQL store via SQLAlchemy.
Provides append-only action_log for provenance.

Tables created on first use:
  workflow_runs  — current state of each run
  action_log     — append-only execution history
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

VALID_STATUSES = frozenset(
    {"pending", "running", "approved", "rejected", "completed", "failed"}
)

_TABLES_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS workflow_runs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT NOT NULL UNIQUE,
        action_type  TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending',
        subject_id   TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        receipt_id   TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT NOT NULL,
        action_type  TEXT NOT NULL,
        actor        TEXT,
        input_json   TEXT,
        output_json  TEXT,
        receipt_id   TEXT,
        ts           TEXT DEFAULT (datetime('now'))
    )
    """,
]

_TABLES_PG = [
    """
    CREATE TABLE IF NOT EXISTS workflow_runs (
        id           SERIAL PRIMARY KEY,
        run_id       VARCHAR(64)  NOT NULL UNIQUE,
        action_type  VARCHAR(128) NOT NULL,
        status       VARCHAR(32)  NOT NULL DEFAULT 'pending',
        subject_id   VARCHAR(256),
        payload_json TEXT         NOT NULL DEFAULT '{}',
        receipt_id   VARCHAR(64),
        created_at   TIMESTAMPTZ  DEFAULT NOW(),
        updated_at   TIMESTAMPTZ  DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_log (
        id           SERIAL PRIMARY KEY,
        run_id       VARCHAR(64)  NOT NULL,
        action_type  VARCHAR(128) NOT NULL,
        actor        VARCHAR(256),
        input_json   TEXT,
        output_json  TEXT,
        receipt_id   VARCHAR(64),
        ts           TIMESTAMPTZ  DEFAULT NOW()
    )
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowEngine:
    """State machine for ontology action workflows."""

    def __init__(self, sql_store: Any) -> None:
        self._sql = sql_store
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        """Create workflow tables if they don't exist."""
        from sqlalchemy import text

        tables = _TABLES_SQLITE if self._sql._is_sqlite else _TABLES_PG
        with self._sql._engine.begin() as conn:
            for ddl in tables:
                conn.execute(text(ddl))

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def create_run(
        self,
        action_type: str,
        payload: dict[str, Any],
        subject_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new workflow run in 'pending' state.

        Returns a dict with run_id, status, receipt_id, and created_at.
        """
        from sqlalchemy import text

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
        payload_json = json.dumps(payload, ensure_ascii=False)

        with self._sql._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(run_id, action_type, status, subject_id, payload_json, receipt_id) "
                    "VALUES (:run_id, :action_type, 'pending', :subject_id, :payload_json, :receipt_id)"
                ),
                {
                    "run_id": run_id,
                    "action_type": action_type,
                    "subject_id": subject_id,
                    "payload_json": payload_json,
                    "receipt_id": receipt_id,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO action_log "
                    "(run_id, action_type, actor, input_json, receipt_id) "
                    "VALUES (:run_id, :action_type, :actor, :input_json, :receipt_id)"
                ),
                {
                    "run_id": run_id,
                    "action_type": action_type,
                    "actor": subject_id,
                    "input_json": payload_json,
                    "receipt_id": receipt_id,
                },
            )

        return {
            "run_id": run_id,
            "action_type": action_type,
            "status": "pending",
            "subject_id": subject_id,
            "receipt_id": receipt_id,
            "created_at": _now_iso(),
        }

    def advance(
        self,
        run_id: str,
        new_status: str,
        output: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """
        Transition a run to *new_status* and append to action_log.

        Raises ValueError if *new_status* is not a recognised status.
        """
        from sqlalchemy import text

        if new_status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{new_status}'. "
                f"Allowed: {sorted(VALID_STATUSES)}"
            )

        output_json = json.dumps(output or {}, ensure_ascii=False)
        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"

        if self._sql._is_sqlite:
            update_sql = (
                "UPDATE workflow_runs "
                "SET status = :status, updated_at = datetime('now') "
                "WHERE run_id = :run_id"
            )
        else:
            update_sql = (
                "UPDATE workflow_runs "
                "SET status = :status, updated_at = NOW() "
                "WHERE run_id = :run_id"
            )

        with self._sql._engine.begin() as conn:
            result = conn.execute(
                text(update_sql), {"status": new_status, "run_id": run_id}
            )
            if result.rowcount == 0:
                raise ValueError(f"Run '{run_id}' not found.")
            conn.execute(
                text(
                    "INSERT INTO action_log "
                    "(run_id, action_type, actor, output_json, receipt_id) "
                    "VALUES (:run_id, "
                    "  (SELECT action_type FROM workflow_runs WHERE run_id = :run_id2), "
                    "  :actor, :output_json, :receipt_id)"
                ),
                {
                    "run_id": run_id,
                    "run_id2": run_id,
                    "actor": actor,
                    "output_json": output_json,
                    "receipt_id": receipt_id,
                },
            )

        return {
            "run_id": run_id,
            "status": new_status,
            "receipt_id": receipt_id,
            "updated_at": _now_iso(),
        }

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return the current state of a run, or None if not found."""
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM workflow_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).fetchone()

        if row is None:
            return None
        return dict(row._mapping)

    def list_runs(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List runs, optionally filtered by status."""
        from sqlalchemy import text

        if status:
            sql = "SELECT * FROM workflow_runs WHERE status = :status ORDER BY id DESC LIMIT :limit"
            params: dict[str, Any] = {"status": status, "limit": limit}
        else:
            sql = "SELECT * FROM workflow_runs ORDER BY id DESC LIMIT :limit"
            params = {"limit": limit}

        with self._sql._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        return [dict(r._mapping) for r in rows]

    def get_log(self, run_id: str) -> list[dict[str, Any]]:
        """Return all action_log entries for a run in chronological order."""
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM action_log WHERE run_id = :run_id ORDER BY id ASC"),
                {"run_id": run_id},
            ).fetchall()

        return [dict(r._mapping) for r in rows]
