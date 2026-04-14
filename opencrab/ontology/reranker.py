"""
Result Reranker — score-fusion and BM25-based cross-reranking.

Takes a mixed list of QueryResult objects (from vector + BM25 + graph sources)
and produces a unified ranking using reciprocal rank fusion (RRF) as the
primary method, with an optional BM25 cross-score pass for text-heavy queries.

Approach:
  - Reciprocal Rank Fusion (RRF): robust, parameter-free, handles multiple
    result lists without needing to normalise scores across different scales.
  - BM25 cross-score: when the original query text is available, additionally
    scores each result's text against the query using in-memory BM25.
  - Final score = alpha * rrf_score + (1-alpha) * bm25_cross_score

RRF constant k=60 (standard, prevents high-rank docs dominating).
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)

_RRF_K = 60
_ALPHA = 0.7   # weight for RRF vs BM25 cross-score
_K1 = 1.5
_B = 0.75


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if t]


def _bm25_cross_score(query_tokens: list[str], doc_tokens: list[str], avgdl: float) -> float:
    """BM25 score for a single (query, doc) pair."""
    if not query_tokens or not doc_tokens:
        return 0.0
    dl = len(doc_tokens)
    tf_map = Counter(doc_tokens)
    n = 1  # single doc, IDF degenerates; use tf-based saturation only
    score = 0.0
    for term in query_tokens:
        tf = tf_map.get(term, 0)
        if tf == 0:
            continue
        idf = 1.0  # flat IDF since we can't compute corpus DF here
        num = tf * (_K1 + 1)
        den = tf + _K1 * (1 - _B + _B * dl / max(avgdl, 1))
        score += idf * (num / den)
    return score


class Reranker:
    """
    Reranks a list of QueryResult dicts using RRF + optional BM25 cross-scoring.

    Input format: list of dicts with keys source, node_id, score, text, metadata.
    (Compatible with QueryResult.to_dict().)
    """

    def rerank(
        self,
        query: str,
        result_lists: list[list[dict[str, Any]]],
        top_k: int = 10,
        use_bm25_cross: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Merge multiple result lists and rerank using RRF + BM25.

        Parameters
        ----------
        query:
            Original query string.
        result_lists:
            One list per source (e.g. [vector_results, bm25_results, graph_results]).
            Each item must have 'node_id' and optionally 'score', 'text'.
        top_k:
            Number of results to return.
        use_bm25_cross:
            If True, supplement RRF with a BM25 cross-score over result texts.

        Returns
        -------
        Reranked list of result dicts with added 'rerank_score' field.
        """
        # Collect all unique results keyed by node_id
        all_results: dict[str, dict[str, Any]] = {}
        for results in result_lists:
            for item in results:
                nid = item.get("node_id")
                if nid and nid not in all_results:
                    all_results[nid] = item

        if not all_results:
            return []

        # RRF: accumulate reciprocal rank from each source list
        rrf_scores: dict[str, float] = defaultdict(float)
        for results in result_lists:
            for rank, item in enumerate(results):
                nid = item.get("node_id")
                if nid:
                    rrf_scores[nid] += 1.0 / (_RRF_K + rank + 1)

        # Normalise RRF scores to [0, 1]
        max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
        if max_rrf == 0:
            max_rrf = 1.0

        # BM25 cross-score (query vs each result's text)
        q_tokens = _tokenize(query)
        bm25_cross: dict[str, float] = {}

        if use_bm25_cross and q_tokens:
            doc_texts = {
                nid: _tokenize(item.get("text") or "")
                for nid, item in all_results.items()
            }
            avg_dl = sum(len(t) for t in doc_texts.values()) / max(len(doc_texts), 1)
            raw_bm25 = {
                nid: _bm25_cross_score(q_tokens, toks, avg_dl)
                for nid, toks in doc_texts.items()
            }
            max_bm25 = max(raw_bm25.values()) if raw_bm25 else 1.0
            if max_bm25 == 0:
                max_bm25 = 1.0
            bm25_cross = {nid: s / max_bm25 for nid, s in raw_bm25.items()}

        # Final score fusion
        final: list[tuple[str, float]] = []
        for nid in all_results:
            rrf = rrf_scores.get(nid, 0.0) / max_rrf
            bm25 = bm25_cross.get(nid, 0.0) if use_bm25_cross else 0.0
            if use_bm25_cross:
                score = _ALPHA * rrf + (1 - _ALPHA) * bm25
            else:
                score = rrf
            final.append((nid, round(score, 4)))

        final.sort(key=lambda x: x[1], reverse=True)

        output = []
        for nid, score in final[:top_k]:
            item = dict(all_results[nid])
            item["rerank_score"] = score
            output.append(item)

        return output
