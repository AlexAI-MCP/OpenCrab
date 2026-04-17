"""
Hybrid Query Engine.

Combines vector similarity search (ChromaDB) with graph traversal
(Neo4j) to answer natural language questions about the ontology.

Query pipeline:
  1. Embed the question and perform a vector similarity search in ChromaDB.
  2. Extract node IDs from the top vector hits.
  3. Use those IDs as anchors for a graph neighbourhood expansion.
  4. Merge, deduplicate, and rank results.
  5. Return a unified result list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from opencrab.stores.chroma_store import ChromaStore
from opencrab.stores.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)

# Edge-type weights for graph expansion scoring
_EDGE_WEIGHTS: dict[str, float] = {
    "SUPPORTS": 0.7,
    "DEPENDS_ON": 0.7,
    "RELATED_TO": 0.6,
    "CONTAINS": 0.65,
    "INFLUENCES": 0.65,
    "CONTRADICTS": 0.5,
}
_DEFAULT_EDGE_SCORE: float = 0.5

# Lazily imported Phase 4 modules to avoid circular deps at module load
_BM25Index: Any = None
_Reranker: Any = None


def _get_bm25():
    global _BM25Index
    if _BM25Index is None:
        from opencrab.ontology.bm25 import BM25Index
        _BM25Index = BM25Index
    return _BM25Index


def _get_reranker():
    global _Reranker
    if _Reranker is None:
        from opencrab.ontology.reranker import Reranker
        _Reranker = Reranker
    return _Reranker


@dataclass
class QueryResult:
    """A single result item from a hybrid query."""

    source: str          # "vector", "graph", or "hybrid"
    node_id: str | None
    score: float
    text: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    graph_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "node_id": self.node_id,
            "score": self.score,
            "text": self.text,
            "metadata": self.metadata,
            "graph_context": self.graph_context,
        }


class HybridQuery:
    """Orchestrates hybrid vector + graph queries."""

    def __init__(self, chroma: ChromaStore, neo4j: Neo4jStore) -> None:
        self._chroma = chroma
        self._neo4j = neo4j
        # Optional stores attached at runtime by _get_context() in tools.py
        self._doc_store: Any = None
        self._rebac: Any = None
        # BM25 index cache — rebuilt lazily, invalidated on every write
        self._bm25_cache: Any = None
        self._bm25_cache_size: int = 0
        self._bm25_dirty: bool = True

    def invalidate_bm25_cache(self) -> None:
        """Mark the BM25 index stale so it is rebuilt on the next query."""
        self._bm25_dirty = True

    def query(
        self,
        question: str,
        spaces: list[str] | None = None,
        limit: int = 10,
        graph_depth: int = 1,
        subject_id: str | None = None,
        use_bm25: bool = True,
        use_rerank: bool = True,
    ) -> list[QueryResult]:
        """
        Execute a hybrid query: vector + BM25 + graph expansion, then rerank.

        Parameters
        ----------
        question:
            Natural language question or search text.
        spaces:
            Optional list of space IDs to filter results.
        limit:
            Maximum number of results to return.
        graph_depth:
            Neighbourhood expansion depth from vector-hit anchors.
        subject_id:
            If set, policy-aware filter: removes nodes the subject cannot view.
            Requires self._rebac to be attached (done by _get_context in tools.py).
        use_bm25:
            Include BM25 keyword results in the merge (default True).
        use_rerank:
            Apply RRF + BM25 cross-score reranking (default True).

        Returns
        -------
        list[QueryResult] sorted by descending score.
        """
        result_lists: list[list[dict[str, Any]]] = []

        # --- Stage 1: Vector similarity search ---
        vector_hits = self._vector_search(question, spaces, limit)
        if vector_hits:
            result_lists.append([r.to_dict() for r in vector_hits])

        # --- Stage 2: BM25 keyword search ---
        if use_bm25 and self._doc_store is not None:
            bm25_hits = self._bm25_search(question, spaces, limit)
            if bm25_hits:
                result_lists.append(bm25_hits)

        # --- Stage 3: Graph expansion from vector anchor nodes ---
        anchor_ids = [hit.node_id for hit in vector_hits if hit.node_id]
        if anchor_ids and self._neo4j.available:
            graph_results = self._graph_expand(anchor_ids, graph_depth, limit)
            if graph_results:
                result_lists.append([r.to_dict() for r in graph_results])

        # --- Stage 4: Rerank ---
        if use_rerank and result_lists:
            reranker = _get_reranker()()
            merged = reranker.rerank(question, result_lists, top_k=limit * 2)
        else:
            # Flat merge without reranking
            seen: set[str | None] = set()
            merged = []
            for lst in result_lists:
                for item in lst:
                    if item.get("node_id") not in seen:
                        seen.add(item.get("node_id"))
                        merged.append(item)
            merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        # --- Stage 5: Policy-aware filter ---
        if subject_id and self._rebac is not None:
            merged = self._policy_filter(merged, subject_id)

        # Convert back to QueryResult
        results = []
        for item in merged[:limit]:
            results.append(QueryResult(
                source=item.get("source", "hybrid"),
                node_id=item.get("node_id"),
                score=item.get("rerank_score") or item.get("score", 0.0),
                text=item.get("text"),
                metadata=item.get("metadata") or {},
                graph_context=item.get("graph_context"),
            ))
        return results

    def _bm25_search(
        self,
        question: str,
        spaces: list[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Run BM25 search against doc store nodes, using a cached index."""
        try:
            if self._bm25_dirty or self._bm25_cache is None:
                nodes = self._doc_store.list_nodes(limit=5000)
                BM25Index = _get_bm25()
                self._bm25_cache = BM25Index.build(nodes)
                self._bm25_cache_size = len(nodes)
                self._bm25_dirty = False
                logger.debug("BM25 index rebuilt (%d nodes)", self._bm25_cache_size)
            hits = self._bm25_cache.search(question, spaces=spaces, limit=limit)
            for h in hits:
                h["source"] = "bm25"
            return hits
        except Exception as exc:
            logger.warning("BM25 search error: %s", exc)
            return []

    def _policy_filter(
        self,
        results: list[dict[str, Any]],
        subject_id: str,
    ) -> list[dict[str, Any]]:
        """
        Remove results the subject cannot view.

        Uses ReBAC 'view' permission check. Nodes with no registered policy
        are passed through (open by default).
        """
        filtered = []
        for item in results:
            nid = item.get("node_id")
            if not nid:
                filtered.append(item)
                continue
            try:
                decision = self._rebac.check(
                    subject_id=subject_id,
                    permission="view",
                    resource_id=nid,
                )
                if decision.granted:
                    filtered.append(item)
                else:
                    logger.debug(
                        "Policy filter: %s denied view on %s", subject_id, nid
                    )
            except Exception:
                # No policy registered = pass through
                filtered.append(item)
        return filtered

    def _vector_search(
        self, question: str, spaces: list[str] | None, limit: int
    ) -> list[QueryResult]:
        """Run ChromaDB semantic similarity search."""
        if not self._chroma.available:
            logger.debug("ChromaDB unavailable, skipping vector search.")
            return []

        try:
            where: dict[str, Any] | None = None
            if spaces:
                if len(spaces) == 1:
                    where = {"space": spaces[0]}
                else:
                    where = {"space": {"$in": spaces}}

            hits = self._chroma.query(
                query_text=question,
                n_results=min(limit, 20),
                where=where,
            )

            results: list[QueryResult] = []
            for hit in hits:
                # Convert cosine distance to similarity score (1 - distance)
                distance = hit.get("distance") or 0.0
                score = max(0.0, 1.0 - float(distance))
                meta = hit.get("metadata") or {}
                results.append(
                    QueryResult(
                        source="vector",
                        node_id=meta.get("node_id") or hit.get("id"),
                        score=score,
                        text=hit.get("document"),
                        metadata=meta,
                    )
                )
            return results
        except Exception as exc:
            logger.warning("Vector search error: %s", exc)
            return []

    def _graph_expand(
        self, anchor_ids: list[str], depth: int, limit: int
    ) -> list[QueryResult]:
        """Expand graph neighbourhood from anchor node IDs.

        Uses at most 3 anchors for depth > 1 (multi-hop) to keep result sets
        manageable. Edge-type weights adjust the baseline score; a per-hop
        decay of 0.85 reduces scores for deeper neighbours.
        """
        if not self._neo4j.available:
            return []

        expanded: list[QueryResult] = []
        seen: set[str] = set(anchor_ids)
        max_anchors = 3 if depth > 1 else 5
        hop_decay = 0.85 ** (depth - 1)

        for anchor_id in anchor_ids[:max_anchors]:
            try:
                neighbours = self._neo4j.find_neighbors(
                    node_id=anchor_id,
                    direction="both",
                    depth=depth,
                    limit=limit,
                )
                for n in neighbours:
                    props = n.get("properties", {})
                    nid = props.get("id")
                    if nid and nid not in seen:
                        seen.add(nid)
                        rel_type = n.get("relation_type") or n.get("relationship_type") or ""
                        base_score = _EDGE_WEIGHTS.get(rel_type, _DEFAULT_EDGE_SCORE) * hop_decay
                        expanded.append(
                            QueryResult(
                                source="graph",
                                node_id=nid,
                                score=base_score,
                                text=props.get("text") or props.get("name"),
                                metadata=props,
                                graph_context={
                                    "anchor_id": anchor_id,
                                    "labels": n.get("labels", []),
                                    "relation_type": rel_type,
                                    "depth": depth,
                                },
                            )
                        )
            except Exception as exc:
                logger.debug("Graph expand error for anchor %s: %s", anchor_id, exc)

        return expanded

    def ingest(
        self,
        text: str,
        source_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Ingest a text chunk into the vector store.

        Parameters
        ----------
        text:
            The text to embed and store.
        source_id:
            Stable identifier for this source (used as the document ID).
        metadata:
            Additional metadata attached to the vector (e.g. space, node_id).

        Returns
        -------
        dict with ingestion status.
        """
        meta = metadata or {}
        meta["source_id"] = source_id

        result: dict[str, Any] = {"source_id": source_id, "stores": {}}

        if not self._chroma.available:
            result["stores"]["chromadb"] = "unavailable"
            return result

        try:
            ids = self._chroma.upsert_texts(
                texts=[text],
                metadatas=[meta],
                ids=[source_id],
            )
            result["stores"]["chromadb"] = f"ok (id={ids[0]})"
            result["vector_id"] = ids[0]
        except Exception as exc:
            logger.warning("Ingest to ChromaDB failed: %s", exc)
            result["stores"]["chromadb"] = f"error: {exc}"

        return result

    def keyword_search(
        self,
        keyword: str,
        spaces: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Simple keyword search in the Neo4j graph using CONTAINS.

        Parameters
        ----------
        keyword:
            Search term.
        spaces:
            Optional list of spaces to filter.
        limit:
            Max results.
        """
        if not self._neo4j.available:
            return []

        space_filter = ""
        params: dict[str, Any] = {"kw": keyword.lower(), "limit": limit}
        if spaces:
            space_filter = "AND n.space IN $spaces"
            params["spaces"] = spaces

        cypher = f"""
            MATCH (n)
            WHERE toLower(n.name) CONTAINS $kw
               OR toLower(n.description) CONTAINS $kw
               OR toLower(n.text) CONTAINS $kw
               {space_filter}
            RETURN properties(n) AS props, labels(n)[0] AS label
            LIMIT $limit
        """
        try:
            rows = self._neo4j.run_cypher(cypher, params)
            return [
                {"node": dict(r.get("props") or {}), "label": r.get("label")}
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Keyword search error: %s", exc)
            return []
