"""
Ontology Builder.

High-level API for adding nodes and edges to the multi-store ontology.
Validates against the MetaOntology grammar before writing to any store.
Writes to Neo4j (graph), MongoDB (document), and PostgreSQL (registry)
in a best-effort fan-out pattern — individual store failures are logged
but do not abort the operation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from opencrab.grammar.validator import validate_edge, validate_node, validate_node_properties
from opencrab.stores.mongo_store import MongoStore
from opencrab.stores.neo4j_store import Neo4jStore
from opencrab.stores.sql_store import SQLStore

logger = logging.getLogger(__name__)


class OntologyBuilder:
    """Coordinates multi-store writes for ontology nodes and edges."""

    def __init__(
        self,
        neo4j: Neo4jStore,
        mongo: MongoStore,
        sql: SQLStore,
    ) -> None:
        self._neo4j = neo4j
        self._mongo = mongo
        self._sql = sql

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def add_node(
        self,
        space: str,
        node_type: str,
        node_id: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Add or update a node in all stores.

        Parameters
        ----------
        space:
            MetaOntology space identifier (e.g. "subject", "resource").
        node_type:
            Node type label (e.g. "User", "Document").
        node_id:
            Stable unique identifier for the node.
        properties:
            Arbitrary key/value properties for the node.

        Returns
        -------
        dict with operation status and node data.

        Raises
        ------
        ValueError
            If the space/node_type combination is invalid.
        """
        props = properties or {}

        # Grammar validation (raises ValueError on failure)
        result = validate_node(space, node_type)
        result.raise_if_invalid()

        # Schema property validation (raises ValueError on failure)
        prop_result = validate_node_properties(node_type, props)
        prop_result.raise_if_invalid()

        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
        receipt_ts = datetime.now(timezone.utc).isoformat()

        output: dict[str, Any] = {
            "node_id": node_id,
            "space": space,
            "node_type": node_type,
            "properties": props,
            "receipt_id": receipt_id,
            "receipt_ts": receipt_ts,
            "stores": {},
        }

        # --- Neo4j write ---
        if self._neo4j.available:
            try:
                node_props = self._neo4j.upsert_node(
                    node_type=node_type,
                    node_id=node_id,
                    properties=props,
                    space_id=space,
                )
                output["stores"]["neo4j"] = "ok"
                output["node_data"] = node_props
            except Exception as exc:
                logger.warning("Neo4j node write failed for %s: %s", node_id, exc)
                output["stores"]["neo4j"] = f"error: {exc}"
        else:
            output["stores"]["neo4j"] = "unavailable"

        # --- MongoDB write ---
        if self._mongo.available:
            try:
                mongo_id = self._mongo.upsert_node_doc(space, node_type, node_id, props)
                output["stores"]["mongodb"] = f"ok (id={mongo_id})"
                self._mongo.log_event(
                    "node_upsert",
                    subject_id=None,
                    details={"space": space, "node_type": node_type, "node_id": node_id},
                )
            except Exception as exc:
                logger.warning("MongoDB node write failed for %s: %s", node_id, exc)
                output["stores"]["mongodb"] = f"error: {exc}"
        else:
            output["stores"]["mongodb"] = "unavailable"

        # --- PostgreSQL registry write ---
        if self._sql.available:
            try:
                self._sql.register_node(space, node_type, node_id)
                output["stores"]["postgres"] = "ok"
            except Exception as exc:
                logger.warning("SQL node registry write failed for %s: %s", node_id, exc)
                output["stores"]["postgres"] = f"error: {exc}"
        else:
            output["stores"]["postgres"] = "unavailable"

        logger.info("Node added: %s/%s (%s)", space, node_id, node_type)
        return output

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def add_edge(
        self,
        from_space: str,
        from_id: str,
        relation: str,
        to_space: str,
        to_id: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Add a directed edge between two nodes.

        Validates the (from_space, to_space, relation) triple against
        the MetaOntology grammar before writing.

        Parameters
        ----------
        from_space:
            Source node's space.
        from_id:
            Source node's ID.
        relation:
            Relation label (must be valid for the given space pair).
        to_space:
            Target node's space.
        to_id:
            Target node's ID.
        properties:
            Optional edge properties.

        Returns
        -------
        dict with operation status.

        Raises
        ------
        ValueError
            If the edge relation is invalid for the given spaces.
        """
        edge_result = validate_edge(from_space, to_space, relation)
        edge_result.raise_if_invalid()

        props = properties or {}
        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
        receipt_ts = datetime.now(timezone.utc).isoformat()

        output: dict[str, Any] = {
            "from": {"space": from_space, "id": from_id},
            "relation": relation,
            "to": {"space": to_space, "id": to_id},
            "receipt_id": receipt_id,
            "receipt_ts": receipt_ts,
            "stores": {},
        }

        # Resolve node types from Neo4j if available, else use space as type
        from_type = _space_to_default_type(from_space)
        to_type = _space_to_default_type(to_space)

        if self._neo4j.available:
            # Try to look up real node types
            try:
                result = self._neo4j.run_cypher(
                    "MATCH (n {id: $id}) RETURN labels(n)[0] AS lbl LIMIT 1",
                    {"id": from_id},
                )
                if result and result[0].get("lbl"):
                    from_type = result[0]["lbl"]

                result = self._neo4j.run_cypher(
                    "MATCH (n {id: $id}) RETURN labels(n)[0] AS lbl LIMIT 1",
                    {"id": to_id},
                )
                if result and result[0].get("lbl"):
                    to_type = result[0]["lbl"]
            except Exception:
                pass  # use defaults

        # --- Neo4j write ---
        if self._neo4j.available:
            try:
                ok = self._neo4j.upsert_edge(from_type, from_id, relation, to_type, to_id, props)
                output["stores"]["neo4j"] = "ok" if ok else "no match"
            except Exception as exc:
                logger.warning("Neo4j edge write failed: %s", exc)
                output["stores"]["neo4j"] = f"error: {exc}"
        else:
            output["stores"]["neo4j"] = "unavailable"

        # --- PostgreSQL registry ---
        if self._sql.available:
            try:
                self._sql.register_edge(from_space, from_id, relation, to_space, to_id)
                output["stores"]["postgres"] = "ok"
            except Exception as exc:
                logger.warning("SQL edge registry failed: %s", exc)
                output["stores"]["postgres"] = f"error: {exc}"
        else:
            output["stores"]["postgres"] = "unavailable"

        # --- MongoDB audit ---
        if self._mongo.available:
            self._mongo.log_event(
                "edge_upsert",
                subject_id=None,
                details={
                    "from_space": from_space,
                    "from_id": from_id,
                    "relation": relation,
                    "to_space": to_space,
                    "to_id": to_id,
                },
            )
            output["stores"]["mongodb"] = "audited"
        else:
            output["stores"]["mongodb"] = "unavailable"

        logger.info("Edge added: %s/%s -[%s]-> %s/%s", from_space, from_id, relation, to_space, to_id)
        return output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _space_to_default_type(space_id: str) -> str:
    """Return a default node type label for a space when the real type is unknown."""
    from opencrab.grammar.manifest import SPACES

    spec = SPACES.get(space_id, {})
    types = spec.get("node_types", [])
    return types[0] if types else space_id.capitalize()
