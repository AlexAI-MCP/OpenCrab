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
_TEXT_FIELDS = (
    "name",
    "description",
    "text",
    "title",
    "label",
    "summary",
    "content",
    "reason",
    "rationale",
    "change_reason",
    "revision_reason",
    "applicability",
    "limitation",
    "limitations",
    "risk",
    "law",
    "standard",
    "evidence",
    "source",
    "heading_path",
)
_HANGUL_RE = re.compile(r"[가-힣]")
_MAX_PROPERTY_TEXT = 1200


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace.

    Korean construction benchmarks contain many compound nouns and short
    relation cues ("변경 이유", "적용 불가", "개정"). Whitespace tokenisation
    alone misses those matches, so Hangul tokens also contribute 2- and 3-char
    n-grams. This keeps exact English behaviour while making Korean recall
    much less brittle.
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens: list[str] = []
    for token in text.split():
        if not token:
            continue
        tokens.append(token)
        if _HANGUL_RE.search(token) and len(token) >= 3:
            for n in (2, 3):
                tokens.extend(token[i : i + n] for i in range(0, len(token) - n + 1))
    return tokens


def _flatten_property_text(value: Any, depth: int = 0) -> list[str]:
    """Collect searchable scalar text from nested property values."""
    if value is None or depth > 2:
        return []
    if isinstance(value, str):
        return [value[:_MAX_PROPERTY_TEXT]]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value[:50]:
            parts.extend(_flatten_property_text(item, depth + 1))
        return parts
    if isinstance(value, dict):
        parts = []
        for key, item in list(value.items())[:80]:
            parts.append(str(key).replace("_", " "))
            parts.extend(_flatten_property_text(item, depth + 1))
        return parts
    return [str(value)[:_MAX_PROPERTY_TEXT]]


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
    for key, val in props.items():
        if key in _TEXT_FIELDS:
            continue
        parts.append(str(key).replace("_", " "))
        parts.extend(_flatten_property_text(val))
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
    def build(
        cls,
        nodes: list[dict[str, Any]],
        texts: list[str] | None = None,
    ) -> "BM25Index":
        """
        Build a BM25 index from a list of node dicts.

        Each dict must have at least 'node_id', 'space', 'node_type'.
        Properties are read from the 'properties' sub-dict. When ``texts`` is
        given, ``texts[i]`` is indexed for ``nodes[i]`` instead of the text
        assembled from its fields.
        """
        if texts is not None and len(texts) != len(nodes):
            raise ValueError("texts must have one entry per node")
        idx = cls()
        idx._docs = nodes
        sources = texts if texts is not None else [_node_text(n) for n in nodes]
        idx._tokens = [_tokenize(t) for t in sources]

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
