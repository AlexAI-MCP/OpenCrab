from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from opencrab.mcp.compact import encode_tool_result

CHUNK_RESULT = {
    "source": "hybrid",
    "node_id": "/data/docs/출장 규정.md#3",
    "score": 0.912345678,
    "text": "문서: 출장 규정\n절: 출장비 > 숙박비\n\n국내 숙박비 상한은 1박 12만 원이다.",
    "metadata": {
        "source_id": "/data/docs/출장 규정.md",
        "source_path": "/data/docs/출장 규정.md",
        "extension": ".md",
        "parser": "text",
        "doc_title": "출장 규정",
        "heading_path": "출장비 > 숙박비",
        "node_id": "/data/docs/출장 규정.md#3",
        "chunk_index": 3,
        "chunk_count": 9,
        "space": "policy",
    },
    "graph_context": None,
}
NODE_RESULT = {
    "source": "graph",
    "node_id": "policy-travel",
    "score": 0.5,
    "text": "출장 정책",
    "metadata": {"title": "출장 정책", "owner": "총무팀"},
    "graph_context": {"anchor_id": "x", "relation_type": "supports"},
}
QUERY = {"question": "숙박비 한도", "total": 2, "results": [CHUNK_RESULT, NODE_RESULT]}


@pytest.fixture
def compact_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCRAB_COMPACT_RESULTS", "1")


def test_default_encoding_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCRAB_COMPACT_RESULTS", raising=False)

    text = encode_tool_result("ontology_query", QUERY)

    assert text == json.dumps(QUERY, ensure_ascii=True, default=str)


@pytest.mark.usefixtures("compact_on")
def test_korean_is_sent_as_text_not_escapes() -> None:
    text = encode_tool_result("ontology_query", QUERY)

    assert "숙박비" in text
    assert "\\u" not in text
    assert len(text) < len(json.dumps(QUERY, ensure_ascii=True, default=str)) / 2


@pytest.mark.usefixtures("compact_on")
def test_lone_surrogates_are_replaced() -> None:
    text = encode_tool_result("ontology_ingest", {"text": "깨진\ud800문자"})

    assert "\ud800" not in text
    assert json.loads(text) == {"text": "깨진�문자"}
    text.encode("utf-8")  # must not raise


@pytest.mark.usefixtures("compact_on")
def test_chunk_metadata_keeps_only_what_the_text_does_not_say() -> None:
    result = json.loads(encode_tool_result("ontology_query", QUERY))

    chunk = result["results"][0]
    assert chunk["metadata"] == {"chunk_index": 3, "chunk_count": 9, "space": "policy"}
    assert chunk["node_id"] == "/data/docs/출장 규정.md#3"
    assert chunk["text"] == CHUNK_RESULT["text"]
    assert chunk["score"] == 0.9123
    assert "graph_context" not in chunk


@pytest.mark.usefixtures("compact_on")
def test_non_chunk_results_keep_their_metadata() -> None:
    result = json.loads(encode_tool_result("ontology_query", QUERY))

    node = result["results"][1]
    assert node["metadata"] == NODE_RESULT["metadata"]
    assert node["graph_context"] == NODE_RESULT["graph_context"]


@pytest.mark.usefixtures("compact_on")
def test_other_tools_are_not_reshaped() -> None:
    payload = {"results": [CHUNK_RESULT]}

    result = json.loads(encode_tool_result("query_bm25", payload))

    assert result == json.loads(json.dumps(payload))


@pytest.mark.usefixtures("compact_on")
def test_input_is_not_mutated() -> None:
    before = json.dumps(QUERY, sort_keys=True)

    encode_tool_result("ontology_query", QUERY)

    assert json.dumps(QUERY, sort_keys=True) == before


@pytest.mark.usefixtures("compact_on")
def test_non_json_values_still_encode() -> None:
    from datetime import date

    text = encode_tool_result("ontology_query", {"results": [], "when": date(2026, 10, 12)})

    assert json.loads(text)["when"] == "2026-10-12"


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_flag_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OPENCRAB_COMPACT_RESULTS", value)

    assert encode_tool_result("ontology_query", QUERY) == json.dumps(
        QUERY, ensure_ascii=True, default=str
    )


def test_server_tools_call_uses_the_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    from opencrab.mcp.server import MCPServer

    monkeypatch.setenv("OPENCRAB_COMPACT_RESULTS", "1")
    with patch("opencrab.mcp.server.get_settings") as cfg:
        cfg.return_value.mcp_server_name = "t"
        cfg.return_value.mcp_server_version = "0"
        server = MCPServer()
    with patch("opencrab.mcp.server.dispatch_tool", return_value=QUERY):
        response: dict[str, Any] = server._handle_tools_call(
            {"name": "ontology_query", "arguments": {}}
        )

    text = response["content"][0]["text"]
    assert "숙박비" in text
    assert json.loads(text)["results"][0]["metadata"] == {
        "chunk_index": 3,
        "chunk_count": 9,
        "space": "policy",
    }


@pytest.mark.usefixtures("compact_on")
def test_unexpected_shapes_pass_through() -> None:
    assert json.loads(encode_tool_result("ontology_query", {"results": "none"})) == {
        "results": "none"
    }
    assert json.loads(encode_tool_result("ontology_query", {"results": [1, "x"]})) == {
        "results": [1, "x"]
    }
    assert json.loads(encode_tool_result("ontology_query", ["a"])) == ["a"]


@pytest.mark.usefixtures("compact_on")
def test_chunk_graph_context_is_kept_when_present() -> None:
    item = {**CHUNK_RESULT, "graph_context": {"anchor_id": "a"}}

    result = json.loads(encode_tool_result("ontology_query", {"results": [item]}))

    assert result["results"][0]["graph_context"] == {"anchor_id": "a"}


@pytest.mark.usefixtures("compact_on")
def test_surrogate_pairs_are_joined_not_replaced() -> None:
    high, low = chr(0xD840), chr(0xDC00)  # a pair encoding U+20000, held as two code points
    emoji_high, emoji_low = chr(0xD83D), chr(0xDE00)  # U+1F600
    payload = {"node_id": "doc-" + high + low, "text": emoji_high + emoji_low + " and lone " + low}

    result = json.loads(encode_tool_result("query_bm25", payload))

    assert result == {
        "node_id": "doc-" + chr(0x20000),
        "text": chr(0x1F600) + " and lone " + chr(0xFFFD),
    }


@pytest.mark.usefixtures("compact_on")
def test_user_metadata_on_chunks_is_kept() -> None:
    item = {
        **CHUNK_RESULT,
        "metadata": {**CHUNK_RESULT["metadata"], "author": "김담당", "url": "https://x"},
    }

    result = json.loads(encode_tool_result("ontology_query", {"results": [item]}))

    assert result["results"][0]["metadata"] == {
        "chunk_index": 3,
        "chunk_count": 9,
        "space": "policy",
        "author": "김담당",
        "url": "https://x",
    }


@pytest.mark.usefixtures("compact_on")
def test_results_that_are_not_chunk_records_keep_all_metadata() -> None:
    node = {
        "source": "graph",
        "node_id": "policy-travel",
        "score": 0.5,
        "text": "출장 정책",
        "metadata": {"chunk_index": 0, "owner": "총무팀", "source_id": "source-7"},
    }

    result = json.loads(encode_tool_result("ontology_query", {"results": [node]}))

    assert result["results"][0]["metadata"] == node["metadata"]


@pytest.mark.usefixtures("compact_on")
@pytest.mark.parametrize("score", [None, 1])
def test_non_float_scores_are_left_alone(score: Any) -> None:
    item = {**CHUNK_RESULT, "score": score}

    result = json.loads(encode_tool_result("ontology_query", {"results": [item]}))

    assert result["results"][0]["score"] == score


@pytest.mark.usefixtures("compact_on")
def test_title_and_section_are_kept_when_the_text_does_not_carry_them() -> None:
    item = {
        "node_id": "doc#3",
        "text": "숙박비 상한은 12만원",
        "metadata": {
            "source_id": "doc",
            "chunk_index": 3,
            "doc_title": "대전 지점 정책",
            "heading_path": "임원 전용",
            "source_path": "/policies/executive.md",
        },
    }

    result = json.loads(encode_tool_result("ontology_query", {"results": [item]}))

    assert result["results"][0]["metadata"] == {
        "chunk_index": 3,
        "doc_title": "대전 지점 정책",
        "heading_path": "임원 전용",
        "source_path": "/policies/executive.md",
    }


@pytest.mark.usefixtures("compact_on")
def test_source_path_is_dropped_only_when_it_equals_the_source_id() -> None:
    item = {
        **CHUNK_RESULT,
        "metadata": {**CHUNK_RESULT["metadata"], "source_path": "/elsewhere/출장.hwp"},
    }

    result = json.loads(encode_tool_result("ontology_query", {"results": [item]}))

    assert result["results"][0]["metadata"]["source_path"] == "/elsewhere/출장.hwp"
    assert "doc_title" not in result["results"][0]["metadata"]
