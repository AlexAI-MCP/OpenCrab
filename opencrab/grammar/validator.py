"""
MetaOntology grammar validator.

All node and edge validation goes through this module. It is the single
source of truth for what constitutes a valid ontology operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opencrab.grammar.manifest import META_EDGES, SPACES

# ---------------------------------------------------------------------------
# Internal lookup tables (built once at import time)
# ---------------------------------------------------------------------------

_SPACE_NODE_TYPES: dict[str, set[str]] = {
    space_id: set(spec["node_types"]) for space_id, spec in SPACES.items()
}

# Map (from_space, to_space) -> set[relation]
_EDGE_RELATION_MAP: dict[tuple[str, str], set[str]] = {}
for _edge in META_EDGES:
    _key = (_edge["from_space"], _edge["to_space"])
    _EDGE_RELATION_MAP[_key] = set(_edge["relations"])


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Outcome of a grammar validation check."""

    valid: bool
    error: str | None = None

    def raise_if_invalid(self) -> None:
        if not self.valid:
            raise ValueError(self.error or "Validation failed")

    def __bool__(self) -> bool:
        return self.valid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_node(space_id: str, node_type: str) -> ValidationResult:
    """
    Check that *node_type* is a valid type within *space_id*.

    Parameters
    ----------
    space_id:
        One of the canonical space identifiers (e.g. "subject", "resource").
    node_type:
        The type label for the node (e.g. "User", "Document").

    Returns
    -------
    ValidationResult
        ``.valid`` is True when the combination is allowed.
    """
    if space_id not in _SPACE_NODE_TYPES:
        known = ", ".join(sorted(_SPACE_NODE_TYPES))
        return ValidationResult(
            valid=False,
            error=f"Unknown space '{space_id}'. Known spaces: {known}.",
        )

    if node_type not in _SPACE_NODE_TYPES[space_id]:
        allowed = ", ".join(sorted(_SPACE_NODE_TYPES[space_id]))
        return ValidationResult(
            valid=False,
            error=(
                f"Node type '{node_type}' is not valid in space '{space_id}'. "
                f"Allowed types: {allowed}."
            ),
        )

    return ValidationResult(valid=True)


def validate_edge(from_space: str, to_space: str, relation: str) -> ValidationResult:
    """
    Check that *relation* is a valid meta-edge from *from_space* to *to_space*.

    Parameters
    ----------
    from_space:
        Source space identifier.
    to_space:
        Target space identifier.
    relation:
        Relation label (e.g. "owns", "supports").

    Returns
    -------
    ValidationResult
    """
    if from_space not in _SPACE_NODE_TYPES:
        return ValidationResult(
            valid=False,
            error=f"Unknown source space '{from_space}'.",
        )

    if to_space not in _SPACE_NODE_TYPES:
        return ValidationResult(
            valid=False,
            error=f"Unknown target space '{to_space}'.",
        )

    key = (from_space, to_space)
    if key not in _EDGE_RELATION_MAP:
        return ValidationResult(
            valid=False,
            error=(
                f"No meta-edge defined from space '{from_space}' to space '{to_space}'. "
                "Check grammar/manifest.py for valid space pairs."
            ),
        )

    allowed = _EDGE_RELATION_MAP[key]
    if relation not in allowed:
        return ValidationResult(
            valid=False,
            error=(
                f"Relation '{relation}' is not valid from '{from_space}' to '{to_space}'. "
                f"Allowed relations: {', '.join(sorted(allowed))}."
            ),
        )

    return ValidationResult(valid=True)


def get_allowed_relations(from_space: str, to_space: str) -> list[str]:
    """
    Return the list of valid relation labels between two spaces.

    Returns an empty list if no meta-edge exists between those spaces.
    """
    key = (from_space, to_space)
    return sorted(_EDGE_RELATION_MAP.get(key, set()))


def validate_metadata_layer(layer: str, attribute: str) -> ValidationResult:
    """
    Validate that *attribute* belongs to *layer* in ACTIVE_METADATA_LAYERS.
    """
    from opencrab.grammar.manifest import ACTIVE_METADATA_LAYERS

    if layer not in ACTIVE_METADATA_LAYERS:
        known = ", ".join(sorted(ACTIVE_METADATA_LAYERS))
        return ValidationResult(
            valid=False,
            error=f"Unknown metadata layer '{layer}'. Known layers: {known}.",
        )

    allowed = ACTIVE_METADATA_LAYERS[layer]
    if attribute not in allowed:
        return ValidationResult(
            valid=False,
            error=(
                f"Attribute '{attribute}' not in layer '{layer}'. "
                f"Allowed: {', '.join(allowed)}."
            ),
        )

    return ValidationResult(valid=True)


def validate_rebac_permission(permission: str) -> ValidationResult:
    """Check that *permission* is a known ReBAC permission."""
    from opencrab.grammar.manifest import REBAC_PERMISSIONS

    if permission not in REBAC_PERMISSIONS:
        return ValidationResult(
            valid=False,
            error=(
                f"Unknown permission '{permission}'. "
                f"Allowed: {', '.join(REBAC_PERMISSIONS)}."
            ),
        )
    return ValidationResult(valid=True)


def validate_node_properties(node_type: str, properties: dict[str, Any]) -> ValidationResult:
    """
    Validate node properties against the Type Schema Registry.

    If no schema exists for the node_type, the check always passes
    (schema is optional — not all types need a registered schema).

    Parameters
    ----------
    node_type:
        The node type label (e.g. "User", "Document").
    properties:
        The property dict to validate.

    Returns
    -------
    ValidationResult
    """
    try:
        from opencrab.schemas.loader import load_type_schema
    except ImportError:
        return ValidationResult(valid=True)

    schema = load_type_schema(node_type)
    if schema is None:
        return ValidationResult(valid=True)

    schema_props: dict[str, Any] = schema.get("properties", {})
    errors: list[str] = []

    # Required field check
    for field, spec in schema_props.items():
        if spec.get("required", False) and "default" not in spec:
            if field not in properties:
                errors.append(f"Required field '{field}' is missing.")

    # Enum value check
    for field, value in properties.items():
        if field in schema_props:
            spec = schema_props[field]
            allowed = spec.get("enum")
            if allowed is not None and value is not None and value not in allowed:
                errors.append(
                    f"Field '{field}' must be one of {allowed}, got '{value}'."
                )

    if errors:
        return ValidationResult(valid=False, error="; ".join(errors))
    return ValidationResult(valid=True)


def describe_grammar() -> dict[str, Any]:
    """Return a JSON-serialisable summary of the full MetaOntology grammar."""
    from opencrab.grammar.manifest import (
        ACTIVE_METADATA_LAYERS,
        GRAMMAR_VERSION,
        IMPACT_CATEGORIES,
        REBAC_OBJECT_TYPES,
        REBAC_PERMISSIONS,
        SPACES,
    )

    return {
        "version": GRAMMAR_VERSION,
        "spaces": SPACES,
        "meta_edges": META_EDGES,
        "impact_categories": IMPACT_CATEGORIES,
        "active_metadata_layers": ACTIVE_METADATA_LAYERS,
        "rebac": {
            "object_types": REBAC_OBJECT_TYPES,
            "permissions": REBAC_PERMISSIONS,
        },
    }
