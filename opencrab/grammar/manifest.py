"""
MetaOntology OS — canonical grammar manifest.

This module is the single source of truth for all space definitions,
meta-edge relationship grammar, impact categories, active metadata layers,
and ReBAC configuration.
"""

from typing import Any

# ---------------------------------------------------------------------------
# Grammar versioning
# ---------------------------------------------------------------------------

GRAMMAR_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Spaces
# Each space has a description and the canonical node types it can contain.
# ---------------------------------------------------------------------------

SPACES: dict[str, dict[str, Any]] = {
    "subject": {
        "description": "Actors and agents that have intentions and permissions.",
        "node_types": ["User", "Team", "Org", "Agent"],
    },
    "resource": {
        "description": "Artifacts and tools that subjects act upon.",
        "node_types": ["Project", "Document", "File", "Dataset", "Tool", "API", "CrawlRun"],
    },
    "evidence": {
        "description": "Raw observations, logs, and empirical records.",
        "node_types": ["TextUnit", "LogEntry", "Evidence"],
    },
    "concept": {
        "description": "Abstract knowledge: entities, categories, and topics.",
        "node_types": ["Entity", "Concept", "Topic", "Class"],
    },
    "claim": {
        "description": "Assertions derived from evidence.",
        "node_types": ["Claim", "Covariate", "CollectionCompleteness"],
    },
    "community": {
        "description": "Clusters of related concepts or actors.",
        "node_types": ["Community", "CommunityReport"],
    },
    "outcome": {
        "description": "Measurable results, performance indicators, and risks.",
        "node_types": ["Outcome", "KPI", "Risk"],
    },
    "lever": {
        "description": "Control variables that influence outcomes.",
        "node_types": ["Lever"],
    },
    "policy": {
        "description": "Rules governing access, classification, and approval.",
        "node_types": ["Policy", "Sensitivity", "ApprovalRule"],
    },
}

# ---------------------------------------------------------------------------
# Meta-Edges
# Defines which relations are valid between spaces.
# ---------------------------------------------------------------------------

META_EDGES: list[dict[str, Any]] = [
    {
        "from_space": "subject",
        "to_space": "resource",
        "relations": ["owns", "member_of", "manages", "can_view", "can_edit", "can_execute", "can_approve"],
        "description": "Subjects hold permissions and roles over resources.",
    },
    {
        "from_space": "resource",
        "to_space": "evidence",
        "relations": ["contains", "derived_from", "logged_as"],
        "description": "Resources produce or reference evidence.",
    },
    {
        "from_space": "evidence",
        "to_space": "concept",
        "relations": ["mentions", "describes", "exemplifies"],
        "description": "Evidence surfaces conceptual knowledge.",
    },
    {
        "from_space": "evidence",
        "to_space": "claim",
        "relations": ["supports", "contradicts", "timestamps"],
        "description": "Evidence grounds or challenges claims.",
    },
    {
        "from_space": "concept",
        "to_space": "concept",
        "relations": ["related_to", "subclass_of", "part_of", "influences", "depends_on"],
        "description": "Inter-concept knowledge graph edges.",
    },
    {
        "from_space": "concept",
        "to_space": "outcome",
        "relations": ["contributes_to", "constrains", "predicts", "degrades"],
        "description": "Concepts have causal or correlative links to outcomes.",
    },
    {
        "from_space": "lever",
        "to_space": "outcome",
        "relations": ["raises", "lowers", "stabilizes", "optimizes"],
        "description": "Levers directly control outcome values.",
    },
    {
        "from_space": "lever",
        "to_space": "concept",
        "relations": ["affects"],
        "description": "Levers influence conceptual state.",
    },
    {
        "from_space": "community",
        "to_space": "concept",
        "relations": ["clusters", "summarizes"],
        "description": "Communities aggregate conceptual structure.",
    },
    {
        "from_space": "policy",
        "to_space": "resource",
        "relations": ["protects", "classifies", "restricts"],
        "description": "Policies govern resource access and classification.",
    },
    {
        "from_space": "policy",
        "to_space": "subject",
        "relations": ["permits", "denies", "requires_approval"],
        "description": "Policies define what subjects are allowed to do.",
    },
]

# ---------------------------------------------------------------------------
# Impact Categories (I1–I7)
# Used by the impact analysis engine to categorize change propagation.
# ---------------------------------------------------------------------------

IMPACT_CATEGORIES: list[dict[str, str]] = [
    {
        "id": "I1",
        "name": "Data impact",
        "question": "What data values or records change?",
    },
    {
        "id": "I2",
        "name": "Relation impact",
        "question": "What relationships or edges in the graph are affected?",
    },
    {
        "id": "I3",
        "name": "Space impact",
        "question": "Which ontology spaces are touched by this change?",
    },
    {
        "id": "I4",
        "name": "Permission impact",
        "question": "Which access permissions or ReBAC policies change?",
    },
    {
        "id": "I5",
        "name": "Logic impact",
        "question": "Which business rules or inference chains are invalidated?",
    },
    {
        "id": "I6",
        "name": "Cache/index impact",
        "question": "Which caches, indexes, or materialized views must be refreshed?",
    },
    {
        "id": "I7",
        "name": "Downstream system impact",
        "question": "Which external systems or integrations are affected?",
    },
]

# ---------------------------------------------------------------------------
# Active Metadata Layers
# Orthogonal metadata dimensions applied to any node or edge.
# ---------------------------------------------------------------------------

ACTIVE_METADATA_LAYERS: dict[str, list[str]] = {
    "existence": ["identity", "provenance", "lineage"],
    "quality": ["confidence", "freshness", "completeness"],
    "relational": ["dependency", "sensitivity", "maturity"],
    "behavioral": ["usage", "mutation", "effect"],
}

# ---------------------------------------------------------------------------
# ReBAC Configuration
# Relationship-Based Access Control object types and permissions.
# ---------------------------------------------------------------------------

REBAC_OBJECT_TYPES: list[str] = [
    "user",
    "team",
    "org",
    "project",
    "document",
    "lever",
    "tool",
]

REBAC_PERMISSIONS: list[str] = [
    "view",
    "edit",
    "execute",
    "simulate",
    "approve",
    "admin",
]

# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def all_node_types() -> list[str]:
    """Return a flat list of all canonical node types across all spaces."""
    types: list[str] = []
    for space in SPACES.values():
        types.extend(space["node_types"])
    return types


def all_relations() -> list[str]:
    """Return a flat de-duplicated list of all valid relation labels."""
    relations: set[str] = set()
    for edge in META_EDGES:
        relations.update(edge["relations"])
    return sorted(relations)


def space_for_node_type(node_type: str) -> str | None:
    """Return the space_id that owns a given node_type, or None."""
    for space_id, spec in SPACES.items():
        if node_type in spec["node_types"]:
            return space_id
    return None
