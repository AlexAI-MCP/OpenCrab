from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SEEN_INDEX_FILE = ".seen.json"


def _get_seen_index_path(workspace_dir: Path) -> Path:
    """Get path to seen-index file."""
    return workspace_dir / SEEN_INDEX_FILE


def _compute_id(source: str, key: str) -> str:
    """Compute unique ID from source + key using SHA256 hash (first 16 chars)."""
    text = f"{source}|{key}"
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def is_seen(workspace_dir: Path, source: str, key: str) -> bool:
    """Check if an item has been seen before."""
    index_path = _get_seen_index_path(workspace_dir)
    if not index_path.exists():
        return False

    index = json.loads(index_path.read_text(encoding="utf-8"))
    item_id = _compute_id(source, key)
    return item_id in index


def mark_seen(
    workspace_dir: Path,
    source: str,
    key: str,
    title: str = "",
    url: str = "",
    status: str = "seen",
) -> None:
    """Mark an item as seen in the index."""
    index_path = _get_seen_index_path(workspace_dir)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {}

    item_id = _compute_id(source, key)
    now = datetime.utcnow().isoformat() + "Z"

    if item_id in index:
        # Update existing entry
        index[item_id]["last_seen"] = now
        index[item_id]["times_seen"] = index[item_id].get("times_seen", 1) + 1
        index[item_id]["status"] = status
    else:
        # Create new entry
        index[item_id] = {
            "source": source,
            "key": key,
            "title": title,
            "url": url,
            "first_seen": now,
            "last_seen": now,
            "times_seen": 1,
            "status": status,
        }

    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_applied(
    workspace_dir: Path,
    source: str,
    key: str,
    score: float = 0.0,
    content_hash: str = "",
) -> None:
    """Mark an item as applied."""
    index_path = _get_seen_index_path(workspace_dir)
    if not index_path.exists():
        mark_seen(workspace_dir, source, key, status="applied")
        return

    index = json.loads(index_path.read_text(encoding="utf-8"))
    item_id = _compute_id(source, key)

    if item_id in index:
        now = datetime.utcnow().isoformat() + "Z"
        index[item_id]["status"] = "applied"
        index[item_id]["applied_at"] = now
        index[item_id]["final_score"] = score
        if content_hash:
            index[item_id]["applied_rule_hash"] = content_hash

    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def get_seen_stats(workspace_dir: Path) -> dict[str, Any]:
    """Get statistics about seen items."""
    index_path = _get_seen_index_path(workspace_dir)
    if not index_path.exists():
        return {
            "total": 0,
            "seen": 0,
            "applied": 0,
            "rejected": 0,
        }

    index = json.loads(index_path.read_text(encoding="utf-8"))
    stats = {"total": len(index), "seen": 0, "applied": 0, "rejected": 0}

    for item in index.values():
        status = item.get("status", "seen")
        if status == "applied":
            stats["applied"] += 1
        elif status == "rejected":
            stats["rejected"] += 1
        else:
            stats["seen"] += 1

    return stats
