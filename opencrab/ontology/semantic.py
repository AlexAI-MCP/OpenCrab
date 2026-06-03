from __future__ import annotations

import hashlib
import re
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "not",
    "of",
    "on",
    "or",
    "the",
    "to",
    "use",
    "was",
    "were",
    "with",
}

STATUS_WORDS = {
    "allow",
    "allowed",
    "block",
    "blocked",
    "complete",
    "completed",
    "fail",
    "failed",
    "go",
    "pass",
    "passed",
    "refine",
    "reject",
    "rejected",
    "결론",
    "결정",
    "금지",
    "완료",
    "차단",
    "통과",
    "허용",
}


def hash_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def title_from_metadata(source_id: str, meta: dict[str, Any]) -> str:
    for key in ("title", "note_name", "source_title", "name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return source_id


def normalise_label(value: str) -> str:
    value = re.sub(r"[_/\\]+", " ", value)
    value = re.sub(r"^\d{4}[- ]\d{2}[- ]\d{2}\s*", "", value)
    value = re.sub(r"\b\d{8,}\b", "", value)
    value = re.sub(r"\s+", " ", value).strip(" -:;,.[](){}\t\r\n")
    return value


def is_semantic_label(label: str) -> bool:
    label = normalise_label(label)
    if not label:
        return False
    tokens = re.findall(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_-]*", label)
    if not tokens:
        return False
    lowered = [token.lower() for token in tokens]
    if len(tokens) == 1 and lowered[0] in STOPWORDS | STATUS_WORDS:
        return False
    if len(tokens) == 1 and len(tokens[0]) < 4 and "-" not in tokens[0]:
        return False
    if all(token in STOPWORDS | STATUS_WORDS for token in lowered):
        return False
    return True


def dedupe_labels(labels: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        clean = normalise_label(label)
        key = clean.lower()
        if not is_semantic_label(clean) or key in seen:
            continue
        seen.add(key)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def semantic_concepts(text: str, title: str, meta: dict[str, Any], limit: int = 8) -> list[str]:
    candidates: list[str] = []

    for value in (meta.get("concepts"), meta.get("tags"), meta.get("topics")):
        if isinstance(value, list):
            candidates.extend(str(item) for item in value)
        elif isinstance(value, str):
            candidates.extend(re.split(r"[,;|]", value))

    candidates.extend(re.split(r"\s+-\s+|\s+\|\s+|:\s+", title))

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            candidates.append(stripped.lstrip("#").strip())
        elif re.match(r"^[A-Z0-9][A-Za-z0-9가-힣 _/-]{8,80}:$", stripped):
            candidates.append(stripped.rstrip(":"))

    phrase_re = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9_-]+|[a-z]+-[a-z0-9_-]+|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z0-9_-]+|[a-z]+-[a-z0-9_-]+|[A-Z]{2,})){0,5}\b"
    )
    candidates.extend(match.group(0) for match in phrase_re.finditer(text[:4000]))

    return dedupe_labels(candidates, limit)


def semantic_claims(text: str, limit: int = 4) -> list[str]:
    candidates: list[str] = []
    for raw_line in text.splitlines():
        line = normalise_label(raw_line)
        if len(line) < 12 or len(line) > 240:
            continue
        lowered = line.lower()
        if any(word in lowered for word in STATUS_WORDS):
            candidates.append(line)
    return dedupe_labels(candidates, limit)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    result: list[str] = []
    for part in parts:
        sentence = normalise_label(part)
        if 12 <= len(sentence) <= 260:
            result.append(sentence)
    return result


def _pick_sentence(sentences: list[str], keywords: set[str], fallback: str) -> str:
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            return sentence
    return fallback


def core_sentence_nodes(text: str, title: str) -> dict[str, str]:
    sentences = _sentences(text)
    fallback = sentences[0] if sentences else title
    evidence_sentence = _pick_sentence(
        sentences,
        {"evidence", "근거", "증거", "확인", "observed", "source"},
        fallback,
    )
    concept_sentence = _pick_sentence(
        sentences,
        {"concept", "개념", "topic", "meaning", "semantic", "온톨로지"},
        evidence_sentence,
    )
    status_sentence = _pick_sentence(
        sentences,
        STATUS_WORDS | {"status", "상태", "완료", "진행", "blocked", "pending"},
        evidence_sentence,
    )
    judgment_sentence = _pick_sentence(
        sentences,
        {"judgment", "판단", "decision", "결론", "should", "must", "해야", "된다"},
        status_sentence,
    )
    return {
        "document": title,
        "evidence": evidence_sentence,
        "concept": concept_sentence,
        "status": status_sentence,
        "judgment": judgment_sentence,
    }


def write_semantic_graph(
    builder: Any,
    *,
    source_id: str,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    graph_result: dict[str, Any] = {
        "mode": "sentence_graph",
        "document_node_id": None,
        "evidence_node_id": None,
        "concept_node_id": None,
        "status_node_id": None,
        "judgment_node_id": None,
        "sentence_nodes": {},
        "edges_written": 0,
        "errors": [],
    }
    title = title_from_metadata(source_id, metadata)
    sentences = core_sentence_nodes(text, title)
    doc_id = metadata.get("node_id") if isinstance(metadata.get("node_id"), str) else hash_id("doc", source_id)
    evidence_id = hash_id("evidence", f"{source_id}:text")
    concept_id = hash_id("concept", f"{source_id}:concept:{sentences['concept'].lower()}")
    status_id = hash_id("claim", f"{source_id}:status:{sentences['status'].lower()}")
    judgment_id = hash_id("claim", f"{source_id}:judgment:{sentences['judgment'].lower()}")
    provenance = {
        "source_id": source_id,
        "source_url": metadata.get("source_url"),
        "source_type": metadata.get("source_type") or metadata.get("source"),
        "storage_mode": "ontology",
        "extraction_mode": "sentence_graph",
    }

    builder.add_node(
        space="resource",
        node_type="Document",
        node_id=doc_id,
        properties={
            **provenance,
            "title": title,
            "sentence": sentences["document"],
            "semantic_role": "document",
            "source_title": metadata.get("source_title") or title,
            "content_chars": len(text),
            "content_bytes": len(text.encode("utf-8", errors="replace")),
            "raw_content_stored": False,
        },
    )
    graph_result["document_node_id"] = doc_id
    graph_result["sentence_nodes"]["document"] = doc_id

    builder.add_node(
        space="evidence",
        node_type="TextUnit",
        node_id=evidence_id,
        properties={
            **provenance,
            "title": f"{title} / evidence",
            "sentence": sentences["evidence"],
            "content": sentences["evidence"],
            "semantic_role": "evidence",
            "content_chars": len(text),
            "content_bytes": len(text.encode("utf-8", errors="replace")),
            "raw_content_stored": True,
        },
    )
    graph_result["evidence_node_id"] = evidence_id
    graph_result["sentence_nodes"]["evidence"] = evidence_id

    builder.add_edge(
        from_space="resource",
        from_id=doc_id,
        relation="contains",
        to_space="evidence",
        to_id=evidence_id,
        properties=provenance,
    )
    graph_result["edges_written"] += 1

    builder.add_node(
        space="concept",
        node_type="Concept",
        node_id=concept_id,
        properties={
            **provenance,
            "title": sentences["concept"][:120],
            "label": sentences["concept"],
            "sentence": sentences["concept"],
            "semantic_role": "concept",
            "source_title": title,
        },
    )
    builder.add_edge(
        from_space="evidence",
        from_id=evidence_id,
        relation="describes",
        to_space="concept",
        to_id=concept_id,
        properties=provenance,
    )
    graph_result["concept_node_id"] = concept_id
    graph_result["sentence_nodes"]["concept"] = concept_id
    graph_result["edges_written"] += 1

    for role, node_id, sentence in (
        ("status", status_id, sentences["status"]),
        ("judgment", judgment_id, sentences["judgment"]),
    ):
        builder.add_node(
            space="claim",
            node_type="Claim",
            node_id=node_id,
            properties={
                **provenance,
                "title": sentence[:120],
                "statement": sentence,
                "sentence": sentence,
                "semantic_role": role,
                "status": "candidate",
                "confidence": 0.7,
                "source_title": title,
            },
        )
        builder.add_edge(
            from_space="evidence",
            from_id=evidence_id,
            relation="supports",
            to_space="claim",
            to_id=node_id,
            properties={**provenance, "semantic_role": role},
        )
        graph_result[f"{role}_node_id"] = node_id
        graph_result["sentence_nodes"][role] = node_id
        graph_result["edges_written"] += 1

    return graph_result
