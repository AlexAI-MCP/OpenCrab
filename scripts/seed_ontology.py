"""
Seed script: populate the OpenCrab stores with a representative
example ontology based on a fictional data analytics platform.

Run with:
    python scripts/seed_ontology.py

Requires all services to be running (docker-compose up -d).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running directly from scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()
logging.basicConfig(level=logging.WARNING)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

NODES: list[tuple[str, str, str, dict]] = [
    # (space, node_type, node_id, properties)
    # Subjects
    ("subject", "User",  "user-alice",  {"name": "Alice Chen",  "email": "alice@example.com", "role": "analyst"}),
    ("subject", "User",  "user-bob",    {"name": "Bob Kim",     "email": "bob@example.com",   "role": "engineer"}),
    ("subject", "Team",  "team-data",   {"name": "Data Team",   "size": 5}),
    ("subject", "Org",   "org-acme",    {"name": "ACME Corp",   "industry": "technology"}),
    ("subject", "Agent", "agent-rag",   {"name": "RAG Agent",   "model": "claude-3-5-sonnet"}),

    # Resources
    ("resource", "Project",  "proj-analytics", {"name": "Analytics Platform", "status": "active"}),
    ("resource", "Document", "doc-spec",        {"name": "Platform Spec",      "version": "2.1"}),
    ("resource", "Dataset",  "ds-events",       {"name": "User Events Dataset","rows": 1000000}),
    ("resource", "Tool",     "tool-dbt",        {"name": "dbt",                "version": "1.7"}),
    ("resource", "API",      "api-query",       {"name": "Query API",          "endpoint": "/v2/query"}),

    # Evidence
    ("evidence", "TextUnit",  "text-001", {"text": "Alice reviewed the Q4 analytics dashboard and flagged a spike in error rates.", "source": "slack"}),
    ("evidence", "LogEntry",  "log-001",  {"message": "ERROR: query timeout after 30s", "timestamp": "2026-01-15T09:23:00Z", "severity": "ERROR"}),
    ("evidence", "Evidence",  "ev-001",   {"summary": "Error rate increased 40% in January 2026", "confidence": 0.92}),

    # Concepts
    ("concept", "Entity",  "ent-user-behaviour", {"name": "User Behaviour",    "domain": "analytics"}),
    ("concept", "Concept", "con-error-rate",      {"name": "Error Rate",        "unit": "percentage"}),
    ("concept", "Topic",   "top-performance",     {"name": "System Performance","category": "reliability"}),
    ("concept", "Class",   "cls-kpi",             {"name": "KPI Class",         "definition": "Measurable business indicator"}),

    # Claims
    ("claim", "Claim",     "claim-perf-deg",  {"statement": "System performance degraded in Q4 2025", "confidence": 0.87}),
    ("claim", "Covariate", "cov-query-vol",   {"variable": "query_volume", "coefficient": 0.73, "p_value": 0.001}),

    # Communities
    ("community", "Community",       "comm-perf-cluster",  {"label": "Performance Cluster", "algorithm": "leiden", "size": 12}),
    ("community", "CommunityReport", "report-perf",        {"title": "Performance Issues Report", "generated_at": "2026-01-20"}),

    # Outcomes
    ("outcome", "Outcome", "out-reliability",  {"name": "System Reliability",    "target": 0.999, "current": 0.987}),
    ("outcome", "KPI",     "kpi-p95-latency",  {"name": "P95 Query Latency",     "target_ms": 100, "current_ms": 145}),
    ("outcome", "Risk",    "risk-data-loss",   {"name": "Data Loss Risk",        "severity": "high", "probability": 0.05}),

    # Levers
    ("lever", "Lever", "lever-cache-ttl",    {"name": "Cache TTL",          "unit": "seconds", "current": 300, "min": 60, "max": 3600}),
    ("lever", "Lever", "lever-query-limit",  {"name": "Query Result Limit", "unit": "rows",    "current": 10000, "min": 1000, "max": 100000}),

    # Policies
    ("policy", "Policy",      "pol-data-access",   {"name": "Data Access Policy",   "version": "1.3"}),
    ("policy", "Sensitivity", "sens-pii",           {"name": "PII Sensitivity",      "level": "restricted"}),
    ("policy", "ApprovalRule","rule-prod-deploy",   {"name": "Production Deployment","approvers_required": 2}),
]

EDGES: list[tuple[str, str, str, str, str]] = [
    # (from_space, from_id, relation, to_space, to_id)
    # Subject → Resource
    ("subject", "user-alice",  "owns",       "resource", "doc-spec"),
    ("subject", "user-alice",  "can_view",   "resource", "ds-events"),
    ("subject", "user-alice",  "can_execute","resource", "tool-dbt"),
    ("subject", "user-bob",    "manages",    "resource", "proj-analytics"),
    ("subject", "user-bob",    "can_edit",   "resource", "api-query"),
    ("subject", "team-data",   "member_of",  "resource", "proj-analytics"),
    ("subject", "agent-rag",   "can_view",   "resource", "ds-events"),
    ("subject", "agent-rag",   "can_execute","resource", "api-query"),

    # Resource → Evidence
    ("resource", "ds-events",       "contains",     "evidence", "ev-001"),
    ("resource", "ds-events",       "logged_as",    "evidence", "log-001"),
    ("resource", "doc-spec",        "contains",     "evidence", "text-001"),
    ("resource", "api-query",       "logged_as",    "evidence", "log-001"),

    # Evidence → Concept
    ("evidence", "text-001",  "mentions",    "concept", "ent-user-behaviour"),
    ("evidence", "ev-001",    "describes",   "concept", "con-error-rate"),
    ("evidence", "log-001",   "exemplifies", "concept", "top-performance"),

    # Evidence → Claim
    ("evidence", "ev-001",   "supports",     "claim", "claim-perf-deg"),
    ("evidence", "log-001",  "supports",     "claim", "claim-perf-deg"),
    ("evidence", "text-001", "timestamps",   "claim", "claim-perf-deg"),

    # Concept → Concept
    ("concept", "con-error-rate",       "related_to",  "concept", "top-performance"),
    ("concept", "top-performance",      "influences",  "concept", "ent-user-behaviour"),
    ("concept", "con-error-rate",       "subclass_of", "concept", "cls-kpi"),

    # Concept → Outcome
    ("concept", "con-error-rate",   "contributes_to", "outcome", "out-reliability"),
    ("concept", "top-performance",  "predicts",       "outcome", "kpi-p95-latency"),
    ("concept", "con-error-rate",   "degrades",       "outcome", "kpi-p95-latency"),
    ("concept", "con-error-rate",   "constrains",     "outcome", "out-reliability"),

    # Lever → Outcome
    ("lever", "lever-cache-ttl",   "raises",     "outcome", "out-reliability"),
    ("lever", "lever-cache-ttl",   "lowers",     "outcome", "kpi-p95-latency"),
    ("lever", "lever-query-limit", "stabilizes", "outcome", "kpi-p95-latency"),
    ("lever", "lever-query-limit", "lowers",     "outcome", "risk-data-loss"),

    # Lever → Concept
    ("lever", "lever-cache-ttl",   "affects", "concept", "top-performance"),
    ("lever", "lever-query-limit", "affects", "concept", "con-error-rate"),

    # Community → Concept
    ("community", "comm-perf-cluster", "clusters",   "concept", "top-performance"),
    ("community", "comm-perf-cluster", "clusters",   "concept", "con-error-rate"),
    ("community", "report-perf",       "summarizes", "concept", "top-performance"),

    # Policy → Resource
    ("policy", "pol-data-access", "protects",   "resource", "ds-events"),
    ("policy", "sens-pii",        "classifies", "resource", "ds-events"),
    ("policy", "rule-prod-deploy","restricts",  "resource", "api-query"),

    # Policy → Subject
    ("policy", "pol-data-access", "permits",          "subject", "user-alice"),
    ("policy", "pol-data-access", "requires_approval","subject", "agent-rag"),
]

INGEST_TEXTS: list[tuple[str, str, dict]] = [
    (
        "The Analytics Platform experienced a 40% increase in query error rates during Q4 2025. "
        "Initial investigation points to database connection pool exhaustion under high concurrency. "
        "The P95 query latency exceeded the 100ms SLA target, reaching 145ms on peak days.",
        "src-incident-q4-2025",
        {"space": "evidence", "type": "incident_report", "date": "2026-01-15"},
    ),
    (
        "Cache TTL optimization: reducing the cache TTL from 300s to 60s increased cache misses "
        "by 15% but reduced stale data issues by 60%. Recommend dynamic TTL based on data volatility.",
        "src-cache-analysis",
        {"space": "lever", "type": "analysis", "date": "2026-01-20"},
    ),
    (
        "ReBAC Policy: The Data Access Policy v1.3 grants Alice Chen full read access to the "
        "User Events Dataset. AI agents require explicit approval before accessing PII-sensitive data.",
        "src-policy-v1.3",
        {"space": "policy", "type": "policy_document", "version": "1.3"},
    ),
    (
        "MetaOntology OS Grammar: The lever space contains control variables that directly "
        "influence outcomes through raises, lowers, stabilizes, and optimizes relationships. "
        "Levers are the primary mechanism for system tuning in the ontology.",
        "src-metaontology-grammar",
        {"space": "concept", "type": "documentation"},
    ),
]


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------


def seed() -> None:
    console.print("\n[bold magenta]OpenCrab Seed Script[/bold magenta]")
    console.print("[dim]Populating example analytics platform ontology...[/dim]\n")

    from opencrab.config import get_settings
    from opencrab.ontology.builder import OntologyBuilder
    from opencrab.ontology.impact import ImpactEngine
    from opencrab.ontology.query import HybridQuery
    from opencrab.ontology.rebac import ReBACEngine
    from opencrab.stores.chroma_store import ChromaStore
    from opencrab.stores.mongo_store import MongoStore
    from opencrab.stores.neo4j_store import Neo4jStore
    from opencrab.stores.sql_store import SQLStore

    from opencrab.stores.factory import (
        make_doc_store,
        make_graph_store,
        make_sql_store,
        make_vector_store,
    )

    cfg = get_settings()

    # Init stores via factory to respect STORAGE_MODE
    neo4j = make_graph_store(cfg)
    chroma = make_vector_store(cfg)
    mongo = make_doc_store(cfg)
    sql = make_sql_store(cfg)

    # Print store status
    store_table = Table(title="Store Status", show_header=True)
    store_table.add_column("Store")
    store_table.add_column("Status")
    for name, store in [("Neo4j", neo4j), ("ChromaDB", chroma), ("MongoDB", mongo), ("PostgreSQL", sql)]:
        status = "[green]CONNECTED[/green]" if store.available else "[red]UNAVAILABLE[/red]"
        store_table.add_row(name, status)
    console.print(store_table)

    if not any([neo4j.available, chroma.available, mongo.available, sql.available]):
        console.print("\n[red]All stores unavailable. Start services with: docker-compose up -d[/red]")
        return

    builder = OntologyBuilder(neo4j, mongo, sql)
    rebac = ReBACEngine(neo4j, sql)
    hybrid = HybridQuery(chroma, neo4j)

    # Ensure constraints
    if neo4j.available:
        neo4j.ensure_constraints()
        console.print("[dim]Neo4j constraints ensured.[/dim]")

    # --- Seed nodes ---
    console.print(f"\n[bold]Seeding {len(NODES)} nodes...[/bold]")
    node_ok = 0
    node_fail = 0
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        task = progress.add_task("Adding nodes...", total=len(NODES))
        for space, node_type, node_id, props in NODES:
            try:
                builder.add_node(space, node_type, node_id, props)
                node_ok += 1
            except Exception as exc:
                console.print(f"  [red]FAIL[/red] {node_id}: {exc}")
                node_fail += 1
            progress.advance(task)

    console.print(f"  Nodes: [green]{node_ok} ok[/green], [red]{node_fail} failed[/red]")

    # --- Seed edges ---
    console.print(f"\n[bold]Seeding {len(EDGES)} edges...[/bold]")
    edge_ok = 0
    edge_fail = 0
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        task = progress.add_task("Adding edges...", total=len(EDGES))
        for from_space, from_id, relation, to_space, to_id in EDGES:
            try:
                builder.add_edge(from_space, from_id, relation, to_space, to_id)
                edge_ok += 1
            except Exception as exc:
                console.print(f"  [red]FAIL[/red] {from_id}-[{relation}]->{to_id}: {exc}")
                edge_fail += 1
            progress.advance(task)

    console.print(f"  Edges: [green]{edge_ok} ok[/green], [red]{edge_fail} failed[/red]")

    # --- Seed ReBAC policies ---
    console.print("\n[bold]Seeding ReBAC policies...[/bold]")
    if sql.available:
        try:
            rebac.grant("user-alice", "view",    "ds-events")
            rebac.grant("user-alice", "edit",    "doc-spec")
            rebac.grant("user-bob",   "admin",   "proj-analytics")
            rebac.grant("team-data",  "view",    "ds-events")
            rebac.deny("agent-rag",   "edit",    "ds-events")
            console.print("  [green]5 policies seeded.[/green]")
        except Exception as exc:
            console.print(f"  [red]Policy seed failed: {exc}[/red]")
    else:
        console.print("  [yellow]PostgreSQL unavailable, skipping ReBAC seed.[/yellow]")

    # --- Ingest text documents ---
    console.print(f"\n[bold]Ingesting {len(INGEST_TEXTS)} text documents...[/bold]")
    ingest_ok = 0
    for text, source_id, meta in INGEST_TEXTS:
        try:
            result = hybrid.ingest(text=text, source_id=source_id, metadata=meta)
            if mongo.available:
                mongo.upsert_source(source_id, text, meta)
            ingest_ok += 1
            console.print(f"  [green]OK[/green] {source_id} ({len(text)} chars)")
        except Exception as exc:
            console.print(f"  [red]FAIL[/red] {source_id}: {exc}")

    console.print(f"  Ingested: [green]{ingest_ok}/{len(INGEST_TEXTS)}[/green]")

    # --- Summary ---
    console.print("\n[bold green]Seed complete![/bold green]")
    if sql.available:
        counts = sql.table_counts()
        summary = Table(title="PostgreSQL Table Counts")
        summary.add_column("Table")
        summary.add_column("Rows", justify="right")
        for table, count in counts.items():
            summary.add_row(table, str(count))
        console.print(summary)

    if mongo.available:
        mongo_counts = mongo.collection_stats()
        console.print(
            f"\n[bold]MongoDB:[/bold] "
            f"nodes={mongo_counts.get('nodes', 0)}, "
            f"sources={mongo_counts.get('sources', 0)}, "
            f"audit_log={mongo_counts.get('audit_log', 0)}"
        )

    if neo4j.available:
        total_nodes = neo4j.count_nodes()
        console.print(f"[bold]Neo4j:[/bold] {total_nodes} nodes")

    if chroma.available:
        console.print(f"[bold]ChromaDB:[/bold] {chroma.count()} vectors")

    console.print(
        "\n[dim]Run 'opencrab query \"system performance\"' to test the ontology.[/dim]"
    )


if __name__ == "__main__":
    seed()
