from __future__ import annotations

import json
import os
from typing import Any

from .models import ArtifactBundle, MissionSpec


def _claude_available() -> bool:
    """Check if Claude API is configured (env var set, SDK installed)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _score_with_claude(
    bundle: ArtifactBundle,
    mission: MissionSpec,
) -> dict[str, Any] | None:
    """Score the bundle using Claude. Returns None on failure (caller falls back)."""
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    model = os.environ.get("CRABHARNESS_SEMANTIC_MODEL", "claude-haiku-4-5-20251001")

    questions = mission.success_criteria.semantic_questions or []
    if not questions:
        return None

    context = {
        "mission_objective": mission.objective,
        "target": mission.target,
        "summary": bundle.summary,
        "metrics": bundle.metrics,
    }

    system_prompt = (
        "You are a mission validator. For each question, score the evidence 0.0-1.0 "
        "(0=no support, 1=strong support). Return ONLY a JSON object shaped as "
        '{"verdicts":[{"question":"...","score":0.0,"reason":"..."}]}. '
        "No preamble, no markdown fences."
    )
    user_prompt = (
        f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        f"QUESTIONS:\n{json.dumps(questions, ensure_ascii=False, indent=2)}"
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        return {
            "semantic_score": 0.0,
            "question_verdicts": [],
            "analysis": f"Claude call failed: {exc}",
            "backend": "claude",
        }

    raw_text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`").split("\n", 1)[-1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

    try:
        parsed = json.loads(raw_text)
        verdicts = parsed.get("verdicts", [])
    except json.JSONDecodeError:
        return {
            "semantic_score": 0.0,
            "question_verdicts": [],
            "analysis": f"Claude returned non-JSON: {raw_text[:200]}",
            "backend": "claude",
        }

    scores = [float(v.get("score", 0.0)) for v in verdicts]
    avg = sum(scores) / len(scores) if scores else 0.0

    return {
        "semantic_score": min(max(avg, 0.0), 1.0),
        "question_verdicts": verdicts,
        "analysis": f"Claude scored {len(verdicts)} questions using {model}",
        "backend": "claude",
    }


def _score_with_heuristic(
    bundle: ArtifactBundle,
    mission: MissionSpec,
) -> dict[str, Any]:
    """Fallback keyword-heuristic scoring when Claude is unavailable."""
    if not mission.success_criteria.semantic_questions:
        return {
            "semantic_score": 0.5,
            "question_verdicts": [],
            "analysis": "No semantic questions defined",
            "backend": "heuristic",
        }

    summary = bundle.summary or {}
    verdicts = []
    score_sum = 0.0

    for question in mission.success_criteria.semantic_questions:
        q = question.lower()
        verdict = 0.0
        reason = ""

        if "bidder" in q:
            n = summary.get("bidders_count", 0)
            verdict = min(n / 5.0, 1.0) if n else 0.0
            reason = f"Found {n} bidders"
        elif "price" in q or "reserve" in q or "compress" in q:
            n = summary.get("reserve_price_count", 0)
            verdict = min(n / 3.0, 1.0) if n else 0.0
            reason = f"Found {n} reserve prices"
        elif "fresh" in q or "data" in q:
            progress = summary.get("progress") or {}
            if progress.get("done", 0) > 0:
                verdict = 0.7
                reason = f"Progress recorded: {progress.get('message', 'unknown')}"
            else:
                verdict = 0.0
                reason = "No progress data"
        else:
            verdict = 0.3 if summary else 0.0
            reason = "Generic heuristic applied"

        verdicts.append({"question": question, "score": verdict, "reason": reason})
        score_sum += verdict

    avg = score_sum / len(verdicts) if verdicts else 0.0
    return {
        "semantic_score": min(avg, 1.0),
        "question_verdicts": verdicts,
        "analysis": f"Heuristic scored {len(verdicts)} questions",
        "backend": "heuristic",
    }


def score_bundle_semantically(
    bundle: ArtifactBundle,
    mission: MissionSpec,
) -> dict[str, Any]:
    """Score artifact bundle against mission's semantic_questions.

    Uses Claude if ANTHROPIC_API_KEY is set and `anthropic` SDK is installed.
    Falls back to keyword heuristic otherwise.
    Override model via CRABHARNESS_SEMANTIC_MODEL env var.
    """
    if _claude_available():
        result = _score_with_claude(bundle, mission)
        if result is not None:
            return result
    return _score_with_heuristic(bundle, mission)


def determine_autoresearch_verdict(
    completeness_score: float,
    semantic_score: float,
    mission: MissionSpec,
    prev_score: float = 0.0,
    curr_score: float = 0.0,
) -> str:
    """Determine autoresearch-style keep/discard/crash verdict.

    Based on loopy Phase 3.5 principles:
    - keep: both completeness and semantic scores meet threshold
    - discard: scores below threshold or no improvement over previous
    - crash: critical validation issues
    """
    min_semantic = mission.success_criteria.min_semantic_score or 0.0
    completeness_threshold = mission.success_criteria.completeness_threshold

    if semantic_score < min_semantic:
        return "discard"
    if completeness_score < completeness_threshold:
        return "discard"

    if prev_score > 0 and curr_score > 0:
        if curr_score > prev_score:
            return "keep"
        return "discard"

    if completeness_score >= completeness_threshold and semantic_score >= min_semantic:
        return "keep"
    return "discard"
