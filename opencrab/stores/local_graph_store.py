"""
Local graph store — SQLite-backed graph for local (no-Docker) mode.

Implements the same interface as Neo4jStore so store consumers are
agnostic of the backend. Nodes and edges are stored in SQLite tables;
BFS traversal is done in Python.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        node_type   TEXT NOT NULL,
        node_id     TEXT NOT NULL,
        space_id    TEXT,
        properties  TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (node_type, node_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        from_type   TEXT NOT NULL,
        from_id     TEXT NOT NULL,
        relation    TEXT NOT NULL,
        to_type     TEXT NOT NULL,
        to_id       TEXT NOT NULL,
        properties  TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (from_type, from_id, relation, to_type, to_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_edges_from ON graph_edges(from_id)",
    "CREATE INDEX IF NOT EXISTS idx_edges_to   ON graph_edges(to_id)",
]


class LocalGraphStore:
    """SQLite-backed graph store with the same interface as Neo4jStore."""

    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._db_path = db_path
        self._available = False
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.cursor()
            for ddl in _DDL:
                cur.execute(ddl)
            self._conn.commit()
            self._available = True
            logger.info("LocalGraphStore initialised at %s", self._db_path)
        except Exception as exc:
            logger.warning("LocalGraphStore init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self._available

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass

    def ping(self) -> bool:
        try:
            assert self._conn
            self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Schema (no-op for local mode)
    # ------------------------------------------------------------------

    def ensure_constraints(self) -> None:
        pass  # PRIMARY KEY constraints cover uniqueness

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
        space_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._available or not self._conn:
            raise RuntimeError("LocalGraphStore is not available.")
        props = {**properties, "id": node_id}
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO graph_nodes(node_type, node_id, space_id, properties)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(node_type, node_id) DO UPDATE SET
                space_id   = excluded.space_id,
                properties = excluded.properties
            """,
            (node_type, node_id, space_id, json.dumps(props)),
        )
        self._conn.commit()
        return props

    def get_node(self, node_type: str, node_id: str) -> dict[str, Any] | None:
        if not self._available or not self._conn:
            raise RuntimeError("LocalGraphStore is not available.")
        cur = self._conn.cursor()
        cur.execute(
            "SELECT properties FROM graph_nodes WHERE node_type=? AND node_id=?",
            (node_type, node_id),
        )
        row = cur.fetchone()
        return json.loads(row["properties"]) if row else None

    def delete_node(self, node_type: str, node_id: str) -> bool:
        if not self._available or not self._conn:
            raise RuntimeError("LocalGraphStore is not available.")
        cur = self._conn.cursor()
        cur.execute(
            "DELETE FROM graph_nodes WHERE node_type=? AND node_id=?",
            (node_type, node_id),
        )
        cur.execute(
            "DELETE FROM graph_edges WHERE (from_type=? AND from_id=?) OR (to_type=? AND to_id=?)",
            (node_type, node_id, node_type, node_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def upsert_edge(
        self,
        from_type: str,
        from_id: str,
        relation: str,
        to_type: str,
        to_id: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        if not self._available or not self._conn:
            raise RuntimeError("LocalGraphStore is not available.")
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO graph_edges(from_type, from_id, relation, to_type, to_id, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(from_type, from_id, relation, to_type, to_id) DO UPDATE SET
                properties = excluded.properties
            """,
            (from_type, from_id, relation, to_type, to_id, json.dumps(properties or {})),
        )
        self._conn.commit()
        return True

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def run_cypher(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Not supported in local mode — returns empty list with a warning."""
        logger.warning("run_cypher() is not supported in local mode; returning [].")
        return []

    def find_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        depth: int = 1,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """BFS neighbour traversal in Python."""
        if not self._available or not self._conn:
            raise RuntimeError("LocalGraphStore is not available.")

        visited: set[str] = {node_id}
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        results: list[dict[str, Any]] = []
        cur = self._conn.cursor()

        while queue and len(results) < limit:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            # Outgoing edges
            if direction in ("out", "both"):
                cur.execute(
                    "SELECT to_type, to_id FROM graph_edges WHERE from_id=?",
                    (current_id,),
                )
                for row in cur.fetchall():
                    nid = row["to_id"]
                    if nid not in visited:
                        visited.add(nid)
                        node = self._fetch_node_props(cur, row["to_type"], nid)
                        if node:
                            results.append({"properties": node, "labels": [row["to_type"]]})
                        queue.append((nid, current_depth + 1))

            # Incoming edges
            if direction in ("in", "both"):
                cur.execute(
                    "SELECT from_type, from_id FROM graph_edges WHERE to_id=?",
                    (current_id,),
                )
                for row in cur.fetchall():
                    nid = row["from_id"]
                    if nid not in visited:
                        visited.add(nid)
                        node = self._fetch_node_props(cur, row["from_type"], nid)
                        if node:
                            results.append({"properties": node, "labels": [row["from_type"]]})
                        queue.append((nid, current_depth + 1))

        return results[:limit]

    def find_path(
        self, from_id: str, to_id: str, max_depth: int = 4
    ) -> list[dict[str, Any]]:
        """BFS shortest path between two nodes."""
        if not self._available or not self._conn:
            raise RuntimeError("LocalGraphStore is not available.")

        cur = self._conn.cursor()
        visited: set[str] = {from_id}
        # Each queue item: (current_id, path_so_far)
        queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(from_id, [])])

        while queue:
            current_id, path = queue.popleft()
            if len(path) >= max_depth * 2:
                continue

            cur.execute(
                "SELECT to_type, to_id, relation FROM graph_edges WHERE from_id=?",
                (current_id,),
            )
            for row in cur.fetchall():
                nid = row["to_id"]
                rel = row["relation"]
                node = self._fetch_node_props(cur, row["to_type"], nid) or {"id": nid}
                new_path = path + [{"node": node, "relation": rel}]

                if nid == to_id:
                    return new_path

                if nid not in visited:
                    visited.add(nid)
                    queue.append((nid, new_path))

        return []

    def count_nodes(self, node_type: str | None = None) -> int:
        if not self._available or not self._conn:
            raise RuntimeError("LocalGraphStore is not available.")
        cur = self._conn.cursor()
        if node_type:
            cur.execute("SELECT COUNT(*) FROM graph_nodes WHERE node_type=?", (node_type,))
        else:
            cur.execute("SELECT COUNT(*) FROM graph_nodes")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_node_props(
        self, cur: sqlite3.Cursor, node_type: str, node_id: str
    ) -> dict[str, Any] | None:
        cur.execute(
            "SELECT properties FROM graph_nodes WHERE node_type=? AND node_id=?",
            (node_type, node_id),
        )
        row = cur.fetchone()
        return json.loads(row["properties"]) if row else None
