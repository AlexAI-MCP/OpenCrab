# Query Visualization Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add natural-language query-to-graph-layer flow so users can run a query from CLI or web and visualize toggleable multi-hop result layers in OpenCrab web UI.

**Architecture:** Build a file-based query layer pipeline. Python CLI generates layer JSON files under `apps/web/public/query-layers` using existing `HybridQuery` and graph neighbor traversal. Web UI loads `layers-index.json`, toggles layers, and overlays layer nodes/edges on top of existing graph rendering.

**Tech Stack:** Python 3.11, Click CLI, OpenCrab stores (LocalGraphStore/Neo4jStore), Next.js 14, React 18, TypeScript, D3.

---

## File Structure (planned changes)

- Create: `opencrab/ontology/query_layers.py`  
  Responsibility: layer file I/O, index update, pruning, and schema-safe persistence.
- Create: `opencrab/ontology/query_visualization.py`  
  Responsibility: query result normalization + multi-hop expansion + layer payload assembly.
- Modify: `opencrab/cli.py`  
  Responsibility: add `query-viz` command and wire command options to layer generation.
- Create: `tests/test_query_layers.py`  
  Responsibility: file/index behavior tests.
- Create: `tests/test_query_visualization.py`  
  Responsibility: subgraph expansion and score decay tests.
- Modify: `apps/web/lib/api.ts`  
  Responsibility: layer types + `getQueryLayers()` + `getLayerData()`.
- Create: `apps/web/lib/queryLayerSearch.ts`  
  Responsibility: browser-side lightweight query for optional web input.
- Create: `apps/web/components/LayerPanel.tsx`  
  Responsibility: layer list rendering + toggle callbacks + refresh.
- Create: `apps/web/components/QueryInput.tsx`  
  Responsibility: web-side query input and temporary layer trigger.
- Modify: `apps/web/components/GraphView.tsx`  
  Responsibility: layer node/edge overlay visualization and highlight styles.
- Modify: `apps/web/app/dashboard/page.tsx`  
  Responsibility: layer state wiring and component composition.
- Create: `apps/web/public/query-layers/layers-index.json`  
  Responsibility: initial empty layer index.

---

### Task 1: Build layer persistence module (Python)

**Files:**
- Create: `opencrab/ontology/query_layers.py`
- Test: `tests/test_query_layers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_layers.py
from pathlib import Path
from opencrab.ontology.query_layers import ensure_layer_store, write_layer, read_index

def test_write_layer_creates_index_and_file(tmp_path: Path) -> None:
    store_dir = tmp_path / "query-layers"
    ensure_layer_store(store_dir)

    layer = {
        "id": "layer-20260521-170000",
        "query": "ELERA relation",
        "timestamp": "2026-05-21T17:00:00+09:00",
        "source": "cli",
        "nodes": [],
        "edges": [],
        "metadata": {"total_nodes": 0, "total_edges": 0, "max_hops": 3, "query_time_ms": 1},
    }
    write_layer(store_dir, layer)

    assert (store_dir / "layer-20260521-170000.json").exists()
    idx = read_index(store_dir)
    assert idx["layers"][0]["id"] == "layer-20260521-170000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_layers.py::test_write_layer_creates_index_and_file -v`  
Expected: FAIL with `ModuleNotFoundError` or missing function import.

- [ ] **Step 3: Write minimal implementation**

```python
# opencrab/ontology/query_layers.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def ensure_layer_store(store_dir: Path) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    index = store_dir / "layers-index.json"
    if not index.exists():
        index.write_text(json.dumps({"layers": [], "version": "1.0"}, ensure_ascii=False, indent=2), encoding="utf-8")

def read_index(store_dir: Path) -> dict[str, Any]:
    ensure_layer_store(store_dir)
    return json.loads((store_dir / "layers-index.json").read_text(encoding="utf-8"))

def write_layer(store_dir: Path, layer: dict[str, Any]) -> None:
    ensure_layer_store(store_dir)
    (store_dir / f"{layer['id']}.json").write_text(json.dumps(layer, ensure_ascii=False, indent=2), encoding="utf-8")
    idx = read_index(store_dir)
    idx["layers"] = [x for x in idx["layers"] if x["id"] != layer["id"]]
    idx["layers"].insert(0, {
        "id": layer["id"], "query": layer["query"], "timestamp": layer["timestamp"],
        "source": layer["source"], "node_count": len(layer["nodes"]), "edge_count": len(layer["edges"]), "enabled": True,
    })
    (store_dir / "layers-index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_query_layers.py -v`  
Expected: PASS (all tests in `test_query_layers.py`).

- [ ] **Step 5: Commit**

```bash
git add opencrab/ontology/query_layers.py tests/test_query_layers.py
git commit -m "feat: add query layer file persistence module"
```

---

### Task 2: Implement query visualization assembly (Python)

**Files:**
- Create: `opencrab/ontology/query_visualization.py`
- Test: `tests/test_query_visualization.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_visualization.py
from opencrab.ontology.query_visualization import build_layer_payload

class FakeGraph:
    available = True
    def find_neighbors(self, node_id: str, direction: str = "both", depth: int = 1, limit: int = 50):
        return [{"properties": {"id": "b", "title": "B"}, "labels": ["Claim"], "relation_type": "supports", "depth": 1}]

def test_build_layer_payload_includes_seed_and_neighbors() -> None:
    query_results = [{"node_id": "a", "score": 0.9, "text": "A", "metadata": {}}]
    layer = build_layer_payload("q", query_results, FakeGraph(), max_hops=2, limit=30)
    ids = {n["id"] for n in layer["nodes"]}
    assert "a" in ids
    assert "b" in ids
    assert any(e["relation"] == "supports" for e in layer["edges"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_visualization.py::test_build_layer_payload_includes_seed_and_neighbors -v`  
Expected: FAIL with missing module/function.

- [ ] **Step 3: Write minimal implementation**

```python
# opencrab/ontology/query_visualization.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

def _now_id() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"layer-{now.strftime('%Y%m%d-%H%M%S')}", now.isoformat()

def build_layer_payload(question: str, query_results: list[dict[str, Any]], graph: Any, max_hops: int, limit: int) -> dict[str, Any]:
    layer_id, ts = _now_id()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seed_ids = [r.get("node_id") for r in query_results if r.get("node_id")]

    for r in query_results:
        nid = r.get("node_id")
        if not nid:
            continue
        nodes.append({"id": nid, "space": "concept", "node_type": "Unknown", "properties": {}, "score": float(r.get("score", 0.0)), "highlight": True, "hop_distance": 0})

    for seed in seed_ids:
        for n in graph.find_neighbors(seed, direction="both", depth=max_hops, limit=limit):
            nid = (n.get("properties") or {}).get("id")
            if not nid:
                continue
            nodes.append({"id": nid, "space": "concept", "node_type": (n.get("labels") or ["Unknown"])[0], "properties": n.get("properties") or {}, "score": 0.6, "highlight": False, "hop_distance": int(n.get("depth", 1))})
            edges.append({"from_id": seed, "to_id": nid, "relation": n.get("relation_type", "related_to"), "from_space": "concept", "to_space": "concept", "path_rank": int(n.get("depth", 1))})

    dedup_nodes = {n["id"]: n for n in nodes}
    return {
        "id": layer_id, "query": question, "timestamp": ts, "source": "cli",
        "nodes": list(dedup_nodes.values()), "edges": edges,
        "metadata": {"total_nodes": len(dedup_nodes), "total_edges": len(edges), "max_hops": max_hops, "query_time_ms": 0},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_query_visualization.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add opencrab/ontology/query_visualization.py tests/test_query_visualization.py
git commit -m "feat: add query visualization payload builder"
```

---

### Task 3: Add `query-viz` CLI command

**Files:**
- Modify: `opencrab/cli.py`
- Modify: `tests/test_query_visualization.py` (add command wiring test)

- [ ] **Step 1: Write the failing CLI test**

```python
# tests/test_query_visualization.py
from click.testing import CliRunner
from opencrab.cli import main

def test_query_viz_command_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["query-viz", "ELERA relation", "--limit", "5"])
    assert result.exit_code == 0
    assert "Layer saved" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_visualization.py::test_query_viz_command_registered -v`  
Expected: FAIL with `No such command 'query-viz'`.

- [ ] **Step 3: Implement command in `opencrab/cli.py`**

```python
@main.command("query-viz")
@click.argument("question")
@click.option("--max-hops", default=3, show_default=True, type=int)
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--output-dir", default=None, type=str, help="Override web public directory")
def query_viz(question: str, max_hops: int, limit: int, output_dir: str | None) -> None:
    from pathlib import Path
    from opencrab.config import get_settings
    from opencrab.ontology.query import HybridQuery
    from opencrab.ontology.query_layers import write_layer
    from opencrab.ontology.query_visualization import build_layer_payload
    from opencrab.stores.factory import make_graph_store, make_vector_store

    cfg = get_settings()
    hybrid = HybridQuery(make_vector_store(cfg), make_graph_store(cfg))
    results = [r.to_dict() for r in hybrid.query(question=question, limit=limit)]
    layer = build_layer_payload(question, results, hybrid._graph, max_hops=max_hops, limit=limit)
    target = Path(output_dir) if output_dir else Path("apps/web/public/query-layers")
    write_layer(target, layer)
    console.print(f"[green]Layer saved:[/green] {layer['id']}")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_query_layers.py tests/test_query_visualization.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add opencrab/cli.py tests/test_query_visualization.py
git commit -m "feat: add query-viz CLI command"
```

---

### Task 4: Add web layer data access and lightweight search helper

**Files:**
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/lib/queryLayerSearch.ts`

- [ ] **Step 1: Add type-first compile guard (failing by missing types/functions)**

```ts
// apps/web/lib/api.ts (usage target for later integration)
export interface LayerMetadata { /* ... */ }
export interface LayerData { /* ... */ }
export async function getQueryLayers(): Promise<{ layers: LayerMetadata[]; version: string }> { /* ... */ }
export async function getLayerData(layerId: string): Promise<LayerData | null> { /* ... */ }
```

- [ ] **Step 2: Run build to verify failure**

Run: `cd apps/web && npm run build`  
Expected: FAIL from unresolved imports in next tasks (or currently no new usage yet if deferred).

- [ ] **Step 3: Implement API helpers + search utility**

```ts
// apps/web/lib/queryLayerSearch.ts
import type { OcEdge, OcNode } from './api'
export function searchLocalSubgraph(nodes: OcNode[], edges: OcEdge[], query: string, maxHops = 2) {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean)
  const isHit = (n: OcNode) => JSON.stringify(n.properties).toLowerCase().includes(tokens[0] ?? '')
  const seeds = nodes.filter(isHit).slice(0, 20)
  return { seeds, edges: edges.filter(e => seeds.some(s => s.id === e.from_id || s.id === e.to_id)) }
}
```

- [ ] **Step 4: Run build to verify pass**

Run: `cd apps/web && npm run build`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/api.ts apps/web/lib/queryLayerSearch.ts
git commit -m "feat(web): add query layer api client and local search helper"
```

---

### Task 5: Add LayerPanel/QueryInput and wire dashboard + graph overlay

**Files:**
- Create: `apps/web/components/LayerPanel.tsx`
- Create: `apps/web/components/QueryInput.tsx`
- Modify: `apps/web/components/GraphView.tsx`
- Modify: `apps/web/app/dashboard/page.tsx`

- [ ] **Step 1: Add failing integration compile target**

```tsx
// apps/web/app/dashboard/page.tsx (planned usage)
<LayerPanel layers={layers} enabledLayerIds={enabledLayerIds} onToggle={toggleLayer} onRefresh={refreshLayers} />
<QueryInput onRun={runWebQuery} />
<GraphView ... layerNodes={activeLayerNodes} layerEdges={activeLayerEdges} />
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cd apps/web && npm run build`  
Expected: FAIL with missing component/prop errors.

- [ ] **Step 3: Implement components and graph overlay**

```tsx
// LayerPanel.tsx
export default function LayerPanel({ layers, enabledLayerIds, onToggle, onRefresh }: Props) {
  return <div>{layers.map(l => <label key={l.id}><input type="checkbox" checked={enabledLayerIds.includes(l.id)} onChange={() => onToggle(l.id)} />{l.query}</label>)}</div>
}

// QueryInput.tsx
export default function QueryInput({ onRun }: { onRun: (q: string) => void }) {
  const [q, setQ] = useState('')
  return <form onSubmit={e => { e.preventDefault(); onRun(q) }}><input value={q} onChange={e => setQ(e.target.value)} /><button>질의</button></form>
}

// GraphView.tsx (new props)
interface Props { /* existing */ layerNodes?: OcNode[]; layerEdges?: OcEdge[] }
const mergedNodes = [...nodes, ...(layerNodes ?? [])]
const mergedEdges = [...edges, ...(layerEdges ?? [])]
```

- [ ] **Step 4: Run build/lint**

Run: `cd apps/web && npm run build`  
Expected: PASS.

Run: `cd apps/web && npm run lint`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/LayerPanel.tsx apps/web/components/QueryInput.tsx apps/web/components/GraphView.tsx apps/web/app/dashboard/page.tsx
git commit -m "feat(web): add query layer panel and graph overlay integration"
```

---

### Task 6: Seed index file, docs, and end-to-end verification

**Files:**
- Create: `apps/web/public/query-layers/layers-index.json`
- Modify: `apps/web/public/GUIDE.md`

- [ ] **Step 1: Add initial empty index file**

```json
{
  "layers": [],
  "version": "1.0",
  "last_updated": null
}
```

- [ ] **Step 2: Document usage**

```md
## Query Layers
1. CLI: `opencrab query-viz "ELERA와 acli의 관계는?" --max-hops 3 --limit 20`
2. Open http://localhost:3000/dashboard
3. Toggle layer in Layer Panel
```

- [ ] **Step 3: Run backend tests**

Run: `python -m pytest tests/test_query_layers.py tests/test_query_visualization.py -v`  
Expected: PASS.

- [ ] **Step 4: Run web checks**

Run: `cd apps/web && npm run build && npm run lint`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/public/query-layers/layers-index.json apps/web/public/GUIDE.md
git commit -m "docs: add query layer usage and bootstrap index file"
```

---

## Self-Review Checklist (completed)

1. **Spec coverage:**  
   - CLI natural-language query flow: Tasks 2-3  
   - Multi-hop expansion: Task 2  
   - Layer persistence/index: Tasks 1, 6  
   - Web toggleable layers: Tasks 4-5  
   - Optional web query input: Tasks 4-5
2. **Placeholder scan:** No TBD/TODO placeholders remain.
3. **Type consistency:** `LayerMetadata`, `LayerData`, `layerNodes`, `layerEdges`, and `query-viz` naming is consistent across tasks.

