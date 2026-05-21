import os
import json
import pytest
import threading
from opencrab.ontology import query_layers


def test_ensure_layer_store_creates_dir_and_index(tmp_path):
    store_dir = tmp_path / "store"
    query_layers.ensure_layer_store(str(store_dir))
    assert store_dir.exists()
    index_path = store_dir / "layers-index.json"
    assert index_path.exists()
    with open(index_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"layers": [], "version": "1.0"}


def test_read_index_returns_index(tmp_path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    index_path = store_dir / "layers-index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"layers": [1, 2], "version": "1.0"}, f)
    result = query_layers.read_index(str(store_dir))
    assert result == {"layers": [1, 2], "version": "1.0"}

def test_write_layer_enabled_defaults_true(tmp_path):
    store_dir = tmp_path / "store"
    query_layers.ensure_layer_store(str(store_dir))
    layer = {
        "id": "def456",
        "query": "MATCH (m)",
        "timestamp": "2024-01-02T00:00:00Z",
        "source": "test2",
        "node_count": 3,
        "edge_count": 1
        # no 'enabled' field
    }
    query_layers.write_layer(str(store_dir), layer)
    # Index
    index_path = store_dir / "layers-index.json"
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    meta = index["layers"][0]
    assert meta["id"] == "def456"
    assert meta["enabled"] is True

def test_write_layer_persists_layer_and_updates_index(tmp_path):
    store_dir = tmp_path / "store"
    query_layers.ensure_layer_store(str(store_dir))
    layer = {
        "id": "abc123",
        "query": "MATCH (n)",
        "timestamp": "2024-01-01T00:00:00Z",
        "source": "test",
        "node_count": 5,
        "edge_count": 2,
        "enabled": True,
        "extra": "should be persisted"
    }
    query_layers.write_layer(str(store_dir), layer)
    # Layer file
    layer_path = store_dir / "abc123.json"
    assert layer_path.exists()
    with open(layer_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == layer
    # Index
    index_path = store_dir / "layers-index.json"
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    assert index["version"] == "1.0"
    meta = index["layers"][0]
    assert meta["id"] == "abc123"
    assert meta["query"] == "MATCH (n)"
    assert meta["timestamp"] == "2024-01-01T00:00:00Z"
    assert meta["source"] == "test"
    assert meta["node_count"] == 5
    assert meta["edge_count"] == 2
    assert meta["enabled"] is True
    # Extra fields should NOT be in index metadata
    assert "extra" not in meta


def test_ensure_layer_store_concurrent_creation(tmp_path):
    """Test that concurrent calls to ensure_layer_store don't cause errors"""
    store_dir = tmp_path / "store"
    errors = []
    
    def create_store():
        try:
            query_layers.ensure_layer_store(str(store_dir))
        except Exception as e:
            errors.append(e)
    
    # Create multiple threads that try to initialize concurrently
    threads = [threading.Thread(target=create_store) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # No errors should have occurred
    assert errors == []
    # Index should exist and be valid
    index_path = store_dir / "layers-index.json"
    assert index_path.exists()
    with open(index_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"layers": [], "version": "1.0"}


def test_write_layer_concurrent_writes(tmp_path):
    """Test that concurrent writes maintain index consistency"""
    store_dir = tmp_path / "store"
    query_layers.ensure_layer_store(str(store_dir))
    
    def write_test_layer(layer_id):
        layer = {
            "id": layer_id,
            "query": f"MATCH (n:{layer_id})",
            "timestamp": "2024-01-01T00:00:00Z",
            "source": "test",
            "node_count": 1,
            "edge_count": 0,
            "enabled": True
        }
        query_layers.write_layer(str(store_dir), layer)
    
    # Write multiple layers concurrently
    layer_ids = [f"layer{i}" for i in range(10)]
    threads = [threading.Thread(target=write_test_layer, args=(lid,)) for lid in layer_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Read final index - it should be valid JSON and contain all layers
    index = query_layers.read_index(str(store_dir))
    assert index["version"] == "1.0"
    assert len(index["layers"]) == 10
    # All layer IDs should be present
    index_ids = {layer["id"] for layer in index["layers"]}
    assert index_ids == set(layer_ids)
