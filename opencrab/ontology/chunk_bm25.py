"""
BM25 keyword search over ingested document chunks.

The node BM25 index (:mod:`opencrab.ontology.bm25`) covers graph nodes only,
so documents added with ``ingest`` were reachable through vector search alone.
With ``OPENCRAB_CHUNKING=1`` this index covers the chunk records written by
chunked ingest (records whose metadata has ``chunk_index``), using the same
tokenizer, including its Korean 2/3-gram expansion. Only the stored chunk text
is indexed, not the chunk id (a file path).

The index is cached. It is rebuilt after a chunked ingest in this process, or
when the vector store's record count changes (ingest from another process).
At most ``OPENCRAB_CHUNK_BM25_LIMIT`` chunks (default 10000) are indexed.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from opencrab.ontology.bm25 import BM25Index

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 10000


def chunk_bm25_limit() -> int:
    raw = os.getenv("OPENCRAB_CHUNK_BM25_LIMIT", "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_LIMIT
    except ValueError:
        value = 0
    if value <= 0:
        logger.warning("Invalid OPENCRAB_CHUNK_BM25_LIMIT=%r; using %d", raw, _DEFAULT_LIMIT)
        return _DEFAULT_LIMIT
    return value


@dataclass(frozen=True)
class _Snapshot:
    """An index and the records it was built from, swapped as one unit."""

    index: BM25Index
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    count: int = -1


class ChunkBM25:
    """Cached BM25 index over chunk records in a vector store."""

    def __init__(self, chroma: Any, limit: int | None = None) -> None:
        self._chroma = chroma
        self._limit = limit
        self._snapshot: _Snapshot | None = None
        self._generation = 0
        self._state_lock = threading.Lock()  # guards _generation and _snapshot together
        self._build_lock = threading.Lock()  # one rebuild at a time

    def invalidate(self) -> None:
        """Force a rebuild on the next search, discarding any rebuild in progress."""
        with self._state_lock:
            self._generation += 1
            self._snapshot = None

    def search(self, question: str, spaces: list[str] | None, limit: int) -> list[dict[str, Any]]:
        """Return chunk hits as result dicts (source, node_id, score, text, metadata)."""
        if not self._chroma.available:
            return []
        try:
            snapshot = self._current_snapshot()
            hits = snapshot.index.search(question, spaces=spaces, limit=limit)
            return [_to_result(hit, snapshot.records[hit["node_id"]]) for hit in hits]
        except Exception as exc:
            logger.warning("Chunk BM25 search error: %s", exc, exc_info=True)
            return []

    def _current_snapshot(self) -> _Snapshot:
        count = self._chroma.count()
        snapshot = self._snapshot
        if snapshot is not None and snapshot.count == count:
            return snapshot
        with self._build_lock:  # waiters reuse the result of the rebuild they waited for
            with self._state_lock:
                snapshot = self._snapshot
                generation = self._generation
            if snapshot is not None and snapshot.count == count:
                return snapshot
            snapshot = self._build(count)
            # An invalidate() during the build means the records read may be outdated:
            # serve them to this query only, and rebuild on the next one.
            with self._state_lock:
                if generation == self._generation:
                    self._snapshot = snapshot
            return snapshot

    def _build(self, count: int) -> _Snapshot:
        limit = self._limit or chunk_bm25_limit()
        records = self._chroma.list_where({"chunk_index": {"$gte": 0}}, limit=limit + 1)
        if len(records) > limit:
            records = records[:limit]
            logger.warning(
                "Chunk BM25 indexes only the first %d chunks; raise OPENCRAB_CHUNK_BM25_LIMIT to cover more",
                limit,
            )
        index = BM25Index.build(
            [_as_node(r) for r in records],
            texts=[r.get("document") or "" for r in records],
        )
        logger.debug("Chunk BM25 index rebuilt (%d chunks)", len(records))
        return _Snapshot(index=index, records={r["id"]: r for r in records}, count=count)


def _as_node(record: dict[str, Any]) -> dict[str, Any]:
    meta = record.get("metadata") or {}
    return {"node_id": record["id"], "space": meta.get("space"), "node_type": "Chunk"}


def _to_result(hit: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "bm25",
        "node_id": hit["node_id"],
        "score": hit["score"],
        "text": record.get("document") or "",
        "metadata": dict(record.get("metadata") or {}),
    }
