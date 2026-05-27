"""Tests for query visualization layer builder."""

from __future__ import annotations

import pytest
from opencrab.ontology import query_visualization


class DummyGraph:
    """Mock graph store that returns dict-based neighbor records."""

    def __init__(self, neighbors: dict[str, list[dict]]) -> None:
        self.neighbors = neighbors
        self.last_direction: str | None = None
        self.last_depth: int | None = None

    def find_neighbors(
        self, node_id: str, direction: str = "both", depth: int = 1, limit: int = 50
    ) -> list[dict]:
        """
        Returns neighbor records as dicts matching LocalGraphStore/Neo4jStore format.
        Each record has: properties, labels, relation_type, depth
        """
        self.last_direction = direction
        self.last_depth = depth
        return self.neighbors.get(node_id, [])[:limit]


def test_build_layer_payload_includes_seed_and_neighbors() -> None:
    """Verify seed nodes and neighbors are included with correct fields."""
    question = "What is the capital of France?"
    query_results = [
        {
            "node_id": "paris",
            "space": "geography",
            "node_type": "City",
            "properties": {"name": "Paris", "population": 2161000},
            "score": 0.95,
        },
        {
            "node_id": "france",
            "space": "geography",
            "node_type": "Country",
            "properties": {"name": "France"},
            "score": 0.90,
        },
    ]

    neighbors = {
        "paris": [
            {
                "properties": {"id": "eiffel-tower", "name": "Eiffel Tower"},
                "labels": ["Landmark"],
                "relation_type": "has_landmark",
                "depth": 1,
            }
        ],
        "france": [
            {
                "properties": {"id": "paris", "name": "Paris"},
                "labels": ["City"],
                "relation_type": "has_capital",
                "depth": 1,
            }
        ],
    }

    graph = DummyGraph(neighbors)
    payload = query_visualization.build_layer_payload(
        question, query_results, graph, max_hops=2, limit=10
    )

    # Verify basic payload structure
    assert payload["id"].startswith("layer-")
    assert payload["query"] == question
    assert payload["source"] == "cli"
    assert isinstance(payload["timestamp"], str)  # ISO string, not float
    assert "T" in payload["timestamp"] or " " in payload["timestamp"]  # ISO format

    # Verify direction='both' and depth parameter were used
    assert graph.last_direction == "both"
    assert graph.last_depth == 2

    # Verify seed nodes have required fields
    node_dict = {n["id"]: n for n in payload["nodes"]}
    assert "paris" in node_dict
    assert "france" in node_dict

    paris = node_dict["paris"]
    assert paris["highlight"] is True
    assert paris["hop_distance"] == 0
    assert paris["space"] == "geography"
    assert paris["node_type"] == "City"
    assert paris["properties"]["name"] == "Paris"
    assert paris["score"] == 0.95

    # Verify neighbor node
    assert "eiffel-tower" in node_dict
    eiffel = node_dict["eiffel-tower"]
    assert eiffel["highlight"] is False
    assert eiffel["hop_distance"] == 1
    assert eiffel["node_type"] == "Landmark"

    # Verify edges have required fields
    assert len(payload["edges"]) > 0
    for edge in payload["edges"]:
        required_fields = {
            "from_id",
            "to_id",
            "relation",
            "from_space",
            "to_space",
            "path_rank",
        }
        assert required_fields.issubset(edge.keys())

    # Verify top-level node_count and edge_count
    assert payload["node_count"] == len(payload["nodes"])
    assert payload["edge_count"] == len(payload["edges"])
    # Verify metadata
    assert payload["metadata"]["total_nodes"] == len(payload["nodes"])
    assert payload["metadata"]["total_edges"] == len(payload["edges"])
    assert payload["metadata"]["max_hops"] == 2
    assert payload["metadata"]["query_time_ms"] >= 0


def test_build_layer_payload_deduplicates_nodes() -> None:
    """Verify nodes are deduplicated by ID."""
    question = "Test deduplication"
    query_results = [
        {
            "node_id": "a",
            "space": "test",
            "node_type": "Node",
            "properties": {"label": "A"},
            "score": 1.0,
        },
        {
            "node_id": "b",
            "space": "test",
            "node_type": "Node",
            "properties": {"label": "B"},
            "score": 0.8,
        },
    ]

    neighbors = {
        "a": [
            {
                "properties": {"id": "b", "label": "B"},
                "labels": ["Node"],
                "relation_type": "relates_to",
                "depth": 1,
            }
        ],
        "b": [
            {
                "properties": {"id": "a", "label": "A"},
                "labels": ["Node"],
                "relation_type": "relates_to",
                "depth": 1,
            }
        ],
    }

    graph = DummyGraph(neighbors)
    payload = query_visualization.build_layer_payload(question, query_results, graph, 1, 10)

    # Should only have 2 unique nodes (a and b), not 4
    node_ids = [n["id"] for n in payload["nodes"]]
    assert len(node_ids) == 2
    assert len(set(node_ids)) == 2
    assert set(node_ids) == {"a", "b"}

    # Verify seed nodes keep highlight=True
    node_dict = {n["id"]: n for n in payload["nodes"]}
    assert node_dict["a"]["highlight"] is True
    assert node_dict["b"]["highlight"] is True


def test_build_layer_payload_uses_direction_both_and_depth() -> None:
    """Verify graph.find_neighbors is called with direction='both' and correct depth."""
    question = "Multi-hop test"
    query_results = [
        {
            "node_id": "start",
            "space": "test",
            "node_type": "Node",
            "properties": {"label": "Start"},
            "score": 1.0,
        }
    ]

    neighbors = {
        "start": [
            {
                "properties": {"id": "hop1", "label": "Hop 1"},
                "labels": ["Node"],
                "relation_type": "rel1",
                "depth": 1,
            },
            {
                "properties": {"id": "hop2", "label": "Hop 2"},
                "labels": ["Node"],
                "relation_type": "rel2",
                "depth": 2,
            },
            {
                "properties": {"id": "hop3", "label": "Hop 3"},
                "labels": ["Node"],
                "relation_type": "rel3",
                "depth": 3,
            },
        ]
    }

    graph = DummyGraph(neighbors)
    payload = query_visualization.build_layer_payload(question, query_results, graph, 3, 10)

    # Verify find_neighbors was called with correct parameters
    assert graph.last_direction == "both"
    assert graph.last_depth == 3

    # Verify hop_distance is set from neighbor depth field
    node_dict = {n["id"]: n for n in payload["nodes"]}
    assert node_dict["start"]["hop_distance"] == 0
    assert node_dict["hop1"]["hop_distance"] == 1
    assert node_dict["hop2"]["hop_distance"] == 2
    assert node_dict["hop3"]["hop_distance"] == 3


def test_query_viz_cli_command(monkeypatch, tmp_path) -> None:
    """Test that query-viz CLI command exists and runs with mocked dependencies."""
    from click.testing import CliRunner
    from opencrab.cli import main
    from opencrab.ontology.query import QueryResult

    # Mock the factories and stores
    class MockVectorStore:
        available = True

    class MockGraphStore:
        available = True
        
        def find_neighbors(self, node_id: str, direction: str = "both", depth: int = 1, limit: int = 50) -> list[dict]:
            return []

    class MockHybridQuery:
        def __init__(self, chroma, graph):
            pass
        
        def query(self, question: str, limit: int = 10, **kwargs) -> list[QueryResult]:
            # Return mock results, including one with node_id=None
            return [
                QueryResult(
                    source="vector",
                    node_id=None,
                    score=0.5,
                    text="Should be skipped",
                    metadata={"space": "test", "node_type": "TestNode", "name": "Test None"},
                ),
                QueryResult(
                    source="vector",
                    node_id="test-node-1",
                    score=0.95,
                    text="Test result",
                    metadata={"space": "test", "node_type": "TestNode", "name": "Test 1"},
                )
            ]

    # Patch the factory functions and classes
    import opencrab.stores.factory
    import opencrab.ontology.query
    
    monkeypatch.setattr(opencrab.stores.factory, "make_vector_store", lambda cfg: MockVectorStore())
    monkeypatch.setattr(opencrab.stores.factory, "make_graph_store", lambda cfg: MockGraphStore())
    monkeypatch.setattr(opencrab.ontology.query, "HybridQuery", MockHybridQuery)

    # Run the CLI command
    runner = CliRunner()
    output_dir = str(tmp_path / "layers")
    result = runner.invoke(main, ["query-viz", "test question", "--output-dir", output_dir])

    # Check that the command ran successfully
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "Layer saved" in result.output
    assert "layer-" in result.output

    # Verify layer file was created
    import json
    from pathlib import Path
    
    layer_dir = Path(output_dir)
    assert layer_dir.exists()
    
    # Check that index was created
    index_file = layer_dir / "layers-index.json"
    assert index_file.exists()
    
    index_data = json.loads(index_file.read_text())
    assert "layers" in index_data
    assert len(index_data["layers"]) == 1
    
    # Check that layer file was created
    layer_files = list(layer_dir.glob("layer-*.json"))
    assert len(layer_files) == 1
    
    layer_data = json.loads(layer_files[0].read_text())
    assert layer_data["query"] == "test question"
    assert layer_data["source"] == "cli"
    assert "nodes" in layer_data
    assert "edges" in layer_data
    # Ensure only the valid node_id is present
    node_ids = [n["id"] for n in layer_data["nodes"]]
    assert "test-node-1" in node_ids
    assert None not in node_ids
