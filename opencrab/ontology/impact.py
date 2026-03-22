"""
Impact Analysis Engine (I1–I7).

Given a node ID and a change type, this engine analyses which impact
categories are triggered by traversing the MetaOntology graph and
applying heuristic rules based on the node's space and relationships.

Impact categories:
  I1 — Data impact
  I2 — Relation impact
  I3 — Space impact
  I4 — Permission impact
  I5 — Logic impact
  I6 — Cache/index impact
  I7 — Downstream system impact
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from opencrab.grammar.manifest import IMPACT_CATEGORIES, SPACES, space_for_node_type
from opencrab.stores.neo4j_store import Neo4jStore
from opencrab.stores.sql_store import SQLStore

logger = logging.getLogger(__name__)


@dataclass
class ImpactResult:
    """Structured result of an impact analysis."""

    node_id: str
    change_type: str
    space: str | None
    node_type: str | None
    triggered: list[dict[str, Any]] = field(default_factory=list)
    affected_nodes: list[dict[str, Any]] = field(default_factory=list)
    affected_spaces: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "change_type": self.change_type,
            "space": self.space,
            "node_type": self.node_type,
            "triggered_impacts": self.triggered,
            "affected_nodes": self.affected_nodes,
            "affected_spaces": self.affected_spaces,
            "summary": self.summary,
        }


# Map: space → set of impact category IDs always triggered
_SPACE_BASELINE_IMPACTS: dict[str, list[str]] = {
    "subject": ["I1", "I4"],          # subjects affect data and permissions
    "resource": ["I1", "I6"],         # resources affect data and caches
    "evidence": ["I1", "I2", "I5"],   # evidence affects data, relations, logic
    "concept": ["I2", "I5", "I6"],    # concepts affect relations and logic
    "claim": ["I2", "I5"],            # claims affect relations and logic
    "community": ["I2", "I6"],        # communities affect relations and caches
    "outcome": ["I1", "I5", "I7"],    # outcomes affect data, logic, and downstream
    "lever": ["I1", "I5", "I7"],      # levers affect all downstream systems
    "policy": ["I4", "I5"],           # policies affect permissions and logic
}

# Map: change_type → additional impact IDs
_CHANGE_TYPE_IMPACTS: dict[str, list[str]] = {
    "create": ["I2", "I6"],
    "update": ["I1", "I5", "I6"],
    "delete": ["I1", "I2", "I3", "I5", "I6"],
    "permission_change": ["I4", "I5"],
    "relationship_add": ["I2", "I5"],
    "relationship_remove": ["I2", "I3", "I5"],
    "bulk_import": ["I1", "I2", "I3", "I6", "I7"],
}


class ImpactEngine:
    """Analyses the blast radius of ontology changes."""

    def __init__(self, neo4j: Neo4jStore, sql: SQLStore) -> None:
        self._neo4j = neo4j
        self._sql = sql

    def analyse(
        self,
        node_id: str,
        change_type: str = "update",
        depth: int = 2,
    ) -> ImpactResult:
        """
        Compute the impact of a change to *node_id*.

        Parameters
        ----------
        node_id:
            The ID of the node being changed.
        change_type:
            Nature of the change (create, update, delete, permission_change, etc.).
        depth:
            Graph traversal depth for finding affected neighbours.

        Returns
        -------
        ImpactResult
        """
        result = ImpactResult(
            node_id=node_id,
            change_type=change_type,
            space=None,
            node_type=None,
        )

        # --- Discover node space and type ---
        if self._neo4j.available:
            try:
                rows = self._neo4j.run_cypher(
                    "MATCH (n {id: $id}) RETURN labels(n)[0] AS lbl, n.space AS space LIMIT 1",
                    {"id": node_id},
                )
                if rows:
                    result.node_type = rows[0].get("lbl")
                    result.space = rows[0].get("space") or space_for_node_type(result.node_type or "")
            except Exception as exc:
                logger.debug("Impact engine: node lookup error: %s", exc)

        # --- Triggered impact categories ---
        triggered_ids: set[str] = set()

        # Baseline from space
        space_impacts = _SPACE_BASELINE_IMPACTS.get(result.space or "", [])
        triggered_ids.update(space_impacts)

        # Additional from change type
        change_impacts = _CHANGE_TYPE_IMPACTS.get(change_type, ["I1", "I2"])
        triggered_ids.update(change_impacts)

        # Always trigger I1 (data) for any change
        triggered_ids.add("I1")

        result.triggered = [
            cat for cat in IMPACT_CATEGORIES if cat["id"] in triggered_ids
        ]

        # --- Affected neighbouring nodes ---
        if self._neo4j.available:
            try:
                neighbours = self._neo4j.find_neighbors(
                    node_id=node_id,
                    direction="both",
                    depth=depth,
                    limit=50,
                )
                result.affected_nodes = neighbours[:20]  # cap output size

                # Collect affected spaces
                affected_spaces: set[str] = set()
                if result.space:
                    affected_spaces.add(result.space)
                for n in neighbours:
                    ns = n.get("properties", {}).get("space")
                    if ns:
                        affected_spaces.add(ns)
                    # Infer from label
                    for lbl in n.get("labels", []):
                        inferred = space_for_node_type(lbl)
                        if inferred:
                            affected_spaces.add(inferred)
                result.affected_spaces = sorted(affected_spaces)

                # If cross-space effects exist, trigger I3 and I7
                if len(result.affected_spaces) > 1:
                    if not any(t["id"] == "I3" for t in result.triggered):
                        i3 = next((c for c in IMPACT_CATEGORIES if c["id"] == "I3"), None)
                        if i3:
                            result.triggered.append(i3)
                    # Downstream systems if lever or outcome space involved
                    if any(s in result.affected_spaces for s in ("lever", "outcome")):
                        if not any(t["id"] == "I7" for t in result.triggered):
                            i7 = next((c for c in IMPACT_CATEGORIES if c["id"] == "I7"), None)
                            if i7:
                                result.triggered.append(i7)
            except Exception as exc:
                logger.debug("Impact engine: neighbor traversal error: %s", exc)

        # --- Build summary ---
        cat_names = [t["name"] for t in result.triggered]
        result.summary = (
            f"Change '{change_type}' on node '{node_id}' "
            f"(space={result.space or 'unknown'}) triggers: {', '.join(cat_names)}. "
            f"Affected spaces: {', '.join(result.affected_spaces) or 'none detected'}."
        )

        # --- Persist to SQL ---
        if self._sql.available:
            try:
                self._sql.save_impact(node_id, change_type, result.to_dict())
            except Exception as exc:
                logger.debug("Impact engine: SQL persist error: %s", exc)

        return result

    def lever_simulate(
        self,
        lever_id: str,
        direction: str,
        magnitude: float,
    ) -> dict[str, Any]:
        """
        Simulate the downstream effects of moving a lever.

        Parameters
        ----------
        lever_id:
            ID of the Lever node.
        direction:
            "raises", "lowers", "stabilizes", or "optimizes".
        magnitude:
            Numeric strength of the lever action (0.0–1.0 scale recommended).

        Returns
        -------
        dict describing predicted outcome changes.
        """
        valid_directions = {"raises", "lowers", "stabilizes", "optimizes"}
        if direction not in valid_directions:
            raise ValueError(
                f"Invalid direction '{direction}'. "
                f"Valid directions: {', '.join(sorted(valid_directions))}."
            )

        outcomes: list[dict[str, Any]] = []
        concepts: list[dict[str, Any]] = []

        if self._neo4j.available:
            try:
                # Find outcomes connected to this lever
                rows = self._neo4j.run_cypher(
                    """
                    MATCH (l {id: $lid})-[r:raises|lowers|stabilizes|optimizes]->(o)
                    RETURN properties(o) AS oProps, type(r) AS rType, labels(o)[0] AS oLabel
                    LIMIT 20
                    """,
                    {"lid": lever_id},
                )
                for row in rows:
                    props = row.get("oProps") or {}
                    outcomes.append(
                        {
                            "node_id": props.get("id", "?"),
                            "node_type": row.get("oLabel", "Outcome"),
                            "relation": row.get("rType"),
                            "predicted_delta": _predict_delta(direction, row.get("rType", ""), magnitude),
                        }
                    )

                # Find concepts affected by this lever
                rows2 = self._neo4j.run_cypher(
                    """
                    MATCH (l {id: $lid})-[:affects]->(c)
                    RETURN properties(c) AS cProps, labels(c)[0] AS cLabel
                    LIMIT 10
                    """,
                    {"lid": lever_id},
                )
                for row in rows2:
                    props = row.get("cProps") or {}
                    concepts.append(
                        {
                            "node_id": props.get("id", "?"),
                            "node_type": row.get("cLabel", "Concept"),
                        }
                    )
            except Exception as exc:
                logger.debug("Lever simulation graph query error: %s", exc)

        sim_result: dict[str, Any] = {
            "lever_id": lever_id,
            "direction": direction,
            "magnitude": magnitude,
            "predicted_outcome_changes": outcomes,
            "affected_concepts": concepts,
            "impact_categories": ["I5", "I7"],
            "confidence": min(0.95, 0.5 + magnitude * 0.45),
            "note": (
                f"Lever '{lever_id}' moved in direction '{direction}' "
                f"with magnitude {magnitude:.2f}."
            ),
        }

        # Persist
        if self._sql.available:
            try:
                self._sql.save_simulation(lever_id, direction, magnitude, sim_result)
            except Exception as exc:
                logger.debug("Lever simulation SQL persist error: %s", exc)

        return sim_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _predict_delta(action_direction: str, edge_relation: str, magnitude: float) -> float:
    """
    Compute a predicted numeric delta for an outcome node.

    Positive delta = increase, negative = decrease.
    """
    direction_sign = {"raises": +1.0, "lowers": -1.0, "stabilizes": 0.0, "optimizes": +0.8}.get(
        action_direction, 0.0
    )
    edge_sign = {"raises": +1.0, "lowers": -1.0, "stabilizes": 0.0, "optimizes": +0.8}.get(
        edge_relation, +1.0
    )
    return round(direction_sign * edge_sign * magnitude, 4)
