"""
MetaOntology canonical glossary.

Provides human-readable definitions for every term in the grammar.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Space definitions
# ---------------------------------------------------------------------------

SPACE_GLOSSARY: dict[str, str] = {
    "subject": (
        "The actor space. Subjects are entities with identity and agency — "
        "users, teams, organisations, and autonomous agents — that hold "
        "permissions, execute actions, and bear responsibility."
    ),
    "resource": (
        "The artefact space. Resources are the objects that subjects act upon: "
        "projects, documents, files, datasets, tools, and APIs."
    ),
    "evidence": (
        "The observation space. Evidence captures raw empirical material — "
        "text units, log entries, and structured evidence records that "
        "ground claims in reality."
    ),
    "concept": (
        "The knowledge space. Concepts are abstract entities, topics, classes, "
        "and categories that form the semantic backbone of the ontology."
    ),
    "claim": (
        "The assertion space. Claims are propositions derived from evidence — "
        "statements that can be supported, contradicted, or timestamped."
    ),
    "community": (
        "The cluster space. Communities are groups of related concepts or actors "
        "identified through graph analysis (e.g. Leiden, Louvain algorithms)."
    ),
    "outcome": (
        "The result space. Outcomes are measurable end-states: KPIs that track "
        "performance, risks that represent threats, and general outcomes."
    ),
    "lever": (
        "The control space. Levers are tunable variables that directly influence "
        "outcomes — analogous to policy dials or system actuators."
    ),
    "policy": (
        "The governance space. Policies encode rules: sensitivity classifications, "
        "approval workflows, and access restrictions."
    ),
}

# ---------------------------------------------------------------------------
# Relation definitions
# ---------------------------------------------------------------------------

RELATION_GLOSSARY: dict[str, str] = {
    # subject → resource
    "owns": "The subject has ownership rights over the resource.",
    "member_of": "The subject is a member of a resource (e.g. project team).",
    "manages": "The subject has managerial authority over the resource.",
    "can_view": "The subject has read-only access to the resource.",
    "can_edit": "The subject can modify the resource.",
    "can_execute": "The subject can run or invoke the resource.",
    "can_approve": "The subject can approve changes to the resource.",
    # resource → evidence
    "contains": "The resource contains the evidence as part of its content.",
    "derived_from": "The resource was produced from or based on the evidence.",
    "logged_as": "The resource operation was recorded as the evidence.",
    # evidence → concept
    "mentions": "The evidence text references the concept.",
    "describes": "The evidence provides a substantive description of the concept.",
    "exemplifies": "The evidence serves as a concrete example of the concept.",
    # evidence → claim
    "supports": "The evidence strengthens the credibility of the claim.",
    "contradicts": "The evidence weakens or refutes the claim.",
    "timestamps": "The evidence provides a temporal anchor for the claim.",
    # concept → concept
    "related_to": "The two concepts share a non-hierarchical semantic relationship.",
    "subclass_of": "The source concept is a specialisation of the target.",
    "part_of": "The source concept is a component of the target concept.",
    "influences": "Changes in the source concept tend to change the target.",
    "depends_on": "The source concept requires the target concept to be meaningful.",
    # concept → outcome
    "contributes_to": "The concept positively drives the outcome.",
    "constrains": "The concept limits or bounds the outcome.",
    "predicts": "The concept is a leading indicator of the outcome.",
    "degrades": "The concept negatively impacts the outcome.",
    # lever → outcome
    "raises": "Activating the lever increases the outcome value.",
    "lowers": "Activating the lever decreases the outcome value.",
    "stabilizes": "The lever reduces variance in the outcome.",
    "optimizes": "The lever moves the outcome toward its target value.",
    # lever → concept
    "affects": "The lever changes the state or salience of the concept.",
    # community → concept
    "clusters": "The community groups this concept with related ones.",
    "summarizes": "The community report provides a summary of the concept cluster.",
    # policy → resource
    "protects": "The policy enforces security controls over the resource.",
    "classifies": "The policy assigns a sensitivity classification to the resource.",
    "restricts": "The policy limits how the resource can be used.",
    # policy → subject
    "permits": "The policy explicitly grants the subject certain actions.",
    "denies": "The policy explicitly prohibits the subject from certain actions.",
    "requires_approval": "The subject's actions on governed resources require approval.",
}

# ---------------------------------------------------------------------------
# Impact category definitions
# ---------------------------------------------------------------------------

IMPACT_GLOSSARY: dict[str, str] = {
    "I1": "Data Impact — changes to raw data values, records, or attributes.",
    "I2": "Relation Impact — changes to edges or relationship attributes in the graph.",
    "I3": "Space Impact — changes affecting the membership or boundaries of ontology spaces.",
    "I4": "Permission Impact — changes to access control rules or ReBAC policy.",
    "I5": "Logic Impact — invalidation of business rules, inferred facts, or reasoning chains.",
    "I6": "Cache/Index Impact — stale caches, outdated search indexes, or materialized views.",
    "I7": "Downstream System Impact — propagated effects to external APIs, data pipelines, or integrations.",
}

# ---------------------------------------------------------------------------
# Metadata layer definitions
# ---------------------------------------------------------------------------

METADATA_LAYER_GLOSSARY: dict[str, dict[str, str]] = {
    "existence": {
        "identity": "Stable identifier and canonical naming of the node.",
        "provenance": "Origin source and creation context of the node.",
        "lineage": "Transformation history from raw input to current state.",
    },
    "quality": {
        "confidence": "Estimated reliability or certainty of the node's content.",
        "freshness": "How recently the node was updated relative to its source.",
        "completeness": "Proportion of expected attributes that are populated.",
    },
    "relational": {
        "dependency": "Other nodes this node depends on for correctness.",
        "sensitivity": "Data sensitivity classification (e.g. PII, confidential).",
        "maturity": "Lifecycle stage: draft, review, approved, deprecated.",
    },
    "behavioral": {
        "usage": "How frequently and by whom the node is accessed.",
        "mutation": "Rate and pattern of changes to the node over time.",
        "effect": "Known downstream effects when this node changes.",
    },
}


def lookup_term(term: str) -> str | None:
    """
    Look up any canonical term across all glossaries.

    Parameters
    ----------
    term:
        A space ID, relation label, impact category ID, or metadata attribute.

    Returns
    -------
    str | None
        The definition string, or None if the term is not found.
    """
    if term in SPACE_GLOSSARY:
        return SPACE_GLOSSARY[term]
    if term in RELATION_GLOSSARY:
        return RELATION_GLOSSARY[term]
    if term in IMPACT_GLOSSARY:
        return IMPACT_GLOSSARY[term]
    for layer_attrs in METADATA_LAYER_GLOSSARY.values():
        if term in layer_attrs:
            return layer_attrs[term]
    return None


def full_glossary() -> dict[str, dict[str, str]]:
    """Return the complete glossary as a nested dictionary."""
    return {
        "spaces": SPACE_GLOSSARY,
        "relations": RELATION_GLOSSARY,
        "impact_categories": IMPACT_GLOSSARY,
        "metadata_layers": {
            attr: definition
            for layer in METADATA_LAYER_GLOSSARY.values()
            for attr, definition in layer.items()
        },
    }
