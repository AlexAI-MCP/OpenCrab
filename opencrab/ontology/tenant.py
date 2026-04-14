"""
Tenant Context — lightweight multi-tenant isolation.

Approach (safe for early stage):
  - tenant_id is injected per-request, not stored globally
  - Nodes are stamped with tenant_id in their properties on write
  - Queries can filter by tenant_id via space metadata or properties
  - The SQL billing_events table tracks usage per tenant
  - No hard DB-level row isolation yet (planned for Phase 6)

TenantContext is a thin dataclass passed through the call stack.
Tools.py extracts it from MCP request headers (X-Tenant-Id) or
defaults to 'default' for single-tenant deployments.

Usage:
    ctx = TenantContext(tenant_id="acme", subject_id="user_42")
    builder.add_node(..., tenant_ctx=ctx)
    hybrid.query(..., tenant_ctx=ctx)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TenantContext:
    """Carries per-request tenant and subject identity."""

    tenant_id: str = "default"
    subject_id: str | None = None

    # Optional: override which spaces this tenant can access
    allowed_spaces: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "allowed_spaces": self.allowed_spaces,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenantContext":
        return cls(
            tenant_id=data.get("tenant_id", "default"),
            subject_id=data.get("subject_id"),
            allowed_spaces=data.get("allowed_spaces"),
        )

    @classmethod
    def default(cls) -> "TenantContext":
        return cls(tenant_id="default")


def extract_tenant_context(
    headers: dict[str, str] | None = None,
    tenant_id: str | None = None,
    subject_id: str | None = None,
) -> TenantContext:
    """
    Build a TenantContext from MCP request headers or explicit kwargs.

    Priority: explicit kwargs > headers > defaults.

    Headers recognised:
      X-Tenant-Id    — tenant identifier
      X-Subject-Id   — subject / user identifier
    """
    tid = tenant_id
    sid = subject_id

    if headers:
        if not tid:
            tid = headers.get("X-Tenant-Id") or headers.get("x-tenant-id")
        if not sid:
            sid = headers.get("X-Subject-Id") or headers.get("x-subject-id")

    return TenantContext(
        tenant_id=tid or "default",
        subject_id=sid,
    )


def stamp_properties(
    properties: dict[str, Any],
    tenant_ctx: TenantContext,
) -> dict[str, Any]:
    """
    Stamp tenant_id (and optionally subject_id) into node properties.

    Preserves existing tenant_id if already set (idempotent).
    """
    stamped = {**properties}
    stamped.setdefault("tenant_id", tenant_ctx.tenant_id)
    if tenant_ctx.subject_id:
        stamped.setdefault("created_by", tenant_ctx.subject_id)
    return stamped


def filter_by_tenant(
    nodes: list[dict[str, Any]],
    tenant_ctx: TenantContext,
) -> list[dict[str, Any]]:
    """
    Filter a list of node dicts to only those belonging to the tenant.

    Nodes without a tenant_id property are treated as belonging to 'default'.
    """
    if tenant_ctx.tenant_id == "default":
        # Single-tenant deployment: pass everything
        return nodes

    filtered = []
    for node in nodes:
        props = node.get("properties") or {}
        node_tenant = props.get("tenant_id", "default")
        if node_tenant == tenant_ctx.tenant_id:
            filtered.append(node)
    return filtered
