import pytest
import time
from opencrab.ontology import query_visualization

class DummyGraph:
    def __init__(self, neighbors):
        self.neighbors = neighbors
    def find_neighbors(self, node_id, depth, limit):
        # Returns a list of (from_id, to_id, relation, path_rank)
        return self.neighbors.get(node_id, [])[:limit]

def test_build_layer_payload_basic():
    question = "What is the capital of France?"
    query_results = [
        {"id": "paris", "label": "Paris"},
        {"id": "france", "label": "France"}
    ]
    neighbors = {
        "paris": [("paris", "france", "capital_of", 1)],
        "france": [("france", "paris", "has_capital", 1)]
    }
    graph = DummyGraph(neighbors)
    max_hops = 1
    limit = 2
    payload = query_visualization.build_layer_payload(question, query_results, graph, max_hops, limit)
    assert payload["id"]
    assert payload["query"] == question
    assert payload["source"] == "cli"
    assert isinstance(payload["timestamp"], float)
    assert len(payload["nodes"]) == 2
    assert len(payload["edges"]) == 2
    assert payload["metadata"]["total_nodes"] == 2
    assert payload["metadata"]["total_edges"] == 2
    assert payload["metadata"]["max_hops"] == 1
    assert "query_time_ms" in payload["metadata"]
    for node in payload["nodes"]:
        assert node["highlight"] is True
        assert node["hop_distance"] == 0
    for edge in payload["edges"]:
        assert set(edge.keys()) == {"relation", "from_id", "to_id", "path_rank"}

def test_build_layer_payload_deduplication():
    question = "Test deduplication"
    query_results = [
        {"id": "a", "label": "A"},
        {"id": "b", "label": "B"}
    ]
    neighbors = {
        "a": [("a", "b", "rel", 1), ("a", "b", "rel", 1)],
        "b": [("b", "a", "rel", 1)]
    }
    graph = DummyGraph(neighbors)
    payload = query_visualization.build_layer_payload(question, query_results, graph, 1, 10)
    node_ids = [n["id"] for n in payload["nodes"]]
    assert len(node_ids) == len(set(node_ids))
    edge_tuples = [(e["from_id"], e["to_id"], e["relation"]) for e in payload["edges"]]
    assert len(edge_tuples) == len(set(edge_tuples))
