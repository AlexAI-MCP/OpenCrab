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
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Store / engine singletons (lazily initialised)
# ---------------------------------------------------------------------------
# These are populated by _get_context() which is called on first tool use.
# This design avoids importing heavy dependencies at module load time.

_context: dict[str, Any] = {}


def _get_context() -> dict[str, Any]:
    """Lazily initialise all stores and engines."""
    global _context
    if _context:
        return _context

    from opencrab.config import get_settings
    from opencrab.ontology.builder import OntologyBuilder
    from opencrab.ontology.impact import ImpactEngine
    from opencrab.ontology.query import HybridQuery
    from opencrab.ontology.rebac import ReBACEngine
    from opencrab.stores.chroma_store import ChromaStore
    from opencrab.stores.mongo_store import MongoStore
    from opencrab.stores.neo4j_store import Neo4jStore
    from opencrab.stores.sql_store import SQLStore

    cfg = get_settings()

    neo4j = Neo4jStore(cfg.neo4j_uri, cfg.neo4j_user, cfg.neo4j_password)
    chroma = ChromaStore(cfg.chroma_host, cfg.chroma_port, cfg.chroma_collection)
    mongo = MongoStore(cfg.mongodb_uri, cfg.mongodb_db)
    sql = SQLStore(cfg.postgres_url)

    builder = OntologyBuilder(neo4j, mongo, sql)
    rebac = ReBACEngine(neo4j, sql)
    impact = ImpactEngine(neo4j, sql)
    hybrid = HybridQuery(chroma, neo4j)

    _context = {
        "neo4j": neo4j,
        "chroma": chroma,
        "mongo": mongo,
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
    "ontology_ingest": ontology_ingest,
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
