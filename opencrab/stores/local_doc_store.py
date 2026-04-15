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
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Corrupt %s.json, resetting: %s", collection, exc)
            return {}

    def _save(self, collection: str, data: dict[str, Any]) -> None:
        """Atomic write: serialize to tmp file then rename to avoid corruption."""
        path = self._collection_path(collection)
        tmp_path = path + ".tmp"
        try:
            serialized = json.dumps(data, ensure_ascii=True, indent=2, default=str)
        except (TypeError, ValueError) as exc:
            logger.error("JSON serialization failed for %s: %s", collection, exc)
            raise
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(serialized)
        os.replace(tmp_path, path)

    # ------------------------------------------------------------------
    # Node document operations (mirrors MongoStore)
    # ------------------------------------------------------------------

    def upsert_node_doc(
        self,
        space: str,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
    ) -> str:
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
            return key

    def get_node_doc(self, space: str, node_id: str) -> dict[str, Any] | None:
        data = self._load("nodes")
        return data.get(f"{space}::{node_id}")

    def list_nodes(self, space: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        data = self._load("nodes")
        rows = list(data.values())
        if space:
            rows = [r for r in rows if r.get("space") == space]
        return rows[:limit]

    def delete_node_doc(self, space: str, node_id: str) -> bool:
        with self._lock:
            data = self._load("nodes")
            key = f"{space}::{node_id}"
            if key in data:
                del data[key]
                self._save("nodes", data)
                return True
            return False

    # ------------------------------------------------------------------
    # Source ingestion (mirrors MongoStore)
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_str(s: str) -> str:
        """Remove surrogate characters that Windows MCP pipeline may introduce."""
        if not isinstance(s, str):
            return str(s)
        return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

    def upsert_source(
        self, source_id: str, text: str, metadata: dict[str, Any]
    ) -> str:
        source_id = self._safe_str(source_id)
        text = self._safe_str(text)
        with self._lock:
            data = self._load("sources")
            data[source_id] = {
                "source_id": source_id,
                "text": text[:4096],  # truncate for storage
                "metadata": metadata,
                "ingested_at": datetime.now(UTC).isoformat(),
            }
            self._save("sources", data)
            return source_id

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return self._load("sources").get(source_id)

    def list_sources(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self._load("sources").values())[:limit]

    # ------------------------------------------------------------------
    # Audit log (mirrors MongoStore)
    # ------------------------------------------------------------------

    def log_event(
        self,
        event_type: str,
        subject_id: str | None,
        details: dict[str, Any],
    ) -> None:
        with self._lock:
            data = self._load("audit_log")
            ts = datetime.now(UTC).isoformat()
            entry_id = f"{event_type}::{ts}"
            data[entry_id] = {
                "event_type": event_type,
                "subject_id": subject_id,
                "details": details,
                "timestamp": ts,
            }
            self._save("audit_log", data)

    def get_audit_log(self, limit: int = 100, event_type: str | None = None) -> list[dict[str, Any]]:
        data = self._load("audit_log")
        entries = sorted(data.values(), key=lambda e: e["timestamp"], reverse=True)
        if event_type:
            entries = [e for e in entries if e.get("event_type") == event_type]
        return entries[:limit]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def collection_stats(self) -> dict[str, int]:
        return {
            "nodes": len(self._load("nodes")),
            "sources": len(self._load("sources")),
            "audit_log": len(self._load("audit_log")),
        }
