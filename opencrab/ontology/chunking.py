"""
Heading-aware document chunking for ingest.

Long documents embedded as a single vector are effectively invisible to
search: the embedding model only reads the opening tokens. This module
splits Markdown (including Kordoc output from HWP/PDF) into section-sized
chunks so each one is embedded on its own.

Rules:
  1. Split at ATX headings ``#`` to ``####`` (outside code fences).
  2. A section longer than ``max_chars`` is split again at paragraph
     boundaries; pipe tables are split by rows with the header repeated;
     a single oversized line is hard-split, preferring whitespace, without
     dropping non-whitespace characters.
  3. Each chunk is prefixed with the document title and its heading path so
     the chunk is self-describing in search results.

Enabled at ingest time with ``OPENCRAB_CHUNKING=1``; the body size limit is
``OPENCRAB_CHUNK_MAX_CHARS`` (default 1200).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 1200
_MAX_HEADING_LEVEL = 4
_TRUTHY = {"1", "true", "yes", "on"}

_HEADING_START_RE = re.compile(r" {0,3}(#{1,6})(?:[ \t]|$)")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)*\|?$")


@dataclass(frozen=True)
class Chunk:
    """One embeddable piece of a document."""

    index: int
    heading_path: tuple[str, ...]
    body: str
    text: str


def chunking_enabled() -> bool:
    return os.getenv("OPENCRAB_CHUNKING", "").strip().lower() in _TRUTHY


def chunk_max_chars() -> int:
    raw = os.getenv("OPENCRAB_CHUNK_MAX_CHARS", "").strip()
    if not raw:
        return DEFAULT_MAX_CHARS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        logger.warning("Invalid OPENCRAB_CHUNK_MAX_CHARS=%r; using %d", raw, DEFAULT_MAX_CHARS)
        return DEFAULT_MAX_CHARS
    return value


def document_title(source_id: str, metadata: dict[str, Any] | None = None) -> str:
    """Pick a human-readable title for chunk headers."""
    meta = metadata or {}
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    source_path = meta.get("source_path")
    if isinstance(source_path, str) and source_path.strip():
        return PurePath(source_path).stem
    if "/" in source_id or "\\" in source_id:
        return PurePath(source_id.replace("\\", "/")).stem
    return source_id


def chunk_markdown(text: str, title: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    """Split Markdown text into heading-scoped chunks of at most ``max_chars`` body characters."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    pieces: list[tuple[tuple[str, ...], str]] = []
    for path, body in _sections(text):
        for part in _split_body(body, max_chars):
            pieces.append((path, part))

    return [
        Chunk(index=i, heading_path=path, body=body, text=_with_header(title, path, body))
        for i, (path, body) in enumerate(pieces)
    ]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Section:
    level: int  # 0 for text before the first heading
    path: tuple[str, ...]
    heading_line: str
    body: str


def _sections(text: str) -> list[tuple[tuple[str, ...], str]]:
    raw = _raw_sections(text)
    sections: list[tuple[tuple[str, ...], str]] = []
    for i, section in enumerate(raw):
        body = section.body
        # A heading with no body and no subsections would vanish; keep its line.
        is_leaf = i + 1 == len(raw) or raw[i + 1].level <= section.level
        if not body and section.level and is_leaf:
            body = section.heading_line.strip()
        if body:
            sections.append((section.path, body))
    return sections


def _raw_sections(text: str) -> list[_Section]:
    raw: list[_Section] = []
    stack: list[tuple[int, str]] = []
    heading_line = ""
    lines: list[str] = []
    fence: str | None = None

    def flush() -> None:
        level = stack[-1][0] if stack else 0
        body = _trim_blank_lines(lines)
        if level or body:
            raw.append(_Section(level, tuple(t for _, t in stack), heading_line, body))

    for line in text.splitlines():
        fence = _next_fence_state(line, fence)
        heading = None if fence is not None else _parse_heading(line)
        if heading is None:
            lines.append(line)
            continue
        flush()
        lines = []
        heading_line = line
        level, heading_title = heading
        stack = [entry for entry in stack if entry[0] < level] + [(level, heading_title)]
    flush()
    return raw


def _trim_blank_lines(lines: list[str]) -> str:
    """Drop leading and trailing blank lines, keeping indentation of the rest."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def _next_fence_state(line: str, fence: str | None) -> str | None:
    """Return the open fence marker after ``line`` (None when outside a fence)."""
    match = _FENCE_RE.match(line)
    if not match:
        return fence
    marker = match.group(1)
    if fence is None:
        # A backtick fence's info string cannot contain backticks (inline code).
        if marker[0] == "`" and "`" in line.strip()[len(marker):]:
            return None
        return marker
    if marker[0] == fence[0] and len(marker) >= len(fence) and not line.strip()[len(marker):].strip():
        return None
    return fence


def _parse_heading(line: str) -> tuple[int, str] | None:
    # String methods instead of a full-line regex: linear time on hostile input.
    match = _HEADING_START_RE.match(line)
    if not match or len(match.group(1)) > _MAX_HEADING_LEVEL:
        return None
    title = line[match.end():].strip(" \t")
    without_closing = title.rstrip("#")
    if without_closing != title and (not without_closing or without_closing[-1] in " \t"):
        title = without_closing.rstrip(" \t")
    return (len(match.group(1)), title) if title else None


# ---------------------------------------------------------------------------
# Splitting oversized sections
# ---------------------------------------------------------------------------


def _split_body(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    parts: list[str] = []
    for block in _blocks(body):
        parts.extend(_split_block(block, max_chars))
    return _pack(parts, max_chars, "\n\n")


def _blocks(body: str) -> list[str]:
    """Split on blank lines and table boundaries, never inside a code fence."""
    blocks: list[str] = []
    current: list[str] = []
    fence: str | None = None

    def flush() -> None:
        block = "\n".join(current).strip("\n")
        if block.strip():
            blocks.append(block)

    for line in body.splitlines():
        was_in_fence = fence is not None
        fence = _next_fence_state(line, fence)
        if not was_in_fence and fence is None:
            if not line.strip():
                flush()
                current = []
                continue
            if current and _is_table_line(line) != _is_table_line(current[-1]):
                flush()
                current = []
        current.append(line)
    flush()
    return blocks


def _split_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    lines = block.splitlines()
    if _is_table(lines):
        return _split_table(lines, max_chars)
    pieces: list[str] = []
    for line in lines:
        pieces.extend(_hard_split(line, max_chars))
    return _pack(pieces, max_chars, "\n")


def _split_table(lines: list[str], max_chars: int) -> list[str]:
    header = "\n".join(lines[:2])
    rows = lines[2:]
    row_budget = max_chars - len(header) - 1
    if row_budget <= 0:
        return _pack([p for line in lines for p in _hard_split(line, max_chars)], max_chars, "\n")
    row_pieces = [p for row in rows for p in _hard_split(row, row_budget)]
    return [f"{header}\n{group}" for group in _pack(row_pieces, row_budget, "\n")]


def _hard_split(line: str, max_chars: int) -> list[str]:
    """Cut ``line`` into pieces of at most ``max_chars``; ``"".join(pieces) == line``.

    Cuts land on the last space before the limit (never inside leading
    indentation), else exactly at the limit.
    """
    indent = len(line) - len(line.lstrip(" \t"))
    pieces: list[str] = []
    start = 0
    while len(line) - start > max_chars:
        end = start + max_chars
        cut = line.rfind(" ", max(start, indent) + 1, end + 1)
        if cut <= start:
            cut = end
        pieces.append(line[start:cut])
        start = cut
    pieces.append(line[start:])
    return pieces


def _pack(pieces: list[str], max_chars: int, sep: str) -> list[str]:
    """Greedily join consecutive pieces while they fit; drop whitespace-only results."""
    packed: list[str] = []
    current: str | None = None
    for piece in pieces:
        if current is None:
            current = piece
            continue
        candidate = f"{current}{sep}{piece}"
        if len(candidate) > max_chars:
            packed.append(current)
            current = piece
        else:
            current = candidate
    if current is not None:
        packed.append(current)
    return [p for p in packed if p.strip()]


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_table(lines: list[str]) -> bool:
    return (
        len(lines) >= 3
        and all(_is_table_line(line) for line in lines)
        and bool(_TABLE_SEPARATOR_RE.match(lines[1].strip()))
    )


def chunk_header(title: str, path: tuple[str, ...]) -> str:
    """The lines that open every chunk's text: document title, then section path."""
    header = f"문서: {title}"
    if path:
        header += "\n절: " + " > ".join(path)
    return header


def _with_header(title: str, path: tuple[str, ...], body: str) -> str:
    return f"{chunk_header(title, path)}\n\n{body}"
