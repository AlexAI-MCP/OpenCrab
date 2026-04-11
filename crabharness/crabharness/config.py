from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT_DIR / "schemas"
CONFIG_DIR = ROOT_DIR / "configs"
MISSION_DIR = ROOT_DIR / "missions"
WORKER_DIR = ROOT_DIR / "codex_workers"
ARTIFACT_DIR = ROOT_DIR / "artifacts"

