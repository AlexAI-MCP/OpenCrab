"""
ReBAC (Relationship-Based Access Control) Engine.

Determines whether a subject has a given permission over a resource
by traversing the Neo4j graph along MetaOntology subject→resource edges
and consulting stored policy rows in PostgreSQL.

Decision logic (in order of priority):
  1. Explicit DENY policy in SQL → deny.
  2. Explicit GRANT policy in SQL → grant.
  3. Direct graph edge from subject to resource matching the permission → grant.
  4. Transitive membership path (subject ∈ team/org that has permission) → grant.
  5. Default → deny.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from opencrab.grammar.manifest import REBAC_PERMISSIONS
from opencrab.grammar.validator import validate_rebac_permission
from opencrab.stores.neo4j_store import Neo4jStore
from opencrab.stores.sql_store import SQLStore

logger = logging.getLogger(__name__)

# Relations in the subject→resource space that map to permissions
_PERMISSION_RELATIONS: dict[str, list[str]] = {
    "view": ["can_view", "can_edit", "can_approve", "owns", "manages"],
    "edit": ["can_edit", "can_approve", "owns", "manages"],
    "execute": ["can_execute", "owns", "manages"],
    "simulate": ["can_execute", "can_edit", "owns", "manages"],
    "approve": ["can_approve", "owns"],
    "admin": ["owns"],
}


@dataclass
class AccessDecision:
    """Result of a ReBAC access check."""

    granted: bool
    reason: str
    subject_id: str
    permission: str
    resource_id: str
    path: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "granted": self.granted,
            "reason": self.reason,
            "subject_id": self.subject_id,
            "permission": self.permission,
            "resource_id": self.resource_id,
            "path": self.path,
        }


class ReBACEngine:
    """Relationship-based access control engine."""

    def __init__(self, neo4j: Neo4jStore, sql: SQLStore) -> None:
        self._neo4j = neo4j
        self._sql = sql

    def check(
        self,
        subject_id: str,
        permission: str,
        resource_id: str,
    ) -> AccessDecision:
        """
        Determine whether *subject_id* has *permission* over *resource_id*.

        Parameters
        ----------
        subject_id:
            ID of the subject (User, Team, Org, or Agent node).
        permission:
            One of the REBAC_PERMISSIONS (view, edit, execute, simulate, approve, admin).
        resource_id:
            ID of the resource being accessed.

        Returns
        -------
        AccessDecision
        """
        # Validate permission label
        perm_result = validate_rebac_permission(permission)
        if not perm_result.valid:
            return AccessDecision(
                granted=False,
                reason=perm_result.error or "Invalid permission",
                subject_id=subject_id,
                permission=permission,
                resource_id=resource_id,
            )

        # 1. Check explicit SQL policy (DENY wins)
        if self._sql.available:
            stored = self._sql.check_policy(subject_id, permission, resource_id)
            if stored is False:
                return AccessDecision(
                    granted=False,
                    reason="Explicit DENY policy in rebac_policies table.",
                    subject_id=subject_id,
                    permission=permission,
                    resource_id=resource_id,
                )
            if stored is True:
                return AccessDecision(
                    granted=True,
                    reason="Explicit GRANT policy in rebac_policies table.",
                    subject_id=subject_id,
                    permission=permission,
                    resource_id=resource_id,
                )

        # 2. Graph traversal check
        if self._neo4j.available:
            decision = self._graph_check(subject_id, permission, resource_id)
            if decision is not None:
                return decision

        # 3. Default deny
        return AccessDecision(
            granted=False,
            reason=(
                "No matching policy or graph relationship found. "
                "Default deny applied."
            ),
            subject_id=subject_id,
            permission=permission,
            resource_id=resource_id,
        )

    def _graph_check(
        self, subject_id: str, permission: str, resource_id: str
    ) -> AccessDecision | None:
        """
        Traverse the graph to find a permission-granting path.

        Returns an AccessDecision if a path is found, else None.
        """
        valid_relations = _PERMISSION_RELATIONS.get(permission, [])
        if not valid_relations:
            return None

        rel_filter = "|".join(valid_relations)

        # Direct check
        cypher_direct = f"""
            MATCH (s {{id: $sid}})-[r:{rel_filter}]->(res {{id: $rid}})
            RETURN type(r) AS rel_type
            LIMIT 1
        """
        try:
            rows = self._neo4j.run_cypher(
                cypher_direct, {"sid": subject_id, "rid": resource_id}
            )
            if rows:
                return AccessDecision(
                    granted=True,
                    reason=f"Direct graph relationship [{rows[0]['rel_type']}] found.",
                    subject_id=subject_id,
                    permission=permission,
                    resource_id=resource_id,
                    path=[subject_id, rows[0]["rel_type"], resource_id],
                )
        except Exception as exc:
            logger.debug("ReBAC direct graph check error: %s", exc)

        # Transitive check: subject → (member_of|manages) → group → permission → resource
        cypher_transitive = f"""
            MATCH (s {{id: $sid}})-[:member_of|manages]->(group)-[r:{rel_filter}]->(res {{id: $rid}})
            RETURN type(r) AS rel_type, properties(group).id AS group_id
            LIMIT 1
        """
        try:
            rows = self._neo4j.run_cypher(
                cypher_transitive, {"sid": subject_id, "rid": resource_id}
            )
            if rows:
                group_id = rows[0].get("group_id", "group")
                return AccessDecision(
                    granted=True,
                    reason=(
                        f"Transitive access via group '{group_id}' "
                        f"with relation [{rows[0]['rel_type']}]."
                    ),
                    subject_id=subject_id,
                    permission=permission,
                    resource_id=resource_id,
                    path=[subject_id, "member_of", str(group_id), rows[0]["rel_type"], resource_id],
                )
        except Exception as exc:
            logger.debug("ReBAC transitive graph check error: %s", exc)

        return None

    def grant(
        self,
        subject_id: str,
        permission: str,
        resource_id: str,
    ) -> None:
        """Explicitly grant a permission in the SQL policy table."""
        validate_rebac_permission(permission).raise_if_invalid()
        if not self._sql.available:
            raise RuntimeError("SQL store not available for policy storage.")
        self._sql.set_policy(subject_id, permission, resource_id, granted=True)
        logger.info("GRANT %s -> %s -> %s", subject_id, permission, resource_id)

    def deny(
        self,
        subject_id: str,
        permission: str,
        resource_id: str,
    ) -> None:
        """Explicitly deny a permission in the SQL policy table."""
        validate_rebac_permission(permission).raise_if_invalid()
        if not self._sql.available:
            raise RuntimeError("SQL store not available for policy storage.")
        self._sql.set_policy(subject_id, permission, resource_id, granted=False)
        logger.info("DENY %s -> %s -> %s", subject_id, permission, resource_id)

    def list_subject_policies(self, subject_id: str) -> list[dict[str, Any]]:
        """Return all stored policies for a subject."""
        if not self._sql.available:
            return []
        return self._sql.list_policies(subject_id)
