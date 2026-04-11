from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import WorkerCapability


def _scan_worker_manifests() -> list[dict]:
    """Scan codex_workers/*/worker.manifest.json and load manifest dicts."""
    manifests: list[dict] = []
    codex_workers_dir = Path(__file__).parent.parent / "codex_workers"
    if not codex_workers_dir.exists():
        return manifests

    for worker_dir in codex_workers_dir.iterdir():
        if not worker_dir.is_dir():
            continue
        manifest_path = worker_dir / "worker.manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifests.append(manifest)
            except Exception as e:
                # Log but don't crash on malformed manifest
                print(f"Warning: Failed to load {manifest_path}: {e}")
    return manifests


def _load_adapter_module(module_path: str):
    """Dynamically import adapter module (e.g., 'codex_workers.soeak.adapter')."""
    try:
        return importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(f"Failed to load adapter module '{module_path}': {e}")


def _manifest_to_capability(manifest: dict) -> WorkerCapability:
    """Convert raw manifest dict to WorkerCapability."""
    from .models import WorkerCapability

    return WorkerCapability(
        worker_id=manifest.get("worker_id", ""),
        job_type=manifest.get("job_type", ""),
        supported_targets=manifest.get("supported_targets", []),
        tags=manifest.get("tags", []),
        command=manifest.get("command", []),
        artifact_types=manifest.get("artifact_types", []),
        validation_checks=manifest.get("validation_checks", []),
        source_ids=manifest.get("source_ids", []),
        description=manifest.get("description", ""),
    )


def list_workers() -> list[WorkerCapability]:
    """Load all registered workers from manifests."""
    manifests = _scan_worker_manifests()
    return [_manifest_to_capability(m) for m in manifests if m.get("worker_id")]


def resolve_worker_adapter(worker_id: str):
    """Load the adapter module for a worker by ID."""
    manifests = _scan_worker_manifests()
    for manifest in manifests:
        if manifest.get("worker_id") == worker_id:
            adapter_module = manifest.get("adapter_module")
            if not adapter_module:
                raise ValueError(f"Worker {worker_id} has no adapter_module defined")
            return _load_adapter_module(adapter_module)
    raise ValueError(f"No worker found with ID {worker_id}")
