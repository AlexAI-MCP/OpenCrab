# Query layer file persistence module

import os
import json
import threading
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Dict

# Global lock for index updates
_index_lock = threading.Lock()


@contextmanager
def _index_file_lock(store_dir: str):
    """Cross-process lock using a lockfile."""
    lock_path = os.path.join(store_dir, ".layers-index.lock")
    lock_fd = None
    deadline = time.time() + 5.0
    while True:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.time() > deadline:
                raise TimeoutError(f"Timeout acquiring index lock: {lock_path}")
            time.sleep(0.01)

    try:
        yield
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass

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
        with _index_file_lock(store_dir):
            with open(index_path, encoding="utf-8") as f:
                return json.load(f)

def write_layer(store_dir: str, layer: Dict[str, Any]) -> None:
    # Synchronize both layer file write and index update in the same lock critical section
    with _index_lock:
        with _index_file_lock(store_dir):
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

            fd, temp_path = tempfile.mkstemp(dir=store_dir, suffix=".json", text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(index, f)
                os.replace(temp_path, index_path)
            except Exception:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
                raise
