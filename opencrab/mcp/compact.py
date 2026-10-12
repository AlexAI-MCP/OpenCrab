"""
Smaller MCP tool results for language-model clients.

With ``OPENCRAB_COMPACT_RESULTS=1`` the text a tool returns to the model is
cut down without dropping anything the model needs:

  1. Non-ASCII text (Korean, CJK) is sent as characters instead of ``\\uXXXX``
     escapes, which made Korean results about 2.4x longer. Surrogate code
     points, the reason escapes were used, are joined when they form a pair
     and replaced with U+FFFD when they do not.
  2. ``ontology_query`` results that are chunk records (``node_id`` is
     ``{source_id}#{chunk_index}``) drop metadata the result already carries:
     ``source_id`` and ``node_id`` (in the result's ``node_id``), ``doc_title``
     and ``heading_path`` when the text really opens with that chunk header,
     ``source_path`` when it equals the source id, and parser bookkeeping.
     Other metadata, including anything the caller attached at ingest, is
     kept. Scores are rounded and empty graph context omitted.

Unset, results are encoded exactly as before.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from opencrab.ontology.chunking import chunk_header

_TRUTHY = {"1", "true", "yes", "on"}
_SURROGATE = re.compile(f"[{chr(0xD800)}-{chr(0xDFFF)}]")
# Always repeated in a chunk record (its node_id) or parser bookkeeping.
_CHUNK_METADATA_DROPPED = frozenset(
    {
        "source_id",
        "node_id",
        "extension",
        "parser",
        "kordoc_major_version",
        "kordoc_page_quality",
        "kordoc_quality_summary",
    }
)


def compact_enabled() -> bool:
    return os.getenv("OPENCRAB_COMPACT_RESULTS", "").strip().lower() in _TRUTHY


def encode_tool_result(name: str, result: Any) -> str:
    """Serialize a tool result into the text handed to the MCP client."""
    if not compact_enabled():
        return json.dumps(result, ensure_ascii=True, default=str)
    if name == "ontology_query" and isinstance(result, dict):
        result = _compact_query(result)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    return _valid_unicode(text) if _SURROGATE.search(text) else text


def _valid_unicode(text: str) -> str:
    """Join surrogate pairs into their characters; replace unpaired ones with U+FFFD."""
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _compact_query(result: dict[str, Any]) -> dict[str, Any]:
    items = result.get("results")
    if not isinstance(items, list):
        return result
    return {**result, "results": [_compact_item(item) for item in items]}


def _compact_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    metadata = item.get("metadata")
    if not isinstance(metadata, dict) or not _is_chunk_record(item, metadata):
        return item
    compact = {k: v for k, v in item.items() if k not in ("metadata", "graph_context")}
    repeated = _repeated_keys(item, metadata)
    compact["metadata"] = {k: v for k, v in metadata.items() if k not in repeated}
    if item.get("graph_context"):
        compact["graph_context"] = item["graph_context"]
    if isinstance(item.get("score"), float):
        compact["score"] = round(item["score"], 4)
    return compact


def _repeated_keys(item: dict[str, Any], metadata: dict[str, Any]) -> set[str]:
    """Metadata keys whose values the result states elsewhere, checked rather than assumed."""
    keys = set(_CHUNK_METADATA_DROPPED)
    if metadata.get("source_path") == metadata.get("source_id"):
        keys.add("source_path")
    title, heading = metadata.get("doc_title"), metadata.get("heading_path", "")
    if isinstance(title, str) and isinstance(heading, str):
        header = chunk_header(title, tuple(heading.split(" > ")) if heading else ())
        if str(item.get("text") or "").startswith(header + "\n\n"):
            keys |= {"doc_title", "heading_path"}
    return keys


def _is_chunk_record(item: dict[str, Any], metadata: dict[str, Any]) -> bool:
    if "chunk_index" not in metadata or "source_id" not in metadata:
        return False
    return bool(item.get("node_id") == f"{metadata['source_id']}#{metadata['chunk_index']}")
