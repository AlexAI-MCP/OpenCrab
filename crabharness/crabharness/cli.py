from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import ArtifactBundle, DelegationJob, MissionSpec, PromotionPackage, ValidationReport
from .delegation import build_codex_payload
from .planner import build_jobs
from .preflight import doctor_worker
from .promotion import build_promotion_package
from .registry import list_workers
from .runtime import run_mission


SCHEMA_MODELS = {
    "mission": MissionSpec,
    "delegation-job": DelegationJob,
    "artifact-bundle": ArtifactBundle,
    "validation-report": ValidationReport,
    "promotion-package": PromotionPackage,
}


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _cmd_catalog(_: argparse.Namespace) -> int:
    _write([worker.model_dump(mode="json") for worker in list_workers()])
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    mission = MissionSpec.model_validate(_load_json(args.mission))
    jobs = build_jobs(mission)
    _write(
        {
            "mission": mission.model_dump(mode="json"),
            "jobs": [job.model_dump(mode="json") for job in jobs],
        }
    )
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    model = SCHEMA_MODELS[args.name]
    _write(model.model_json_schema())
    return 0


def _cmd_delegate(args: argparse.Namespace) -> int:
    mission = MissionSpec.model_validate(_load_json(args.mission))
    jobs = build_jobs(mission)
    payloads = [build_codex_payload(job) for job in jobs]
    _write({"mission_id": mission.mission_id, "delegations": payloads})
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    payload = _load_json(args.mission)
    if args.dry_run:
        payload.setdefault("constraints", {})
        payload["constraints"]["dry_run"] = True
    mission = MissionSpec.model_validate(payload)
    _write(run_mission(mission))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    _write(doctor_worker(args.worker))
    return 0


def _cmd_promotion_stub(args: argparse.Namespace) -> int:
    mission = MissionSpec.model_validate(_load_json(args.mission))
    bundle = ArtifactBundle.model_validate(_load_json(args.bundle))
    validation = ValidationReport.model_validate(_load_json(args.validation))
    package = build_promotion_package(mission, bundle, validation)
    _write(package.model_dump(mode="json"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crabharness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="List registered workers.")
    catalog.set_defaults(func=_cmd_catalog)

    plan = subparsers.add_parser("plan", help="Compile a mission into delegation jobs.")
    plan.add_argument("mission", help="Path to a mission JSON file.")
    plan.set_defaults(func=_cmd_plan)

    delegate = subparsers.add_parser("delegate", help="Build Codex delegation payloads for a mission.")
    delegate.add_argument("mission", help="Path to a mission JSON file.")
    delegate.set_defaults(func=_cmd_delegate)

    run = subparsers.add_parser("run", help="Execute a mission locally and emit bundle/validation/promotion outputs.")
    run.add_argument("mission", help="Path to a mission JSON file.")
    run.add_argument("--dry-run", action="store_true", help="Force worker dry-run mode.")
    run.set_defaults(func=_cmd_run)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check worker prerequisites. Accepts worker alias (e.g. `soeak`) or full worker_id.",
    )
    doctor.add_argument("worker", help="Worker alias or full worker_id (see `crabharness catalog`).")
    doctor.set_defaults(func=_cmd_doctor)

    schema = subparsers.add_parser("schema", help="Emit a JSON schema.")
    schema.add_argument("name", choices=sorted(SCHEMA_MODELS))
    schema.set_defaults(func=_cmd_schema)

    promotion = subparsers.add_parser("promotion-stub", help="Build a promotion package from sample inputs.")
    promotion.add_argument("mission")
    promotion.add_argument("bundle")
    promotion.add_argument("validation")
    promotion.set_defaults(func=_cmd_promotion_stub)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))
