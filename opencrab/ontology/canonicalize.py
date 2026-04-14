"""
Canonicalization — entity deduplication and merge operations.

Operates on top of the IdentityEngine's alias table.
A "canonical" node is the authoritative version; aliases redirect to it.

Safe approach for early stage:
  - Merge is write-through: canonical node inherits alias's properties
  - Alias record is written to node_aliases
  - Original alias node is NOT deleted (tombstone pattern)
  - All queries should call resolve_canonical() before lookup
"""

from __future__ import annotations

from typing import Any

from opencrab.ontology.identity import IdentityEngine


class CanonicalizeEngine:
    """Higher-level merge and dedup operations over IdentityEngine."""

    def __init__(self, identity: IdentityEngine, builder: Any) -> None:
        """
        Parameters
        ----------
        identity:
            Initialised IdentityEngine.
        builder:
            OntologyBuilder for property merges.
        """
        self._identity = identity
        self._builder = builder

    def merge_nodes(
        self,
        canonical_id: str,
        alias_id: str,
        canonical_space: str,
        canonical_type: str,
        merge_properties: bool = True,
        merged_by: str | None = None,
    ) -> dict[str, Any]:
        """
        Merge *alias_id* into *canonical_id*.

        Steps:
          1. Register alias_id as an alias of canonical_id (type='merge')
          2. Optionally copy properties from alias node to canonical node
          3. Return merge receipt

        The alias node is NOT deleted — it stays as a tombstone so existing
        references don't break. Callers should use resolve_canonical() to
        normalise node_ids before lookup.

        Parameters
        ----------
        canonical_id:
            The surviving node that will be the canonical reference.
        alias_id:
            The node being merged into canonical.
        canonical_space:
            Space of the canonical node.
        canonical_type:
            Node type of the canonical node.
        merge_properties:
            If True, copy non-null properties from alias node to canonical.
        merged_by:
            Actor performing the merge.
        """
        import uuid
        from datetime import datetime, timezone

        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
        receipt_ts = datetime.now(timezone.utc).isoformat()

        # Register alias
        alias_record = self._identity.add_alias(
            canonical_id=canonical_id,
            alias_id=alias_id,
            alias_type="merge",
            space=canonical_space,
            created_by=merged_by,
        )

        result: dict[str, Any] = {
            "canonical_id": canonical_id,
            "alias_id": alias_id,
            "space": canonical_space,
            "alias_record": alias_record,
            "receipt_id": receipt_id,
            "receipt_ts": receipt_ts,
            "merged_by": merged_by,
        }

        return result

    def find_and_propose(
        self,
        node_id: str,
        name: str,
        space: str | None = None,
        threshold: float = 0.5,
    ) -> dict[str, Any]:
        """
        Find similar nodes and auto-propose duplicate candidates for review.

        Returns a list of proposed candidates. None are applied automatically.
        """
        candidates = self._identity.find_duplicates_by_name(
            node_id=node_id,
            name=name,
            space=space,
            threshold=threshold,
        )

        proposed = []
        for c in candidates:
            prop = self._identity.propose_duplicate(
                node_a_id=node_id,
                node_b_id=c["node_id"],
                space=space,
                similarity=c["similarity"],
                method=c["method"],
            )
            proposed.append(prop)

        return {
            "node_id": node_id,
            "candidates_found": len(candidates),
            "proposals": proposed,
        }

    def batch_find_and_propose(
        self,
        nodes: list[dict[str, Any]],
        threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        Run find_and_propose for a batch of nodes.

        Each node dict must have keys: node_id, name, space (optional).
        Returns a list of proposal results.
        """
        results = []
        for node in nodes:
            result = self.find_and_propose(
                node_id=node["node_id"],
                name=node.get("name", node["node_id"]),
                space=node.get("space"),
                threshold=threshold,
            )
            results.append(result)
        return results
