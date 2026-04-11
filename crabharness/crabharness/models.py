from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MissionConstraints(BaseModel):
    model_config = ConfigDict(extra="allow")

    max_jobs: int = Field(default=1, ge=1)
    max_steps: int = Field(default=8, ge=1)
    concurrency: int | None = Field(default=None, ge=1)
    delay_ms: int | None = Field(default=None, ge=0)
    dry_run: bool = False
    allowed_sources: list[str] = Field(default_factory=list)


class MissionSuccessCriteria(BaseModel):
    model_config = ConfigDict(extra="allow")

    min_artifacts: int = Field(default=1, ge=1)
    required_fields: list[str] = Field(default_factory=list)
    completeness_threshold: float = Field(default=0.8, ge=0, le=1)
    semantic_questions: list[str] = Field(default_factory=list)
    min_semantic_score: float = Field(default=0.0, ge=0, le=1)


class MissionSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    mission_id: str
    workspace_id: str = "default"
    objective: str
    target_object: str
    target: dict[str, Any] = Field(default_factory=dict)
    questions: list[str] = Field(default_factory=list)
    collection_mode: Literal["targeted", "exploratory", "refresh", "harvest"] = "targeted"
    required_evidence: list[str] = Field(default_factory=list)
    promotion_policy: Literal["manual_review", "auto_if_valid", "disabled"] = "manual_review"
    dedupe_key: str | None = Field(default=None)
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)
    success_criteria: MissionSuccessCriteria = Field(default_factory=MissionSuccessCriteria)


class WorkerCapability(BaseModel):
    model_config = ConfigDict(extra="allow")

    worker_id: str
    job_type: str
    supported_targets: list[str]
    tags: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    artifact_types: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    description: str


class DelegationJob(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str
    mission_id: str
    workspace_id: str
    worker_id: str
    job_type: str
    objective: str
    target: dict[str, Any] = Field(default_factory=dict)
    questions: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    expected_artifacts: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    promotion_policy: str = "manual_review"
    delegation_brief: str = ""


class ArtifactFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    path: str
    format: str
    description: str | None = None


class ArtifactBundle(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    mission_id: str
    worker_id: str
    job_id: str
    target_ref: dict[str, Any] = Field(default_factory=dict)
    files: list[ArtifactFile] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    mission_id: str
    status: Literal["pass", "retry", "fail"]
    completeness_score: float = Field(ge=0, le=1)
    semantic_score: float = Field(default=0.0, ge=0, le=1)
    semantic_verdict: Literal["keep", "discard", "crash"] | None = Field(default=None)
    issues: list[ValidationIssue] = Field(default_factory=list)
    next_action: Literal["promote", "retry", "expand_scope", "reject"] = "retry"


class PromotionNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    space: str
    node_type: str
    node_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class PromotionEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    from_space: str
    from_id: str
    relation: str
    to_space: str
    to_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class PromotionPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    package_id: str
    mission_id: str
    run_id: str
    nodes: list[PromotionNode] = Field(default_factory=list)
    edges: list[PromotionEdge] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)

