from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import which

from .config import ARTIFACT_DIR, ROOT_DIR
from .delegation import build_codex_payload
from .models import ArtifactBundle, DelegationJob, MissionSpec, PromotionPackage, ValidationReport
from .planner import build_jobs
from .promotion import build_promotion_package
from .registry import resolve_worker_adapter


@dataclass(slots=True)
class JobRunResult:
    job: DelegationJob
    payload: dict
    returncode: int
    stdout_path: Path
    stderr_path: Path
    progress_path: Path
    error_log_path: Path
    bundle_path: Path
    validation_path: Path
    promotion_path: Path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _run_dir(mission: MissionSpec, run_id: str) -> Path:
    return ARTIFACT_DIR / "runs" / mission.mission_id / run_id


def _resolve_command(command: list[str]) -> list[str]:
    if not command:
        raise ValueError("Delegation command is empty.")

    executable = command[0]
    resolved = which(executable) or which(f"{executable}.cmd") or which(f"{executable}.exe")
    if resolved is None:
        raise FileNotFoundError(f"Unable to resolve command `{executable}` in PATH.")
    return [resolved, *command[1:]]


def _collect_bundle(
    root_dir: Path,
    mission: MissionSpec,
    job: DelegationJob,
    run_id: str,
    progress_path: Path,
    error_log_path: Path,
) -> ArtifactBundle:
    adapter = resolve_worker_adapter(job.worker_id)

    # Try generic function names first
    if hasattr(adapter, "collect_bundle"):
        return adapter.collect_bundle(root_dir, mission, job, run_id, progress_path, error_log_path)

    # Fallback to domain-specific function names (backward compat)
    domain = job.worker_id.split(".")[1]  # e.g., "soeak" from "codex.soeak.detail"
    collect_fn_name = f"collect_{domain}_bundle"
    if hasattr(adapter, collect_fn_name):
        return getattr(adapter, collect_fn_name)(root_dir, mission, job, run_id, progress_path, error_log_path)

    raise ValueError(f"Worker adapter for {job.worker_id} has no collect_bundle or {collect_fn_name} function")


def _validate_bundle(bundle: ArtifactBundle, mission: MissionSpec) -> ValidationReport:
    adapter = resolve_worker_adapter(bundle.worker_id)

    # Try generic function name first
    if hasattr(adapter, "validate_bundle"):
        return adapter.validate_bundle(bundle, mission)

    # Fallback to domain-specific function names (backward compat)
    domain = bundle.worker_id.split(".")[1]  # e.g., "soeak" from "codex.soeak.detail"
    validate_fn_name = f"validate_{domain}_bundle"
    if hasattr(adapter, validate_fn_name):
        return getattr(adapter, validate_fn_name)(bundle, mission)

    raise ValueError(f"Worker adapter for {bundle.worker_id} has no validate_bundle or {validate_fn_name} function")


def run_mission(mission: MissionSpec) -> dict:
    jobs = build_jobs(mission)
    run_id = f"{mission.mission_id}--{_timestamp()}"
    run_dir = _run_dir(mission, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    mission_path = run_dir / "mission.json"
    mission_path.write_text(json.dumps(mission.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

    results: list[JobRunResult] = []
    bundles: list[ArtifactBundle] = []
    validations: list[ValidationReport] = []
    promotions: list[PromotionPackage] = []

    for index, job in enumerate(jobs, start=1):
        payload = build_codex_payload(job)
        payload_path = run_dir / f"job-{index:02d}-delegation.json"
        stdout_path = run_dir / f"job-{index:02d}.stdout.log"
        stderr_path = run_dir / f"job-{index:02d}.stderr.log"
        progress_path = run_dir / f"job-{index:02d}-progress.json"
        error_log_path = run_dir / f"job-{index:02d}-errors.ndjson"
        bundle_path = run_dir / f"job-{index:02d}-artifact-bundle.json"
        validation_path = run_dir / f"job-{index:02d}-validation-report.json"
        promotion_path = run_dir / f"job-{index:02d}-promotion-package.json"

        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        env = os.environ.copy()
        env["SOEAK_PROGRESS_PATH"] = str(progress_path)
        env["SOEAK_ERROR_LOG_PATH"] = str(error_log_path)

        completed = subprocess.run(
            _resolve_command(payload["command"]),
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")

        bundle = _collect_bundle(ROOT_DIR, mission, job, run_id, progress_path, error_log_path)
        validation = _validate_bundle(bundle, mission)
        promotion = build_promotion_package(mission, bundle, validation)

        bundle_path.write_text(json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        validation_path.write_text(json.dumps(validation.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        promotion_path.write_text(json.dumps(promotion.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")

        results.append(
            JobRunResult(
                job=job,
                payload=payload,
                returncode=completed.returncode,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                progress_path=progress_path,
                error_log_path=error_log_path,
                bundle_path=bundle_path,
                validation_path=validation_path,
                promotion_path=promotion_path,
            )
        )
        bundles.append(bundle)
        validations.append(validation)
        promotions.append(promotion)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "mission": mission.model_dump(mode="json"),
        "jobs": [
            {
                "job": result.job.model_dump(mode="json"),
                "payload": result.payload,
                "returncode": result.returncode,
                "stdout_path": str(result.stdout_path),
                "stderr_path": str(result.stderr_path),
                "progress_path": str(result.progress_path),
                "error_log_path": str(result.error_log_path),
                "bundle_path": str(result.bundle_path),
                "validation_path": str(result.validation_path),
                "promotion_path": str(result.promotion_path),
            }
            for result in results
        ],
        "bundles": [bundle.model_dump(mode="json") for bundle in bundles],
        "validations": [validation.model_dump(mode="json") for validation in validations],
        "promotions": [promotion.model_dump(mode="json") for promotion in promotions],
    }
