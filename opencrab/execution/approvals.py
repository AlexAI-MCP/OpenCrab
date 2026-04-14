"""
Approval Engine — three-state approval queue.

States: pending → approved | rejected

Table created on first use:
  approval_queue — pending/resolved approval requests
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS approval_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id  TEXT NOT NULL UNIQUE,
    run_id       TEXT,
    action_type  TEXT NOT NULL,
    subject_id   TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'pending',
    reviewer_id  TEXT,
    review_note  TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    resolved_at  TEXT
)
"""

_TABLE_PG = """
CREATE TABLE IF NOT EXISTS approval_queue (
    id           SERIAL PRIMARY KEY,
    approval_id  VARCHAR(64)  NOT NULL UNIQUE,
    run_id       VARCHAR(64),
    action_type  VARCHAR(128) NOT NULL,
    subject_id   VARCHAR(256),
    payload_json TEXT         NOT NULL DEFAULT '{}',
    status       VARCHAR(32)  NOT NULL DEFAULT 'pending',
    reviewer_id  VARCHAR(256),
    review_note  TEXT,
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
)
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalEngine:
    """Simple three-state approval queue: pending → approved | rejected."""

    def __init__(self, sql_store: Any) -> None:
        self._sql = sql_store
        self._ensure_table()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        """Create approval_queue table if it doesn't exist."""
        from sqlalchemy import text

        ddl = _TABLE_SQLITE if self._sql._is_sqlite else _TABLE_PG
        with self._sql._engine.begin() as conn:
            conn.execute(text(ddl))

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def request(
        self,
        action_type: str,
        subject_id: str,
        payload: dict[str, Any],
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit a new approval request.

        Returns a dict with approval_id, status='pending', and created_at.
        """
        from sqlalchemy import text

        approval_id = f"appr_{uuid.uuid4().hex[:12]}"
        payload_json = json.dumps(payload, ensure_ascii=False)

        with self._sql._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO approval_queue "
                    "(approval_id, run_id, action_type, subject_id, payload_json) "
                    "VALUES (:approval_id, :run_id, :action_type, :subject_id, :payload_json)"
                ),
                {
                    "approval_id": approval_id,
                    "run_id": run_id,
                    "action_type": action_type,
                    "subject_id": subject_id,
                    "payload_json": payload_json,
                },
            )

        return {
            "approval_id": approval_id,
            "run_id": run_id,
            "action_type": action_type,
            "subject_id": subject_id,
            "status": "pending",
            "created_at": _now_iso(),
        }

    def resolve(
        self,
        approval_id: str,
        decision: str,
        reviewer_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """
        Resolve a pending approval request.

        Parameters
        ----------
        approval_id:
            The approval to resolve.
        decision:
            Must be 'approved' or 'rejected'.
        reviewer_id:
            Optional identifier of the reviewer.
        note:
            Optional review note or reason.

        Raises
        ------
        ValueError
            If decision is not 'approved' or 'rejected', or approval not found.
        """
        from sqlalchemy import text

        if decision not in {"approved", "rejected"}:
            raise ValueError(f"Decision must be 'approved' or 'rejected', got '{decision}'.")

        if self._sql._is_sqlite:
            update_sql = (
                "UPDATE approval_queue "
                "SET status = :decision, reviewer_id = :reviewer_id, "
                "    review_note = :note, resolved_at = datetime('now') "
                "WHERE approval_id = :approval_id AND status = 'pending'"
            )
        else:
            update_sql = (
                "UPDATE approval_queue "
                "SET status = :decision, reviewer_id = :reviewer_id, "
                "    review_note = :note, resolved_at = NOW() "
                "WHERE approval_id = :approval_id AND status = 'pending'"
            )

        with self._sql._engine.begin() as conn:
            result = conn.execute(
                text(update_sql),
                {
                    "decision": decision,
                    "reviewer_id": reviewer_id,
                    "note": note,
                    "approval_id": approval_id,
                },
            )
            if result.rowcount == 0:
                raise ValueError(
                    f"Approval '{approval_id}' not found or already resolved."
                )

        return {
            "approval_id": approval_id,
            "status": decision,
            "reviewer_id": reviewer_id,
            "review_note": note,
            "resolved_at": _now_iso(),
        }

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, approval_id: str) -> dict[str, Any] | None:
        """Return the approval record, or None if not found."""
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM approval_queue WHERE approval_id = :approval_id"
                ),
                {"approval_id": approval_id},
            ).fetchone()

        if row is None:
            return None
        return dict(row._mapping)

    def list_pending(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return all pending approval requests, oldest first."""
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM approval_queue "
                    "WHERE status = 'pending' "
                    "ORDER BY id ASC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()

        return [dict(r._mapping) for r in rows]

    def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return all approval records, newest first."""
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM approval_queue ORDER BY id DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()

        return [dict(r._mapping) for r in rows]
