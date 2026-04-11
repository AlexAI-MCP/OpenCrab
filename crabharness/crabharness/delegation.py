from __future__ import annotations

import json
from pathlib import Path

from .models import DelegationJob
from .registry import list_workers


def _build_job_args_from_schema(worker_id: str, job: DelegationJob) -> list[str]:
    """Build CLI arguments from worker's arg_schema and job.target/options."""
    # Load manifest to get arg_schema
    codex_workers_dir = Path(__file__).parent.parent / "codex_workers"
    manifest_path = None
    for worker_dir in codex_workers_dir.iterdir():
        if worker_dir.is_dir():
            mp = worker_dir / "worker.manifest.json"
            if mp.exists():
                manifest = json.loads(mp.read_text(encoding="utf-8"))
                if manifest.get("worker_id") == worker_id:
                    manifest_path = mp
                    break

    if not manifest_path:
        raise ValueError(f"No manifest found for worker {worker_id}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    arg_schema = manifest.get("arg_schema", {})
    args: list[str] = []

    for param_name, param_spec in arg_schema.items():
        flag = param_spec.get("flag")
        if not flag:
            continue

        # Check if value comes from target or options
        from_option = param_spec.get("from_option", False)
        source = job.options if from_option else job.target
        value = source.get(param_name)

        # Use default if not provided
        if value is None:
            value = param_spec.get("default")

        if value is None:
            continue

        # Handle boolean flags
        if param_spec.get("type") == "boolean":
            if value:
                args.append(flag)
        else:
            args.extend([flag, str(value)])

    return args


def build_codex_payload(job: DelegationJob) -> dict:
    worker = next(worker for worker in list_workers() if worker.worker_id == job.worker_id)
    job_args = _build_job_args_from_schema(job.worker_id, job)
    return {
        "delegate_target": "codex_plugin",
        "worker_id": worker.worker_id,
        "job_type": job.job_type,
        "workspace_id": job.workspace_id,
        "command": [*worker.command, *job_args],
        "instructions": job.delegation_brief,
        "expected_artifacts": job.expected_artifacts,
        "validation_checks": job.validation_checks,
        "promotion_policy": job.promotion_policy,
    }
