<p align="center">
  <img src="logo.png" alt="OpenCrab Logo" width="260"/>
</p>

# OpenCrab

**MetaOntology OS MCP Server Plugin**

> Carcinization is the evolutionary tendency for crustaceans to converge on a crab-like body plan.
> OpenCrab applies the same principle to agent environments:
> all sufficiently advanced AI systems eventually evolve toward ontology-structured forms.

OpenCrab is an MCP (Model Context Protocol) server that exposes the MetaOntology OS grammar
to any OpenClaw-compatible agent environment — Claude Code, n8n, LangGraph, and beyond.

**Companion:** [`crabharness/`](./crabharness/) — a plugin-based mission control plane that plans evidence collection, delegates heavy crawling to Codex workers, validates artifacts through a three-gate pipeline, and emits OpenCrab-ready promotion packages. See [CrabHarness README](./crabharness/README.md).

---

## What's New (v1.5.0)

### Phase 1 — Core Stabilization
- **Grammar versioning**: `GRAMMAR_VERSION = "1.0.0"` in every manifest response
- **Type Schema Registry**: YAML schemas in `schemas/types/` — `required`, `enum` validation on every node write
- **Receipt IDs**: every `add_node` / `add_edge` returns `receipt_id + receipt_ts` for provenance

### Phase 2 — Action / Workflow Runtime
- **WorkflowEngine**: SQL state machine (`pending → running → approved/rejected → completed/failed`) with full audit log
- **ApprovalEngine**: three-state approval queue linked to workflow runs
- **CrabHarness `promotion-apply`**: CLI command + MCP tool to apply PromotionPackages inline

### Phase 3 — Identity / Canonicalization / Promotion
- **IdentityEngine**: alias table + fuzzy duplicate detection — no auto-merge, human review first
- **CanonicalizeEngine**: tombstone-based node merge — alias nodes preserved, `resolve_canonical()` for lookups
- **PromotionEngine**: full extraction lifecycle `candidate → validated → promoted | rejected` with evidence linking

### Phase 4 — Query / Reasoning Upgrade
- **BM25 Index**: pure Python keyword search over all node properties (no external deps)
- **RRF Reranker**: Reciprocal Rank Fusion merges vector + BM25 + graph results; BM25 cross-score boosts query-relevant hits
- **Policy-aware filtering**: pass `subject_id` to `ontology_query` and results are filtered by ReBAC `view` permission

### Phase 5 — Productization
- **Tenant isolation**: `tenant_id` context stamped on writes; `X-Tenant-Id` header support
- **Billing hooks**: `billing_events` table tracks node_write / query / ingest / promotion per tenant
- **Schema packs**: domain bundles (`saas`, `biomedical`, `legal`) installable with one MCP call

**Total MCP tools: 30**

---

## Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │           OpenCrab MCP Server               │
                        │              (stdio JSON-RPC)               │
                        └──────────────────┬──────────────────────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                           │                            │
      ┌───────▼──────┐           ┌────────▼───────┐          ┌────────▼───────┐
      │  grammar/    │           │   ontology/    │          │    stores/     │
      │  manifest.py │           │   builder.py   │          │                │
      │  validator.py│           │   rebac.py     │          │  neo4j_store   │
      │  glossary.py │           │   impact.py    │          │  chroma_store  │
      └──────────────┘           │   query.py     │          │  mongo_store   │
                                 │   identity.py  │          │  sql_store     │
      ┌───────────────┐          │   canonicalize │          └───────┬────────┘
      │  schemas/     │          │   promotion.py │                  │
      │  types/*.yaml │          │   bm25.py      │   ┌─────────────▼──────────┐
      │  packs/*.yaml │          │   reranker.py  │   │       billing/         │
      │  loader.py    │          │   tenant.py    │   │   hooks.py             │
      │  pack_registry│          └────────────────┘   └────────────────────────┘
      └───────────────┘
                                 ┌──────────────────────────────────┐
                                 │         execution/               │
                                 │   workflow.py  approvals.py      │
                                 │   action_registry.py             │
                                 └──────────────────────────────────┘
```

### MetaOntology OS — 9 Spaces

| Space      | Node Types                                  | Role                              |
|------------|---------------------------------------------|-----------------------------------|
| subject    | User, Team, Org, Agent                      | Actors with identity and agency   |
| resource   | Project, Document, File, Dataset, Tool, API | Artifacts that subjects act upon  |
| evidence   | TextUnit, LogEntry, Evidence                | Raw empirical observations        |
| concept    | Entity, Concept, Topic, Class               | Abstract knowledge                |
| claim      | Claim, Covariate                            | Derived assertions                |
| community  | Community, CommunityReport                  | Concept clusters                  |
| outcome    | Outcome, KPI, Risk                          | Measurable results                |
| lever      | Lever                                       | Tunable control variables         |
| policy     | Policy, Sensitivity, ApprovalRule           | Governance rules                  |

### MetaEdge Relationship Grammar

```
subject    ──[owns, manages, can_view, can_edit, can_execute, can_approve]──► resource
resource   ──[contains, derived_from, logged_as]──────────────────────────► evidence
evidence   ──[mentions, describes, exemplifies]────────────────────────────► concept
evidence   ──[supports, contradicts, timestamps]───────────────────────────► claim
concept    ──[related_to, subclass_of, part_of, influences, depends_on]────► concept
concept    ──[contributes_to, constrains, predicts, degrades]──────────────► outcome
lever      ──[raises, lowers, stabilizes, optimizes]───────────────────────► outcome
lever      ──[affects]─────────────────────────────────────────────────────► concept
community  ──[clusters, summarizes]────────────────────────────────────────► concept
policy     ──[protects, classifies, restricts]─────────────────────────────► resource
policy     ──[permits, denies, requires_approval]──────────────────────────► subject
```

---

## Quick Start

### 1. Start the data services

```bash
docker-compose up -d
```

This starts Neo4j, MongoDB, PostgreSQL, and ChromaDB.

### 2. Install OpenCrab

```bash
pip install -e ".[dev]"
```

### 3. Configure environment

```bash
opencrab init          # creates .env from template
# Edit .env if your credentials differ from defaults
```

**Local mode (no Docker required):**

```bash
STORAGE_MODE=local opencrab serve
```

Local mode uses SQLite + JSON files — no external services needed.

### 4. Seed example data

```bash
python scripts/seed_ontology.py
```

### 5. Verify connectivity

```bash
opencrab status
```

### 6. Add to Claude Code MCP

```bash
claude mcp add opencrab -- opencrab serve
```

Or add to your `.claude/mcp.json` manually (see below).

### 7. Run a query

```bash
opencrab query "system performance and error rates"
opencrab manifest    # see the full grammar
```

---

## Claude Code MCP Configuration

Add to `~/.claude/mcp.json` (or project-level `.mcp.json`):

```json
{
  "mcpServers": {
    "opencrab": {
      "command": "opencrab",
      "args": ["serve"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "opencrab",
        "MONGODB_URI": "mongodb://root:opencrab@localhost:27017",
        "MONGODB_DB": "opencrab",
        "POSTGRES_URL": "postgresql://opencrab:opencrab@localhost:5432/opencrab",
        "CHROMA_HOST": "localhost",
        "CHROMA_PORT": "8000"
      }
    }
  }
}
```

**Local mode (SQLite + JSON, no Docker):**

```json
{
  "mcpServers": {
    "opencrab": {
      "command": "opencrab",
      "args": ["serve"],
      "env": {
        "STORAGE_MODE": "local"
      }
    }
  }
}
```

---

## MCP Tool Reference

### Core Ontology (9 tools)

#### `ontology_manifest`
Returns the full MetaOntology grammar with version, spaces, meta-edges, impact categories, and ReBAC config.

#### `ontology_add_node`
```json
{
  "space": "subject",
  "node_type": "User",
  "node_id": "user-alice",
  "properties": { "name": "Alice Chen", "role": "analyst" },
  "tenant_id": "acme",
  "subject_id": "user-alice"
}
```
Returns `receipt_id + receipt_ts`. Properties validated against type schema if one exists.

#### `ontology_add_edge`
```json
{
  "from_space": "subject", "from_id": "user-alice",
  "relation": "owns",
  "to_space": "resource", "to_id": "doc-spec"
}
```
Validates the `(from_space, to_space, relation)` triple against the grammar before write.

#### `ontology_query` — Hybrid Query (v2)
```json
{
  "question": "What factors degrade system performance?",
  "spaces": ["concept", "outcome"],
  "limit": 10,
  "subject_id": "user-alice",
  "tenant_id": "acme",
  "use_bm25": true,
  "use_rerank": true
}
```
Pipeline: vector similarity → BM25 keyword → graph expansion → RRF reranking → policy filter.

#### `query_bm25`
```json
{ "question": "machine learning", "spaces": ["concept"], "limit": 10 }
```
BM25-only keyword search. Fast and deterministic, no embeddings.

#### `ontology_impact`
```json
{ "node_id": "lever-cache-ttl", "change_type": "update" }
```
Returns triggered I1–I7 impact categories and affected neighbours.

#### `ontology_rebac_check`
```json
{ "subject_id": "user-alice", "permission": "edit", "resource_id": "ds-events" }
```
Returns `{ "granted": true/false, "reason": "...", "path": [...] }`.

#### `ontology_lever_simulate`
```json
{ "lever_id": "lever-cache-ttl", "direction": "lowers", "magnitude": 0.7 }
```

#### `ontology_ingest`
```json
{ "text": "...", "source_id": "incident-2026-01", "metadata": { "space": "evidence" } }
```

---

### Identity & Canonicalization (7 tools)

#### `identity_add_alias`
Register `alias_id` as an alias for `canonical_id`. Types: `name`, `merge`, `external`.

#### `identity_resolve_canonical`
Resolve a node ID to its canonical form. Returns `is_alias: true` if it was an alias.

#### `identity_propose_duplicate`
Propose two nodes as potential duplicates for human review.

#### `identity_resolve_duplicate`
Accept or reject a pending duplicate candidate. On accept, registers alias automatically.

#### `identity_list_pending_duplicates`
List all pending duplicate candidates sorted by similarity.

#### `canonicalize_merge_nodes`
Merge `alias_id` into `canonical_id` using tombstone pattern — alias node is preserved.

#### `canonicalize_find_and_propose`
Find nodes with similar names and auto-propose them as duplicate candidates.

---

### Promotion Lifecycle (4 tools)

Tracks extracted entities through: `candidate → validated → promoted | rejected`.

#### `promotion_register_candidate`
Register an extracted entity as a promotion candidate (not visible in normal queries yet).

#### `promotion_validate_candidate`
Mark a candidate as validated — ready for final review.

#### `promotion_promote`
Promote to `promoted` status. Optionally links evidence nodes via `supports` edges.

#### `promotion_reject`
Mark a candidate as rejected with an optional reason.

---

### Workflow & Approvals (3 tools)

#### `workflow_create_run`
Start an auditable workflow run in `pending` state before executing any sensitive action.

#### `workflow_advance`
Advance a run to a new status (`pending → running → approved/rejected → completed/failed`).

#### `approval_request`
Submit an approval request linked to a workflow run.

---

### CrabHarness Integration (1 tool)

#### `harness_promotion_apply`
```json
{ "package": { ... }, "dry_run": false }
```
Apply a CrabHarness PromotionPackage inline. Returns `receipt_id + receipt_ts` per node/edge written. Use `dry_run: true` to validate without writing.

---

### Billing & Usage (2 tools)

#### `billing_get_usage`
```json
{ "tenant_id": "acme", "event_type": "query", "since": "2026-04-01T00:00:00Z" }
```
Aggregated usage counts by event type for a tenant.

#### `billing_list_events`
Recent raw billing events for a tenant (last N).

---

### Schema Packs (3 tools)

Domain-specific schema bundles that extend the type registry without touching core schemas.

#### `schema_pack_list`
List available packs with install status. Built-in packs: `saas`, `biomedical`, `legal`.

#### `schema_pack_install`
```json
{ "name": "biomedical" }
```
Generates stub YAML type schemas in `schemas/types/`. Existing user schemas are never overwritten.

#### `schema_pack_uninstall`
```json
{ "name": "biomedical", "force": false }
```

---

## CLI Reference

```
opencrab init              Create .env from template
opencrab serve             Start MCP server (stdio)
opencrab status            Check store connections
opencrab ingest <path>     Ingest files into vector store
opencrab query <question>  Run a hybrid query
opencrab manifest          Print MetaOntology grammar
```

Global flags:

```
opencrab --version
opencrab query --json-output <q>
opencrab manifest --json-output
opencrab ingest -r <dir>
opencrab ingest -e .txt,.md <dir>
```

---

## Impact Categories (I1–I7)

| ID | Name                     | Question                                              |
|----|--------------------------|-------------------------------------------------------|
| I1 | Data impact              | What data values or records change?                   |
| I2 | Relation impact          | What graph edges are affected?                        |
| I3 | Space impact             | Which ontology spaces are touched?                    |
| I4 | Permission impact        | Which access permissions change?                      |
| I5 | Logic impact             | Which business rules are invalidated?                 |
| I6 | Cache/index impact       | Which caches or indexes must be refreshed?            |
| I7 | Downstream system impact | Which external systems or APIs are affected?          |

---

## Active Metadata Layers

Every node and edge can carry orthogonal metadata attributes:

| Layer      | Attributes                         |
|------------|------------------------------------|
| existence  | identity, provenance, lineage      |
| quality    | confidence, freshness, completeness|
| relational | dependency, sensitivity, maturity  |
| behavioral | usage, mutation, effect            |

---

## Development

```bash
make dev-install    # install with dev extras
make up             # start docker services
make seed           # seed example data
make test           # run test suite
make coverage       # test + coverage report
make lint           # ruff linter
make format         # black + isort
make status         # check store connections
```

### Running integration tests

```bash
OPENCRAB_INTEGRATION=1 pytest tests/ -v
```

### Project structure

```
opencrab/
├── grammar/          # MetaOntology grammar (manifest, validator, glossary)
├── schemas/          # Type schemas (YAML), schema packs, loader
│   ├── types/        # Per-node-type YAML schemas (required/enum validation)
│   └── packs/        # Domain packs: saas, biomedical, legal
├── ontology/         # Core engines
│   ├── builder.py    # Node/edge write with receipt IDs + schema validation
│   ├── query.py      # Hybrid query: vector + BM25 + graph + RRF reranker
│   ├── bm25.py       # Pure Python BM25 index
│   ├── reranker.py   # RRF + BM25 cross-score fusion
│   ├── identity.py   # Alias table + duplicate candidate detection
│   ├── canonicalize.py # Tombstone-based node merge
│   ├── promotion.py  # Extraction lifecycle (candidate → promoted)
│   ├── tenant.py     # Tenant isolation context + property stamping
│   ├── rebac.py      # Relationship-based access control
│   └── impact.py     # I1–I7 impact analysis
├── execution/        # Workflow & approvals runtime
│   ├── workflow.py   # WorkflowEngine state machine
│   ├── approvals.py  # ApprovalEngine queue
│   └── action_registry.py # YAML action schemas
├── billing/          # Usage metering
│   └── hooks.py      # BillingHooks — billing_events table
├── stores/           # Store adapters (Neo4j, ChromaDB, MongoDB, PostgreSQL, Local)
└── mcp/              # MCP server (stdio JSON-RPC) + 30 tool definitions
tests/                # Test suite
scripts/              # Seed script
crabharness/          # Evidence collection pipeline
docker-compose.yml    # All data services
```

---

## CrabHarness — Mission Control Plane

[`crabharness/`](./crabharness/) is the companion data collection pipeline for OpenCrab. It owns the "how do we *get* the evidence that fills the ontology" layer, while OpenCrab owns the "how is the ontology structured and queried" layer.

### What CrabHarness adds

| Capability | Description |
|------------|-------------|
| **Plugin workers** | Drop a `worker.manifest.json` + `adapter.py` into `codex_workers/` and a new collector appears in the catalog — no core changes. |
| **Mission-first planner** | Declarative `mission.json` picks workers by `target_object` + tag match instead of hardcoded pipelines. |
| **Three-gate validation** | Every artifact bundle scored on (1) completeness, (2) semantic relevance, (3) autoresearch verdict. |
| **Harvest dedupe** | `.seen.json` side-index with SHA256 IDs for `harvest` collection mode. |
| **Promotion packages** | Builds OpenCrab node/edge packages — **never mutates OpenCrab directly**. |
| **MCP-native apply** | `harness_promotion_apply` MCP tool applies packages inline from Claude without file I/O. |

### Quickstart

```bash
cd crabharness
pip install -e .
crabharness catalog
crabharness run missions/examples/github-trending-harvest.json
crabharness promotion-apply artifacts/runs/<mission>/<run>/promotion_package.json
```

### Integration with OpenCrab

CrabHarness produces promotion packages as pure JSON. Apply them via:
- **CLI**: `crabharness promotion-apply <package.json>`
- **MCP**: `harness_promotion_apply { "package": { ... } }`

The `dry_run: true` flag validates grammar and schemas without writing.

---

## License

MIT — see [LICENSE](LICENSE).

---

*OpenCrab: resistance is futile. Your agent will become an ontology.*
