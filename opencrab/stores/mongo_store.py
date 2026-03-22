"""
MongoDB document store adapter.

Stores rich ontology node documents, ingested source records, and
audit logs. Uses pymongo with a connection pool.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class MongoStore:
    """MongoDB adapter for document-oriented ontology storage."""

    def __init__(self, uri: str, db_name: str) -> None:
        self._uri = uri
        self._db_name = db_name
        self._client: Any = None
        self._db: Any = None
        self._available = False
        self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        try:
            from pymongo import MongoClient  # type: ignore[import]
            from pymongo.errors import ConnectionFailure

            self._client = MongoClient(self._uri, serverSelectionTimeoutMS=5000)
            # Force connection check
            self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            self._available = True
            logger.info("MongoDB connected (db=%s)", self._db_name)
            self._ensure_indexes()
        except Exception as exc:
            logger.warning("MongoDB unavailable: %s", exc)
            self._available = False

    def _ensure_indexes(self) -> None:
        """Create indexes for common query patterns."""
        try:
            # nodes collection: unique on (space, node_id)
            self._db["nodes"].create_index(
                [("space", 1), ("node_id", 1)], unique=True
            )
            # sources collection: unique on source_id
            self._db["sources"].create_index("source_id", unique=True)
            # audit_log: sorted by timestamp
            self._db["audit_log"].create_index([("timestamp", -1)])
        except Exception as exc:
            logger.debug("MongoDB index creation: %s", exc)

    @property
    def available(self) -> bool:
        return self._available

    def ping(self) -> bool:
        """Return True if MongoDB is reachable."""
        try:
            self._client.admin.command("ping")
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Node document operations
    # ------------------------------------------------------------------

    def upsert_node_doc(
        self,
        space: str,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
    ) -> str:
        """
        Upsert a node document. Returns the MongoDB _id as string.
        """
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        doc = {
            "space": space,
            "node_type": node_type,
            "node_id": node_id,
            "properties": properties,
            "updated_at": datetime.now(tz=timezone.utc),
        }
        result = self._db["nodes"].update_one(
            {"space": space, "node_id": node_id},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(tz=timezone.utc)}},
            upsert=True,
        )
        if result.upserted_id:
            return str(result.upserted_id)
        # Return existing doc id
        existing = self._db["nodes"].find_one(
            {"space": space, "node_id": node_id}, {"_id": 1}
        )
        return str(existing["_id"]) if existing else ""

    def get_node_doc(self, space: str, node_id: str) -> dict[str, Any] | None:
        """Retrieve a node document by space and node_id."""
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        doc = self._db["nodes"].find_one(
            {"space": space, "node_id": node_id}, {"_id": 0}
        )
        return dict(doc) if doc else None

    def list_nodes(
        self, space: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List node documents, optionally filtered by space."""
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        query: dict[str, Any] = {}
        if space:
            query["space"] = space
        cursor = self._db["nodes"].find(query, {"_id": 0}).limit(limit)
        return [dict(doc) for doc in cursor]

    def delete_node_doc(self, space: str, node_id: str) -> bool:
        """Delete a node document. Returns True if deleted."""
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        result = self._db["nodes"].delete_one({"space": space, "node_id": node_id})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Source / ingestion records
    # ------------------------------------------------------------------

    def upsert_source(
        self,
        source_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> str:
        """Store or update a raw ingestion source document."""
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        doc = {
            "source_id": source_id,
            "text": text,
            "metadata": metadata,
            "updated_at": datetime.now(tz=timezone.utc),
        }
        result = self._db["sources"].update_one(
            {"source_id": source_id},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(tz=timezone.utc)}},
            upsert=True,
        )
        if result.upserted_id:
            return str(result.upserted_id)
        existing = self._db["sources"].find_one({"source_id": source_id}, {"_id": 1})
        return str(existing["_id"]) if existing else ""

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        """Retrieve a source document."""
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        doc = self._db["sources"].find_one({"source_id": source_id}, {"_id": 0})
        return dict(doc) if doc else None

    def list_sources(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all ingested sources."""
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        cursor = self._db["sources"].find({}, {"_id": 0, "text": 0}).limit(limit)
        return [dict(doc) for doc in cursor]

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def log_event(
        self,
        event_type: str,
        subject_id: str | None,
        details: dict[str, Any],
    ) -> None:
        """Append an audit log entry (fire-and-forget; errors are suppressed)."""
        if not self._available:
            return

        try:
            self._db["audit_log"].insert_one(
                {
                    "event_type": event_type,
                    "subject_id": subject_id,
                    "details": details,
                    "timestamp": datetime.now(tz=timezone.utc),
                }
            )
        except Exception as exc:
            logger.debug("Audit log write failed: %s", exc)

    def get_audit_log(
        self, limit: int = 100, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Retrieve recent audit log entries."""
        if not self._available:
            raise RuntimeError("MongoDB is not available.")

        query: dict[str, Any] = {}
        if event_type:
            query["event_type"] = event_type
        cursor = (
            self._db["audit_log"]
            .find(query, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return [dict(doc) for doc in cursor]

    # ------------------------------------------------------------------
    # Collection stats
    # ------------------------------------------------------------------

    def collection_stats(self) -> dict[str, int]:
        """Return document counts for all collections."""
        if not self._available:
            return {}

        return {
            "nodes": self._db["nodes"].count_documents({}),
            "sources": self._db["sources"].count_documents({}),
            "audit_log": self._db["audit_log"].count_documents({}),
        }
