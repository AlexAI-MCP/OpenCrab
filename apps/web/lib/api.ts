const BASE = process.env.NEXT_PUBLIC_API_URL || 'https://opencrabback.up.railway.app'

function headers(apiKey: string) {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${apiKey}`,
  }
}

export interface OcNode {
  id: string
  space: string
  node_type: string
  properties: Record<string, unknown>
  degree: number
}

export interface OcEdge {
  from_id: string
  to_id: string
  relation: string
  from_space: string
  to_space: string
}

export interface QueryResult {
  node_id: string | null
  score: number
  text: string | null
  metadata: Record<string, unknown>
}

export async function getStatus(): Promise<boolean> {
  try {
    const r = await fetch(`${BASE}/api/status`, { cache: 'no-store' })
    return r.ok
  } catch { return false }
}

export async function getNodes(apiKey: string): Promise<OcNode[]> {
  try {
    const r = await fetch(`${BASE}/api/nodes`, { headers: headers(apiKey), cache: 'no-store' })
    if (!r.ok) return []
    const d = await r.json()
    return d.nodes ?? []
  } catch { return [] }
}

export async function getEdges(apiKey: string): Promise<OcEdge[]> {
  try {
    const r = await fetch(`${BASE}/api/edges`, { headers: headers(apiKey), cache: 'no-store' })
    if (!r.ok) return []
    const d = await r.json()
    return d.edges ?? []
  } catch { return [] }
}

export async function query(apiKey: string, question: string, spaces?: string[], limit = 10) {
  const r = await fetch(`${BASE}/api/query`, {
    method: 'POST',
    headers: headers(apiKey),
    body: JSON.stringify({ question, spaces, limit }),
  })
  if (!r.ok) throw new Error('Query failed')
  return r.json()
}

export async function ingest(
  apiKey: string,
  text: string,
  sourceId?: string,
  metadata?: Record<string, unknown>
) {
  const r = await fetch(`${BASE}/api/ingest`, {
    method: 'POST',
    headers: headers(apiKey),
    body: JSON.stringify({ text, source_id: sourceId, metadata }),
  })
  if (!r.ok) throw new Error('Ingest failed')
  return r.json()
}
