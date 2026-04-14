"""
MCP Tool Definitions for OpenCrab.

Each tool is a plain function that accepts keyword arguments and returns
a JSON-serialisable dict. The TOOLS registry maps tool names to their
schema (for tools/list) and their implementation function.

Tools:
  1. ontology_manifest          — full grammar as JSON
  2. ontology_add_node          — add/update a node
  3. ontology_add_edge          — add/update an edge (grammar-validated)
  4. ontology_query             — hybrid vector + graph search
  5. ontology_impact            — impact analysis (I1–I7)
  6. ontology_rebac_check       — ReBAC access check
  7. ontology_lever_simulate    — predict outcome changes from lever movement
  8. ontology_ingest            — ingest text into vector store
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Store / engine singletons (lazily initialised)
# ---------------------------------------------------------------------------
# These are populated by _get_context() which is called on first tool use.
# This design avoids importing heavy dependencies at module load time.

_context: dict[str, Any] = {}


def _get_context() -> dict[str, Any]:
    """Lazily initialise all stores and engines using the factory (respects STORAGE_MODE)."""
    global _context
    if _context:
        return _context

    from opencrab.config import get_settings
    from opencrab.ontology.builder import OntologyBuilder
    from opencrab.ontology.impact import ImpactEngine
    from opencrab.ontology.query import HybridQuery
    from opencrab.ontology.rebac import ReBACEngine
    from opencrab.stores.factory import make_doc_store, make_graph_store, make_sql_store, make_vector_store

    cfg = get_settings()

    graph = make_graph_store(cfg)
    vector = make_vector_store(cfg)
    docs = make_doc_store(cfg)
    sql = make_sql_store(cfg)

    builder = OntologyBuilder(graph, docs, sql)
    rebac = ReBACEngine(graph, sql)
    impact = ImpactEngine(graph, sql)
    hybrid = HybridQuery(vector, graph)

    _context = {
        "neo4j": graph,
        "chroma": vector,
        "mongo": docs,
        "sql": sql,
        "builder": builder,
        "rebac": rebac,
        "impact": impact,
        "hybrid": hybrid,
    }
    return _context


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def ontology_manifest() -> dict[str, Any]:
    """
    Return the full MetaOntology OS grammar.

    Includes spaces, meta-edges, impact categories, active metadata
    layers, and ReBAC configuration.
    """
    from opencrab.grammar.validator import describe_grammar

    return describe_grammar()


def ontology_add_node(
    space: str,
    node_type: str,
    node_id: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Add or update a node in the MetaOntology graph.

    Parameters
    ----------
    space:
        MetaOntology space (e.g. "subject", "resource", "concept").
    node_type:
        Node type within that space (e.g. "User", "Document").
    node_id:
        Stable unique identifier.
    properties:
        Key/value properties for the node.
    """
    ctx = _get_context()
    try:
        return ctx["builder"].add_node(
            space=space,
            node_type=node_type,
            node_id=node_id,
            properties=properties or {},
        )
    except ValueError as exc:
        return {"error": str(exc), "valid": False}
    except Exception as exc:
        logger.error("ontology_add_node failed: %s", exc)
        return {"error": str(exc)}


def ontology_add_edge(
    from_space: str,
    from_id: str,
    relation: str,
    to_space: str,
    to_id: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Add a directed edge between two ontology nodes.

    The (from_space, to_space, relation) triple is validated against
    the MetaOntology grammar before the write is attempted.

    Parameters
    ----------
    from_space:
        Space of the source node.
    from_id:
        ID of the source node.
    relation:
        Relation label (must be valid for the space pair).
    to_space:
        Space of the target node.
    to_id:
        ID of the target node.
    properties:
        Optional edge properties.
    """
    ctx = _get_context()
    try:
        return ctx["builder"].add_edge(
            from_space=from_space,
            from_id=from_id,
            relation=relation,
            to_space=to_space,
            to_id=to_id,
            properties=properties,
        )
    except ValueError as exc:
        return {"error": str(exc), "valid": False}
    except Exception as exc:
        logger.error("ontology_add_edge failed: %s", exc)
        return {"error": str(exc)}


def ontology_query(
    question: str,
    spaces: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Run a hybrid vector + graph query against the ontology.

    Parameters
    ----------
    question:
        Natural language question or keyword query.
    spaces:
        Optional list of space IDs to restrict the search.
    limit:
        Maximum number of results.
    """
    ctx = _get_context()
    try:
        results = ctx["hybrid"].query(
            question=question,
            spaces=spaces,
            limit=limit,
        )
        return {
            "question": question,
            "spaces_filter": spaces,
            "total": len(results),
            "results": [r.to_dict() for r in results],
        }
    except Exception as exc:
        logger.error("ontology_query failed: %s", exc)
        return {"error": str(exc)}


def ontology_impact(
    node_id: str,
    change_type: str = "update",
) -> dict[str, Any]:
    """
    Analyse the impact of a change to a specific node.

    Returns which impact categories (I1–I7) are triggered,
    which neighbouring nodes are affected, and a human-readable summary.

    Parameters
    ----------
    node_id:
        ID of the node being changed.
    change_type:
        Nature of the change: create, update, delete, permission_change,
        relationship_add, relationship_remove, bulk_import.
    """
    ctx = _get_context()
    try:
        result = ctx["impact"].analyse(node_id=node_id, change_type=change_type)
        return result.to_dict()
    except Exception as exc:
        logger.error("ontology_impact failed: %s", exc)
        return {"error": str(exc)}


def ontology_rebac_check(
    subject_id: str,
    permission: str,
    resource_id: str,
) -> dict[str, Any]:
    """
    Check whether a subject has a given permission over a resource.

    Uses ReBAC (Relationship-Based Access Control): checks explicit SQL
    policies first, then traverses the graph for relationship-based access.

    Parameters
    ----------
    subject_id:
        ID of the subject (User, Team, Org, Agent).
    permission:
        One of: view, edit, execute, simulate, approve, admin.
    resource_id:
        ID of the resource being accessed.
    """
    ctx = _get_context()
    try:
        decision = ctx["rebac"].check(
            subject_id=subject_id,
            permission=permission,
            resource_id=resource_id,
        )
        return decision.to_dict()
    except Exception as exc:
        logger.error("ontology_rebac_check failed: %s", exc)
        return {"error": str(exc), "granted": False}


def ontology_lever_simulate(
    lever_id: str,
    direction: str,
    magnitude: float,
) -> dict[str, Any]:
    """
    Simulate the downstream effects of moving a lever.

    Predicts changes to connected Outcome nodes and affected Concepts
    based on the current graph structure.

    Parameters
    ----------
    lever_id:
        ID of the Lever node.
    direction:
        One of: raises, lowers, stabilizes, optimizes.
    magnitude:
        Strength of the lever movement (recommended 0.0–1.0).
    """
    ctx = _get_context()
    try:
        return ctx["impact"].lever_simulate(
            lever_id=lever_id,
            direction=direction,
            magnitude=float(magnitude),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.error("ontology_lever_simulate failed: %s", exc)
        return {"error": str(exc)}


def ontology_extract(
    text: str,
    source_id: str,
    model: str = "claude-haiku-4-5-20251001",
) -> dict[str, Any]:
    """
    LLM-extract ontology nodes and edges from text and write to the graph.

    Uses Claude to identify entities and relationships according to the
    9-Space MetaOntology grammar, then persists them.

    Parameters
    ----------
    text:
        Raw text to extract knowledge from.
    source_id:
        Stable identifier for this source (e.g. file path or URL).
    model:
        Claude model to use for extraction.
    """
    import os

    from opencrab.ontology.extractor import LLMExtractor

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    ctx = _get_context()

    try:
        extractor = LLMExtractor(api_key=api_key, model=model)
        result = extractor.extract_from_text(text, source_id=source_id)

        added_nodes = 0
        added_edges = 0
        node_errors: list[str] = []
        edge_errors: list[str] = []

        for node in result.nodes:
            try:
                ctx["builder"].add_node(
                    space=node.space,
                    node_type=node.node_type,
                    node_id=node.node_id,
                    properties=node.properties,
                )
                added_nodes += 1
            except Exception as exc:
                node_errors.append(f"{node.node_id}: {exc}")

        for edge in result.edges:
            try:
                ctx["builder"].add_edge(
                    from_space=edge.from_space,
                    from_id=edge.from_id,
                    relation=edge.relation,
                    to_space=edge.to_space,
                    to_id=edge.to_id,
                    properties=edge.properties,
                )
                added_edges += 1
            except Exception as exc:
                edge_errors.append(f"{edge.from_id}→{edge.to_id}: {exc}")

        return {
            "source_id": source_id,
            "extracted_nodes": len(result.nodes),
            "extracted_edges": len(result.edges),
            "added_nodes": added_nodes,
            "added_edges": added_edges,
            "extraction_errors": result.errors,
            "node_errors": node_errors,
            "edge_errors": edge_errors,
        }
    except Exception as exc:
        logger.error("ontology_extract failed: %s", exc)
        return {"error": str(exc)}


def ontology_ingest(
    text: str,
    source_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Ingest a text document into the vector store.

    The text is embedded and stored in ChromaDB. A source record is
    also created in MongoDB if available.

    Parameters
    ----------
    text:
        The text content to ingest.
    source_id:
        Stable unique identifier for this source document.
    metadata:
        Optional metadata (e.g. space, node_id, author, created_at).
    """
    ctx = _get_context()
    meta = metadata or {}
    result: dict[str, Any] = {"source_id": source_id, "stores": {}}

    # Ingest into vector store
    try:
        vector_result = ctx["hybrid"].ingest(text=text, source_id=source_id, metadata=meta)
        result["stores"].update(vector_result.get("stores", {}))
        if "vector_id" in vector_result:
            result["vector_id"] = vector_result["vector_id"]
    except Exception as exc:
        result["stores"]["chromadb"] = f"error: {exc}"

    # Ingest into MongoDB
    mongo: Any = ctx["mongo"]
    if mongo.available:
        try:
            mongo_id = mongo.upsert_source(source_id, text, meta)
            result["stores"]["mongodb"] = f"ok (id={mongo_id})"
        except Exception as exc:
            result["stores"]["mongodb"] = f"error: {exc}"
    else:
        result["stores"]["mongodb"] = "unavailable"

    result["text_length"] = len(text)
    result["metadata"] = meta
    return result


def workflow_create_run(
    action_type: str,
    payload: dict[str, Any],
    subject_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a new workflow run in 'pending' state.

    Use this to start an auditable action workflow before executing it.
    Returns run_id, receipt_id, and status='pending'.

    Parameters
    ----------
    action_type:
        The action being requested (e.g. 'add_node', 'harness_apply').
    payload:
        The full action payload (will be stored for audit).
    subject_id:
        Optional identifier of the actor initiating the run.
    """
    from opencrab.execution.workflow import WorkflowEngine

    ctx = _get_context()
    engine = WorkflowEngine(ctx["sql"])
    return engine.create_run(action_type, payload, subject_id)


def workflow_advance(
    run_id: str,
    new_status: str,
    output: dict[str, Any] | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """
    Advance a workflow run to a new status.

    Valid statuses: pending, running, approved, rejected, completed, failed.
    Each advance is appended to the action_log for full provenance.

    Parameters
    ----------
    run_id:
        The workflow run to advance.
    new_status:
        Target status.
    output:
        Optional output/result dict to log.
    actor:
        Optional identifier of who triggered this transition.
    """
    from opencrab.execution.workflow import WorkflowEngine

    ctx = _get_context()
    engine = WorkflowEngine(ctx["sql"])
    return engine.advance(run_id, new_status, output, actor)


def approval_request(
    action_type: str,
    subject_id: str,
    payload: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Submit an approval request for a sensitive action.

    Creates a pending approval entry that must be resolved (approved/rejected)
    before the action is executed. Returns approval_id and status='pending'.

    Parameters
    ----------
    action_type:
        The type of action requiring approval.
    subject_id:
        The subject requesting the action.
    payload:
        The full action payload to be reviewed.
    run_id:
        Optional workflow run_id this approval is linked to.
    """
    from opencrab.execution.approvals import ApprovalEngine

    ctx = _get_context()
    engine = ApprovalEngine(ctx["sql"])
    return engine.request(action_type, subject_id, payload, run_id)


# ---------------------------------------------------------------------------
# Phase 3: Identity / Canonicalization / Promotion tools
# ---------------------------------------------------------------------------


def identity_add_alias(
    canonical_id: str,
    alias_id: str,
    alias_type: str = "name",
    space: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """
    Register alias_id as an alias for canonical_id.

    alias_type hints: 'name' (same name, diff ID), 'merge' (confirmed merge),
    'external' (same entity from external source).
    """
    from opencrab.ontology.identity import IdentityEngine

    ctx = _get_context()
    engine = IdentityEngine(ctx["sql"])
    return engine.add_alias(canonical_id, alias_id, alias_type, space, created_by)


def identity_resolve_canonical(node_id: str) -> dict[str, Any]:
    """
    Resolve node_id to its canonical ID.

    If node_id is an alias, returns the canonical. Otherwise returns node_id unchanged.
    """
    from opencrab.ontology.identity import IdentityEngine

    ctx = _get_context()
    engine = IdentityEngine(ctx["sql"])
    canonical = engine.resolve_canonical(node_id)
    return {"node_id": node_id, "canonical_id": canonical, "is_alias": canonical != node_id}


def identity_propose_duplicate(
    node_a_id: str,
    node_b_id: str,
    space: str | None = None,
    similarity: float | None = None,
    method: str = "name_fuzzy",
) -> dict[str, Any]:
    """
    Propose that two nodes may be the same entity.

    Creates a pending duplicate candidate for human review. Returns early if
    the pair is already proposed.
    """
    from opencrab.ontology.identity import IdentityEngine

    ctx = _get_context()
    engine = IdentityEngine(ctx["sql"])
    return engine.propose_duplicate(node_a_id, node_b_id, space, similarity, method)


def identity_resolve_duplicate(
    candidate_id: str,
    decision: str,
    decided_by: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """
    Accept or reject a pending duplicate candidate.

    decision: 'accepted' | 'rejected'
    If accepted, automatically registers node_b as alias of node_a.
    """
    from opencrab.ontology.identity import IdentityEngine

    ctx = _get_context()
    engine = IdentityEngine(ctx["sql"])
    try:
        return engine.resolve_duplicate(candidate_id, decision, decided_by, note)
    except ValueError as exc:
        return {"error": str(exc)}


def identity_list_pending_duplicates(limit: int = 50) -> dict[str, Any]:
    """Return all pending duplicate candidates sorted by similarity descending."""
    from opencrab.ontology.identity import IdentityEngine

    ctx = _get_context()
    engine = IdentityEngine(ctx["sql"])
    candidates = engine.list_pending_candidates(limit)
    return {"total": len(candidates), "candidates": candidates}


def canonicalize_merge_nodes(
    canonical_id: str,
    alias_id: str,
    canonical_space: str,
    canonical_type: str,
    merge_properties: bool = True,
    merged_by: str | None = None,
) -> dict[str, Any]:
    """
    Merge alias_id into canonical_id (tombstone pattern).

    The alias node is preserved — use resolve_canonical() to normalise IDs.
    Returns a merge receipt.
    """
    from opencrab.ontology.canonicalize import CanonicalizeEngine
    from opencrab.ontology.identity import IdentityEngine

    ctx = _get_context()
    identity = IdentityEngine(ctx["sql"])
    engine = CanonicalizeEngine(identity, ctx["builder"])
    return engine.merge_nodes(
        canonical_id, alias_id, canonical_space, canonical_type, merge_properties, merged_by
    )


def canonicalize_find_and_propose(
    node_id: str,
    name: str,
    space: str | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """
    Find similar nodes by name and auto-propose them as duplicate candidates for review.

    Returns proposed candidates — none are applied automatically.
    """
    from opencrab.ontology.canonicalize import CanonicalizeEngine
    from opencrab.ontology.identity import IdentityEngine

    ctx = _get_context()
    identity = IdentityEngine(ctx["sql"])
    engine = CanonicalizeEngine(identity, ctx["builder"])
    return engine.find_and_propose(node_id, name, space, threshold)


def promotion_register_candidate(
    space: str,
    node_type: str,
    node_id: str,
    properties: dict[str, Any],
    confidence: float | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """
    Register an extracted entity as a promotion candidate (status='candidate').

    The node will not appear in promoted queries until promoted.
    """
    from opencrab.ontology.promotion import PromotionEngine

    ctx = _get_context()
    engine = PromotionEngine(ctx["builder"], ctx["sql"])
    return engine.register_candidate(space, node_type, node_id, properties, confidence, source_id)


def promotion_validate_candidate(
    space: str,
    node_type: str,
    node_id: str,
    existing_properties: dict[str, Any],
    validator_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """
    Mark a candidate as 'validated' — ready for final promotion review.

    Does not promote yet. Call promotion_promote() after validation.
    """
    from opencrab.ontology.promotion import PromotionEngine

    ctx = _get_context()
    engine = PromotionEngine(ctx["builder"], ctx["sql"])
    return engine.validate_candidate(space, node_type, node_id, existing_properties, validator_id, note)


def promotion_promote(
    space: str,
    node_type: str,
    node_id: str,
    existing_properties: dict[str, Any],
    promoted_by: str | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Promote a validated candidate to 'promoted' status.

    Optionally links evidence nodes via 'supports' edges.
    Returns a promotion receipt with receipt_id and receipt_ts.
    """
    from opencrab.ontology.promotion import PromotionEngine

    ctx = _get_context()
    engine = PromotionEngine(ctx["builder"], ctx["sql"])
    return engine.promote(space, node_type, node_id, existing_properties, promoted_by, evidence_ids)


def promotion_reject(
    space: str,
    node_type: str,
    node_id: str,
    existing_properties: dict[str, Any],
    rejected_by: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Mark a candidate as 'rejected' with an optional reason."""
    from opencrab.ontology.promotion import PromotionEngine

    ctx = _get_context()
    engine = PromotionEngine(ctx["builder"], ctx["sql"])
    return engine.reject(space, node_type, node_id, existing_properties, rejected_by, reason)


def harness_promotion_apply(
    package: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Apply a CrabHarness PromotionPackage directly to the OpenCrab ontology stores.

    Accepts the promotion package as a JSON object (not a file path) so it can
    be called inline from Claude or any MCP client without file I/O.

    Each node and edge write returns a receipt_id + receipt_ts for provenance.

    Parameters
    ----------
    package:
        A serialised PromotionPackage object (from CrabHarness promotion-stub output).
    dry_run:
        If True, validate grammar + schema without writing to any store.
    """
    try:
        from crabharness.crabharness.models import PromotionPackage
    except ImportError:
        return {"error": "crabharness package not installed. Run: pip install -e crabharness/"}

    from opencrab.grammar.validator import validate_node, validate_node_properties

    try:
        promo = PromotionPackage.model_validate(package)
    except Exception as exc:
        return {"error": f"Invalid PromotionPackage: {exc}"}

    node_receipts: list[dict[str, Any]] = []
    edge_receipts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if dry_run:
        for node in promo.nodes:
            r = validate_node(node.space, node.node_type)
            if not r.valid:
                errors.append({"node_id": node.node_id, "error": r.error})
            else:
                pr = validate_node_properties(node.node_type, node.properties or {})
                if not pr.valid:
                    errors.append({"node_id": node.node_id, "error": pr.error})
                else:
                    node_receipts.append({
                        "node_id": node.node_id,
                        "space": node.space,
                        "node_type": node.node_type,
                        "status": "dry_run_valid",
                    })
        return {
            "package_id": promo.package_id,
            "dry_run": True,
            "node_receipts": node_receipts,
            "edge_receipts": edge_receipts,
            "errors": errors,
        }

    ctx = _get_context()
    builder = ctx["builder"]

    for node in promo.nodes:
        try:
            result = builder.add_node(
                space=node.space,
                node_type=node.node_type,
                node_id=node.node_id,
                properties=node.properties or {},
            )
            node_receipts.append({
                "node_id": node.node_id,
                "receipt_id": result.get("receipt_id"),
                "receipt_ts": result.get("receipt_ts"),
                "stores": result.get("stores"),
            })
        except Exception as exc:
            errors.append({"node_id": node.node_id, "error": str(exc)})

    for edge in promo.edges:
        try:
            result = builder.add_edge(
                from_space=edge.from_space,
                from_id=edge.from_id,
                relation=edge.relation,
                to_space=edge.to_space,
                to_id=edge.to_id,
            )
            edge_receipts.append({
                "from_id": edge.from_id,
                "relation": edge.relation,
                "to_id": edge.to_id,
                "receipt_id": result.get("receipt_id"),
                "receipt_ts": result.get("receipt_ts"),
                "stores": result.get("stores"),
            })
        except Exception as exc:
            errors.append({
                "edge": f"{edge.from_id}-[{edge.relation}]->{edge.to_id}",
                "error": str(exc),
            })

    return {
        "package_id": promo.package_id,
        "mission_id": promo.mission_id,
        "run_id": promo.run_id,
        "dry_run": False,
        "node_receipts": node_receipts,
        "edge_receipts": edge_receipts,
        "errors": errors,
        "summary": {
            "nodes_written": len(node_receipts),
            "edges_written": len(edge_receipts),
            "errors": len(errors),
        },
    }


# ---------------------------------------------------------------------------
# Tool registry (used by the MCP server for tools/list)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "ontology_manifest": {
        "description": (
            "Return the full MetaOntology OS grammar: spaces, meta-edges, "
            "impact categories, active metadata layers, and ReBAC config."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "ontology_add_node": {
        "description": "Add or update a node in the MetaOntology graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {
                    "type": "string",
                    "description": "MetaOntology space (e.g. subject, resource, concept).",
                },
                "node_type": {
                    "type": "string",
                    "description": "Node type within the space (e.g. User, Document).",
                },
                "node_id": {
                    "type": "string",
                    "description": "Stable unique identifier for the node.",
                },
                "properties": {
                    "type": "object",
                    "description": "Optional key/value properties.",
                },
            },
            "required": ["space", "node_type", "node_id"],
        },
    },
    "ontology_add_edge": {
        "description": (
            "Add a directed edge between two nodes. Validates the relation "
            "against the MetaOntology grammar."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_space": {"type": "string", "description": "Source node space."},
                "from_id": {"type": "string", "description": "Source node ID."},
                "relation": {"type": "string", "description": "Relation label."},
                "to_space": {"type": "string", "description": "Target node space."},
                "to_id": {"type": "string", "description": "Target node ID."},
                "properties": {"type": "object", "description": "Optional edge properties."},
            },
            "required": ["from_space", "from_id", "relation", "to_space", "to_id"],
        },
    },
    "ontology_query": {
        "description": "Hybrid vector + graph search across the ontology.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural language query."},
                "spaces": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of spaces to filter results.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10).",
                    "default": 10,
                },
            },
            "required": ["question"],
        },
    },
    "ontology_impact": {
        "description": "Analyse the I1–I7 impact of a change to a node.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the node being changed."},
                "change_type": {
                    "type": "string",
                    "description": "Type of change: create, update, delete, etc.",
                    "default": "update",
                },
            },
            "required": ["node_id"],
        },
    },
    "ontology_rebac_check": {
        "description": "Check whether a subject has a permission over a resource.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject_id": {"type": "string", "description": "Subject node ID."},
                "permission": {
                    "type": "string",
                    "description": "Permission: view, edit, execute, simulate, approve, admin.",
                },
                "resource_id": {"type": "string", "description": "Resource node ID."},
            },
            "required": ["subject_id", "permission", "resource_id"],
        },
    },
    "ontology_lever_simulate": {
        "description": "Simulate downstream outcome changes from a lever movement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lever_id": {"type": "string", "description": "ID of the Lever node."},
                "direction": {
                    "type": "string",
                    "description": "Direction: raises, lowers, stabilizes, optimizes.",
                },
                "magnitude": {
                    "type": "number",
                    "description": "Strength of the lever movement (0.0–1.0).",
                },
            },
            "required": ["lever_id", "direction", "magnitude"],
        },
    },
    "ontology_extract": {
        "description": (
            "LLM-extract ontology nodes and edges from text using Claude, "
            "then persist them into the knowledge graph."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to extract knowledge from."},
                "source_id": {"type": "string", "description": "Stable source identifier."},
                "model": {
                    "type": "string",
                    "description": "Claude model (default: claude-haiku-4-5-20251001).",
                    "default": "claude-haiku-4-5-20251001",
                },
            },
            "required": ["text", "source_id"],
        },
    },
    "ontology_ingest": {
        "description": "Ingest a text document into the vector and document stores.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content to ingest."},
                "source_id": {"type": "string", "description": "Stable source identifier."},
                "metadata": {"type": "object", "description": "Optional metadata."},
            },
            "required": ["text", "source_id"],
        },
    },
    "workflow_create_run": {
        "description": (
            "Create a new workflow run in 'pending' state. "
            "Use before executing any auditable action to get a run_id and receipt_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "description": "Action being requested (e.g. add_node, harness_apply)."},
                "payload": {"type": "object", "description": "Full action payload for audit."},
                "subject_id": {"type": "string", "description": "Optional actor identifier."},
            },
            "required": ["action_type", "payload"],
        },
    },
    "workflow_advance": {
        "description": (
            "Advance a workflow run to a new status. "
            "Valid statuses: pending, running, approved, rejected, completed, failed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Workflow run to advance."},
                "new_status": {"type": "string", "description": "Target status."},
                "output": {"type": "object", "description": "Optional result to log."},
                "actor": {"type": "string", "description": "Optional actor identifier."},
            },
            "required": ["run_id", "new_status"],
        },
    },
    "approval_request": {
        "description": (
            "Submit an approval request for a sensitive action. "
            "Returns approval_id with status='pending'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "description": "Action requiring approval."},
                "subject_id": {"type": "string", "description": "Subject requesting the action."},
                "payload": {"type": "object", "description": "Full payload to be reviewed."},
                "run_id": {"type": "string", "description": "Optional linked workflow run_id."},
            },
            "required": ["action_type", "subject_id", "payload"],
        },
    },
    "harness_promotion_apply": {
        "description": (
            "Apply a CrabHarness PromotionPackage to the OpenCrab ontology stores. "
            "Writes each node and edge, returning receipt_id + receipt_ts per operation. "
            "Use dry_run=true to validate grammar and schema without writing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "object",
                    "description": "Serialised PromotionPackage (from crabharness promotion-stub or run output).",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate without writing to stores.",
                    "default": False,
                },
            },
            "required": ["package"],
        },
    },
    # ------------------------------------------------------------------
    # Phase 3 — Identity / Canonicalization / Promotion
    # ------------------------------------------------------------------
    "identity_add_alias": {
        "description": "Register an alias_id for a canonical_id in the alias table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "canonical_id": {"type": "string", "description": "Authoritative node ID."},
                "alias_id": {"type": "string", "description": "Alias to register."},
                "alias_type": {
                    "type": "string",
                    "description": "Type hint: name, merge, external (default: name).",
                    "default": "name",
                },
                "space": {"type": "string", "description": "Optional space of the canonical node."},
                "created_by": {"type": "string", "description": "Optional actor ID."},
            },
            "required": ["canonical_id", "alias_id"],
        },
    },
    "identity_resolve_canonical": {
        "description": "Resolve a node_id to its canonical ID. Returns is_alias=true if it was an alias.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "Node ID to resolve."},
            },
            "required": ["node_id"],
        },
    },
    "identity_propose_duplicate": {
        "description": (
            "Propose that two nodes may be the same entity. "
            "Creates a pending duplicate candidate for human review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_a_id": {"type": "string", "description": "First node ID."},
                "node_b_id": {"type": "string", "description": "Second node ID."},
                "space": {"type": "string", "description": "Optional shared space."},
                "similarity": {"type": "number", "description": "Optional similarity score (0.0–1.0)."},
                "method": {"type": "string", "description": "Detection method (default: name_fuzzy).", "default": "name_fuzzy"},
            },
            "required": ["node_a_id", "node_b_id"],
        },
    },
    "identity_resolve_duplicate": {
        "description": "Accept or reject a pending duplicate candidate. If accepted, registers alias automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Duplicate candidate ID."},
                "decision": {"type": "string", "description": "accepted or rejected."},
                "decided_by": {"type": "string", "description": "Optional reviewer ID."},
                "note": {"type": "string", "description": "Optional decision note."},
            },
            "required": ["candidate_id", "decision"],
        },
    },
    "identity_list_pending_duplicates": {
        "description": "List all pending duplicate candidates sorted by similarity descending.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 50).", "default": 50},
            },
            "required": [],
        },
    },
    "canonicalize_merge_nodes": {
        "description": (
            "Merge alias_id into canonical_id using the tombstone pattern. "
            "Alias node is preserved; use identity_resolve_canonical to normalise IDs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "canonical_id": {"type": "string", "description": "Surviving canonical node ID."},
                "alias_id": {"type": "string", "description": "Node being merged in."},
                "canonical_space": {"type": "string", "description": "Space of the canonical node."},
                "canonical_type": {"type": "string", "description": "Node type of the canonical node."},
                "merge_properties": {"type": "boolean", "description": "Copy alias properties to canonical (default true).", "default": True},
                "merged_by": {"type": "string", "description": "Optional actor ID."},
            },
            "required": ["canonical_id", "alias_id", "canonical_space", "canonical_type"],
        },
    },
    "canonicalize_find_and_propose": {
        "description": "Find nodes with similar names and auto-propose them as duplicate candidates for review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "Source node ID."},
                "name": {"type": "string", "description": "Name to search for."},
                "space": {"type": "string", "description": "Optional space to limit search."},
                "threshold": {"type": "number", "description": "Minimum similarity threshold (default 0.5).", "default": 0.5},
            },
            "required": ["node_id", "name"],
        },
    },
    "promotion_register_candidate": {
        "description": "Register an extracted entity as a promotion candidate (status=candidate). Will not appear in promoted queries until promoted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "Target space."},
                "node_type": {"type": "string", "description": "Node type."},
                "node_id": {"type": "string", "description": "Node ID."},
                "properties": {"type": "object", "description": "Node properties."},
                "confidence": {"type": "number", "description": "Extraction confidence (0.0–1.0)."},
                "source_id": {"type": "string", "description": "Source document ID."},
            },
            "required": ["space", "node_type", "node_id", "properties"],
        },
    },
    "promotion_validate_candidate": {
        "description": "Mark a candidate as validated (ready for final promotion review). Does not promote yet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "node_type": {"type": "string"},
                "node_id": {"type": "string"},
                "existing_properties": {"type": "object", "description": "Current node properties."},
                "validator_id": {"type": "string", "description": "Optional validator ID."},
                "note": {"type": "string", "description": "Optional validation note."},
            },
            "required": ["space", "node_type", "node_id", "existing_properties"],
        },
    },
    "promotion_promote": {
        "description": "Promote a validated candidate to promoted status. Optionally links evidence nodes via supports edges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "node_type": {"type": "string"},
                "node_id": {"type": "string"},
                "existing_properties": {"type": "object", "description": "Current node properties."},
                "promoted_by": {"type": "string", "description": "Optional actor ID."},
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional evidence node IDs to link via supports edges.",
                },
            },
            "required": ["space", "node_type", "node_id", "existing_properties"],
        },
    },
    "promotion_reject": {
        "description": "Mark a candidate as rejected with an optional reason.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "space": {"type": "string"},
                "node_type": {"type": "string"},
                "node_id": {"type": "string"},
                "existing_properties": {"type": "object", "description": "Current node properties."},
                "rejected_by": {"type": "string", "description": "Optional actor ID."},
                "reason": {"type": "string", "description": "Rejection reason."},
            },
            "required": ["space", "node_type", "node_id", "existing_properties"],
        },
    },
}

# Callable map
_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "ontology_manifest": ontology_manifest,
    "ontology_add_node": ontology_add_node,
    "ontology_add_edge": ontology_add_edge,
    "ontology_query": ontology_query,
    "ontology_impact": ontology_impact,
    "ontology_rebac_check": ontology_rebac_check,
    "ontology_lever_simulate": ontology_lever_simulate,
    "ontology_extract": ontology_extract,
    "ontology_ingest": ontology_ingest,
    "harness_promotion_apply": harness_promotion_apply,
    "workflow_create_run": workflow_create_run,
    "workflow_advance": workflow_advance,
    "approval_request": approval_request,
    # Phase 3
    "identity_add_alias": identity_add_alias,
    "identity_resolve_canonical": identity_resolve_canonical,
    "identity_propose_duplicate": identity_propose_duplicate,
    "identity_resolve_duplicate": identity_resolve_duplicate,
    "identity_list_pending_duplicates": identity_list_pending_duplicates,
    "canonicalize_merge_nodes": canonicalize_merge_nodes,
    "canonicalize_find_and_propose": canonicalize_find_and_propose,
    "promotion_register_candidate": promotion_register_candidate,
    "promotion_validate_candidate": promotion_validate_candidate,
    "promotion_promote": promotion_promote,
    "promotion_reject": promotion_reject,
}

# Combined tool descriptor list (name + schema)
TOOLS: list[dict[str, Any]] = [
    {"name": name, **schema}
    for name, schema in TOOL_SCHEMAS.items()
]


def dispatch_tool(name: str, arguments: dict[str, Any]) -> Any:
    """
    Look up and call a tool by name.

    Parameters
    ----------
    name:
        Tool name from TOOL_SCHEMAS.
    arguments:
        Arguments dict from the MCP tools/call request.

    Returns
    -------
    JSON-serialisable result.

    Raises
    ------
    KeyError
        If the tool name is not registered.
    """
    fn = _TOOL_FUNCTIONS.get(name)
    if fn is None:
        raise KeyError(f"Unknown tool: '{name}'. Available: {list(_TOOL_FUNCTIONS)}")
    return fn(**arguments)
