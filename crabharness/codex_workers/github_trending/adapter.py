from __future__ import annotations

from pathlib import Path
from typing import Any

from crabharness.models import ArtifactBundle, ArtifactFile, DelegationJob, MissionSpec, ValidationIssue, ValidationReport
from crabharness.semantic import score_bundle_semantically, determine_autoresearch_verdict


def collect_bundle(
    root_dir: Path,
    mission: MissionSpec,
    job: DelegationJob,
    run_id: str,
    progress_path: Path | None = None,
    error_log_path: Path | None = None,
) -> ArtifactBundle:
    """Collect GitHub trending repos. Stub implementation."""
    workspace_dir = root_dir / "_workspace"

    files: list[ArtifactFile] = [
        ArtifactFile(
            kind="progress_log",
            path=str(progress_path or workspace_dir / "github-trending-progress.json"),
            format="json",
            description="GitHub trending crawl progress.",
        ),
    ]

    # Stub: simulate finding 5 repos
    summary: dict[str, Any] = {
        "language": job.target.get("language", "python"),
        "since": job.target.get("since", "weekly"),
        "repos_count": 5,
        "repos": [
            {"name": "anthropics/anthropic-sdk-python", "stars": 1200, "topic": "ai-sdk"},
            {"name": "openai/swarm", "stars": 800, "topic": "agents"},
            {"name": "karpathy/minGPT", "stars": 600, "topic": "llm"},
            {"name": "simonw/llm", "stars": 400, "topic": "cli"},
            {"name": "langchain-ai/langchain", "stars": 3200, "topic": "rag"},
        ],
    }

    return ArtifactBundle(
        run_id=run_id,
        mission_id=mission.mission_id,
        worker_id=job.worker_id,
        job_id=job.job_id,
        target_ref=job.target,
        files=files,
        metrics={"repos_count": 5, "avg_stars": 1240},
        summary=summary,
    )


def validate_bundle(bundle: ArtifactBundle, mission: MissionSpec) -> ValidationReport:
    """Validate GitHub trending bundle."""
    issues: list[ValidationIssue] = []
    required = mission.success_criteria.required_fields or ["repos"]

    repos_count = bundle.summary.get("repos_count", 0)
    passed = 0
    checks_total = max(len(required), 1)

    for field in required:
        if field == "repos":
            ok = repos_count > 0
        else:
            ok = field in bundle.summary

        if ok:
            passed += 1
        else:
            issues.append(
                ValidationIssue(
                    code=f"missing_{field}",
                    severity="error",
                    message=f"Required field `{field}` is missing from GitHub trending bundle.",
                )
            )

    completeness = round(passed / checks_total, 3)

    # Semantic scoring
    semantic_result = score_bundle_semantically(bundle, mission)
    semantic_score = semantic_result.get("semantic_score", 0.0)

    # Autoresearch verdict
    autoresearch_verdict = determine_autoresearch_verdict(
        completeness_score=completeness,
        semantic_score=semantic_score,
        mission=mission,
    )

    threshold = mission.success_criteria.completeness_threshold
    status = "pass" if completeness >= threshold and not any(issue.severity == "error" for issue in issues) else "retry"
    next_action = "promote" if status == "pass" else "retry"

    if passed == 0 and issues:
        status = "fail"
        next_action = "reject"

    return ValidationReport(
        run_id=bundle.run_id,
        mission_id=mission.mission_id,
        status=status,
        completeness_score=completeness,
        semantic_score=semantic_score,
        semantic_verdict=autoresearch_verdict,
        issues=issues,
        next_action=next_action,
    )
