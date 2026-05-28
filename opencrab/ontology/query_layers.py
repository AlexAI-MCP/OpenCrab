# Query layer file persistence module

import os
import json
import threading
from typing import Any, Dict

# Global lock for index updates
_index_lock = threading.Lock()

def ensure_layer_store(store_dir: str) -> None:
    os.makedirs(store_dir, exist_ok=True)
    index_path = os.path.join(store_dir, "layers-index.json")
    # Atomic file creation: use 'x' mode to fail if file exists
    try:
        with open(index_path, "x", encoding="utf-8") as f:
            json.dump({"layers": [], "version": "1.0"}, f)
    except FileExistsError:
        # Index already exists, no action needed
        pass

def read_index(store_dir: str) -> Dict[str, Any]:
    index_path = os.path.join(store_dir, "layers-index.json")
    with _index_lock:
        with open(index_path, encoding="utf-8") as f:
            return json.load(f)

def write_layer(store_dir: str, layer: Dict[str, Any]) -> None:
    # Synchronize both layer file write and index update in the same lock critical section
    with _index_lock:
        layer_id = layer["id"]
        layer_path = os.path.join(store_dir, f"{layer_id}.json")
        with open(layer_path, "w", encoding="utf-8") as f:
            json.dump(layer, f)
        index_path = os.path.join(store_dir, "layers-index.json")
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
        # Ensure enabled is always present in index metadata
        meta = {k: layer[k] for k in ["id", "query", "timestamp", "source", "node_count", "edge_count"] if k in layer}
        meta["enabled"] = layer.get("enabled", True)
        # Prepend to layers
        index["layers"] = [meta] + [l for l in index["layers"] if l.get("id") != layer_id]
        # Lock serializes read/write in-process, so direct overwrite is sufficient here.
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f)
