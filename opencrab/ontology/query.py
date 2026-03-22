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

    def query(
        self,
        question: str,
        spaces: list[str] | None = None,
        limit: int = 10,
        graph_depth: int = 1,
    ) -> list[QueryResult]:
        """
        Execute a hybrid query against vector and graph stores.

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

        Returns
        -------
        list[QueryResult] sorted by descending score.
        """
        results: list[QueryResult] = []

        # --- Stage 1: Vector similarity search ---
        vector_hits = self._vector_search(question, spaces, limit)
        results.extend(vector_hits)

        # --- Stage 2: Graph expansion from vector anchor nodes ---
        anchor_ids = [
            hit.node_id for hit in vector_hits if hit.node_id
        ]
        if anchor_ids and self._neo4j.available:
            graph_results = self._graph_expand(anchor_ids, graph_depth, limit)
            # Avoid duplicating nodes already in vector results
            seen_ids = {r.node_id for r in results}
            for gr in graph_results:
                if gr.node_id not in seen_ids:
                    results.append(gr)
                    seen_ids.add(gr.node_id)

        # --- Sort and truncate ---
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

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
        """Expand graph neighbourhood from anchor node IDs."""
        if not self._neo4j.available:
            return []

        expanded: list[QueryResult] = []
        seen: set[str] = set(anchor_ids)

        for anchor_id in anchor_ids[:5]:  # expand at most 5 anchors
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
                        expanded.append(
                            QueryResult(
                                source="graph",
                                node_id=nid,
                                score=0.5,  # graph neighbours get a baseline score
                                text=props.get("text") or props.get("name"),
                                metadata=props,
                                graph_context={
                                    "anchor_id": anchor_id,
                                    "labels": n.get("labels", []),
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
