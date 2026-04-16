from __future__ import annotations

import json
import re
from hashlib import sha1
from pathlib import Path
from typing import Any

from crabharness.models import (
    ArtifactBundle,
    ArtifactFile,
    DelegationJob,
    MissionSpec,
    PromotionEdge,
    PromotionNode,
    PromotionPackage,
    ValidationIssue,
    ValidationReport,
)
from crabharness.semantic import determine_autoresearch_verdict, score_bundle_semantically


def _workspace_dir(root_dir: Path) -> Path:
    return root_dir / "_workspace"


def _output_path(root_dir: Path) -> Path:
    return _workspace_dir(root_dir) / "landscape-ai-usecases.json"


def collect_bundle(
    root_dir: Path,
    mission: MissionSpec,
    job: DelegationJob,
    run_id: str,
    progress_path: Path | None = None,
    error_log_path: Path | None = None,
) -> ArtifactBundle:
    output_path = _output_path(root_dir)
    dataset: dict[str, Any] = {}
    if output_path.exists():
        dataset = json.loads(output_path.read_text(encoding="utf-8"))

    documents = dataset.get("documents", [])
    use_cases = dataset.get("use_cases", [])
    files = [
        ArtifactFile(
            kind="json_dataset",
            path=str(output_path),
            format="json",
            description="Collected landscape and construction AI use cases.",
        ),
    ]
    if progress_path is not None:
        files.append(
            ArtifactFile(
                kind="progress_log",
                path=str(progress_path),
                format="json",
                description="Mission execution progress log.",
            )
        )
    if error_log_path is not None:
        files.append(
            ArtifactFile(
                kind="error_log",
                path=str(error_log_path),
                format="ndjson",
                description="Crawler fetch errors.",
            )
        )

    categories = sorted({str(item.get("category", "")) for item in use_cases if item.get("category")})
    publishers = sorted({str(item.get("publisher", "")) for item in use_cases if item.get("publisher")})

    return ArtifactBundle(
        run_id=run_id,
        mission_id=mission.mission_id,
        worker_id=job.worker_id,
        job_id=job.job_id,
        target_ref=job.target,
        files=files,
        metrics={
            "documents_count": len(documents),
            "use_cases_count": len(use_cases),
            "category_count": len(categories),
            "publisher_count": len(publishers),
        },
        summary={
            "topic": dataset.get("topic"),
            "documents": documents,
            "source_documents": len(documents),
            "use_cases": use_cases,
            "use_cases_count": len(use_cases),
            "categories": categories,
            "publishers": publishers,
        },
    )


def validate_bundle(bundle: ArtifactBundle, mission: MissionSpec) -> ValidationReport:
    issues: list[ValidationIssue] = []
    documents = bundle.summary.get("documents", [])
    use_cases = bundle.summary.get("use_cases", [])
    categories = bundle.summary.get("categories", [])

    required = mission.success_criteria.required_fields or ["source_documents", "use_cases"]
    passed = 0
    for field in required:
        if field == "source_documents":
            ok = len(documents) > 0
        elif field == "use_cases":
            ok = len(use_cases) > 0
        elif field == "categories":
            ok = len(categories) >= 2
        else:
            ok = field in bundle.summary and bundle.summary.get(field) not in (None, "", [], {})

        if ok:
            passed += 1
        else:
            issues.append(
                ValidationIssue(
                    code=f"missing_{field}",
                    severity="error",
                    message=f"Required field `{field}` is missing from the landscape AI bundle.",
                )
            )

    if len(categories) < 2:
        issues.append(
            ValidationIssue(
                code="insufficient_category_coverage",
                severity="warning",
                message="Expected both landscape_ai and construction_ai categories in the collected bundle.",
            )
        )

    completeness = round(passed / max(len(required), 1), 3)
    semantic_result = score_bundle_semantically(bundle, mission)
    semantic_score = max(semantic_result.get("semantic_score", 0.0), _domain_semantic_score(bundle))
    verdict = determine_autoresearch_verdict(completeness, semantic_score, mission)
    threshold = mission.success_criteria.completeness_threshold
    semantic_threshold = mission.success_criteria.min_semantic_score or 0.0
    status = (
        "pass"
        if completeness >= threshold and semantic_score >= semantic_threshold and not any(issue.severity == "error" for issue in issues)
        else "retry"
    )
    next_action = "promote" if status == "pass" else "retry"
    if not documents and not use_cases:
        status = "fail"
        next_action = "reject"

    return ValidationReport(
        run_id=bundle.run_id,
        mission_id=mission.mission_id,
        status=status,
        completeness_score=completeness,
        semantic_score=semantic_score,
        semantic_verdict=verdict,
        issues=issues,
        next_action=next_action,
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "item"


def _domain_semantic_score(bundle: ArtifactBundle) -> float:
    use_cases = bundle.summary.get("use_cases", [])
    categories = set(bundle.summary.get("categories", []))
    publishers = set(bundle.summary.get("publishers", []))
    outcomes = {
        outcome
        for use_case in use_cases
        for outcome in use_case.get("outcomes", [])
    }
    capabilities = {
        capability
        for use_case in use_cases
        for capability in use_case.get("capabilities", [])
    }

    score = 0.0
    if use_cases:
        score += 0.2
    if {"construction_ai", "landscape_ai"}.issubset(categories):
        score += 0.3
    score += min(len(publishers) / 4.0, 1.0) * 0.2
    score += min(len(capabilities) / 6.0, 1.0) * 0.15
    score += min(len(outcomes) / 4.0, 1.0) * 0.15
    return round(min(score, 1.0), 3)


def build_promotion_package(
    mission: MissionSpec,
    bundle: ArtifactBundle,
    validation: ValidationReport,
) -> PromotionPackage:
    seed = f"{mission.mission_id}:{bundle.run_id}:{bundle.worker_id}"
    package_id = f"promotion-{sha1(seed.encode('utf-8')).hexdigest()[:12]}"
    dataset_id = f"resource-dataset-{_slug(mission.target.get('topic', mission.mission_id))}"
    crawlrun_id = f"resource-crawlrun-{bundle.run_id}"
    run_evidence_id = f"evidence-run-{bundle.run_id}"
    completeness_claim_id = f"claim-completeness-{bundle.run_id}"

    nodes: list[PromotionNode] = [
        PromotionNode(
            space="resource",
            node_type="Dataset",
            node_id=dataset_id,
            properties={
                "objective": mission.objective,
                "topic": mission.target.get("topic", mission.mission_id),
                "workspace_id": mission.workspace_id,
            },
        ),
        PromotionNode(
            space="resource",
            node_type="CrawlRun",
            node_id=crawlrun_id,
            properties={
                "worker_id": bundle.worker_id,
                "job_id": bundle.job_id,
                "mission_id": mission.mission_id,
            },
        ),
        PromotionNode(
            space="evidence",
            node_type="Evidence",
            node_id=run_evidence_id,
            properties={
                "title": f"Run summary for {mission.mission_id}",
                "content": json.dumps(
                    {
                        "metrics": bundle.metrics,
                        "categories": bundle.summary.get("categories", []),
                        "publishers": bundle.summary.get("publishers", []),
                    },
                    ensure_ascii=False,
                ),
            },
        ),
        PromotionNode(
            space="claim",
            node_type="CollectionCompleteness",
            node_id=completeness_claim_id,
            properties={
                "status": validation.status,
                "score": validation.completeness_score,
                "semantic_score": validation.semantic_score,
                "semantic_verdict": validation.semantic_verdict,
                "next_action": validation.next_action,
            },
        ),
    ]

    edges: list[PromotionEdge] = [
        PromotionEdge(from_space="resource", from_id=dataset_id, relation="contains", to_space="evidence", to_id=run_evidence_id),
        PromotionEdge(from_space="resource", from_id=crawlrun_id, relation="logged_as", to_space="evidence", to_id=run_evidence_id),
        PromotionEdge(from_space="evidence", from_id=run_evidence_id, relation="supports", to_space="claim", to_id=completeness_claim_id),
    ]

    concept_nodes: dict[str, str] = {}
    outcome_nodes: dict[str, str] = {}
    entity_nodes: dict[str, str] = {}
    claim_refs: list[str] = [completeness_claim_id]

    for index, use_case in enumerate(bundle.summary.get("use_cases", []), start=1):
        title = str(use_case.get("title", f"use-case-{index}"))
        publisher = str(use_case.get("publisher", "Unknown"))
        statement = str(use_case.get("statement", "")).strip()
        if not statement:
            continue

        evidence_id = f"evidence-usecase-{index:02d}-{_slug(title)[:32]}"
        claim_id = f"claim-usecase-{index:02d}-{_slug(title)[:32]}"
        claim_refs.append(claim_id)

        nodes.append(
            PromotionNode(
                space="evidence",
                node_type="Evidence",
                node_id=evidence_id,
                properties={
                    "title": title,
                    "content": statement,
                    "source_url": str(use_case.get("url", "")),
                    "category": str(use_case.get("category", "")),
                    "publisher": publisher,
                },
            )
        )
        nodes.append(
            PromotionNode(
                space="claim",
                node_type="Claim",
                node_id=claim_id,
                properties={
                    "statement": statement,
                    "confidence": 0.7,
                    "status": "validated",
                },
            )
        )
        edges.append(PromotionEdge(from_space="resource", from_id=dataset_id, relation="contains", to_space="evidence", to_id=evidence_id))
        edges.append(PromotionEdge(from_space="evidence", from_id=evidence_id, relation="supports", to_space="claim", to_id=claim_id))

        entity_key = publisher.lower()
        entity_id = entity_nodes.get(entity_key)
        if entity_id is None:
            entity_id = f"concept-entity-{_slug(publisher)}"
            entity_nodes[entity_key] = entity_id
            nodes.append(
                PromotionNode(
                    space="concept",
                    node_type="Entity",
                    node_id=entity_id,
                    properties={
                        "name": publisher,
                        "entity_type": "organization",
                        "description": f"Publisher or vendor associated with AI use case sources for {mission.mission_id}.",
                    },
                )
            )
        edges.append(PromotionEdge(from_space="evidence", from_id=evidence_id, relation="mentions", to_space="concept", to_id=entity_id))

        category = str(use_case.get("category", "")).replace("_", " ").strip()
        if category:
            concept_id = concept_nodes.get(category)
            if concept_id is None:
                concept_id = f"concept-topic-{_slug(category)}"
                concept_nodes[category] = concept_id
                nodes.append(
                    PromotionNode(
                        space="concept",
                        node_type="Topic",
                        node_id=concept_id,
                        properties={"name": category},
                    )
                )
            edges.append(PromotionEdge(from_space="evidence", from_id=evidence_id, relation="describes", to_space="concept", to_id=concept_id))

        for capability in use_case.get("capabilities", []):
            concept_id = concept_nodes.get(capability)
            if concept_id is None:
                concept_id = f"concept-capability-{_slug(capability)}"
                concept_nodes[capability] = concept_id
                nodes.append(
                    PromotionNode(
                        space="concept",
                        node_type="Concept",
                        node_id=concept_id,
                        properties={"name": capability},
                    )
                )
            edges.append(PromotionEdge(from_space="evidence", from_id=evidence_id, relation="exemplifies", to_space="concept", to_id=concept_id))

            for outcome in use_case.get("outcomes", []):
                outcome_id = outcome_nodes.get(outcome)
                if outcome_id is None:
                    outcome_id = f"outcome-{_slug(outcome)}"
                    outcome_nodes[outcome] = outcome_id
                    nodes.append(
                        PromotionNode(
                            space="outcome",
                            node_type="Outcome",
                            node_id=outcome_id,
                            properties={"name": outcome},
                        )
                    )
                edges.append(PromotionEdge(from_space="concept", from_id=concept_id, relation="contributes_to", to_space="outcome", to_id=outcome_id))

    return PromotionPackage(
        package_id=package_id,
        mission_id=mission.mission_id,
        run_id=bundle.run_id,
        nodes=nodes,
        edges=edges,
        evidence_refs=[file.path for file in bundle.files],
        claim_refs=claim_refs,
    )
