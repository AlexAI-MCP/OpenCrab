from __future__ import annotations

from typing import Any

import pytest

from opencrab.ontology.chunking import chunk_markdown, document_title
from opencrab.ontology.query import HybridQuery

# ---------------------------------------------------------------------------
# chunk_markdown
# ---------------------------------------------------------------------------


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_markdown("", title="doc") == []
    assert chunk_markdown("  \n\n ", title="doc") == []


def test_splits_on_headings_and_tracks_heading_path() -> None:
    text = (
        "# 휴가 규정\n"
        "연차는 입사일 기준으로 산정한다.\n\n"
        "## 신청 절차\n"
        "휴가는 3일 전까지 신청한다.\n\n"
        "### 승인권자\n"
        "팀장이 승인한다.\n\n"
        "## 이월\n"
        "미사용 연차는 이월하지 않는다.\n"
    )

    chunks = chunk_markdown(text, title="휴가 안내")

    assert [c.heading_path for c in chunks] == [
        ("휴가 규정",),
        ("휴가 규정", "신청 절차"),
        ("휴가 규정", "신청 절차", "승인권자"),
        ("휴가 규정", "이월"),
    ]
    assert [c.index for c in chunks] == [0, 1, 2, 3]
    assert chunks[2].body == "팀장이 승인한다."


def test_chunk_text_has_document_and_section_header() -> None:
    chunks = chunk_markdown("# 개요\n본문 내용\n\n## 세부\n세부 내용", title="안내서")

    assert chunks[1].text == "문서: 안내서\n절: 개요 > 세부\n\n세부 내용"


def test_preamble_before_first_heading_has_no_section_line() -> None:
    chunks = chunk_markdown("머리글 문단\n\n# 첫 절\n내용", title="안내서")

    assert chunks[0].heading_path == ()
    assert chunks[0].text == "문서: 안내서\n\n머리글 문단"


def test_heading_without_body_emits_no_chunk() -> None:
    chunks = chunk_markdown("# 상위\n\n## 하위\n내용", title="d")

    assert len(chunks) == 1
    assert chunks[0].heading_path == ("상위", "하위")


def test_headings_inside_code_fences_are_ignored() -> None:
    text = "# 설정\n예시는 아래와 같다.\n\n```bash\n# 주석이지 제목이 아님\necho hi\n```\n\n~~~\n## 이것도 아님\n~~~\n"

    chunks = chunk_markdown(text, title="d")

    assert len(chunks) == 1
    assert "# 주석이지 제목이 아님" in chunks[0].body
    assert "## 이것도 아님" in chunks[0].body


def test_level_five_heading_is_not_a_split_point() -> None:
    chunks = chunk_markdown("# 절\n앞\n\n##### 작은 제목\n뒤", title="d")

    assert len(chunks) == 1
    assert "##### 작은 제목" in chunks[0].body


def test_heading_requires_space_after_hashes() -> None:
    chunks = chunk_markdown("# 절\n#태그 는 제목이 아니다", title="d")

    assert len(chunks) == 1
    assert "#태그" in chunks[0].body


def test_closing_hashes_are_stripped_from_heading() -> None:
    chunks = chunk_markdown("## 제목 ##\n내용", title="d")

    assert chunks[0].heading_path == ("제목",)


def test_long_section_splits_on_paragraphs_within_limit() -> None:
    paragraphs = [f"문단 {i} " + "가" * 50 for i in range(10)]
    text = "# 긴 절\n" + "\n\n".join(paragraphs)

    chunks = chunk_markdown(text, title="d", max_chars=130)

    assert len(chunks) > 1
    assert all(len(c.body) <= 130 for c in chunks)
    assert all(c.heading_path == ("긴 절",) for c in chunks)
    rejoined = "\n\n".join(c.body for c in chunks)
    for p in paragraphs:
        assert p in rejoined


def test_long_table_splits_by_rows_and_repeats_header() -> None:
    header = "| 날짜 | 대상 | 내용 |\n| --- | --- | --- |"
    rows = [f"| 2026-01-{i:02d} | 절 {i} | 변경 내용 {i} |" for i in range(1, 21)]
    text = "# 변경 이력\n" + header + "\n" + "\n".join(rows)

    chunks = chunk_markdown(text, title="d", max_chars=200)

    assert len(chunks) > 1
    for c in chunks:
        assert c.body.startswith(header)
        assert len(c.body) <= 200
    found = [r for r in rows if any(r in c.body for c in chunks)]
    assert found == rows


def test_oversized_single_paragraph_is_hard_split() -> None:
    text = "# 절\n" + "가나다라마바사 " * 100

    chunks = chunk_markdown(text, title="d", max_chars=120)

    assert len(chunks) > 1
    assert all(0 < len(c.body) <= 120 for c in chunks)


def test_text_without_headings_is_chunked_by_paragraph() -> None:
    text = "\n\n".join(["첫 문단 " + "a" * 60, "둘째 문단 " + "b" * 60])

    chunks = chunk_markdown(text, title="memo.txt", max_chars=80)

    assert len(chunks) == 2
    assert all(c.heading_path == () for c in chunks)


def test_chunk_is_immutable() -> None:
    chunk = chunk_markdown("# a\nb", title="d")[0]

    with pytest.raises(AttributeError):
        chunk.body = "changed"  # type: ignore[misc]


def test_invalid_max_chars_is_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_markdown("# a\nb", title="d", max_chars=0)


def test_heading_only_document_keeps_leaf_heading() -> None:
    chunks = chunk_markdown("# 상위\n## 하위", title="d")

    assert [(c.heading_path, c.body) for c in chunks] == [(("상위", "하위"), "## 하위")]


def test_trailing_empty_heading_is_kept() -> None:
    chunks = chunk_markdown("# A\n본문\n## 부록", title="d")

    assert [c.body for c in chunks] == ["본문", "## 부록"]


def test_inline_triple_backticks_do_not_open_a_fence() -> None:
    chunks = chunk_markdown("```code``` 설명\n# 실제 제목\n본문", title="d")

    assert [c.heading_path for c in chunks] == [(), ("실제 제목",)]


def test_unclosed_fence_runs_to_end_of_document() -> None:
    chunks = chunk_markdown("# A\nx\n```\n# 제목 아님\n본문", title="d")

    assert len(chunks) == 1
    assert "# 제목 아님" in chunks[0].body


def test_fence_closes_only_with_same_marker_of_equal_or_greater_length() -> None:
    chunks = chunk_markdown("# A\n````\n~~~\n```\n# 아직 코드\n````\n# B\n본문", title="d")

    assert [c.heading_path for c in chunks] == [("A",), ("B",)]
    assert "# 아직 코드" in chunks[0].body


def test_table_glued_to_paragraph_is_split_as_its_own_block() -> None:
    rows = "\n".join(f"| {i} | 값 {i} |" for i in range(12))
    text = "# T\n설명 문단입니다.\n| 번호 | 값 |\n| --- | --- |\n" + rows

    chunks = chunk_markdown(text, title="d", max_chars=80)

    assert chunks[0].body == "설명 문단입니다."
    assert all(c.body.startswith("| 번호 | 값 |\n| --- | --- |") for c in chunks[1:])


def test_crlf_line_endings() -> None:
    chunks = chunk_markdown("# A\r\nx\r\n\r\n## B\r\ny", title="d")

    assert [(c.heading_path, c.body) for c in chunks] == [(("A",), "x"), (("A", "B"), "y")]


def test_first_line_indentation_is_preserved() -> None:
    chunks = chunk_markdown("# A\n    code line\n  next", title="d")

    assert chunks[0].body == "    code line\n  next"


def test_hard_split_keeps_text_and_indentation() -> None:
    line = "    print(\"" + "x" * 300 + " " + "y" * 300 + "\")"
    chunks = chunk_markdown("# A\n```python\n" + line + "\n```", title="d", max_chars=200)

    assert all(len(c.body) <= 200 for c in chunks)
    joined = "".join(c.body.replace("\n", "") for c in chunks)
    assert line in joined
    assert any(c.body.startswith("    print(") or "\n    print(" in c.body for c in chunks)


def test_blank_lines_inside_oversized_fence_are_kept() -> None:
    body = "\n\n".join(["l" * 50] * 3)
    chunks = chunk_markdown("# A\n```\n" + body + "\n```", title="d", max_chars=120)

    assert any("\n\n" in c.body for c in chunks)


def test_table_with_header_larger_than_limit_falls_back_to_line_split() -> None:
    table = "| 아주 긴 머리말 열 | 다른 열 |\n| --- | --- |\n| a | b |\n| c | d |"
    chunks = chunk_markdown("# T\n" + table, title="d", max_chars=20)

    assert all(len(c.body) <= 20 for c in chunks)
    assert any("| a | b |" in c.body for c in chunks)


def test_hostile_heading_whitespace_is_linear() -> None:
    import time

    start = time.perf_counter()
    chunk_markdown("# a" + " " * 200_000 + "x", title="d")

    assert time.perf_counter() - start < 1.0


def test_huge_single_line_is_linear() -> None:
    import time

    start = time.perf_counter()
    chunks = chunk_markdown("x" * 4_000_000, title="d")

    assert time.perf_counter() - start < 1.0
    assert sum(len(c.body) for c in chunks) == 4_000_000


@pytest.mark.parametrize(("raw", "expected"), [("abc", 1200), ("-1", 1200), ("0", 1200), (" 300 ", 300)])
def test_chunk_max_chars_env_parsing(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
    from opencrab.ontology.chunking import chunk_max_chars

    monkeypatch.setenv("OPENCRAB_CHUNK_MAX_CHARS", raw)

    assert chunk_max_chars() == expected


# ---------------------------------------------------------------------------
# document_title
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_id", "metadata", "expected"),
    [
        ("x", {"title": "명시 제목", "source_path": "/a/b.md"}, "명시 제목"),
        ("x", {"source_path": "/docs/휴가 규정.hwp"}, "휴가 규정"),
        ("/abs/path/report.pdf", {}, "report"),
        ("note-123", None, "note-123"),
    ],
)
def test_document_title(source_id: str, metadata: dict[str, Any] | None, expected: str) -> None:
    assert document_title(source_id, metadata) == expected


# ---------------------------------------------------------------------------
# HybridQuery.ingest with chunking
# ---------------------------------------------------------------------------


class FakeChroma:
    """In-memory stand-in for ChromaStore that records the call order."""

    available = True

    def __init__(self, records: dict[str, tuple[str, dict[str, Any]]] | None = None) -> None:
        self.records = dict(records or {})
        self.calls: list[str] = []
        self.fail_upsert = False

    def ids_where(self, where: dict[str, Any]) -> list[str]:
        self.calls.append("ids_where")
        return [i for i, (_, m) in self.records.items() if all(m.get(k) == v for k, v in where.items())]

    def existing_ids(self, ids: list[str]) -> list[str]:
        self.calls.append("existing_ids")
        return [i for i in ids if i in self.records]

    def upsert_texts(self, texts: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> list[str]:
        self.calls.append("upsert")
        if self.fail_upsert:
            raise RuntimeError("embedding failed")
        self.records.update({i: (t, m) for i, t, m in zip(ids, texts, metadatas)})
        return ids

    def delete(self, ids: list[str]) -> None:
        self.calls.append("delete")
        for i in ids:
            del self.records[i]


SAMPLE = "# 개요\n개요 내용\n\n## 세부\n세부 내용"


def _ingest(chroma: FakeChroma, text: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return HybridQuery(chroma, None).ingest(text, source_id, metadata)  # type: ignore[arg-type]


@pytest.fixture
def chunking_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    monkeypatch.delenv("OPENCRAB_CHUNK_MAX_CHARS", raising=False)


def test_ingest_without_chunking_keeps_single_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAB_CHUNKING", raising=False)
    chroma = FakeChroma()

    result = _ingest(chroma, SAMPLE, "doc-1", {"space": "resource"})

    assert list(chroma.records) == ["doc-1"]
    assert chroma.records["doc-1"][0] == SAMPLE
    assert chroma.calls == ["upsert"]
    assert result["vector_id"] == "doc-1"


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_chunking_flag_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", value)
    chroma = FakeChroma()

    _ingest(chroma, SAMPLE, "doc-3")

    assert list(chroma.records) == ["doc-3"]


@pytest.mark.usefixtures("chunking_on")
def test_ingest_with_chunking_writes_one_record_per_chunk() -> None:
    chroma = FakeChroma()
    meta = {"space": "resource", "source_path": "/docs/안내서.md"}

    result = _ingest(chroma, SAMPLE, "doc-1", meta)

    assert sorted(chroma.records) == ["doc-1#0", "doc-1#1"]
    text, second = chroma.records["doc-1#1"]
    assert text == "문서: 안내서\n절: 개요 > 세부\n\n세부 내용"
    assert second["source_id"] == "doc-1"
    assert second["node_id"] == "doc-1#1"
    assert second["space"] == "resource"
    assert second["chunk_index"] == 1
    assert second["chunk_count"] == 2
    assert second["heading_path"] == "개요 > 세부"
    assert second["doc_title"] == "안내서"
    assert result["chunks"] == 2
    assert result["vector_ids"] == ["doc-1#0", "doc-1#1"]
    assert chroma.calls.count("upsert") == 1
    assert meta == {"space": "resource", "source_path": "/docs/안내서.md"}


@pytest.mark.usefixtures("chunking_on")
def test_caller_node_id_is_kept_as_source_node_id() -> None:
    chroma = FakeChroma()

    _ingest(chroma, SAMPLE, "doc-1", {"node_id": "policy-node"})

    node_ids = {m["node_id"] for _, m in chroma.records.values()}
    assert node_ids == {"doc-1#0", "doc-1#1"}
    assert all(m["source_node_id"] == "policy-node" for _, m in chroma.records.values())


@pytest.mark.usefixtures("chunking_on")
def test_reserved_metadata_keys_override_caller_values() -> None:
    chroma = FakeChroma()

    _ingest(chroma, SAMPLE, "doc-1", {"chunk_index": 99, "heading_path": "x", "source_id": "other"})

    _, meta = chroma.records["doc-1#1"]
    assert (meta["chunk_index"], meta["heading_path"], meta["source_id"]) == (1, "개요 > 세부", "doc-1")


def test_ingest_chunking_respects_max_chars_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_CHUNKING", "true")
    monkeypatch.setenv("OPENCRAB_CHUNK_MAX_CHARS", "60")
    chroma = FakeChroma()
    text = "# 절\n" + "\n\n".join("문단 " + "가" * 40 for _ in range(4))

    _ingest(chroma, text, "doc-2")

    assert len(chroma.records) == 4


@pytest.mark.usefixtures("chunking_on")
def test_reingest_upserts_before_deleting_only_stale_chunks() -> None:
    old = {"source_id": "doc-1"}
    chroma = FakeChroma({i: ("old", old) for i in ["doc-1", "doc-1#0", "doc-1#1", "doc-1#2"]})

    _ingest(chroma, SAMPLE, "doc-1")

    assert sorted(chroma.records) == ["doc-1#0", "doc-1#1"]
    assert chroma.calls.index("upsert") < chroma.calls.index("delete")


@pytest.mark.usefixtures("chunking_on")
def test_failed_upsert_keeps_existing_chunks() -> None:
    old = {"source_id": "doc-1"}
    chroma = FakeChroma({"doc-1#0": ("old", old), "doc-1#5": ("old", old)})
    chroma.fail_upsert = True

    result = _ingest(chroma, SAMPLE, "doc-1")

    assert sorted(chroma.records) == ["doc-1#0", "doc-1#5"]
    assert "delete" not in chroma.calls
    assert result["stores"]["chromadb"].startswith("error")


@pytest.mark.usefixtures("chunking_on")
def test_chunk_id_owned_by_another_source_is_not_overwritten() -> None:
    chroma = FakeChroma({"doc#0": ("original", {"source_id": "doc#0"})})

    result = _ingest(chroma, "replacement", "doc")

    assert chroma.records == {"doc#0": ("original", {"source_id": "doc#0"})}
    assert "upsert" not in chroma.calls
    assert result["stores"]["chromadb"].startswith("error: chunk ids already used")


@pytest.mark.usefixtures("chunking_on")
def test_reingest_with_no_content_removes_previous_chunks() -> None:
    chroma = FakeChroma({"doc-4#0": ("old", {"source_id": "doc-4"})})

    result = _ingest(chroma, "   ", "doc-4")

    assert chroma.records == {}
    assert "upsert" not in chroma.calls
    assert result["chunks"] == 0
    assert result["stores"]["chromadb"] == "ok (0 chunks)"


@pytest.mark.usefixtures("chunking_on")
def test_unavailable_store_reports_unavailable() -> None:
    chroma = FakeChroma()
    chroma.available = False

    result = _ingest(chroma, SAMPLE, "doc-5")

    assert result["stores"]["chromadb"] == "unavailable"
    assert chroma.calls == []


# ---------------------------------------------------------------------------
# Real local Chroma round trip
# ---------------------------------------------------------------------------


def test_chunked_ingest_round_trip_with_local_chroma(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opencrab.stores.chroma_store import ChromaStore

    store = ChromaStore("unused", 0, "chunk_test", local_mode=True, local_path=str(tmp_path / "chroma"))
    if not store.available:
        pytest.skip("local chromadb unavailable")
    hybrid = HybridQuery(store, None)  # type: ignore[arg-type]

    monkeypatch.delenv("OPENCRAB_CHUNKING", raising=False)
    hybrid.ingest("whole document", "doc-rt")
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    hybrid.ingest("# A\nalpha\n\n# B\nbeta\n\n# C\ngamma", "doc-rt")
    hybrid.ingest("# A\nalpha only", "doc-rt")

    assert store.count() == 1
    assert store.get_by_id("doc-rt#0")["metadata"]["heading_path"] == "A"


def test_existing_ids_with_empty_list(tmp_path) -> None:
    from opencrab.stores.chroma_store import ChromaStore

    store = ChromaStore("unused", 0, "chunk_empty", local_mode=True, local_path=str(tmp_path / "chroma"))
    if not store.available:
        pytest.skip("local chromadb unavailable")

    assert store.existing_ids([]) == []


def test_round_trip_refuses_to_overwrite_another_sources_record(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opencrab.stores.chroma_store import ChromaStore

    store = ChromaStore("unused", 0, "chunk_conflict", local_mode=True, local_path=str(tmp_path / "chroma"))
    if not store.available:
        pytest.skip("local chromadb unavailable")
    hybrid = HybridQuery(store, None)  # type: ignore[arg-type]

    monkeypatch.delenv("OPENCRAB_CHUNKING", raising=False)
    hybrid.ingest("other document", "x#0")
    monkeypatch.setenv("OPENCRAB_CHUNKING", "1")
    result = hybrid.ingest("# A\nalpha", "x")

    assert result["stores"]["chromadb"].startswith("error")
    assert store.get_by_id("x#0")["document"] == "other document"
