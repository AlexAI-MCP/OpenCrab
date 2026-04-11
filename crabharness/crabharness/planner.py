from __future__ import annotations

from typing import Iterable

from .models import DelegationJob, MissionSpec, WorkerCapability
from .registry import list_workers


def _mission_terms(mission: MissionSpec) -> set[str]:
    parts: list[str] = [mission.objective, mission.target_object, mission.collection_mode]
    parts.extend(mission.questions)
    parts.extend(str(value) for value in mission.target.values())
    return {token.strip().lower() for part in parts for token in part.replace("/", " ").replace("-", " ").split() if token.strip()}


def _score_worker(mission: MissionSpec, worker: WorkerCapability) -> int:
    score = 0
    if mission.target_object in worker.supported_targets:
        score += 5

    terms = _mission_terms(mission)
    score += sum(1 for tag in worker.tags if tag.lower() in terms)

    source = str(mission.target.get("source", "")).lower()
    if source and source in {tag.lower() for tag in worker.tags}:
        score += 3

    return score


def build_delegation_brief(mission: MissionSpec, worker: WorkerCapability) -> str:
    required = ", ".join(mission.required_evidence) or "mission-defined evidence"
    checks = ", ".join(worker.validation_checks)
    return (
        f"Mission `{mission.mission_id}` for workspace `{mission.workspace_id}`.\n"
        f"Objective: {mission.objective}\n"
        f"Target object: {mission.target_object}\n"
        f"Target payload: {mission.target}\n"
        f"Questions: {mission.questions}\n"
        f"Required evidence: {required}\n"
        f"Return artifacts: {worker.artifact_types}\n"
        f"Validation expectations: {checks}\n"
        "Do not modify OpenCrab directly. Produce artifacts first."
    )


def select_workers(mission: MissionSpec, workers: Iterable[WorkerCapability] | None = None) -> list[WorkerCapability]:
    candidates = list(workers or list_workers())
    ranked = sorted(
        ((worker, _score_worker(mission, worker)) for worker in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    selected = [worker for worker, score in ranked if score > 0]
    if not selected:
        raise ValueError(f"No registered worker matches mission `{mission.mission_id}`")
    return selected[: mission.constraints.max_jobs]


def build_jobs(mission: MissionSpec) -> list[DelegationJob]:
    jobs: list[DelegationJob] = []
    for index, worker in enumerate(select_workers(mission), start=1):
        options = {
            "collection_mode": mission.collection_mode,
            "dry_run": mission.constraints.dry_run,
        }
        if mission.constraints.concurrency is not None:
            options["concurrency"] = mission.constraints.concurrency
        if mission.constraints.delay_ms is not None:
            options["delay_ms"] = mission.constraints.delay_ms

        jobs.append(
            DelegationJob(
                job_id=f"{mission.mission_id}--job-{index}",
                mission_id=mission.mission_id,
                workspace_id=mission.workspace_id,
                worker_id=worker.worker_id,
                job_type=worker.job_type,
                objective=mission.objective,
                target=mission.target,
                questions=mission.questions,
                options=options,
                expected_artifacts=worker.artifact_types,
                validation_checks=worker.validation_checks,
                promotion_policy=mission.promotion_policy,
                delegation_brief=build_delegation_brief(mission, worker),
            )
        )
    return jobs

