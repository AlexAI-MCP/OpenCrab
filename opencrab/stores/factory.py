"""
Store factory — returns LocalCrab's local-only backends.

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
    """Return the local SQLite graph store."""
    from opencrab.stores.local_graph_store import LocalGraphStore

    db_path = os.path.join(settings.local_data_dir, "graph.db")
    return LocalGraphStore(db_path=db_path)


def make_vector_store(settings: Settings) -> Any:
    """Return the local persistent Chroma store.

    EMBEDDING_BACKEND 환경변수로 임베딩 함수를 선택한다:
      "local"  (기본): ChromaDB 기본 EF (all-MiniLM-L6-v2, 384d).
                       기존 컬렉션("opencrab_vectors") 그대로 사용. 롤백 경로.
      "openai"        : OpenAI 호환 임베딩 서버(LM Studio 등) + 로컬 GGUF 폴백.
                       EMBED_COLLECTION("opencrab_vectors_kure") 사용. 차원 비호환 방지.

    변경 이유: 한국어 검색 품질 개선. minilm 실측 MRR 0.285 vs KURE-v1 1.000.
    """
    from opencrab.stores.chroma_store import ChromaStore

    chroma_path = os.path.join(settings.local_data_dir, "chroma")

    if settings.embedding_backend == "openai":
        # OpenAI 호환 서버 백엔드: 주력 임베딩 + 로컬 GGUF 폴백
        from opencrab.stores.openai_embedding import OpenAIEmbeddingFunction
        from opencrab.stores.llamacpp_embedding import LlamaCppEmbeddingFunction
        from opencrab.stores.resilient_embedding import ResilientEmbeddingFunction

        primary_ef = OpenAIEmbeddingFunction(
            api_base=settings.openai_api_base,
            model=settings.openai_embed_model,
            dim=settings.embed_dim,
            timeout=settings.openai_timeout,
            api_key=settings.openai_api_key,
        )
        # local_gguf_path 가 비어있으면 llamacpp_embedding._ensure_local_gguf() 가
        # KURE-v1-Q4_K_M 을 자동 다운로드. 원격 서버 장애 시 폴백으로 사용됨.
        fallback_ef = LlamaCppEmbeddingFunction(
            gguf_path=settings.local_gguf_path,
            dim=settings.embed_dim,
        )
        ef = ResilientEmbeddingFunction(primary=primary_ef, fallback=fallback_ef)

        return ChromaStore(
            host=settings.chroma_host,
            port=settings.chroma_port,
            collection_name=settings.embed_collection,
            local_mode=True,
            local_path=chroma_path,
            embedding_function=ef,
        )

    # 기존 경로: EMBEDDING_BACKEND=local 또는 미설정
    # ChromaDB 기본 EF (minilm, 384d) 사용. 기존 동작 100% 보존.
    return ChromaStore(
        host=settings.chroma_host,
        port=settings.chroma_port,
        collection_name=settings.chroma_collection,
        local_mode=True,
        local_path=chroma_path,
    )


def make_doc_store(settings: Settings) -> Any:
    """Return the local JSON document store."""
    from opencrab.stores.local_doc_store import LocalDocStore

    docs_path = os.path.join(settings.local_data_dir, "docs")
    return LocalDocStore(data_dir=docs_path)


def make_sql_store(settings: Settings) -> Any:
    """Return the local SQLite SQL store."""
    from opencrab.stores.sql_store import SQLStore

    return SQLStore(url=settings.sqlite_url)
