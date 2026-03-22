"""
Store factory — returns the right backend based on STORAGE_MODE setting.

Usage:
    from opencrab.stores.factory import make_graph_store, make_vector_store, ...
    graph  = make_graph_store(settings)
    vector = make_vector_store(settings)
    docs   = make_doc_store(settings)
    sql    = make_sql_store(settings)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opencrab.config import Settings


def make_graph_store(settings: Settings) -> Any:
    """Return LocalGraphStore (local) or Neo4jStore (docker)."""
    if settings.is_local:
        from opencrab.stores.local_graph_store import LocalGraphStore

        db_path = os.path.join(settings.local_data_dir, "graph.db")
        return LocalGraphStore(db_path=db_path)
    else:
        from opencrab.stores.neo4j_store import Neo4jStore

        return Neo4jStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )


def make_vector_store(settings: Settings) -> Any:
    """Return ChromaStore in local or docker mode."""
    from opencrab.stores.chroma_store import ChromaStore

    chroma_path = os.path.join(settings.local_data_dir, "chroma")
    return ChromaStore(
        host=settings.chroma_host,
        port=settings.chroma_port,
        collection_name=settings.chroma_collection,
        local_mode=settings.is_local,
        local_path=chroma_path,
    )


def make_doc_store(settings: Settings) -> Any:
    """Return LocalDocStore (local) or MongoStore (docker)."""
    if settings.is_local:
        from opencrab.stores.local_doc_store import LocalDocStore

        docs_path = os.path.join(settings.local_data_dir, "docs")
        return LocalDocStore(data_dir=docs_path)
    else:
        from opencrab.stores.mongo_store import MongoStore

        return MongoStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db)


def make_sql_store(settings: Settings) -> Any:
    """Return SQLStore with SQLite (local) or PostgreSQL (docker)."""
    from opencrab.stores.sql_store import SQLStore

    url = settings.sqlite_url if settings.is_local else settings.postgres_url
    return SQLStore(database_url=url)
