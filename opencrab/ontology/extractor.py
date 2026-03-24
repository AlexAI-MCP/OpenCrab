"""
LLM-based entity and relationship extractor for MetaOntology.

Given raw text, calls Claude to extract nodes and edges in 9-Space grammar
format, then writes them into the ontology stores.
"""

from __future__ import annotations

import json
import logging
import os
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Grammar summary injected into the extraction prompt
_GRAMMAR_SUMMARY = """
MetaOntology 9-Space grammar:

SPACES and valid node types:
  subject  → User, Team, Org, Agent
  resource → Project, Document, File, Dataset, Tool, API
  evidence → TextUnit, LogEntry, Evidence
  concept  → Entity, Concept, Topic, Class
  claim    → Claim, Covariate
  community→ Community, CommunityReport
  outcome  → Outcome, KPI, Risk
  lever    → Lever
  policy   → Policy, Sensitivity, ApprovalRule

Valid meta-edges (from_space → to_space: [relations]):
  subject  → resource  : owns, member_of, manages, can_view, can_edit, can_execute, can_approve
  resource → evidence  : contains, derived_from, logged_as
  evidence → concept   : mentions, describes, exemplifies
  evidence → claim     : supports, contradicts, timestamps
  concept  → concept   : related_to, subclass_of, part_of, influences, depends_on
  concept  → outcome   : contributes_to, constrains, predicts, degrades
  lever    → outcome   : raises, lowers, stabilizes, optimizes
  lever    → concept   : affects
  community→ concept   : clusters, summarizes
  policy   → resource  : protects, classifies, restricts
  policy   → subject   : permits, denies, requires_approval
""".strip()


@dataclass
class ExtractedNode:
    space: str
    node_type: str
    node_id: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedEdge:
    from_space: str
    from_id: str
    relation: str
    to_space: str
    to_id: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    source_id: str
    nodes: list[ExtractedNode]
    edges: list[ExtractedEdge]
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.nodes) + len(self.edges)


class LLMExtractor:
    """
    Extracts ontology nodes and edges from text using Claude.

    Parameters
    ----------
    api_key:
        Anthropic API key. Defaults to ANTHROPIC_API_KEY env var.
    model:
        Claude model to use for extraction.
    chunk_size:
        Approximate character length per text chunk.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
        chunk_size: int = 3000,
    ) -> None:
        import anthropic

        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        self.model = model
        self.chunk_size = chunk_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_from_text(self, text: str, source_id: str) -> ExtractionResult:
        """Extract nodes and edges from a single text document."""
        chunks = self._split(text)
        all_nodes: list[ExtractedNode] = []
        all_edges: list[ExtractedEdge] = []
        errors: list[str] = []

        for i, chunk in enumerate(chunks):
            try:
                nodes, edges = self._extract_chunk(chunk, source_id, chunk_index=i)
                all_nodes.extend(nodes)
                all_edges.extend(edges)
            except Exception as exc:
                logger.warning("Chunk %d extraction failed: %s", i, exc)
                errors.append(str(exc))

        # De-duplicate nodes by node_id
        seen: set[str] = set()
        unique_nodes = []
        for n in all_nodes:
            if n.node_id not in seen:
                seen.add(n.node_id)
                unique_nodes.append(n)

        return ExtractionResult(
            source_id=source_id,
            nodes=unique_nodes,
            edges=all_edges,
            errors=errors,
        )

    def extract_from_file(self, path: str | Path) -> ExtractionResult:
        """Extract ontology elements from a file."""
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="ignore")
        return self.extract_from_text(text, source_id=str(p.resolve()))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split(self, text: str) -> list[str]:
        """Split text into chunks at paragraph boundaries."""
        paragraphs = re.split(r"\n{2,}", text)
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) > self.chunk_size and current:
                chunks.append(current.strip())
                current = para
            else:
                current = current + "\n\n" + para if current else para
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text[: self.chunk_size]]

    def _extract_chunk(
        self, chunk: str, source_id: str, chunk_index: int
    ) -> tuple[list[ExtractedNode], list[ExtractedEdge]]:
        """Call Claude to extract nodes and edges from one chunk."""
        prompt = textwrap.dedent(f"""
            You are an expert knowledge graph builder using the MetaOntology OS grammar.

            {_GRAMMAR_SUMMARY}

            Source file: {source_id}

            Analyze the following text and extract ALL meaningful entities (nodes) and
            relationships (edges) according to the grammar above.

            Rules:
            - node_id must be a stable snake_case identifier (e.g. "alexlee_agent", "albabot_project")
            - Only use spaces and node_types listed in the grammar
            - Only use relations listed in the grammar for the given space pair
            - Extract at least 3-5 nodes if there is meaningful content
            - If no clear entities exist, return empty arrays

            Text:
            ---
            {chunk[:2500]}
            ---

            Respond ONLY with valid JSON in this exact format:
            {{
              "nodes": [
                {{"space": "subject", "node_type": "Agent", "node_id": "example_agent", "properties": {{"name": "Example", "description": "..."}}}}
              ],
              "edges": [
                {{"from_space": "subject", "from_id": "example_agent", "relation": "owns", "to_space": "resource", "to_id": "example_project", "properties": {{}}}}
              ]
            }}
        """).strip()

        response = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()

        # Extract JSON block if wrapped in markdown
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)
        elif raw.startswith("{"):
            pass
        else:
            # Try to find first { ... }
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if brace_match:
                raw = brace_match.group(0)
            else:
                logger.debug("No JSON found in LLM response for chunk %d", chunk_index)
                return [], []

        data = json.loads(raw)
        nodes = [
            ExtractedNode(
                space=n["space"],
                node_type=n["node_type"],
                node_id=n["node_id"],
                properties=n.get("properties", {}),
            )
            for n in data.get("nodes", [])
        ]
        edges = [
            ExtractedEdge(
                from_space=e["from_space"],
                from_id=e["from_id"],
                relation=e["relation"],
                to_space=e["to_space"],
                to_id=e["to_id"],
                properties=e.get("properties", {}),
            )
            for e in data.get("edges", [])
        ]
        return nodes, edges
