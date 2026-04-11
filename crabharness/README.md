# CrabHarness

**Mission-first control plane** for plugin-based data collection. CrabHarness plans collection missions, delegates heavy crawling to Codex workers, validates artifacts (completeness + semantic scoring), and emits promotion packages for OpenCrab's ontology graph.

> v0.2.0 — Fully generalized plugin architecture. No domain hardcoding. Add new workers with just a manifest + adapter.

## Architecture

```
     mission.json
          |
          v
   +--------------+        +------------------+
   | Planner      | -----> | Worker Registry  |  (scans codex_workers/*/worker.manifest.json)
   +--------------+        +------------------+
          |
          v
   +--------------+
   | Delegation   | ---> Codex worker subprocess (via arg_schema)
   +--------------+
          |
          v
   +--------------+        +------------------+
   | Runtime      | -----> | Worker Adapter   |  (collect_bundle / validate_bundle)
   +--------------+        +------------------+
          |
          v
   +--------------------+
   | Validation         |  completeness + semantic_score + autoresearch_verdict
   +--------------------+
          |
          v
   +--------------+
   | Promotion    | ---> OpenCrab node/edge graph
   +--------------+
```

**Core principles:**
1. **Mission-first, not crawler-first** — declarative `mission.json` drives worker selection
2. **Plugin-based workers** — add a manifest + adapter, no core code changes
3. **Three-gate validation** — completeness score, semantic score, autoresearch verdict
4. **OpenCrab promotion separated** — harness produces packages, doesn't write the graph

## Install

```bash
# Clone and install in editable mode
git clone <repo> && cd Crabharness
pip install -e .

# With dev tools (pytest, ruff)
pip install -e ".[dev]"
```

Verify:
```bash
crabharness catalog
```

## Quick start

### 1. Run an example mission

```bash
crabharness run missions/examples/github-trending-harvest.json
```

Output: a run directory in `artifacts/runs/<mission_id>/<run_id>/` containing:
- `mission.json` — frozen mission spec
- `job-01-delegation.json` — Codex delegation payload
- `job-01.stdout.log` / `.stderr.log` — worker output
- `job-01-artifact-bundle.json` — collected evidence
- `job-01-validation-report.json` — completeness + semantic scores
- `job-01-promotion-package.json` — OpenCrab-ready node/edge package

### 2. Inspect what's registered

```bash
crabharness catalog
```

Returns all workers from `codex_workers/*/worker.manifest.json`.

### 3. Plan without executing

```bash
crabharness plan missions/examples/github-trending-harvest.json
```

Shows the resolved jobs (which worker, what args) without running them.

### 4. Build a delegation payload

```bash
crabharness delegate missions/examples/github-trending-harvest.json
```

Shows the exact CLI command that will be invoked. Useful for debugging arg_schema.

### 5. Doctor a worker

```bash
crabharness doctor soeak                    # alias match (second segment of worker_id)
crabharness doctor codex.github.trending    # full worker_id
```

Runs the adapter's `doctor()` function if present, otherwise checks the manifest's command is on PATH.

### 6. Export JSON schemas

```bash
crabharness schema mission           # MissionSpec schema
crabharness schema artifact-bundle   # ArtifactBundle schema
```

Available schemas: `mission`, `delegation-job`, `artifact-bundle`, `validation-report`, `promotion-package`.

## Writing a mission

A mission is a declarative JSON file that describes *what* to collect, *how to validate it*, and *what to promote*. See `missions/examples/github-trending-harvest.json`:

```json
{
  "mission_id": "ai-trends-harvest-001",
  "workspace_id": "trends",
  "objective": "Collect emerging AI/LLM trends from GitHub trending repos.",
  "target_object": "TrendSignal",
  "target": {
    "source": "github",
    "language": "python",
    "since": "weekly"
  },
  "questions": [
    "What new AI frameworks or patterns are emerging in top repos?"
  ],
  "collection_mode": "harvest",
  "required_evidence": ["repos", "readme_content"],
  "dedupe_key": "github|trending|{language}|{since}",
  "promotion_policy": "auto_if_valid",
  "constraints": {
    "max_jobs": 1,
    "concurrency": 2,
    "delay_ms": 500,
    "dry_run": false
  },
  "success_criteria": {
    "min_artifacts": 1,
    "required_fields": ["repos"],
    "completeness_threshold": 0.8,
    "semantic_questions": [
      "Are repos focused on AI/LLM/agents?",
      "Is implementation quality high (stars>500)?"
    ],
    "min_semantic_score": 0.6
  }
}
```

### Key fields
- `target` — passed to the worker as CLI args via its `arg_schema`
- `target_object` — must match a worker's `supported_targets`
- `collection_mode` — `fetch` | `harvest` | `refresh` | `discover`
- `success_criteria.required_fields` — each must appear in the bundle's `summary`
- `success_criteria.semantic_questions` — fed to the semantic scorer (currently heuristic, LLM integration pending)
- `dedupe_key` — template for the `.seen.json` dedupe index (use `{var}` for target fields)

## Adding a new worker plugin

Create a folder under `codex_workers/`:

```
codex_workers/
  my_worker/
    __init__.py            # empty
    worker.manifest.json   # capability metadata
    adapter.py             # collect_bundle / validate_bundle
```

### worker.manifest.json

```json
{
  "worker_id": "codex.my_worker.collector",
  "job_type": "my_worker_crawl",
  "supported_targets": ["MyTarget"],
  "tags": ["mydomain", "topic1"],
  "source_ids": ["my_source"],
  "command": ["python", "-m", "my_worker.run"],
  "arg_schema": {
    "region": {
      "flag": "--region",
      "type": "string",
      "default": "us",
      "description": "Region to crawl"
    },
    "limit": {
      "flag": "--limit",
      "from_option": true,
      "type": "integer",
      "description": "Max items"
    }
  },
  "adapter_module": "codex_workers.my_worker.adapter",
  "artifact_types": ["json_dataset", "progress_log"],
  "validation_checks": ["items_found"],
  "description": "My new collector"
}
```

`arg_schema` notes:
- `from_option: true` pulls from `mission.constraints` (e.g. concurrency, delay_ms)
- Otherwise pulls from `mission.target`
- `type: "boolean"` emits the flag only if truthy

### adapter.py

```python
from pathlib import Path
from crabharness.models import ArtifactBundle, ArtifactFile, DelegationJob, MissionSpec, ValidationIssue, ValidationReport
from crabharness.semantic import score_bundle_semantically, determine_autoresearch_verdict


def collect_bundle(root_dir: Path, mission: MissionSpec, job: DelegationJob, run_id: str,
                   progress_path: Path | None = None, error_log_path: Path | None = None) -> ArtifactBundle:
    # Read the artifacts your worker produced, return an ArtifactBundle
    return ArtifactBundle(
        run_id=run_id,
        mission_id=mission.mission_id,
        worker_id=job.worker_id,
        job_id=job.job_id,
        target_ref=job.target,
        files=[ArtifactFile(kind="json_dataset", path="...", format="json", description="...")],
        metrics={"items_count": 42},
        summary={"items_count": 42, "items": [...]},
    )


def validate_bundle(bundle: ArtifactBundle, mission: MissionSpec) -> ValidationReport:
    issues: list[ValidationIssue] = []
    required = mission.success_criteria.required_fields or []
    passed = sum(1 for f in required if f in bundle.summary)
    completeness = round(passed / max(len(required), 1), 3)

    semantic_result = score_bundle_semantically(bundle, mission)
    semantic_score = semantic_result.get("semantic_score", 0.0)
    verdict = determine_autoresearch_verdict(completeness, semantic_score, mission)

    status = "pass" if completeness >= mission.success_criteria.completeness_threshold else "retry"
    return ValidationReport(
        run_id=bundle.run_id,
        mission_id=mission.mission_id,
        status=status,
        completeness_score=completeness,
        semantic_score=semantic_score,
        semantic_verdict=verdict,
        issues=issues,
        next_action="promote" if status == "pass" else "retry",
    )


def doctor(root_dir: Path) -> dict:
    """Optional: worker-specific preflight checks. Called by `crabharness doctor`."""
    return {"checks": [...], "ok": True}
```

**Function naming:** prefer generic `collect_bundle` / `validate_bundle`. Legacy domain names like `collect_soeak_bundle` are still supported via fallback.

## Validation layers

Every bundle goes through three gates:

1. **Completeness** (`completeness_score`, 0.0–1.0)
   - Ratio of `required_fields` present in `bundle.summary`
   - Must meet `mission.success_criteria.completeness_threshold`

2. **Semantic score** (`semantic_score`, 0.0–1.0)
   - Currently a keyword-heuristic placeholder in `crabharness/semantic.py`
   - LLM-based scoring against `mission.success_criteria.semantic_questions` is planned

3. **Autoresearch verdict** (`keep` | `discard` | `crash`)
   - Loopy-era Phase 3.5 gate
   - Derived from completeness + semantic thresholds
   - Feeds the promotion package's `CollectionCompleteness` claim

## Dedupe

Harvest missions use `crabharness/dedupe.py` with a `.seen.json` side file:

```python
from crabharness.dedupe import is_seen, mark_seen, mark_applied, get_seen_stats
```

`dedupe_key` in the mission (e.g. `"github|trending|{language}|{since}"`) is templated against `mission.target` and hashed to SHA256.

## Promotion

`build_promotion_package()` produces:
- **Nodes**: target resource, CrawlRun, CollectionCompleteness claim
- **Edges**: derived_from, logged_as
- **Evidence refs**: all artifact file paths
- **Claim refs**: the completeness claim ID

This package is meant to be applied to OpenCrab separately — CrabHarness never mutates OpenCrab directly.

## Project layout

```
Crabharness/
├── crabharness/              # Control-plane package
│   ├── cli.py                # `crabharness` entry point
│   ├── models.py             # Pydantic schemas
│   ├── registry.py           # Plugin manifest scanner
│   ├── planner.py            # Mission -> jobs
│   ├── delegation.py         # Job -> Codex payload (arg_schema driven)
│   ├── runtime.py            # Subprocess + adapter dispatch
│   ├── semantic.py           # Semantic scoring (placeholder)
│   ├── dedupe.py             # .seen.json index
│   ├── promotion.py          # OpenCrab node/edge builder
│   └── preflight.py          # `crabharness doctor`
├── codex_workers/            # Worker plugins
│   ├── soeak/                # G2B bid crawler (Playwright + SQLite)
│   └── github_trending/      # GitHub trending (stub)
├── missions/examples/        # Example mission templates
├── schemas/                  # JSON schemas (regenerated via `crabharness schema`)
└── artifacts/runs/           # Run outputs
```

## Common workflows

**Run a new mission end-to-end:**
```bash
crabharness run missions/my-mission.json
```

**Test a mission without running the worker (dry-run):**
```bash
crabharness run missions/my-mission.json --dry-run
```

**Debug worker argument construction:**
```bash
crabharness delegate missions/my-mission.json
# Copy the `command` array, run it manually, inspect output
```

**Rebuild JSON schemas from Pydantic models:**
```bash
for name in mission delegation-job artifact-bundle validation-report promotion-package; do
  crabharness schema "$name" > "schemas/${name}.schema.json"
done
```

## Roadmap

- [ ] Real Claude LLM integration for `semantic.score_bundle_semantically()`
- [ ] Cron/loop runner for harvest missions
- [ ] `crabharness promotion apply` — push packages into OpenCrab directly
- [ ] Reference workers: guru_github, rss_feed
- [ ] Worker test harness (mock adapters for CI)

## Design principles

1. **Mission-first** — the mission is the source of truth, not the crawler
2. **Plugin isolation** — workers can't import from each other
3. **Three-gate validation** — completeness + semantic + autoresearch
4. **Separation from OpenCrab** — promotion packages, not direct writes
5. **No hardcoded domains** — everything flows through manifest + adapter
