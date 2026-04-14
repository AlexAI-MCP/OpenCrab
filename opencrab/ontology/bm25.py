"""
BM25 keyword search index over ontology node properties.

Operates on the doc store (LocalDocStore / MongoStore) — no external deps.
Provides fast, deterministic keyword matching as a complement to vector search.

BM25 parameters:
  k1 = 1.5  (term frequency saturation)
  b  = 0.75 (length normalisation)
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

# BM25 hyper-parameters
_K1 = 1.5
_B = 0.75

# Properties to include when building the text representation of a node
_TEXT_FIELDS = ("name", "description", "text", "title", "label", "summary", "content")


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if t]


def _node_text(node: dict[str, Any]) -> str:
    """Build a flat text string from a node document for indexing."""
    props = node.get("properties") or {}
    parts: list[str] = []
    # Include node_id and node_type as searchable terms
    if node.get("node_id"):
        parts.append(str(node["node_id"]).replace("_", " ").replace("-", " "))
    if node.get("node_type"):
        parts.append(str(node["node_type"]))
    for field in _TEXT_FIELDS:
        val = props.get(field)
        if val:
            parts.append(str(val))
    return " ".join(parts)


class BM25Index:
    """
    In-memory BM25 index built from a list of node documents.

    Usage:
        index = BM25Index.build(doc_store.list_nodes(limit=10000))
        results = index.search("machine learning", limit=10)
    """

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []       # raw node docs
        self._tokens: list[list[str]] = []           # tokenised docs
        self._df: Counter[str] = Counter()           # document frequency
        self._avgdl: float = 0.0                     # average document length
        self._idf: dict[str, float] = {}             # IDF cache

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, nodes: list[dict[str, Any]]) -> "BM25Index":
        """
        Build a BM25 index from a list of node dicts.

        Each dict must have at least 'node_id', 'space', 'node_type'.
        Properties are read from the 'properties' sub-dict.
        """
        idx = cls()
        idx._docs = nodes
        idx._tokens = [_tokenize(_node_text(n)) for n in nodes]

        # Document frequency
        for toks in idx._tokens:
            for term in set(toks):
                idx._df[term] += 1

        # Average document length
        total_len = sum(len(t) for t in idx._tokens)
        idx._avgdl = total_len / max(len(idx._tokens), 1)

        # Pre-compute IDF for all known terms
        n = len(nodes)
        for term, df in idx._df.items():
            idx._idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1)

        logger.debug("BM25Index built: %d nodes, %d unique terms", n, len(idx._idf))
        return idx

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        spaces: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Return top-k nodes ranked by BM25 score.

        Parameters
        ----------
        query:
            Search text.
        spaces:
            Optional space filter.
        limit:
            Maximum results.

        Returns
        -------
        list of dicts with keys: node_id, space, node_type, score, properties.
        """
        q_tokens = _tokenize(query)
        if not q_tokens or not self._docs:
            return []

        scores: list[tuple[int, float]] = []

        for i, (doc, toks) in enumerate(zip(self._docs, self._tokens)):
            # Space filter
            if spaces and doc.get("space") not in spaces:
                continue

            dl = len(toks)
            tf_map = Counter(toks)
            score = 0.0

            for term in q_tokens:
                if term not in self._idf:
                    continue
                tf = tf_map.get(term, 0)
                idf = self._idf[term]
                numerator = tf * (_K1 + 1)
                denominator = tf + _K1 * (1 - _B + _B * dl / max(self._avgdl, 1))
                score += idf * (numerator / denominator)

            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in scores[:limit]:
            doc = self._docs[idx]
            results.append({
                "node_id": doc.get("node_id"),
                "space": doc.get("space"),
                "node_type": doc.get("node_type"),
                "score": round(score, 4),
                "properties": doc.get("properties") or {},
                "text": _node_text(doc),
            })
        return results

    def __len__(self) -> int:
        return len(self._docs)
