import type { LayerNode, LayerEdge } from './api'

export interface SubgraphResult {
  seeds: LayerNode[]
  edges: LayerEdge[]
}

/**
 * Lightweight local subgraph search.
 * Finds nodes matching query string, then expands by maxHops.
 * Returns seeds and connected edges deterministically.
 */
export function searchLocalSubgraph(
  nodes: LayerNode[],
  edges: LayerEdge[],
  query: string,
  maxHops = 2
): SubgraphResult {
  const lowerQuery = query.toLowerCase().trim()
  
  // Find seed nodes matching query
  const seeds = nodes.filter(node => {
    const label = node.label?.toLowerCase() || ''
    const id = node.id?.toLowerCase() || ''
    return label.includes(lowerQuery) || id.includes(lowerQuery)
  })
  
  if (seeds.length === 0) {
    return { seeds: [], edges: [] }
  }
  
  // Collect reachable node IDs via BFS
  const seedIds = new Set(seeds.map(n => n.id))
  const reachable = new Set<string>(seedIds)
  
  let frontier = Array.from(seedIds)
  for (let hop = 0; hop < maxHops; hop++) {
    const nextFrontier: string[] = []
    for (const nodeId of frontier) {
      for (const edge of edges) {
        if (edge.from === nodeId && !reachable.has(edge.to)) {
          reachable.add(edge.to)
          nextFrontier.push(edge.to)
        }
        if (edge.to === nodeId && !reachable.has(edge.from)) {
          reachable.add(edge.from)
          nextFrontier.push(edge.from)
        }
      }
    }
    frontier = nextFrontier
    if (frontier.length === 0) break
  }
  
  // Filter edges connecting reachable nodes
  const connectedEdges = edges.filter(
    e => reachable.has(e.from) && reachable.has(e.to)
  )
  
  return { seeds, edges: connectedEdges }
}
