"""
Type Schema Registry loader.

Loads YAML type schemas from opencrab/schemas/types/ and caches them.
If a node type has no registered schema file, load_type_schema() returns None
and validation is skipped (schema-optional pattern).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SCHEMAS_DIR = Path(__file__).parent / "types"


@lru_cache(maxsize=None)
def load_type_schema(node_type: str) -> dict[str, Any] | None:
    """
    Load the YAML schema for *node_type* from schemas/types/<node_type>.yaml.

    Returns None if no schema file exists for that type.
    The result is cached after the first load.
    """
    path = SCHEMAS_DIR / f"{node_type}.yaml"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_registered_types() -> list[str]:
    """Return a list of all node types that have a registered YAML schema."""
    if not SCHEMAS_DIR.exists():
        return []
    return sorted(p.stem for p in SCHEMAS_DIR.glob("*.yaml"))


def reload_schema(node_type: str) -> dict[str, Any] | None:
    """Clear the cache for *node_type* and reload from disk."""
    load_type_schema.cache_clear()
    return load_type_schema(node_type)
