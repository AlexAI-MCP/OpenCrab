from __future__ import annotations

from hashlib import sha1

from .models import ArtifactBundle, MissionSpec, PromotionEdge, PromotionNode, PromotionPackage, ValidationReport


def build_promotion_package(
    mission: MissionSpec,
    bundle: ArtifactBundle,
    validation: ValidationReport,
) -> PromotionPackage:
    seed = f"{mission.mission_id}:{bundle.run_id}:{bundle.worker_id}"
    package_id = f"promotion-{sha1(seed.encode('utf-8')).hexdigest()[:12]}"
    target_id = "-".join(str(value) for value in mission.target.values() if value) or mission.target_object.lower()
    resource_id = f"resource-{mission.target_object.lower()}-{target_id}"
    run_id = f"resource-crawlrun-{bundle.run_id}"
    claim_id = f"claim-completeness-{bundle.run_id}"

    nodes = [
        PromotionNode(
            space="resource",
            node_type=mission.target_object,
            node_id=resource_id,
            properties={"objective": mission.objective, **mission.target},
        ),
        PromotionNode(
            space="resource",
            node_type="CrawlRun",
            node_id=run_id,
            properties={"worker_id": bundle.worker_id, "job_id": bundle.job_id},
        ),
        PromotionNode(
            space="claim",
            node_type="CollectionCompleteness",
            node_id=claim_id,
            properties={
                "status": validation.status,
                "score": validation.completeness_score,
                "semantic_score": validation.semantic_score,
                "semantic_verdict": validation.semantic_verdict,
                "autoresearch_verdict": "keep" if validation.semantic_verdict == "keep" else "discard",
                "next_action": validation.next_action,
            },
        ),
    ]

    edges = [
        PromotionEdge(
            from_space="resource",
            from_id=run_id,
            relation="derived_from",
            to_space="resource",
            to_id=resource_id,
        ),
        PromotionEdge(
            from_space="resource",
            from_id=resource_id,
            relation="logged_as",
            to_space="claim",
            to_id=claim_id,
        ),
    ]

    return PromotionPackage(
        package_id=package_id,
        mission_id=mission.mission_id,
        run_id=bundle.run_id,
        nodes=nodes,
        edges=edges,
        evidence_refs=[file.path for file in bundle.files],
        claim_refs=[claim_id],
    )

