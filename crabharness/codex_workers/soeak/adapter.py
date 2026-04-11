from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from crabharness.models import ArtifactBundle, ArtifactFile, DelegationJob, MissionSpec, ValidationIssue, ValidationReport
from crabharness.semantic import score_bundle_semantically, determine_autoresearch_verdict


def _db_path(root_dir: Path) -> Path:
    return root_dir / "nara.db"


def _workspace_dir(root_dir: Path) -> Path:
    return root_dir / "_workspace"


def _fetchone_dict(cursor: sqlite3.Cursor, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    row = cursor.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


def collect_soeak_bundle(
    root_dir: Path,
    mission: MissionSpec,
    job: DelegationJob,
    run_id: str,
    progress_path: Path | None = None,
    error_log_path: Path | None = None,
) -> ArtifactBundle:
    db_path = _db_path(root_dir)
    workspace_dir = _workspace_dir(root_dir)
    progress_file = progress_path or workspace_dir / "soeak-detail-crawler-progress.json"
    error_file = error_log_path or workspace_dir / "soeak-detail-crawler-errors.ndjson"
    bid_no = str(job.target.get("bid_no", ""))
    bid_ord = str(job.target.get("bid_ntce_ord", "000"))
    files: list[ArtifactFile] = [
        ArtifactFile(kind="sqlite_dataset", path=str(db_path), format="sqlite", description="Primary SOEAK analysis database."),
        ArtifactFile(
            kind="progress_log",
            path=str(progress_file),
            format="json",
            description="Latest crawler progress snapshot.",
        ),
        ArtifactFile(
            kind="error_log",
            path=str(error_file),
            format="ndjson",
            description="Crawler error event log.",
        ),
    ]

    summary: dict[str, Any] = {
        "bid_no": bid_no,
        "bid_ntce_ord": bid_ord,
        "case": None,
        "bidders_count": 0,
        "reserve_price_count": 0,
        "progress": None,
        "db_exists": db_path.exists(),
    }

    metrics: dict[str, Any] = {}

    if db_path.exists():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            cursor = connection.cursor()
            case = _fetchone_dict(
                cursor,
                """
                SELECT *
                FROM analysis_soeak_cases
                WHERE bid_ntce_no = ? AND bid_ntce_ord = ?
                """,
                (bid_no, bid_ord),
            )
            bidders_count = cursor.execute(
                """
                SELECT COUNT(*)
                FROM analysis_soeak_bidders
                WHERE bid_ntce_no = ?
                """,
                (bid_no,),
            ).fetchone()[0]
            reserve_price_count = cursor.execute(
                """
                SELECT COUNT(*)
                FROM analysis_soeak_reserve_prices
                WHERE bid_ntce_no = ?
                """,
                (bid_no,),
            ).fetchone()[0]
        finally:
            connection.close()

        summary["case"] = case
        summary["bidders_count"] = bidders_count
        summary["reserve_price_count"] = reserve_price_count
        metrics.update(
            {
                "bidders_count": bidders_count,
                "reserve_price_count": reserve_price_count,
                "winner_rate": None if case is None else case.get("winner_rate"),
                "reserve_ratio": None if case is None else case.get("reserve_ratio"),
            }
        )

    if progress_file.exists():
        summary["progress"] = json.loads(progress_file.read_text(encoding="utf-8"))

    return ArtifactBundle(
        run_id=run_id,
        mission_id=mission.mission_id,
        worker_id=job.worker_id,
        job_id=job.job_id,
        target_ref=job.target,
        files=files,
        metrics=metrics,
        summary=summary,
    )


def validate_soeak_bundle(bundle: ArtifactBundle, mission: MissionSpec) -> ValidationReport:
    issues: list[ValidationIssue] = []
    required = mission.success_criteria.required_fields
    case = bundle.summary.get("case") or {}
    bidders_count = int(bundle.summary.get("bidders_count", 0) or 0)
    reserve_price_count = int(bundle.summary.get("reserve_price_count", 0) or 0)
    checks_total = max(len(required), 1)
    passed = 0

    for field in required:
        if field == "bidders":
            ok = bidders_count > 0
        elif field == "reserve_prices":
            ok = reserve_price_count > 0
        else:
            ok = case.get(field) not in (None, "", [])

        if ok:
            passed += 1
        else:
            issues.append(
                ValidationIssue(
                    code=f"missing_{field}",
                    severity="error",
                    message=f"Required field `{field}` is missing from the SOEAK artifact bundle.",
                )
            )

    if not bundle.summary.get("db_exists"):
        issues.append(
            ValidationIssue(
                code="missing_db",
                severity="error",
                message="Expected `nara.db` does not exist in the workspace root.",
            )
        )

    progress = bundle.summary.get("progress") or {}
    if progress.get("fatal"):
        issues.append(
            ValidationIssue(
                code="fatal_progress",
                severity="error",
                message="Crawler progress file reports a fatal execution error.",
            )
        )

    completeness = round(passed / checks_total, 3)

    # Phase 2: Semantic scoring (loopy integration)
    semantic_result = score_bundle_semantically(bundle, mission)
    semantic_score = semantic_result.get("semantic_score", 0.0)

    # Phase 3.5: Autoresearch verdict
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
