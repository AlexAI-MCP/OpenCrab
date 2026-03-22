"""MetaOntology grammar: manifest, validator, and glossary."""

from opencrab.grammar.manifest import (
    ACTIVE_METADATA_LAYERS,
    IMPACT_CATEGORIES,
    META_EDGES,
    REBAC_OBJECT_TYPES,
    REBAC_PERMISSIONS,
    SPACES,
)
from opencrab.grammar.validator import (
    get_allowed_relations,
    validate_edge,
    validate_node,
)

__all__ = [
    "SPACES",
    "META_EDGES",
    "IMPACT_CATEGORIES",
    "ACTIVE_METADATA_LAYERS",
    "REBAC_OBJECT_TYPES",
    "REBAC_PERMISSIONS",
    "validate_node",
    "validate_edge",
    "get_allowed_relations",
]
