# OpenCrab Query Visualization Design

**Date:** 2026-05-21  
**Author:** Copilot CLI  
**Status:** Approved

## Overview

Enable users to query OpenCrab's knowledge graph using natural language from either the Copilot CLI or web UI, and visualize the results as interactive graph layers that can be toggled on/off independently.

## Problem Statement

Users currently interact with OpenCrab data in two ways:
1. Direct SQLite queries (technical, requires SQL knowledge)
2. Web UI search box (basic keyword filtering)

Neither approach supports:
- Natural language queries with semantic understanding
- Multi-hop relationship exploration
- Persistent query results for comparison
- Visual exploration of query-specific subgraphs

## Goals

1. **Natural Language Querying**: Users can ask questions in natural language (Korean or English)
2. **Multi-hop Graph Exploration**: Find not just matching nodes, but relationships between them
3. **Layer-based Management**: Each query creates a toggleable layer for independent visualization
4. **Dual Interface**: Support queries from both CLI and web UI
5. **No API Dependency**: Maintain current static file architecture (no mandatory API server)

## Non-Goals

- Real-time collaborative querying
- Complex query language (keep it natural language only)
- Automatic query result caching/indexing
- Vector similarity search from web UI (CLI only)

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────┐
│ Copilot CLI                                             │
│  - Natural language query input                         │
│  - HybridQuery engine (vector + graph)                  │
│  - Multi-hop graph traversal                            │
│  - Layer file generation                                │
└─────────────────────────────────────────────────────────┘
                        ↓ JSON files
┌─────────────────────────────────────────────────────────┐
│ File System (apps/web/public/query-layers/)             │
│  ├── layers-index.json         (metadata)               │
│  ├── layer-{timestamp}.json    (query results)          │
│  └── ...                                                │
└─────────────────────────────────────────────────────────┘
                        ↑ HTTP fetch
┌─────────────────────────────────────────────────────────┐
│ Web UI (Next.js)                                        │
│  - Layer panel (toggle layers on/off)                   │
│  - Query input (optional client-side search)            │
│  - Graph visualization (D3.js with layer overlay)       │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

**CLI Query Flow:**
1. User executes: `opencrab query-viz "ELERA와 acli의 관계는?"`
2. HybridQuery performs vector similarity search (ChromaDB/BM25)
3. Top-k results used as seed nodes for graph traversal
4. Multi-hop BFS/DFS explores relationships (up to 3 hops)
5. Results saved to `public/query-layers/layer-{timestamp}.json`
6. `layers-index.json` updated with new layer metadata

**Web UI Display Flow:**
1. Page load → fetch `layers-index.json`
2. User toggles layer → fetch specific `layer-{id}.json`
3. Layer nodes/edges merged with main graph
4. Highlighted nodes rendered with special styling
5. User can toggle multiple layers simultaneously

**Web UI Query Flow (Optional):**
1. User enters query in web UI input box
2. Client-side filtering on existing nodes.json/edges.json
3. Simple BFS (max 2 hops) to find paths
4. Results displayed as temporary layer (not saved)
5. Optional "Save as Layer" button to persist

## Data Schema

### Layer File Format

**File:** `public/query-layers/layer-{timestamp}.json`

```json
{
  "id": "layer-20260521-164500",
  "query": "ELERA와 acli의 관계는?",
  "timestamp": "2026-05-21T16:45:00+09:00",
  "source": "cli",
  "nodes": [
    {
      "id": "concept_elera_platform",
      "space": "concept",
      "node_type": "platform",
      "properties": {
        "name": "ELERA POS",
        "description": "..."
      },
      "score": 0.95,
      "highlight": true,
      "hop_distance": 0
    },
    {
      "id": "resource_acli_jira_workitem",
      "space": "resource",
      "node_type": "tool",
      "properties": {},
      "score": 0.87,
      "highlight": true,
      "hop_distance": 0
    },
    {
      "id": "intermediate_node_123",
      "space": "evidence",
      "node_type": "documentation",
      "properties": {},
      "score": 0.65,
      "highlight": false,
      "hop_distance": 1
    }
  ],
  "edges": [
    {
      "from_id": "concept_elera_platform",
      "to_id": "intermediate_node_123",
      "relation": "documented_by",
      "from_space": "concept",
      "to_space": "evidence",
      "path_rank": 1
    },
    {
      "from_id": "intermediate_node_123",
      "to_id": "resource_acli_jira_workitem",
      "relation": "mentions",
      "from_space": "evidence",
      "to_space": "resource",
      "path_rank": 2
    }
  ],
  "metadata": {
    "total_nodes": 15,
    "total_edges": 23,
    "max_hops": 3,
    "query_time_ms": 234,
    "vector_search_hits": 5,
    "graph_expansion_nodes": 10
  }
}
```

**Field Descriptions:**
- `id`: Unique layer identifier (layer-{timestamp})
- `query`: Original user query string
- `timestamp`: ISO 8601 timestamp with timezone
- `source`: "cli" or "web"
- `nodes[].score`: Relevance score (0-1, from vector search or decay by hop distance)
- `nodes[].highlight`: True for initial search results, false for path nodes
- `nodes[].hop_distance`: Graph distance from initial results (0 = seed node)
- `edges[].path_rank`: Importance rank in connecting query results (lower = more important)

### Layers Index Format

**File:** `public/query-layers/layers-index.json`

```json
{
  "layers": [
    {
      "id": "layer-20260521-164500",
      "query": "ELERA와 acli의 관계는?",
      "timestamp": "2026-05-21T16:45:00+09:00",
      "source": "cli",
      "node_count": 15,
      "edge_count": 23,
      "enabled": true
    },
    {
      "id": "layer-20260521-165200",
      "query": "GitLab CI 파이프라인 구조",
      "timestamp": "2026-05-21T16:52:00+09:00",
      "source": "web",
      "node_count": 8,
      "edge_count": 12,
      "enabled": false
    }
  ],
  "version": "1.0",
  "last_updated": "2026-05-21T16:52:00+09:00"
}
```

## Component Details

### 1. CLI Implementation

**File:** `opencrab/cli.py` (extend existing)

**New Command:**
```python
@cli.command()
@click.argument("question")
@click.option("--max-hops", default=3, help="Maximum graph traversal depth")
@click.option("--limit", default=20, help="Maximum nodes to return")
@click.option("--output-dir", default=None, help="Custom output directory")
def query_viz(question: str, max_hops: int, limit: int, output_dir: str):
    """
    Execute natural language query and generate visualization layer.
    
    Example:
        opencrab query-viz "ELERA와 acli의 관계는?" --max-hops 3
    """
    # Implementation details below
```

**Implementation Steps:**

1. **Vector Search (Phase 1)**:
   - Use existing `HybridQuery` from `opencrab/ontology/query.py`
   - Perform vector similarity search via ChromaDB or BM25
   - Get top-k nodes with relevance scores

2. **Graph Expansion (Phase 2)**:
   - Extract node IDs from search results
   - Perform multi-hop BFS/DFS from seed nodes
   - Apply edge weights and decay scores by hop distance
   - Stop at max_hops or when no new nodes found

3. **Path Ranking**:
   - Score edges by: vector similarity × edge weight × hop decay
   - Edge weight from existing `_EDGE_WEIGHTS` in query.py
   - Hop decay: score × 0.7^hop_distance

4. **Result Assembly**:
   - Merge seed nodes + expansion nodes
   - Mark seed nodes with `highlight: true`
   - Include all connecting edges with path_rank

5. **File Output**:
   - Generate layer JSON with timestamp ID
   - Save to `{output_dir}/query-layers/layer-{timestamp}.json`
   - Default output_dir: `apps/web/public/`
   - Update `layers-index.json` atomically

**Helper Functions:**

```python
def save_layer(layer_data: dict, output_dir: str) -> str:
    """Save layer to file and update index."""
    
def update_layers_index(layer_metadata: dict, output_dir: str):
    """Atomically update layers-index.json."""
    
def explore_subgraph(
    graph_store, 
    seed_nodes: list[str], 
    max_hops: int
) -> tuple[list[dict], list[dict]]:
    """Multi-hop graph traversal from seed nodes."""
```

### 2. Web UI Components

#### 2.1 Layer Panel Component

**File:** `apps/web/components/LayerPanel.tsx` (new)

**Features:**
- Display list of available layers from `layers-index.json`
- Checkbox to enable/disable each layer
- Show metadata: query text, timestamp, node count
- Delete button to remove layer (updates index file via API or manual)
- Refresh button to reload layers-index.json
- Keyboard shortcuts: `l` to toggle panel, arrow keys to navigate

**Layout:**
```
┌─────────────────────────────┐
│ Query Layers          [↻]   │ ← Refresh
├─────────────────────────────┤
│ ☑ ELERA와 acli 관계         │
│   2026-05-21 16:45          │
│   15 nodes, 23 edges   [×]  │ ← Delete
├─────────────────────────────┤
│ ☐ GitLab CI 구조            │
│   2026-05-21 16:52          │
│   8 nodes, 12 edges    [×]  │
└─────────────────────────────┘
```

**State Management:**
- React state for enabled layers (boolean map)
- Fetch layers-index.json on mount and refresh
- Emit events when layers toggled (parent re-renders graph)

#### 2.2 Query Input Component

**File:** `apps/web/components/QueryInput.tsx` (new)

**Features:**
- Text input for natural language query
- "Search" button to execute client-side query
- Loading indicator during search
- Results displayed as temporary layer
- "Save as Layer" button to persist (writes to filesystem via API or manual)

**Client-Side Search Algorithm:**
1. Tokenize query (simple split on spaces)
2. Filter nodes where properties contain any token (case-insensitive)
3. Perform BFS up to 2 hops from matching nodes
4. Score by: token match count × hop decay (0.7^hop)
5. Return top 50 nodes with connecting edges

**Limitations:**
- No vector similarity (no embeddings in browser)
- Simple keyword matching only
- Limited to 2 hops (performance)
- Results not as accurate as CLI HybridQuery

**Layout:**
```
┌───────────────────────────────────────────┐
│ Ask a question about the graph...         │
│ [ELERA와 acli의 관계는?          ] [Search]│
└───────────────────────────────────────────┘
```

#### 2.3 Graph Visualization Updates

**File:** `apps/web/components/Graph.tsx` (modify existing)

**Changes:**

1. **Layer Data Loading**:
   - Accept `enabledLayers: string[]` prop
   - Fetch each enabled layer's JSON file
   - Merge layer nodes/edges with base graph data

2. **Visual Styling**:
   - Highlighted nodes (highlight: true):
     - Larger radius (×1.5)
     - Thicker border (3px)
     - Pulsing animation
   - Layer edges:
     - Dashed stroke
     - Different colors per layer (max 5 colors, cycle)
   - Layer color legend (top-right corner)

3. **Tooltips**:
   - Show layer info on node hover
   - Display relevance score and hop distance
   - List which layers include this node

4. **Performance**:
   - Limit total visible nodes to 1000 (merge + filter by score)
   - Use canvas rendering if node count > 500
   - Debounce layer toggle events (300ms)

**Color Scheme (Layers):**
- Layer 1: `#FF6B6B` (red)
- Layer 2: `#4ECDC4` (teal)
- Layer 3: `#FFE66D` (yellow)
- Layer 4: `#A8DADC` (blue)
- Layer 5: `#F1A7FE` (purple)

#### 2.4 API Client Updates

**File:** `apps/web/lib/api.ts` (extend existing)

**New Functions:**

```typescript
export async function getQueryLayers(): Promise<LayerIndex> {
  const res = await fetch('/query-layers/layers-index.json', {
    cache: 'no-store'
  })
  if (!res.ok) return { layers: [], version: '1.0' }
  return res.json()
}

export async function getLayerData(layerId: string): Promise<LayerData | null> {
  const res = await fetch(`/query-layers/${layerId}.json`, {
    cache: 'no-store'
  })
  if (!res.ok) return null
  return res.json()
}

export async function deleteLayer(layerId: string): Promise<boolean> {
  // Client-side only: Cannot delete files from browser
  // User must manually delete or use CLI command
  console.warn('Layer deletion requires CLI or API server')
  return false
}
```

**Types:**

```typescript
export interface LayerIndex {
  layers: LayerMetadata[]
  version: string
  last_updated?: string
}

export interface LayerMetadata {
  id: string
  query: string
  timestamp: string
  source: 'cli' | 'web'
  node_count: number
  edge_count: number
  enabled: boolean
}

export interface LayerData {
  id: string
  query: string
  timestamp: string
  source: string
  nodes: LayerNode[]
  edges: LayerEdge[]
  metadata: {
    total_nodes: number
    total_edges: number
    max_hops: number
    query_time_ms: number
  }
}

export interface LayerNode extends OcNode {
  score: number
  highlight: boolean
  hop_distance: number
}

export interface LayerEdge extends OcEdge {
  path_rank: number
}
```

### 3. Graph Traversal Algorithm

**Multi-hop BFS Implementation:**

```python
def explore_subgraph(
    graph_store,
    seed_nodes: list[str],
    max_hops: int,
    max_nodes: int = 500
) -> tuple[list[dict], list[dict]]:
    """
    Breadth-first traversal from seed nodes.
    
    Returns:
        (nodes, edges) where nodes include score and hop_distance
    """
    visited = set()
    nodes_by_id = {}
    edges = []
    queue = [(nid, 0) for nid in seed_nodes]  # (node_id, hop)
    
    while queue and len(nodes_by_id) < max_nodes:
        node_id, hop = queue.pop(0)
        
        if node_id in visited or hop > max_hops:
            continue
            
        visited.add(node_id)
        
        # Fetch node data
        node = graph_store.get_node(node_id)
        nodes_by_id[node_id] = {
            **node,
            'hop_distance': hop,
            'highlight': hop == 0
        }
        
        # Get neighbors
        neighbors = graph_store.get_neighbors(node_id)
        for neighbor_id, edge_data in neighbors:
            edges.append({
                'from_id': node_id,
                'to_id': neighbor_id,
                'relation': edge_data['relation'],
                'from_space': node['space'],
                'to_space': edge_data['to_space'],
                'path_rank': hop + 1
            })
            
            if neighbor_id not in visited:
                queue.append((neighbor_id, hop + 1))
    
    return list(nodes_by_id.values()), edges
```

**Score Decay:**
```python
def apply_score_decay(nodes: list[dict], initial_scores: dict[str, float]):
    """Apply hop-based decay to relevance scores."""
    for node in nodes:
        base_score = initial_scores.get(node['id'], 0.5)
        hop = node['hop_distance']
        node['score'] = base_score * (0.7 ** hop)
```

## Error Handling

### File System Errors

1. **Missing Directory**:
   - Create `public/query-layers/` if not exists
   - Set proper permissions (read/write)

2. **JSON Parse Errors**:
   - Skip corrupted layer files
   - Log warning to console
   - Continue loading other layers

3. **Write Permission Denied**:
   - CLI: Show clear error message with file path
   - Suggest running with appropriate permissions

### Query Errors

1. **No Results Found**:
   - Create empty layer with 0 nodes
   - Show message: "No results found for query: {query}"

2. **Graph Traversal Timeout**:
   - Set 30-second timeout
   - Return partial results found so far
   - Log warning in metadata

3. **Database Connection Failure**:
   - CLI: Show error and exit with code 1
   - Web UI: Show error toast, disable query input

### Web UI Errors

1. **Layer File Not Found (404)**:
   - Remove from layers-index
   - Show notification: "Layer file missing, removed from list"

2. **Invalid Layer Data**:
   - Skip layer rendering
   - Show warning in layer panel

3. **Too Many Active Layers**:
   - Limit to 5 active layers
   - Show warning: "Maximum 5 layers, disable others first"

## Constraints & Limitations

### Performance Limits

1. **Layer Size**:
   - Max 500 nodes per layer (CLI enforced)
   - Max 1000 edges per layer
   - Layers exceeding limits truncated with warning

2. **Active Layers**:
   - Max 5 layers enabled simultaneously (Web UI enforced)
   - Total visible nodes capped at 1000

3. **Query Complexity**:
   - CLI: Max 3 hops (configurable via --max-hops)
   - Web UI: Max 2 hops (hardcoded for performance)

### Storage Limits

1. **Layer Count**:
   - Max 100 layer files (oldest auto-deleted)
   - Each layer file ≈ 100KB - 1MB

2. **Disk Space**:
   - Total layers folder < 100MB
   - CLI warns if approaching limit

### Synchronization

1. **File-Based Latency**:
   - Web UI not real-time (file system polling)
   - Auto-refresh every 30 seconds (configurable)
   - Manual refresh button always available

2. **Concurrent Access**:
   - No file locking (last write wins)
   - Race conditions possible if multiple users
   - Document as single-user limitation

## Testing Strategy

### Unit Tests

1. **CLI (`tests/test_query_viz.py`)**:
   - Test vector search integration
   - Test multi-hop graph traversal
   - Test layer file generation
   - Test index update logic

2. **Web UI (`apps/web/__tests__/LayerPanel.test.tsx`)**:
   - Test layer loading
   - Test layer toggling
   - Test layer deletion (UI only)

### Integration Tests

1. **End-to-End Flow**:
   - CLI query → file creation → web UI display
   - Multiple layers → visual rendering
   - Layer deletion → index update

2. **Performance Tests**:
   - Large query results (500 nodes)
   - Multiple active layers (5 layers)
   - Graph rendering speed

### Manual Testing Checklist

- [ ] CLI query with Korean text
- [ ] CLI query with English text
- [ ] Web UI client-side search
- [ ] Toggle 5 layers simultaneously
- [ ] Delete layer from web UI
- [ ] Refresh layers list
- [ ] Graph highlights correct nodes
- [ ] Tooltips show layer info
- [ ] Layer colors distinct

## Migration Path

### Phase 1: MVP (Static Files)
- Current design (this document)
- File-based layer storage
- No API server required

### Phase 2: API Enhancement (Future)
- Add REST API endpoints:
  - `POST /api/query-layers` (create)
  - `GET /api/query-layers` (list)
  - `GET /api/query-layers/{id}` (get)
  - `DELETE /api/query-layers/{id}` (delete)
- Real-time layer sync via WebSocket
- Collaborative features (share layers)

### Phase 3: Advanced Features (Future)
- Layer merging (combine multiple queries)
- Layer filtering (by space, node type)
- Export to PNG/SVG
- Scheduled queries (daily snapshots)

## Open Questions

None - all questions resolved during brainstorming.

## Success Criteria

1. ✅ Users can query in natural language from CLI
2. ✅ Results visualized as graph layers in web UI
3. ✅ Multiple layers can be toggled independently
4. ✅ Multi-hop relationships explored correctly
5. ✅ Performance acceptable (< 5s query, < 1s render)
6. ✅ No API server dependency (static files only)

## References

- Existing HybridQuery: `opencrab/ontology/query.py`
- Graph stores: `opencrab/stores/neo4j_store.py`, SQLite
- Web UI: `apps/web/components/Graph.tsx`
- CLI: `opencrab/cli.py`
