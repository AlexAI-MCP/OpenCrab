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
                                 └────────────────┘          │  sql_store     │
                                                             └───────┬────────┘
                                                                     │
                              ┌──────────────────────────────────────┤
                              │              Data Layer              │
              ┌───────────────┼───────────────┬──────────────────────┤
              │               │               │                      │
      ┌───────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌────────────▼───┐
      │    Neo4j     │ │  ChromaDB   │ │  MongoDB   │ │  PostgreSQL    │
      │  (graph)     │ │  (vectors)  │ │ (documents)│ │  (registry +   │
      │  Cypher      │ │  semantic   │ │  audit log │ │   ReBAC policy)│
      │  traversal   │ │  search     │ │            │ │                │
      └──────────────┘ └─────────────┘ └────────────┘ └────────────────┘
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

Alternatively, with `uvx` (no install required):

```json
{
  "mcpServers": {
    "opencrab": {
      "command": "uvx",
      "args": ["--from", "opencrab", "opencrab", "serve"]
    }
  }
}
```

---

## MCP Tool Reference

### `ontology_manifest`

Returns the full MetaOntology grammar: spaces, meta-edges, impact categories,
active metadata layers, and ReBAC configuration.

```json
{}
```

### `ontology_add_node`

Add or update a node in the ontology.

```json
{
  "space": "subject",
  "node_type": "User",
  "node_id": "user-alice",
  "properties": {
    "name": "Alice Chen",
    "role": "analyst"
  }
}
```

### `ontology_add_edge`

Add a directed edge (grammar-validated before write).

```json
{
  "from_space": "subject",
  "from_id": "user-alice",
  "relation": "owns",
  "to_space": "resource",
  "to_id": "doc-spec"
}
```

Returns a validation error if the relation is not valid for the given space pair.

### `ontology_query`

Hybrid vector + graph search.

```json
{
  "question": "What factors degrade system performance?",
  "spaces": ["concept", "outcome"],
  "limit": 10
}
```

### `ontology_impact`

Impact analysis: which I1–I7 categories are triggered by a change?

```json
{
  "node_id": "lever-cache-ttl",
  "change_type": "update"
}
```

Returns triggered impact categories, affected neighbouring nodes, and a summary.

### `ontology_rebac_check`

Relationship-based access control check.

```json
{
  "subject_id": "user-alice",
  "permission": "edit",
  "resource_id": "ds-events"
}
```

Returns `{ "granted": true/false, "reason": "...", "path": [...] }`.

### `ontology_lever_simulate`

Predict downstream outcome changes from a lever movement.

```json
{
  "lever_id": "lever-cache-ttl",
  "direction": "lowers",
  "magnitude": 0.7
}
```

### `ontology_ingest`

Ingest text into the vector and document stores.

```json
{
  "text": "The Q4 incident report shows error rates increased by 40%...",
  "source_id": "incident-2026-01",
  "metadata": {
    "space": "evidence",
    "type": "incident_report"
  }
}
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
opencrab --version         Show version
opencrab query --json-output <q>   Raw JSON output
opencrab manifest --json-output    Raw JSON grammar
opencrab ingest -r <dir>   Recursive ingestion
opencrab ingest -e .txt,.md <dir>  Filter by extension
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

Integration tests require live services:

```bash
OPENCRAB_INTEGRATION=1 pytest tests/ -v
```

### Project structure

```
opencrab/
├── grammar/          # MetaOntology grammar (manifest, validator, glossary)
├── stores/           # Store adapters (Neo4j, ChromaDB, MongoDB, PostgreSQL)
├── ontology/         # Ontology engine (builder, ReBAC, impact, query)
└── mcp/              # MCP server (stdio JSON-RPC) and tool definitions
tests/                # Test suite (grammar, stores, MCP tools)
scripts/              # Seed script
docker-compose.yml    # All data services
```

---

## License

MIT — see [LICENSE](LICENSE).

---

*OpenCrab: resistance is futile. Your agent will become an ontology.*
