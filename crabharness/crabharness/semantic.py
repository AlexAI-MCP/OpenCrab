from __future__ import annotations

import json
from typing import Any

from .models import ArtifactBundle, MissionSpec


def score_bundle_semantically(
    bundle: ArtifactBundle,
    mission: MissionSpec,
) -> dict[str, Any]:
    """
    Score artifact bundle against mission's semantic_questions using Claude.
    Returns dict with semantic_score (0~1) and question_verdicts.

    This is a placeholder that implements the loopy Phase 2 analysis loop.
    Real implementation would call Claude API with mission.semantic_questions.
    """

    # If no semantic questions, return neutral score
    if not mission.success_criteria.semantic_questions:
        return {
            "semantic_score": 0.5,
            "question_verdicts": [],
            "analysis": "No semantic questions defined",
        }

    summary = bundle.summary or {}

    # Simple heuristic-based scoring (placeholder for LLM)
    # In production, this would invoke Claude with:
    #   prompt: "Evaluate this artifact bundle against these questions"
    #   questions: mission.success_criteria.semantic_questions
    #   context: bundle.summary + bundle.metrics

    verdicts = []
    score_sum = 0.0

    for question in mission.success_criteria.semantic_questions:
        # Placeholder scoring logic
        # Real implementation: Claude reads question + bundle content, returns 0~1 score

        # Example heuristics:
        # - "How many bidders?" → check bidders_count > 0
        # - "Are prices compressed?" → check reserve_ratio
        # - "Is data fresh?" → check collected_at timestamp

        question_lower = question.lower()
        verdict = 0.0
        reason = ""

        if "bidder" in question_lower:
            bidders = summary.get("bidders_count", 0)
            verdict = min(bidders / 5.0, 1.0) if bidders else 0.0
            reason = f"Found {bidders} bidders"
        elif "price" in question_lower or "reserve" in question_lower or "compress" in question_lower:
            reserve_count = summary.get("reserve_price_count", 0)
            verdict = min(reserve_count / 3.0, 1.0) if reserve_count else 0.0
            reason = f"Found {reserve_count} reserve prices"
        elif "data" in question_lower or "fresh" in question_lower:
            # Check if progress log exists and is recent
            progress = summary.get("progress")
            if progress and progress.get("done", 0) > 0:
                verdict = 0.7
                reason = f"Progress recorded: {progress.get('message', 'unknown')}"
            else:
                verdict = 0.0
                reason = "No progress data"
        else:
            # Generic: if we have any summary data, give partial credit
            verdict = 0.3 if summary else 0.0
            reason = "Generic heuristic applied"

        verdicts.append({
            "question": question,
            "score": verdict,
            "reason": reason,
        })
        score_sum += verdict

    avg_semantic_score = score_sum / len(verdicts) if verdicts else 0.0

    return {
        "semantic_score": min(avg_semantic_score, 1.0),
        "question_verdicts": verdicts,
        "analysis": f"Scored {len(verdicts)} semantic questions",
    }


def determine_autoresearch_verdict(
    completeness_score: float,
    semantic_score: float,
    mission: MissionSpec,
    prev_score: float = 0.0,
    curr_score: float = 0.0,
) -> str:
    """
    Determine autoresearch-style keep/discard/crash verdict.

    Based on loopy Phase 3.5 principles:
    - keep: both completeness and semantic scores meet threshold
    - discard: scores below threshold or no improvement over previous
    - crash: critical validation issues
    """

    min_semantic = mission.success_criteria.min_semantic_score or 0.0
    completeness_threshold = mission.success_criteria.completeness_threshold

    # If semantic score below minimum, discard
    if semantic_score < min_semantic:
        return "discard"

    # If completeness below threshold, discard
    if completeness_score < completeness_threshold:
        return "discard"

    # If harness-report metrics provided, check improvement
    # (in real harness: prev_score and curr_score come from harness-report)
    if prev_score > 0 and curr_score > 0:
        if curr_score > prev_score:
            return "keep"
        elif curr_score == prev_score:
            # No change: apply loopy principle "simple > complex"
            return "discard"
        else:
            # Score regression
            return "discard"

    # If both scores are above thresholds, keep
    if completeness_score >= completeness_threshold and semantic_score >= min_semantic:
        return "keep"

    # Default to discard if uncertain
    return "discard"
