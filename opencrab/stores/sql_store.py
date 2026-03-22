"""
SQLAlchemy relational store adapter (PostgreSQL / SQLite).

Manages structured ontology metadata: impact records, ReBAC policy
assignments, lever simulations, and configuration tables.
Falls back to SQLite for development if Postgres is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLAlchemy table declarations (metadata-only, not using ORM declarative)
# ---------------------------------------------------------------------------

_TABLES_SQL = [
    # Ontology nodes registry (lightweight, structural)
    """
    CREATE TABLE IF NOT EXISTS ontology_nodes (
        id          SERIAL PRIMARY KEY,
        space       VARCHAR(64)  NOT NULL,
        node_type   VARCHAR(64)  NOT NULL,
        node_id     VARCHAR(256) NOT NULL,
        created_at  TIMESTAMPTZ  DEFAULT NOW(),
        updated_at  TIMESTAMPTZ  DEFAULT NOW(),
        UNIQUE (space, node_id)
    )
    """,
    # Ontology edges registry
    """
    CREATE TABLE IF NOT EXISTS ontology_edges (
        id          SERIAL PRIMARY KEY,
        from_space  VARCHAR(64)  NOT NULL,
        from_id     VARCHAR(256) NOT NULL,
        relation    VARCHAR(64)  NOT NULL,
        to_space    VARCHAR(64)  NOT NULL,
        to_id       VARCHAR(256) NOT NULL,
        created_at  TIMESTAMPTZ  DEFAULT NOW(),
        UNIQUE (from_space, from_id, relation, to_space, to_id)
    )
    """,
    # Impact analysis records
    """
    CREATE TABLE IF NOT EXISTS impact_records (
        id          SERIAL PRIMARY KEY,
        node_id     VARCHAR(256) NOT NULL,
        change_type VARCHAR(64)  NOT NULL,
        impact_json TEXT         NOT NULL,
        analyzed_at TIMESTAMPTZ  DEFAULT NOW()
    )
    """,
    # Lever simulation records
    """
    CREATE TABLE IF NOT EXISTS lever_simulations (
        id          SERIAL PRIMARY KEY,
        lever_id    VARCHAR(256) NOT NULL,
        direction   VARCHAR(32)  NOT NULL,
        magnitude   FLOAT        NOT NULL,
        results     TEXT         NOT NULL,
        simulated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    # ReBAC policy table
    """
    CREATE TABLE IF NOT EXISTS rebac_policies (
        id           SERIAL PRIMARY KEY,
        subject_id   VARCHAR(256) NOT NULL,
        permission   VARCHAR(64)  NOT NULL,
        resource_id  VARCHAR(256) NOT NULL,
        granted      BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMPTZ  DEFAULT NOW(),
        UNIQUE (subject_id, permission, resource_id)
    )
    """,
]

# SQLite-compatible equivalents (no SERIAL, no TIMESTAMPTZ)
_TABLES_SQL_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS ontology_nodes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        space       TEXT NOT NULL,
        node_type   TEXT NOT NULL,
        node_id     TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now')),
        UNIQUE (space, node_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ontology_edges (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        from_space  TEXT NOT NULL,
        from_id     TEXT NOT NULL,
        relation    TEXT NOT NULL,
        to_space    TEXT NOT NULL,
        to_id       TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now')),
        UNIQUE (from_space, from_id, relation, to_space, to_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS impact_records (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id     TEXT NOT NULL,
        change_type TEXT NOT NULL,
        impact_json TEXT NOT NULL,
        analyzed_at TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lever_simulations (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        lever_id     TEXT NOT NULL,
        direction    TEXT NOT NULL,
        magnitude    REAL NOT NULL,
        results      TEXT NOT NULL,
        simulated_at TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rebac_policies (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id   TEXT NOT NULL,
        permission   TEXT NOT NULL,
        resource_id  TEXT NOT NULL,
        granted      INTEGER NOT NULL DEFAULT 1,
        created_at   TEXT DEFAULT (datetime('now')),
        UNIQUE (subject_id, permission, resource_id)
    )
    """,
]


class SQLStore:
    """SQLAlchemy adapter supporting PostgreSQL and SQLite."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._engine: Any = None
        self._available = False
        self._is_sqlite = url.startswith("sqlite")
        self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        try:
            from sqlalchemy import create_engine, text  # type: ignore[import]

            connect_args: dict[str, Any] = {}
            if self._is_sqlite:
                connect_args["check_same_thread"] = False

            self._engine = create_engine(self._url, connect_args=connect_args)
            self._text = text

            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            self._available = True
            logger.info("SQL store connected (%s)", self._url.split("@")[-1])
            self._create_tables()
        except Exception as exc:
            logger.warning("SQL store unavailable: %s", exc)
            self._available = False

    def _create_tables(self) -> None:
        """Create all tables if they do not exist."""
        from sqlalchemy import text

        tables = _TABLES_SQL_SQLITE if self._is_sqlite else _TABLES_SQL
        with self._engine.begin() as conn:
            for ddl in tables:
                conn.execute(text(ddl))
        logger.debug("SQL tables ensured.")

    @property
    def available(self) -> bool:
        return self._available

    def ping(self) -> bool:
        """Return True if the database is reachable."""
        try:
            from sqlalchemy import text

            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Node registry
    # ------------------------------------------------------------------

    def register_node(self, space: str, node_type: str, node_id: str) -> None:
        """Insert or update a node registry entry."""
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        from sqlalchemy import text

        if self._is_sqlite:
            sql = text(
                "INSERT OR REPLACE INTO ontology_nodes (space, node_type, node_id) "
                "VALUES (:space, :node_type, :node_id)"
            )
        else:
            sql = text(
                "INSERT INTO ontology_nodes (space, node_type, node_id, updated_at) "
                "VALUES (:space, :node_type, :node_id, NOW()) "
                "ON CONFLICT (space, node_id) DO UPDATE SET node_type=EXCLUDED.node_type, updated_at=NOW()"
            )

        with self._engine.begin() as conn:
            conn.execute(sql, {"space": space, "node_type": node_type, "node_id": node_id})

    def register_edge(
        self, from_space: str, from_id: str, relation: str, to_space: str, to_id: str
    ) -> None:
        """Insert or ignore an edge registry entry."""
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        from sqlalchemy import text

        if self._is_sqlite:
            sql = text(
                "INSERT OR IGNORE INTO ontology_edges "
                "(from_space, from_id, relation, to_space, to_id) "
                "VALUES (:fs, :fi, :rel, :ts, :ti)"
            )
        else:
            sql = text(
                "INSERT INTO ontology_edges (from_space, from_id, relation, to_space, to_id) "
                "VALUES (:fs, :fi, :rel, :ts, :ti) "
                "ON CONFLICT DO NOTHING"
            )

        with self._engine.begin() as conn:
            conn.execute(
                sql,
                {"fs": from_space, "fi": from_id, "rel": relation, "ts": to_space, "ti": to_id},
            )

    # ------------------------------------------------------------------
    # Impact records
    # ------------------------------------------------------------------

    def save_impact(
        self, node_id: str, change_type: str, impact: dict[str, Any]
    ) -> int:
        """Persist an impact analysis result. Returns the row id."""
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        import json

        from sqlalchemy import text

        sql = text(
            "INSERT INTO impact_records (node_id, change_type, impact_json) "
            "VALUES (:node_id, :change_type, :json) "
            "RETURNING id"
        )
        if self._is_sqlite:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO impact_records (node_id, change_type, impact_json) "
                        "VALUES (:node_id, :change_type, :json)"
                    ),
                    {"node_id": node_id, "change_type": change_type, "json": json.dumps(impact)},
                )
                result = conn.execute(text("SELECT last_insert_rowid()"))
                row = result.fetchone()
                return int(row[0]) if row else -1
        else:
            with self._engine.begin() as conn:
                result = conn.execute(
                    sql,
                    {"node_id": node_id, "change_type": change_type, "json": json.dumps(impact)},
                )
                row = result.fetchone()
                return int(row[0]) if row else -1

    def get_impacts(self, node_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent impact records for a node."""
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        import json

        from sqlalchemy import text

        sql = text(
            "SELECT id, node_id, change_type, impact_json, analyzed_at "
            "FROM impact_records WHERE node_id = :node_id "
            "ORDER BY analyzed_at DESC LIMIT :limit"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"node_id": node_id, "limit": limit}).fetchall()
        return [
            {
                "id": r[0],
                "node_id": r[1],
                "change_type": r[2],
                "impact": json.loads(r[3]),
                "analyzed_at": str(r[4]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Lever simulations
    # ------------------------------------------------------------------

    def save_simulation(
        self, lever_id: str, direction: str, magnitude: float, results: dict[str, Any]
    ) -> int:
        """Persist a lever simulation result."""
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        import json

        from sqlalchemy import text

        if self._is_sqlite:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO lever_simulations (lever_id, direction, magnitude, results) "
                        "VALUES (:lever_id, :direction, :magnitude, :results)"
                    ),
                    {
                        "lever_id": lever_id,
                        "direction": direction,
                        "magnitude": magnitude,
                        "results": json.dumps(results),
                    },
                )
                row = conn.execute(text("SELECT last_insert_rowid()")).fetchone()
                return int(row[0]) if row else -1
        else:
            sql = text(
                "INSERT INTO lever_simulations (lever_id, direction, magnitude, results) "
                "VALUES (:lever_id, :direction, :magnitude, :results) RETURNING id"
            )
            with self._engine.begin() as conn:
                row = conn.execute(
                    sql,
                    {
                        "lever_id": lever_id,
                        "direction": direction,
                        "magnitude": magnitude,
                        "results": json.dumps(results),
                    },
                ).fetchone()
                return int(row[0]) if row else -1

    # ------------------------------------------------------------------
    # ReBAC policies
    # ------------------------------------------------------------------

    def set_policy(
        self,
        subject_id: str,
        permission: str,
        resource_id: str,
        granted: bool = True,
    ) -> None:
        """Upsert a ReBAC policy row."""
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        from sqlalchemy import text

        if self._is_sqlite:
            sql = text(
                "INSERT OR REPLACE INTO rebac_policies "
                "(subject_id, permission, resource_id, granted) "
                "VALUES (:sid, :perm, :rid, :granted)"
            )
        else:
            sql = text(
                "INSERT INTO rebac_policies (subject_id, permission, resource_id, granted) "
                "VALUES (:sid, :perm, :rid, :granted) "
                "ON CONFLICT (subject_id, permission, resource_id) "
                "DO UPDATE SET granted=EXCLUDED.granted"
            )
        with self._engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "sid": subject_id,
                    "perm": permission,
                    "rid": resource_id,
                    "granted": granted,
                },
            )

    def check_policy(
        self, subject_id: str, permission: str, resource_id: str
    ) -> bool | None:
        """
        Look up a stored ReBAC policy.

        Returns True/False if a policy exists, None if no policy row found.
        """
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        from sqlalchemy import text

        sql = text(
            "SELECT granted FROM rebac_policies "
            "WHERE subject_id=:sid AND permission=:perm AND resource_id=:rid"
        )
        with self._engine.connect() as conn:
            row = conn.execute(
                sql,
                {"sid": subject_id, "perm": permission, "rid": resource_id},
            ).fetchone()
        if row is None:
            return None
        return bool(row[0])

    def list_policies(self, subject_id: str) -> list[dict[str, Any]]:
        """List all policies for a given subject."""
        if not self._available:
            raise RuntimeError("SQL store is not available.")

        from sqlalchemy import text

        sql = text(
            "SELECT subject_id, permission, resource_id, granted, created_at "
            "FROM rebac_policies WHERE subject_id=:sid"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"sid": subject_id}).fetchall()
        return [
            {
                "subject_id": r[0],
                "permission": r[1],
                "resource_id": r[2],
                "granted": bool(r[3]),
                "created_at": str(r[4]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def table_counts(self) -> dict[str, int]:
        """Return row counts for all tables."""
        if not self._available:
            return {}

        from sqlalchemy import text

        counts: dict[str, int] = {}
        tables = ["ontology_nodes", "ontology_edges", "impact_records", "lever_simulations", "rebac_policies"]
        with self._engine.connect() as conn:
            for table in tables:
                row = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()  # noqa: S608
                counts[table] = int(row[0]) if row else 0
        return counts
