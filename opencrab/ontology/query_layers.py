# Query layer file persistence module

import os
import json
import tempfile
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
    with open(index_path, encoding="utf-8") as f:
        return json.load(f)

def write_layer(store_dir: str, layer: Dict[str, Any]) -> None:
    # Write the layer file
    layer_id = layer["id"]
    layer_path = os.path.join(store_dir, f"{layer_id}.json")
    with open(layer_path, "w", encoding="utf-8") as f:
        json.dump(layer, f)
    # Update the index atomically via write-to-temp-then-replace
    # Use lock to prevent race conditions on Windows where os.replace can fail
    # if the target file is open by another thread
    with _index_lock:
        index_path = os.path.join(store_dir, "layers-index.json")
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
        # Ensure enabled is always present in index metadata
        meta = {k: layer[k] for k in ["id", "query", "timestamp", "source", "node_count", "edge_count"] if k in layer}
        meta["enabled"] = layer.get("enabled", True)
        # Prepend to layers
        index["layers"] = [meta] + [l for l in index["layers"] if l.get("id") != layer_id]
        # Write to temp file in same directory, then replace atomically
        fd, temp_path = tempfile.mkstemp(dir=store_dir, suffix=".json", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(index, f)
            # os.replace is atomic on both Windows and POSIX
            os.replace(temp_path, index_path)
        except:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise
