"""
Tests for grammar/manifest.py, grammar/validator.py, and grammar/glossary.py.

These tests require no external services and should always pass.
"""

import pytest

from opencrab.grammar.glossary import (
    IMPACT_GLOSSARY,
    RELATION_GLOSSARY,
    SPACE_GLOSSARY,
    full_glossary,
    lookup_term,
)
from opencrab.grammar.manifest import (
    ACTIVE_METADATA_LAYERS,
    IMPACT_CATEGORIES,
    META_EDGES,
    REBAC_OBJECT_TYPES,
    REBAC_PERMISSIONS,
    SPACES,
    all_node_types,
    all_relations,
    space_for_node_type,
)
from opencrab.grammar.validator import (
    ValidationResult,
    describe_grammar,
    get_allowed_relations,
    validate_edge,
    validate_metadata_layer,
    validate_node,
    validate_rebac_permission,
)


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------


class TestManifest:
    def test_spaces_have_all_required_keys(self):
        for space_id, spec in SPACES.items():
            assert "description" in spec, f"Space '{space_id}' missing description"
            assert "node_types" in spec, f"Space '{space_id}' missing node_types"
            assert len(spec["node_types"]) > 0, f"Space '{space_id}' has empty node_types"

    def test_nine_spaces_defined(self):
        assert len(SPACES) == 9

    def test_expected_spaces_present(self):
        expected = {
            "subject", "resource", "evidence", "concept",
            "claim", "community", "outcome", "lever", "policy",
        }
        assert set(SPACES.keys()) == expected

    def test_meta_edges_have_required_keys(self):
        for edge in META_EDGES:
            assert "from_space" in edge
            assert "to_space" in edge
            assert "relations" in edge
            assert len(edge["relations"]) > 0

    def test_meta_edges_reference_valid_spaces(self):
        valid_spaces = set(SPACES.keys())
        for edge in META_EDGES:
            assert edge["from_space"] in valid_spaces, f"Unknown from_space: {edge['from_space']}"
            assert edge["to_space"] in valid_spaces, f"Unknown to_space: {edge['to_space']}"

    def test_impact_categories_ids(self):
        ids = [cat["id"] for cat in IMPACT_CATEGORIES]
        assert ids == ["I1", "I2", "I3", "I4", "I5", "I6", "I7"]

    def test_active_metadata_layers(self):
        expected_layers = {"existence", "quality", "relational", "behavioral"}
        assert set(ACTIVE_METADATA_LAYERS.keys()) == expected_layers

    def test_rebac_permissions_complete(self):
        expected = {"view", "edit", "execute", "simulate", "approve", "admin"}
        assert set(REBAC_PERMISSIONS) == expected

    def test_rebac_object_types_include_user(self):
        assert "user" in REBAC_OBJECT_TYPES
        assert "project" in REBAC_OBJECT_TYPES
        assert "document" in REBAC_OBJECT_TYPES

    def test_all_node_types_is_flat_list(self):
        types = all_node_types()
        assert "User" in types
        assert "Document" in types
        assert "Lever" in types
        assert "Claim" in types

    def test_all_relations_is_sorted_list(self):
        relations = all_relations()
        assert isinstance(relations, list)
        assert relations == sorted(relations)
        assert "owns" in relations
        assert "supports" in relations

    def test_space_for_node_type(self):
        assert space_for_node_type("User") == "subject"
        assert space_for_node_type("Document") == "resource"
        assert space_for_node_type("Claim") == "claim"
        assert space_for_node_type("Lever") == "lever"
        assert space_for_node_type("Unknown") is None


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


class TestValidateNode:
    def test_valid_node(self):
        result = validate_node("subject", "User")
        assert result.valid is True
        assert result.error is None

    def test_valid_node_resource(self):
        assert validate_node("resource", "Document").valid

    def test_valid_node_all_spaces(self):
        valid_pairs = [
            ("subject", "User"), ("subject", "Team"), ("subject", "Org"), ("subject", "Agent"),
            ("resource", "Project"), ("resource", "Document"), ("resource", "File"),
            ("resource", "Dataset"), ("resource", "Tool"), ("resource", "API"),
            ("evidence", "TextUnit"), ("evidence", "LogEntry"), ("evidence", "Evidence"),
            ("concept", "Entity"), ("concept", "Concept"), ("concept", "Topic"), ("concept", "Class"),
            ("claim", "Claim"), ("claim", "Covariate"),
            ("community", "Community"), ("community", "CommunityReport"),
            ("outcome", "Outcome"), ("outcome", "KPI"), ("outcome", "Risk"),
            ("lever", "Lever"),
            ("policy", "Policy"), ("policy", "Sensitivity"), ("policy", "ApprovalRule"),
        ]
        for space, node_type in valid_pairs:
            result = validate_node(space, node_type)
            assert result.valid, f"Expected valid: ({space}, {node_type}). Error: {result.error}"

    def test_invalid_space(self):
        result = validate_node("nonexistent", "User")
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_invalid_node_type_in_valid_space(self):
        result = validate_node("subject", "Document")
        assert result.valid is False
        assert "Document" in result.error

    def test_wrong_node_type_wrong_space(self):
        result = validate_node("lever", "User")
        assert result.valid is False

    def test_validation_result_bool(self):
        result = validate_node("subject", "User")
        assert bool(result) is True

        result = validate_node("bad", "type")
        assert bool(result) is False

    def test_raise_if_invalid(self):
        result = validate_node("bad_space", "X")
        with pytest.raises(ValueError, match="bad_space"):
            result.raise_if_invalid()

    def test_raise_if_invalid_no_raise_on_valid(self):
        result = validate_node("subject", "User")
        result.raise_if_invalid()  # should not raise


class TestValidateEdge:
    def test_valid_edge_subject_resource(self):
        for relation in ["owns", "member_of", "manages", "can_view", "can_edit", "can_execute", "can_approve"]:
            result = validate_edge("subject", "resource", relation)
            assert result.valid, f"Expected valid edge: subject-[{relation}]->resource"

    def test_valid_edge_evidence_concept(self):
        for relation in ["mentions", "describes", "exemplifies"]:
            result = validate_edge("evidence", "concept", relation)
            assert result.valid

    def test_valid_edge_concept_concept(self):
        for relation in ["related_to", "subclass_of", "part_of", "influences", "depends_on"]:
            result = validate_edge("concept", "concept", relation)
            assert result.valid

    def test_valid_edge_lever_outcome(self):
        for relation in ["raises", "lowers", "stabilizes", "optimizes"]:
            result = validate_edge("lever", "outcome", relation)
            assert result.valid

    def test_valid_edge_policy_subject(self):
        for relation in ["permits", "denies", "requires_approval"]:
            result = validate_edge("policy", "subject", relation)
            assert result.valid

    def test_invalid_relation_for_valid_space_pair(self):
        result = validate_edge("subject", "resource", "mentions")
        assert result.valid is False
        assert "mentions" in result.error

    def test_no_meta_edge_between_spaces(self):
        result = validate_edge("outcome", "subject", "owns")
        assert result.valid is False

    def test_invalid_from_space(self):
        result = validate_edge("badspace", "resource", "owns")
        assert result.valid is False

    def test_invalid_to_space(self):
        result = validate_edge("subject", "badspace", "owns")
        assert result.valid is False


class TestGetAllowedRelations:
    def test_subject_resource_relations(self):
        relations = get_allowed_relations("subject", "resource")
        assert "owns" in relations
        assert "can_view" in relations
        assert "can_edit" in relations
        assert isinstance(relations, list)
        assert relations == sorted(relations)

    def test_no_edge_returns_empty(self):
        relations = get_allowed_relations("outcome", "subject")
        assert relations == []

    def test_concept_concept_relations(self):
        relations = get_allowed_relations("concept", "concept")
        assert "related_to" in relations
        assert "subclass_of" in relations


class TestValidateMetadataLayer:
    def test_valid_layer_attribute(self):
        result = validate_metadata_layer("existence", "identity")
        assert result.valid

    def test_valid_quality_confidence(self):
        result = validate_metadata_layer("quality", "confidence")
        assert result.valid

    def test_invalid_layer(self):
        result = validate_metadata_layer("badlayer", "identity")
        assert not result.valid

    def test_invalid_attribute_in_valid_layer(self):
        result = validate_metadata_layer("existence", "confidence")
        assert not result.valid


class TestValidateReBACPermission:
    def test_all_valid_permissions(self):
        for perm in REBAC_PERMISSIONS:
            result = validate_rebac_permission(perm)
            assert result.valid, f"Expected '{perm}' to be valid"

    def test_invalid_permission(self):
        result = validate_rebac_permission("delete")
        assert not result.valid
        assert "delete" in result.error


class TestDescribeGrammar:
    def test_describe_grammar_has_all_keys(self):
        grammar = describe_grammar()
        assert "spaces" in grammar
        assert "meta_edges" in grammar
        assert "impact_categories" in grammar
        assert "active_metadata_layers" in grammar
        assert "rebac" in grammar

    def test_rebac_has_expected_structure(self):
        grammar = describe_grammar()
        rebac = grammar["rebac"]
        assert "object_types" in rebac
        assert "permissions" in rebac


# ---------------------------------------------------------------------------
# Glossary tests
# ---------------------------------------------------------------------------


class TestGlossary:
    def test_all_spaces_in_glossary(self):
        for space_id in SPACES:
            assert space_id in SPACE_GLOSSARY, f"Space '{space_id}' missing from glossary"

    def test_some_relations_in_glossary(self):
        for rel in ["owns", "supports", "raises", "permits", "clusters"]:
            assert rel in RELATION_GLOSSARY, f"Relation '{rel}' missing from glossary"

    def test_all_impact_ids_in_glossary(self):
        for cat in IMPACT_CATEGORIES:
            assert cat["id"] in IMPACT_GLOSSARY

    def test_lookup_term_finds_space(self):
        defn = lookup_term("subject")
        assert defn is not None
        assert "actor" in defn.lower() or "subject" in defn.lower()

    def test_lookup_term_finds_relation(self):
        defn = lookup_term("owns")
        assert defn is not None
        assert "ownership" in defn.lower() or "own" in defn.lower()

    def test_lookup_term_returns_none_for_unknown(self):
        defn = lookup_term("nonexistent_term_xyz")
        assert defn is None

    def test_full_glossary_structure(self):
        glossary = full_glossary()
        assert "spaces" in glossary
        assert "relations" in glossary
        assert "impact_categories" in glossary
        assert "metadata_layers" in glossary
