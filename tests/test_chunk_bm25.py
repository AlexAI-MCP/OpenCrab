from __future__ import annotations

from typing import Any

import pytest

from opencrab.ontology.chunk_bm25 import ChunkBM25
from opencrab.ontology.query import HybridQuery

CHUNKS = {
    "trip#0": ("문서: 출장 규정\n절: 숙박비\n\n국내 숙박비 상한은 1박 12만 원이다.", {"heading_path": "숙박비", "space": "policy"}),
    "trip#1": ("문서: 출장 규정\n절: 식비\n\n식비는 하루 5만 원까지 실비로 정산한다.", {"heading_path": "식비", "space": "policy"}),
    "trip#2": ("문서: 출장 규정\n절: 승인\n\n해외 출장은 본부장 승인이 필요하다.", {"heading_path": "승인", "space": "hr"}),
}


class FakeChroma:
    """Chroma stand-in: chunk records, no vector hits."""

    available = True

    def __init__(self, records: dict[str, tuple[str, dict[str, Any]]] | None = None) -> None:
        self.records = {
            rid: (text, {**meta, "chunk_index": i, "source_id": rid.split("#")[0]})
            for i, (rid, (text, meta)) in enumerate((records if records is not None else CHUNKS).items())
        }
        self.list_calls = 0
        self.fail_list = False

    def count(self) -> int:
        return len(self.records)

    def list_where(self, where: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        self.list_calls += 1
        if self.fail_list:
            raise RuntimeError("chroma down")
        assert where == {"chunk_index": {"$gte": 0}}
        return [{"id": rid, "document": t, "metadata": m} for rid, (t, m) in list(self.records.items())[:limit]]

    def query(self, query_text: str, n_results: int = 10, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []


class FakeGraph:
    available = True

    def __init__(self) -> None:
        self.anchors: list[str] = []

    def find_neighbors(self, node_id: str, direction: str = "both", depth: int = 1, limit: int = 50) -> list[Any]:
        self.anchors.append(node_id)
        return []


# ---------------------------------------------------------------------------
# ChunkBM25
# ---------------------------------------------------------------------------


def test_search_returns_chunk_text_and_metadata() -> None:
    hits = ChunkBM25(FakeChroma()).search("숙박비 상한", spaces=None, limit=3)

    assert hits[0]["node_id"] == "trip#0"
    assert hits[0]["source"] == "bm25"
    assert hits[0]["text"] == CHUNKS["trip#0"][0]
    assert hits[0]["metadata"]["heading_path"] == "숙박비"
    assert hits[0]["score"] > 0


def test_korean_compound_matches_through_ngrams() -> None:
    hits = ChunkBM25(FakeChroma()).search("본부장승인", spaces=None, limit=1)

    assert hits[0]["node_id"] == "trip#2"


def test_space_filter() -> None:
    hits = ChunkBM25(FakeChroma()).search("출장", spaces=["hr"], limit=5)

    assert [h["node_id"] for h in hits] == ["trip#2"]


def test_index_is_cached_until_count_changes_or_invalidated() -> None:
    chroma = FakeChroma()
    index = ChunkBM25(chroma)

    index.search("식비", spaces=None, limit=1)
    index.search("식비", spaces=None, limit=1)
    assert chroma.list_calls == 1

    chroma.records["trip#3"] = ("문서: 출장 규정\n\n교통비는 실비 정산", {"chunk_index": 3, "source_id": "trip"})
    hits = index.search("교통비", spaces=None, limit=1)
    assert chroma.list_calls == 2
    assert hits[0]["node_id"] == "trip#3"

    index.invalidate()
    index.search("교통비", spaces=None, limit=1)
    assert chroma.list_calls == 3


def test_chunk_id_path_is_not_indexed() -> None:
    chroma = FakeChroma({"/data/budget_report/plan.md#0": ("문서: plan\n\n매출 보고", {})})

    assert ChunkBM25(chroma).search("budget", spaces=None, limit=3) == []
    assert ChunkBM25(chroma).search("chunk", spaces=None, limit=3) == []


def test_limit_truncation_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        hits = ChunkBM25(FakeChroma(), limit=2).search("출장", spaces=None, limit=5)

    assert {h["node_id"] for h in hits} <= {"trip#0", "trip#1"}
    assert "only the first 2 chunks" in caplog.text


@pytest.mark.parametrize(("raw", "expected"), [("", 10000), ("abc", 10000), ("-3", 10000), ("500", 500)])
def test_limit_env_parsing(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
    from opencrab.ontology.chunk_bm25 import chunk_bm25_limit

    monkeypatch.setenv("OPENCRAB_CHUNK_BM25_LIMIT", raw)

    assert chunk_bm25_limit() == expected


def test_no_chunks_returns_empty() -> None:
    assert ChunkBM25(FakeChroma({})).search("숙박비", spaces=None, limit=3) == []


def test_store_error_returns_empty() -> None:
    chroma = FakeChroma()
    chroma.fail_list = True

    assert ChunkBM25(chroma).search("숙박비", spaces=None, limit=3) == []


def test_unavailable_store_returns_empty() -> None:
    chroma = FakeChroma()
    chroma.available = False

    assert ChunkBM25(chroma).search("숙박비", spaces=None, limit=3) == []
    assert chroma.list_calls == 0


# ---------------------------------------------------------------------------
# HybridQuery integration
# ---------------------------------------------------------------------------


def test_query_includes_chunk_bm25_hits_when_chunking_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    graph = FakeGraph()
    hybrid = HybridQuery(FakeChroma(), graph)  # type: ignore[arg-type]

    results = hybrid.query("해외 출장 승인권자", limit=3)

    assert results[0].node_id == "trip#2"
    assert results[0].text == CHUNKS["trip#2"][0]
    assert results[0].metadata["heading_path"] == "승인"
    assert graph.anchors == []


def test_query_skips_chunk_bm25_when_chunking_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAB_CHUNKING", raising=False)
    chroma = FakeChroma()
    hybrid = HybridQuery(chroma, FakeGraph())  # type: ignore[arg-type]

    results = hybrid.query("해외 출장 승인권자", limit=3)

    assert results == []
    assert chroma.list_calls == 0


def test_query_respects_use_bm25_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    chroma = FakeChroma()
    hybrid = HybridQuery(chroma, FakeGraph())  # type: ignore[arg-type]

    hybrid.query("해외 출장 승인권자", limit=3, use_bm25=False)

    assert chroma.list_calls == 0


def test_node_writes_do_not_rebuild_chunk_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    chroma = FakeChroma()
    hybrid = HybridQuery(chroma, FakeGraph())  # type: ignore[arg-type]
    hybrid.query("식비", limit=1)

    hybrid.invalidate_bm25_cache()
    hybrid.query("식비", limit=1)

    assert chroma.list_calls == 1


# ---------------------------------------------------------------------------
# Real local Chroma
# ---------------------------------------------------------------------------


def test_round_trip_keyword_only_match_is_found(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opencrab.stores.chroma_store import ChromaStore

    store = ChromaStore("unused", 0, "chunk_bm25", local_mode=True, local_path=str(tmp_path / "chroma"))
    if not store.available:
        pytest.skip("local chromadb unavailable")
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    hybrid = HybridQuery(store, FakeGraph())  # type: ignore[arg-type]
    hybrid.ingest(
        "# 출장 규정\n## 숙박비\n국내 숙박비 상한은 1박 12만 원이다.\n\n"
        "## 식비\n식비는 하루 5만 원까지 실비로 정산한다.\n\n"
        "## 승인\n해외 출장은 본부장 승인이 필요하다.",
        "trip",
    )

    results = hybrid.query("본부장 승인", limit=3)

    assert results[0].node_id == "trip#2"
    assert results[0].source in ("bm25", "hybrid")
    assert store.list_where({"chunk_index": {"$gte": 0}}, limit=10)[0]["metadata"]["source_id"] == "trip"


def _local_hybrid(tmp_path, name: str) -> tuple[Any, HybridQuery]:
    from opencrab.stores.chroma_store import ChromaStore

    store = ChromaStore("unused", 0, name, local_mode=True, local_path=str(tmp_path / "chroma"))
    if not store.available:
        pytest.skip("local chromadb unavailable")
    return store, HybridQuery(store, FakeGraph())  # type: ignore[arg-type]


def test_reingest_with_same_chunk_count_refreshes_keywords(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    _, hybrid = _local_hybrid(tmp_path, "chunk_bm25_refresh")
    hybrid.ingest("# 절\n외장디스크 반출은 금지한다.", "doc")
    assert hybrid.query("외장디스크", limit=1)[0].node_id == "doc#0"

    hybrid.ingest("# 절\n노트북 반납은 퇴사일까지 한다.", "doc")

    assert "노트북" in hybrid.query("노트북 반납", limit=1)[0].text
    assert all("외장디스크" not in r.text for r in hybrid.query("외장디스크", limit=3))


def test_failed_stale_delete_still_refreshes_keywords(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    store, hybrid = _local_hybrid(tmp_path, "chunk_bm25_delete")
    hybrid.ingest("# 하나\nalpha 내용\n\n# 둘\nomega 내용", "doc")
    hybrid.query("alpha", limit=1)

    def broken_delete(ids: list[str]) -> None:
        raise RuntimeError("delete failed")

    monkeypatch.setattr(store, "delete", broken_delete)
    hybrid.ingest("# 둘\nomega 내용", "doc")

    texts = [r.text for r in hybrid.query("alpha", limit=3) if r.node_id == "doc#0"]
    assert all("alpha" not in t for t in texts)


def _run_threads(threads: list[Any], errors: list[BaseException]) -> None:
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive(), "worker thread did not finish"
    assert errors == []


def test_invalidate_during_rebuild_does_not_store_the_stale_index() -> None:
    import threading

    chroma = FakeChroma({"doc#0": ("alpha 옛 본문", {})})
    index = ChunkBM25(chroma)
    reading = threading.Event()
    resume = threading.Event()
    errors: list[BaseException] = []
    original = chroma.list_where

    def slow_list_where(where: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        records = original(where, limit)
        reading.set()
        if not resume.wait(timeout=5):
            errors.append(TimeoutError("resume not signalled"))
        return records

    def worker() -> None:
        try:
            index.search("alpha", None, 3)
        except BaseException as exc:  # noqa: BLE001 - surfaced through `errors`
            errors.append(exc)

    chroma.list_where = slow_list_where  # type: ignore[method-assign]
    thread = threading.Thread(target=worker)
    thread.start()
    assert reading.wait(timeout=5)
    chroma.records["doc#0"] = ("omega 새 본문", {"chunk_index": 0, "source_id": "doc"})
    index.invalidate()
    resume.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []
    chroma.list_where = original  # type: ignore[method-assign]

    assert index.search("alpha", spaces=None, limit=3) == []
    assert index.search("omega", spaces=None, limit=3)[0]["text"] == "omega 새 본문"


def test_concurrent_cold_searches_build_once() -> None:
    import threading
    import time

    callers = 8
    chroma = FakeChroma()
    index = ChunkBM25(chroma)
    # All callers read the record count before any build starts, and the slow build
    # keeps the first rebuild running while the others arrive (likely, not guaranteed).
    all_checked = threading.Barrier(callers, timeout=5)
    original_count = chroma.count
    original_list = chroma.list_where
    errors: list[BaseException] = []

    def count_after_everyone_checked() -> int:
        value = original_count()
        all_checked.wait()
        return value

    def slow_list_where(where: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        time.sleep(0.1)  # keep the first build running while the others arrive
        return original_list(where, limit)

    def worker() -> None:
        try:
            index.search("숙박비", None, 3)
        except BaseException as exc:  # noqa: BLE001 - surfaced through `errors`
            errors.append(exc)

    chroma.count = count_after_everyone_checked  # type: ignore[method-assign]
    chroma.list_where = slow_list_where  # type: ignore[method-assign]
    _run_threads([threading.Thread(target=worker) for _ in range(callers)], errors)

    assert chroma.list_calls == 1


def test_exact_limit_is_not_reported_as_truncated(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        ChunkBM25(FakeChroma(), limit=3).search("출장", spaces=None, limit=5)

    assert "only the first" not in caplog.text
