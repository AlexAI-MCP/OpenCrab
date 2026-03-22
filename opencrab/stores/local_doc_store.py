"""
Local document store — JSON-file-backed store for local (no-Docker) mode.

Implements the same interface as MongoStore so consumers are agnostic
of the backend. Each "collection" is a single JSON file on disk.
Thread-safety is handled by a simple file lock via a threading.Lock.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class LocalDocStore:
    """JSON-file document store with the same interface as MongoStore."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._available = True
        self._lock = threading.Lock()
        logger.info("LocalDocStore initialised at %s", data_dir)

    @property
    def available(self) -> bool:
        return self._available

    def ping(self) -> bool:
        return os.path.isdir(self._data_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collection_path(self, name: str) -> str:
        return os.path.join(self._data_dir, f"{name}.json")

    def _load(self, collection: str) -> dict[str, Any]:
        path = self._collection_path(collection)
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, collection: str, data: dict[str, Any]) -> None:
        path = self._collection_path(collection)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    # ------------------------------------------------------------------
    # Node document operations (mirrors MongoStore)
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        space: str,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
    ) -> None:
        with self._lock:
            data = self._load("nodes")
            key = f"{space}::{node_id}"
            data[key] = {
                "space": space,
                "node_type": node_type,
                "node_id": node_id,
                "properties": properties,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self._save("nodes", data)

    def get_node(self, space: str, node_id: str) -> dict[str, Any] | None:
        data = self._load("nodes")
        return data.get(f"{space}::{node_id}")

    def list_nodes(self, space: str | None = None) -> list[dict[str, Any]]:
        data = self._load("nodes")
        rows = list(data.values())
        if space:
            rows = [r for r in rows if r.get("space") == space]
        return rows

    # ------------------------------------------------------------------
    # Source ingestion (mirrors MongoStore)
    # ------------------------------------------------------------------

    def upsert_source(
        self, source_id: str, text: str, metadata: dict[str, Any]
    ) -> None:
        with self._lock:
            data = self._load("sources")
            data[source_id] = {
                "source_id": source_id,
                "text": text[:4096],  # truncate for storage
                "metadata": metadata,
                "ingested_at": datetime.now(UTC).isoformat(),
            }
            self._save("sources", data)

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return self._load("sources").get(source_id)

    def list_sources(self) -> list[dict[str, Any]]:
        return list(self._load("sources").values())

    # ------------------------------------------------------------------
    # Audit log (mirrors MongoStore)
    # ------------------------------------------------------------------

    def log_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        actor: str = "system",
    ) -> None:
        with self._lock:
            data = self._load("audit_log")
            ts = datetime.now(UTC).isoformat()
            entry_id = f"{event_type}::{ts}"
            data[entry_id] = {
                "event_type": event_type,
                "actor": actor,
                "payload": payload,
                "timestamp": ts,
            }
            self._save("audit_log", data)

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        data = self._load("audit_log")
        entries = sorted(data.values(), key=lambda e: e["timestamp"], reverse=True)
        return entries[:limit]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "nodes": len(self._load("nodes")),
            "sources": len(self._load("sources")),
            "audit_events": len(self._load("audit_log")),
            "data_dir": self._data_dir,
        }
