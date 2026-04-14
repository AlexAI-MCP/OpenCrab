"""
Identity Resolution — alias table, duplicate detection, merge queue.

Answers the question: "Is this node the same entity as that node?"

Approach (safe for early stage):
  - Alias table: explicit canonical_id → alias_id mappings
  - Duplicate candidates: proposed merges awaiting human review
  - No auto-merge: candidates are suggested, not applied

Tables:
  node_aliases         — canonical_id ↔ alias mappings
  duplicate_candidates — proposed merge pairs (pending/accepted/rejected)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

_TABLES_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS node_aliases (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_id  TEXT NOT NULL,
        alias_id      TEXT NOT NULL,
        alias_type    TEXT NOT NULL DEFAULT 'name',
        space         TEXT,
        created_by    TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        UNIQUE (canonical_id, alias_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duplicate_candidates (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id  TEXT NOT NULL UNIQUE,
        node_a_id     TEXT NOT NULL,
        node_b_id     TEXT NOT NULL,
        space         TEXT,
        similarity    REAL,
        method        TEXT NOT NULL DEFAULT 'name_fuzzy',
        status        TEXT NOT NULL DEFAULT 'pending',
        decided_by    TEXT,
        decision_note TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        resolved_at   TEXT
    )
    """,
]

_TABLES_PG = [
    """
    CREATE TABLE IF NOT EXISTS node_aliases (
        id            SERIAL PRIMARY KEY,
        canonical_id  VARCHAR(256) NOT NULL,
        alias_id      VARCHAR(256) NOT NULL,
        alias_type    VARCHAR(64)  NOT NULL DEFAULT 'name',
        space         VARCHAR(64),
        created_by    VARCHAR(256),
        created_at    TIMESTAMPTZ  DEFAULT NOW(),
        UNIQUE (canonical_id, alias_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duplicate_candidates (
        id            SERIAL PRIMARY KEY,
        candidate_id  VARCHAR(64)  NOT NULL UNIQUE,
        node_a_id     VARCHAR(256) NOT NULL,
        node_b_id     VARCHAR(256) NOT NULL,
        space         VARCHAR(64),
        similarity    FLOAT,
        method        VARCHAR(64)  NOT NULL DEFAULT 'name_fuzzy',
        status        VARCHAR(32)  NOT NULL DEFAULT 'pending',
        decided_by    VARCHAR(256),
        decision_note TEXT,
        created_at    TIMESTAMPTZ  DEFAULT NOW(),
        resolved_at   TIMESTAMPTZ
    )
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fuzzy_similarity(a: str, b: str) -> float:
    """Simple token-overlap similarity (0.0–1.0). No external deps."""
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return round(overlap / union, 3)


class IdentityEngine:
    """Alias table and duplicate candidate management."""

    def __init__(self, sql_store: Any) -> None:
        self._sql = sql_store
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        from sqlalchemy import text
        tables = _TABLES_SQLITE if self._sql._is_sqlite else _TABLES_PG
        with self._sql._engine.begin() as conn:
            for ddl in tables:
                conn.execute(text(ddl))

    # ------------------------------------------------------------------
    # Aliases
    # ------------------------------------------------------------------

    def add_alias(
        self,
        canonical_id: str,
        alias_id: str,
        alias_type: str = "name",
        space: str | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """
        Register *alias_id* as an alias for *canonical_id*.

        alias_type hints at why they are linked:
          'name'      — same name, different ID
          'merge'     — result of a confirmed merge
          'external'  — same entity from external source
        """
        from sqlalchemy import text

        with self._sql._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO node_aliases "
                    "(canonical_id, alias_id, alias_type, space, created_by) "
                    "VALUES (:canonical_id, :alias_id, :alias_type, :space, :created_by)"
                    if self._sql._is_sqlite else
                    "INSERT INTO node_aliases "
                    "(canonical_id, alias_id, alias_type, space, created_by) "
                    "VALUES (:canonical_id, :alias_id, :alias_type, :space, :created_by) "
                    "ON CONFLICT (canonical_id, alias_id) DO NOTHING"
                ),
                {
                    "canonical_id": canonical_id,
                    "alias_id": alias_id,
                    "alias_type": alias_type,
                    "space": space,
                    "created_by": created_by,
                },
            )

        return {
            "canonical_id": canonical_id,
            "alias_id": alias_id,
            "alias_type": alias_type,
            "space": space,
        }

    def get_aliases(self, canonical_id: str) -> list[dict[str, Any]]:
        """Return all alias records for *canonical_id*."""
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM node_aliases WHERE canonical_id = :cid ORDER BY id ASC"
                ),
                {"cid": canonical_id},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def resolve_canonical(self, node_id: str) -> str:
        """
        Return the canonical_id for *node_id*.

        If *node_id* is itself an alias, returns the canonical. Otherwise returns *node_id*.
        """
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT canonical_id FROM node_aliases WHERE alias_id = :nid LIMIT 1"
                ),
                {"nid": node_id},
            ).fetchone()
        return row[0] if row else node_id

    # ------------------------------------------------------------------
    # Duplicate candidates
    # ------------------------------------------------------------------

    def propose_duplicate(
        self,
        node_a_id: str,
        node_b_id: str,
        space: str | None = None,
        similarity: float | None = None,
        method: str = "name_fuzzy",
    ) -> dict[str, Any]:
        """
        Propose that *node_a_id* and *node_b_id* may be the same entity.

        Creates a pending duplicate candidate for human review.
        Returns early (without duplicate insert) if an identical pair already exists.
        """
        from sqlalchemy import text

        # Normalise pair order for dedup
        a, b = sorted([node_a_id, node_b_id])
        candidate_id = f"dup_{uuid.uuid4().hex[:12]}"

        with self._sql._engine.begin() as conn:
            # Check existing
            existing = conn.execute(
                text(
                    "SELECT candidate_id, status FROM duplicate_candidates "
                    "WHERE node_a_id = :a AND node_b_id = :b LIMIT 1"
                ),
                {"a": a, "b": b},
            ).fetchone()
            if existing:
                return {
                    "candidate_id": existing[0],
                    "status": existing[1],
                    "already_exists": True,
                }

            conn.execute(
                text(
                    "INSERT INTO duplicate_candidates "
                    "(candidate_id, node_a_id, node_b_id, space, similarity, method) "
                    "VALUES (:cid, :a, :b, :space, :sim, :method)"
                ),
                {
                    "cid": candidate_id,
                    "a": a,
                    "b": b,
                    "space": space,
                    "sim": similarity,
                    "method": method,
                },
            )

        return {
            "candidate_id": candidate_id,
            "node_a_id": a,
            "node_b_id": b,
            "space": space,
            "similarity": similarity,
            "method": method,
            "status": "pending",
            "created_at": _now_iso(),
        }

    def resolve_duplicate(
        self,
        candidate_id: str,
        decision: str,
        decided_by: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """
        Accept or reject a duplicate candidate.

        decision: 'accepted' | 'rejected'
        If accepted, automatically registers an alias (node_b → node_a canonical).
        """
        from sqlalchemy import text

        if decision not in {"accepted", "rejected"}:
            raise ValueError(f"decision must be 'accepted' or 'rejected', got '{decision}'.")

        if self._sql._is_sqlite:
            update_sql = (
                "UPDATE duplicate_candidates "
                "SET status = :decision, decided_by = :by, "
                "    decision_note = :note, resolved_at = datetime('now') "
                "WHERE candidate_id = :cid AND status = 'pending'"
            )
        else:
            update_sql = (
                "UPDATE duplicate_candidates "
                "SET status = :decision, decided_by = :by, "
                "    decision_note = :note, resolved_at = NOW() "
                "WHERE candidate_id = :cid AND status = 'pending'"
            )

        with self._sql._engine.begin() as conn:
            result = conn.execute(
                text(update_sql),
                {"decision": decision, "by": decided_by, "note": note, "cid": candidate_id},
            )
            if result.rowcount == 0:
                raise ValueError(f"Candidate '{candidate_id}' not found or already resolved.")

            if decision == "accepted":
                row = conn.execute(
                    text(
                        "SELECT node_a_id, node_b_id, space FROM duplicate_candidates "
                        "WHERE candidate_id = :cid"
                    ),
                    {"cid": candidate_id},
                ).fetchone()
                if row:
                    # node_a is canonical, node_b becomes alias
                    conn.execute(
                        text(
                            "INSERT OR IGNORE INTO node_aliases "
                            "(canonical_id, alias_id, alias_type, space, created_by) "
                            "VALUES (:cid, :aid, 'merge', :space, :by)"
                            if self._sql._is_sqlite else
                            "INSERT INTO node_aliases "
                            "(canonical_id, alias_id, alias_type, space, created_by) "
                            "VALUES (:cid, :aid, 'merge', :space, :by) "
                            "ON CONFLICT (canonical_id, alias_id) DO NOTHING"
                        ),
                        {
                            "cid": row[0],
                            "aid": row[1],
                            "space": row[2],
                            "by": decided_by,
                        },
                    )

        return {
            "candidate_id": candidate_id,
            "status": decision,
            "decided_by": decided_by,
            "resolved_at": _now_iso(),
        }

    def find_duplicates_by_name(
        self,
        node_id: str,
        name: str,
        space: str | None = None,
        threshold: float = 0.5,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find existing nodes whose names are similar to *name*.

        Uses token-overlap fuzzy match against all nodes in the space.
        Returns candidates above *threshold* sorted by similarity desc.

        Note: For production scale, replace with embedding similarity via vector store.
        """
        from sqlalchemy import text

        sql = (
            "SELECT node_id, node_type FROM ontology_nodes WHERE space = :space AND node_id != :nid"
            if space
            else "SELECT node_id, node_type FROM ontology_nodes WHERE node_id != :nid"
        )
        params: dict[str, Any] = {"nid": node_id}
        if space:
            params["space"] = space

        with self._sql._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        candidates = []
        for row in rows:
            other_id = row[0]
            sim = _fuzzy_similarity(name, other_id)
            if sim >= threshold:
                candidates.append({
                    "node_id": other_id,
                    "node_type": row[1],
                    "similarity": sim,
                    "method": "name_fuzzy",
                })

        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        return candidates[:limit]

    def list_pending_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return all pending duplicate candidates."""
        from sqlalchemy import text

        with self._sql._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM duplicate_candidates "
                    "WHERE status = 'pending' ORDER BY similarity DESC, id ASC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [dict(r._mapping) for r in rows]
