"""
Neo4j graph store adapter.

Wraps the official neo4j-python-driver and exposes typed methods for
creating nodes and edges, running Cypher queries, and traversing paths.
All methods gracefully handle connection failures.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


class Neo4jStore:
    """Thread-safe Neo4j adapter using the official driver."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: Any = None
        self._available = False
        self._connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore[import]

            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
            # Verify connectivity with a lightweight query
            with self._driver.session() as session:
                session.run("RETURN 1")
            self._available = True
            logger.info("Neo4j connected at %s", self._uri)
        except Exception as exc:
            logger.warning("Neo4j unavailable (%s): %s", self._uri, exc)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def close(self) -> None:
        if self._driver:
            try:
                self._driver.close()
            except Exception:
                pass

    @contextmanager
    def _session(self) -> Generator[Any, None, None]:
        if not self._available or self._driver is None:
            raise RuntimeError("Neo4j is not available.")
        with self._driver.session() as session:
            yield session

    # ------------------------------------------------------------------
    # Schema / constraints
    # ------------------------------------------------------------------

    def ensure_constraints(self) -> None:
        """Create uniqueness constraints for all node types if they don't exist."""
        from opencrab.grammar.manifest import all_node_types

        if not self._available:
            logger.warning("Neo4j unavailable; skipping constraint creation.")
            return

        with self._session() as session:
            for node_type in all_node_types():
                try:
                    session.run(
                        f"CREATE CONSTRAINT IF NOT EXISTS "
                        f"FOR (n:{node_type}) REQUIRE n.id IS UNIQUE"
                    )
                except Exception as exc:
                    logger.debug("Constraint for %s: %s", node_type, exc)

        logger.info("Neo4j constraints ensured.")

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
        """
        Create or update a node. Returns the node's properties.

        Parameters
        ----------
        node_type:
            Label to apply (e.g. "User", "Document").
        node_id:
            Unique identifier for the node.
        properties:
            Additional properties to merge onto the node.
        space_id:
            Optional space tag stored as a property.
        """
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        props = {**properties, "id": node_id}
        if space_id:
            props["space"] = space_id

        set_clause = ", ".join(f"n.{k} = ${k}" for k in props)
        cypher = f"""
            MERGE (n:{node_type} {{id: $id}})
            SET {set_clause}
            RETURN properties(n) AS props
        """
        with self._session() as session:
            result = session.run(cypher, **props)
            record = result.single()
            return dict(record["props"]) if record else {}

    def get_node(self, node_type: str, node_id: str) -> dict[str, Any] | None:
        """Retrieve a node by type and id."""
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        cypher = f"MATCH (n:{node_type} {{id: $id}}) RETURN properties(n) AS props"
        with self._session() as session:
            result = session.run(cypher, id=node_id)
            record = result.single()
            return dict(record["props"]) if record else None

    def delete_node(self, node_type: str, node_id: str) -> bool:
        """Delete a node and all its relationships."""
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        cypher = f"MATCH (n:{node_type} {{id: $id}}) DETACH DELETE n RETURN count(n) AS cnt"
        with self._session() as session:
            result = session.run(cypher, id=node_id)
            record = result.single()
            return bool(record and record["cnt"] > 0)

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
        """
        Create or update a directed relationship between two nodes.

        Returns True on success.
        """
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        props = properties or {}
        prop_str = ", ".join(f"r.{k} = ${k}" for k in props) if props else "r.created = timestamp()"
        cypher = f"""
            MATCH (a:{from_type} {{id: $from_id}})
            MATCH (b:{to_type} {{id: $to_id}})
            MERGE (a)-[r:{relation}]->(b)
            SET {prop_str}
            RETURN r
        """
        params = {"from_id": from_id, "to_id": to_id, **props}
        with self._session() as session:
            result = session.run(cypher, **params)
            return result.single() is not None

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def run_cypher(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute arbitrary Cypher and return a list of record dicts."""
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        with self._session() as session:
            result = session.run(cypher, **(params or {}))
            return [dict(record) for record in result]

    def find_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        depth: int = 1,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Find neighboring nodes up to *depth* hops.

        Parameters
        ----------
        direction:
            "out", "in", or "both".
        """
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        arrow = {
            "out": "-[r*1..{depth}]->",
            "in": "<-[r*1..{depth}]-",
            "both": "-[r*1..{depth}]-",
        }.get(direction, "-[r*1..{depth}]-").format(depth=depth)

        cypher = f"""
            MATCH (start {{id: $id}}){arrow}(neighbor)
            RETURN DISTINCT properties(neighbor) AS props, labels(neighbor) AS labels
            LIMIT $limit
        """
        with self._session() as session:
            result = session.run(cypher, id=node_id, limit=limit)
            return [
                {"properties": dict(record["props"]), "labels": list(record["labels"])}
                for record in result
            ]

    def find_path(
        self, from_id: str, to_id: str, max_depth: int = 4
    ) -> list[dict[str, Any]]:
        """Find shortest path between two nodes by id."""
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        cypher = """
            MATCH path = shortestPath(
                (a {id: $from_id})-[*1..{max_depth}]-(b {id: $to_id})
            )
            RETURN [node IN nodes(path) | properties(node)] AS node_props,
                   [rel IN relationships(path) | type(rel)] AS rel_types
        """.format(max_depth=max_depth)
        with self._session() as session:
            result = session.run(cypher, from_id=from_id, to_id=to_id)
            record = result.single()
            if not record:
                return []
            return [
                {"node": node, "relation": rel}
                for node, rel in zip(record["node_props"], record["rel_types"] + [""])
            ]

    def count_nodes(self, node_type: str | None = None) -> int:
        """Count nodes, optionally filtered by type."""
        if not self._available:
            raise RuntimeError("Neo4j is not available.")

        if node_type:
            cypher = f"MATCH (n:{node_type}) RETURN count(n) AS cnt"
        else:
            cypher = "MATCH (n) RETURN count(n) AS cnt"

        with self._session() as session:
            result = session.run(cypher)
            record = result.single()
            return int(record["cnt"]) if record else 0

    def ping(self) -> bool:
        """Return True if the database is reachable."""
        try:
            with self._session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False
