"""Harness Loop Orchestrator — self-evolving CrabHarness runs with Claude Haiku reasoning.

Uses hermes-style structured thinking to augment Haiku's decision-making:
- Memory-based state tracking (hermes pattern)
- Multi-step reasoning with JSON schemas
- Mission parameter evolution based on verdicts
- Loop cycle: run → validate → analyze → evolve → repeat
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .models import MissionSpec


class LoopState:
    """Hermes-style state tracking for loop iterations."""

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or Path.cwd() / ".harness-loop-state.json"
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {
            "iteration": 0,
            "mission_id": "",
            "start_time": "",
            "history": [],
            "best_score": 0.0,
            "current_mission": {},
        }

    def save(self) -> None:
        """Persist state to disk (hermes memory pattern)."""
        self.state_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_iteration(
        self, verdict: str, completeness: float, semantic_score: float, reason: str
    ) -> None:
        """Record iteration outcome."""
        self.data["iteration"] += 1
        self.data["history"].append(
            {
                "iteration": self.data["iteration"],
                "timestamp": datetime.now().isoformat(),
                "verdict": verdict,
                "completeness": completeness,
                "semantic_score": semantic_score,
                "reason": reason,
            }
        )
        best = self.data.get("best_score", 0.0)
        combined = (completeness + semantic_score) / 2.0
        if combined > best:
            self.data["best_score"] = combined
        self.save()

    def get_iteration_count(self) -> int:
        return self.data.get("iteration", 0)

    def get_history_summary(self) -> str:
        """Hermes-style summary for Haiku context."""
        if not self.data["history"]:
            return "No iterations yet."
        hist = self.data["history"]
        verdicts = [h["verdict"] for h in hist]
        scores = [h["completeness"] for h in hist]
        return (
            f"Iterations: {len(hist)}\n"
            f"Verdicts: {verdicts}\n"
            f"Avg completeness: {sum(scores) / len(scores):.2f}\n"
            f"Best combined score: {self.data.get('best_score', 0.0):.2f}"
        )


def _call_haiku_for_evolution(
    mission: MissionSpec,
    validation_verdict: str,
    completeness: float,
    semantic_score: float,
    loop_state: LoopState,
) -> dict[str, Any]:
    """Call Claude Haiku with structured reasoning for mission evolution.

    Uses hermes-style multi-step thinking to enhance Haiku's decision-making.
    """
    try:
        import anthropic
    except ImportError:
        return {
            "decision": "keep",
            "reason": "Claude API not configured, keeping mission as-is",
            "suggested_changes": {},
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "decision": "keep",
            "reason": "ANTHROPIC_API_KEY not set",
            "suggested_changes": {},
        }

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "You are a harness evolution strategist. Given mission results, decide whether to "
        "keep/retry/pivot/abort and suggest parameter adjustments. "
        "Return ONLY valid JSON shaped as: "
        '{"decision":"keep|retry|pivot|abort","reason":"...","suggested_changes":{...}}'
    )

    history_context = loop_state.get_history_summary()
    user_prompt = (
        f"MISSION OBJECTIVE: {mission.objective}\n"
        f"CURRENT TARGET: {mission.target}\n"
        f"ITERATION HISTORY:\n{history_context}\n\n"
        f"LAST RUN RESULTS:\n"
        f"- Verdict: {validation_verdict}\n"
        f"- Completeness: {completeness:.2f}\n"
        f"- Semantic score: {semantic_score:.2f}\n\n"
        f"DECISION NEEDED:\n"
        f"1. Keep (proceed to next iteration with same mission)?\n"
        f"2. Retry (same target, adjust parameters like concurrency/delay)?\n"
        f"3. Pivot (change target or strategy)?\n"
        f"4. Abort (give up, not worth continuing)?\n\n"
        f"For retry/pivot, suggest parameter adjustments in JSON."
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        return {
            "decision": "keep",
            "reason": f"Haiku call failed: {exc}",
            "suggested_changes": {},
        }

    raw_text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()

    try:
        result = json.loads(raw_text)
        return result
    except json.JSONDecodeError:
        return {
            "decision": "keep",
            "reason": f"Haiku returned non-JSON: {raw_text[:100]}",
            "suggested_changes": {},
        }


def evolve_mission(
    mission: MissionSpec,
    validation_verdict: str,
    completeness: float,
    semantic_score: float,
    loop_state: LoopState,
) -> tuple[MissionSpec, bool]:
    """Evolve mission parameters based on Haiku's analysis.

    Returns: (evolved_mission, should_continue)
    """
    haiku_decision = _call_haiku_for_evolution(
        mission, validation_verdict, completeness, semantic_score, loop_state
    )

    decision = haiku_decision.get("decision", "keep").lower()
    reason = haiku_decision.get("reason", "")
    changes = haiku_decision.get("suggested_changes", {})

    # Record the decision
    loop_state.add_iteration(decision, completeness, semantic_score, reason)

    if decision == "abort":
        return mission, False

    # Apply suggested changes to mission constraints/target
    evolved = mission.model_copy(deep=True)
    if "constraints" in changes and isinstance(changes["constraints"], dict):
        for key, val in changes["constraints"].items():
            evolved.constraints.__dict__[key] = val
    if "target" in changes and isinstance(changes["target"], dict):
        evolved.target.update(changes["target"])

    return evolved, True


def run_harness_loop(
    mission: MissionSpec,
    max_iterations: int = 5,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Execute the self-evolving harness loop.

    Runs the mission, validates, analyzes with Haiku, evolves, and repeats.
    """
    from .runtime import run_mission

    state = LoopState(state_path)
    state.data["mission_id"] = mission.mission_id
    state.data["start_time"] = datetime.now().isoformat()
    state.data["current_mission"] = mission.model_dump(mode="json")
    state.save()

    iteration = 0
    current_mission = mission
    final_result = None

    while iteration < max_iterations:
        iteration += 1
        print(f"\n=== Harness Loop Iteration {iteration}/{max_iterations} ===")

        # Run the mission
        print(f"Running mission: {current_mission.mission_id}")
        result = run_mission(current_mission)

        # Extract validation results from the run
        if not result.get("validations"):
            print("No validation results found")
            break

        validation = result["validations"][0]
        completeness = validation.get("completeness_score", 0.0)
        semantic_score = validation.get("semantic_score", 0.0)
        verdict = validation.get("semantic_verdict", "discard")

        print(f"Completeness: {completeness:.2f}, Semantic: {semantic_score:.2f}, Verdict: {verdict}")

        # Let Haiku analyze and evolve
        print("Analyzing with Claude Haiku...")
        evolved_mission, should_continue = evolve_mission(
            current_mission, verdict, completeness, semantic_score, state
        )

        haiku_decision = _call_haiku_for_evolution(
            current_mission, verdict, completeness, semantic_score, state
        )
        print(f"Haiku decision: {haiku_decision.get('decision')} — {haiku_decision.get('reason')}")

        final_result = result

        if not should_continue:
            print("Loop terminated by Haiku (abort decision)")
            break

        current_mission = evolved_mission
        state.data["current_mission"] = evolved_mission.model_dump(mode="json")
        state.save()

    # Summary
    print("\n=== Loop Complete ===")
    print(f"Total iterations: {state.get_iteration_count()}")
    print(f"Best score: {state.data.get('best_score', 0.0):.2f}")

    return {
        "loop_completed": True,
        "iterations": state.get_iteration_count(),
        "best_score": state.data.get("best_score", 0.0),
        "final_mission_result": final_result,
        "state_path": str(state.state_path),
    }
