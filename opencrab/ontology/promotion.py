"""
Ontology Promotion — extraction lifecycle: candidate → validated → promoted.

Raw extractions from text/LLM are stored as 'candidate' nodes.
They must pass validation before being 'promoted' to the main ontology.

Lifecycle:
  extracted → candidate → (review) → validated → promoted
                                   ↘ rejected

This module provides the PromotionEngine which operates on Claim nodes
with a 'status' property tracking the lifecycle stage.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromotionEngine:
    """
    Manages the lifecycle of extracted/candidate ontology nodes and claims.

    Works in conjunction with OntologyBuilder (for writes) and
    WorkflowEngine (for audit trail).
    """

    def __init__(self, builder: Any, sql_store: Any) -> None:
        """
        Parameters
        ----------
        builder:
            OntologyBuilder for node/edge writes.
        sql_store:
            SQLStore for workflow state tracking.
        """
        self._builder = builder
        self._sql = sql_store

    # ------------------------------------------------------------------
    # Candidate registration
    # ------------------------------------------------------------------

    def register_candidate(
        self,
        space: str,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
        confidence: float | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Register an extracted entity as a promotion candidate.

        Sets status='candidate' in properties and writes to OntologyBuilder.
        The node will not appear in promoted queries until promoted.

        Parameters
        ----------
        space / node_type / node_id / properties:
            Standard OntologyBuilder.add_node() arguments.
        confidence:
            Extraction confidence (0.0–1.0), stored in properties.
        source_id:
            Source document that produced this candidate.
        """
        props = {**properties}
        props.setdefault("status", "candidate")
        if confidence is not None:
            props["confidence"] = round(min(max(confidence, 0.0), 1.0), 3)
        if source_id is not None:
            props["source_id"] = source_id

        result = self._builder.add_node(
            space=space,
            node_type=node_type,
            node_id=node_id,
            properties=props,
        )
        result["lifecycle_status"] = "candidate"
        return result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_candidate(
        self,
        space: str,
        node_type: str,
        node_id: str,
        existing_properties: dict[str, Any],
        validator_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """
        Mark a candidate as 'validated' — ready for final promotion review.

        Updates status in the node's properties. Does not promote yet.
        """
        props = {**existing_properties, "status": "validated"}
        if validator_id:
            props["validated_by"] = validator_id
        if note:
            props["validation_note"] = note
        props["validated_at"] = _now_iso()

        result = self._builder.add_node(
            space=space,
            node_type=node_type,
            node_id=node_id,
            properties=props,
        )
        result["lifecycle_status"] = "validated"
        return result

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    def promote(
        self,
        space: str,
        node_type: str,
        node_id: str,
        existing_properties: dict[str, Any],
        promoted_by: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Promote a validated candidate to 'promoted' status.

        Writes the final node with status='promoted'. Optionally links
        evidence nodes via 'supports' edges if evidence_ids is provided.

        Parameters
        ----------
        evidence_ids:
            IDs of evidence nodes (space: 'evidence') supporting this promotion.
        """
        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
        receipt_ts = _now_iso()

        props = {**existing_properties, "status": "promoted"}
        if promoted_by:
            props["promoted_by"] = promoted_by
        props["promoted_at"] = receipt_ts

        result = self._builder.add_node(
            space=space,
            node_type=node_type,
            node_id=node_id,
            properties=props,
        )
        result["lifecycle_status"] = "promoted"
        result["promotion_receipt_id"] = receipt_id
        result["promotion_receipt_ts"] = receipt_ts

        # Link evidence if provided
        edge_results = []
        for ev_id in (evidence_ids or []):
            try:
                edge = self._builder.add_edge(
                    from_space="evidence",
                    from_id=ev_id,
                    relation="supports",
                    to_space=space,
                    to_id=node_id,
                )
                edge_results.append({"evidence_id": ev_id, "status": "linked"})
            except Exception as exc:
                edge_results.append({"evidence_id": ev_id, "status": f"error: {exc}"})

        result["evidence_links"] = edge_results
        return result

    def reject(
        self,
        space: str,
        node_type: str,
        node_id: str,
        existing_properties: dict[str, Any],
        rejected_by: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Mark a candidate as 'rejected' with an optional reason."""
        props = {**existing_properties, "status": "rejected"}
        if rejected_by:
            props["rejected_by"] = rejected_by
        if reason:
            props["rejection_reason"] = reason
        props["rejected_at"] = _now_iso()

        result = self._builder.add_node(
            space=space,
            node_type=node_type,
            node_id=node_id,
            properties=props,
        )
        result["lifecycle_status"] = "rejected"
        return result
