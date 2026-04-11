from __future__ import annotations

import sqlite3
from pathlib import Path
from shutil import which

from .config import ROOT_DIR
from .registry import _scan_worker_manifests, resolve_worker_adapter


def doctor_worker(worker_alias: str, root_dir: Path | None = None) -> dict:
    """Run worker-specific prerequisite checks.

    Resolution order:
    1. Full worker_id match (e.g. `codex.soeak.detail`)
    2. Domain alias match on second segment (e.g. `soeak` -> `codex.soeak.detail`)
    3. Fallback: generic command-on-PATH check from manifest
    """
    root = root_dir or ROOT_DIR
    manifests = _scan_worker_manifests()

    manifest = None
    for candidate in manifests:
        worker_id = candidate.get("worker_id", "")
        if worker_id == worker_alias:
            manifest = candidate
            break
        segments = worker_id.split(".")
        if len(segments) >= 2 and segments[1] == worker_alias:
            manifest = candidate
            break

    if manifest is None:
        available = [m.get("worker_id") for m in manifests]
        raise ValueError(
            f"Unknown worker alias `{worker_alias}`. Registered workers: {available}"
        )

    worker_id = manifest["worker_id"]
    adapter = resolve_worker_adapter(worker_id)

    if hasattr(adapter, "doctor"):
        result = adapter.doctor(root)
        result.setdefault("worker_id", worker_id)
        return result

    command = manifest.get("command", [])
    executable = command[0] if command else None
    checks = []
    if executable:
        checks.append(
            {
                "name": f"command:{executable}",
                "ok": which(executable) is not None
                or which(f"{executable}.cmd") is not None
                or which(f"{executable}.exe") is not None,
            }
        )

    return {
        "worker_id": worker_id,
        "root_dir": str(root),
        "checks": checks,
        "ok": all(check["ok"] for check in checks) if checks else True,
        "note": "Generic doctor: adapter has no doctor() function, only checking command availability.",
    }


def doctor_soeak(root_dir: Path | None = None) -> dict:
    """Legacy SOEAK-specific doctor. Kept for backward compat."""
    root = root_dir or ROOT_DIR
    db_path = root / "nara.db"
    required_tables = ["analysis_soeak_raw", "procurement_listings", "award_results"]
    tables_present: dict[str, bool] = {name: False for name in required_tables}

    if db_path.exists():
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
            existing = {row[0] for row in rows}
            tables_present = {name: name in existing for name in required_tables}
        finally:
            connection.close()

    checks = [
        {"name": "node", "ok": which("node") is not None},
        {"name": "npm", "ok": which("npm") is not None or which("npm.cmd") is not None},
        {"name": "worker_script", "ok": (root / "soeak-detail-crawler.ts").exists()},
        {"name": "database_file", "ok": db_path.exists()},
        {"name": "analysis_soeak_raw", "ok": tables_present["analysis_soeak_raw"]},
        {"name": "procurement_listings", "ok": tables_present["procurement_listings"]},
        {"name": "award_results", "ok": tables_present["award_results"]},
    ]

    return {
        "worker_id": "codex.soeak.detail",
        "root_dir": str(root),
        "database_path": str(db_path),
        "checks": checks,
        "runtime_ok": all(check["ok"] for check in checks[:3]),
        "source_dataset_ok": all(check["ok"] for check in checks[3:]),
        "ok": all(check["ok"] for check in checks[:3]),
    }
