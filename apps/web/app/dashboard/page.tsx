'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import dynamic from 'next/dynamic'
import FileExplorer from '../../components/FileExplorer'
import RightPanel from '../../components/RightPanel'
import LayerPanel from '../../components/LayerPanel'
import QueryInput from '../../components/QueryInput'
import type { OcNode, OcEdge, LayerMetadata, LayerData, LayerNode, LayerEdge } from '../../lib/api'
import { getNodes, getEdges, getStatus, getQueryLayers, getLayerData } from '../../lib/api'
import { searchLocalSubgraph } from '../../lib/queryLayerSearch'

const GraphView = dynamic(() => import('../../components/GraphView'), { ssr: false })

interface GraphControls {
  nodeSize: number
  linkStrength: number
  centerForce: number
  repelForce: number
  searchTerm: string
  hiddenSpaces: string[]
}

export default function DashboardPage() {
  const [apiKey, setApiKey] = useState('')
  const [nodes, setNodes] = useState<OcNode[]>([])
  const [edges, setEdges] = useState<OcEdge[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const [controls, setControls] = useState<GraphControls>({
    nodeSize: 1,
    linkStrength: 0.3,
    centerForce: 0.1,
    repelForce: 200,
    searchTerm: '',
    hiddenSpaces: [],
  })
  const [showIngest, setShowIngest] = useState(false)
  const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  // Query layer state
  const [layers, setLayers] = useState<LayerMetadata[]>([])
  const [enabledLayerIds, setEnabledLayerIds] = useState<string[]>([])
  const [layerDataMap, setLayerDataMap] = useState<Map<string, LayerData>>(new Map())
  const [queryLayerNodes, setQueryLayerNodes] = useState<OcNode[]>([])
  const [queryLayerEdges, setQueryLayerEdges] = useState<OcEdge[]>([])

  // Load API key from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('oc_api_key') || ''
    setApiKey(saved)
  }, [])

  function handleApiKeyChange(key: string) {
    setApiKey(key)
    localStorage.setItem('oc_api_key', key)
  }

  const fetchData = useCallback(async () => {
    const ok = await getStatus()
    setConnected(ok.ok)
    const [n, e] = await Promise.all([getNodes(apiKey), getEdges(apiKey)])
    setNodes(n.filter(node => !controls.hiddenSpaces.includes(node.space)))
    setEdges(e)
  }, [apiKey, controls.hiddenSpaces])

  const fetchLayers = useCallback(async () => {
    const index = await getQueryLayers()
    setLayers(index.layers)
  }, [])

  useEffect(() => {
    fetchData()
    fetchLayers()
    refreshTimer.current = setInterval(fetchData, 30000)
    return () => { if (refreshTimer.current) clearInterval(refreshTimer.current) }
  }, [fetchData, fetchLayers])

  const selectedNode = nodes.find(n => n.id === selectedId) ?? null

  function handleNodeClick(node: OcNode) {
    setSelectedId(node.id)
  }

  function handleControlChange(partial: Partial<GraphControls>) {
    setControls(p => ({ ...p, ...partial }))
  }

  async function handleLayerToggle(layerId: string) {
    if (enabledLayerIds.includes(layerId)) {
      // Disable layer
      setEnabledLayerIds(ids => ids.filter(id => id !== layerId))
      setLayerDataMap(map => {
        const newMap = new Map(map)
        newMap.delete(layerId)
        return newMap
      })
    } else {
      // Enable layer - fetch data
      setEnabledLayerIds(ids => [...ids, layerId])
      const data = await getLayerData(layerId)
      if (data) {
        setLayerDataMap(map => new Map(map).set(layerId, data))
      }
    }
  }

  function handleQueryRun(query: string) {
    // Collect all nodes and edges from enabled layers
    const allLayerNodes: LayerNode[] = []
    const allLayerEdges: LayerEdge[] = []
    
    for (const layerId of enabledLayerIds) {
      const data = layerDataMap.get(layerId)
      if (data) {
        allLayerNodes.push(...data.nodes)
        allLayerEdges.push(...data.edges)
      }
    }

    // Run local subgraph search
    const result = searchLocalSubgraph(allLayerNodes, allLayerEdges, query, 2)

    // Convert LayerNode to OcNode and LayerEdge to OcEdge for rendering
    // Collect all node IDs referenced by result edges plus seeds
    const overlayNodeIds = new Set<string>(result.seeds.map(n => n.id))
    for (const edge of result.edges) {
      overlayNodeIds.add(edge.from)
      overlayNodeIds.add(edge.to)
    }
    // Map allLayerNodes by id for fast lookup
    const nodeMap = new Map(allLayerNodes.map(n => [n.id, n]))
    const ocNodes: OcNode[] = Array.from(overlayNodeIds)
      .map(id => nodeMap.get(id))
      .filter((ln): ln is LayerNode => Boolean(ln))
      .map(ln => ({
        id: ln.id,
        space: 'query_layer',
        node_type: 'layer_node',
        properties: { name: ln.label, ...ln.metadata },
        degree: 0,
      }))

    const ocEdges: OcEdge[] = result.edges.map(le => ({
      from_id: le.from,
      to_id: le.to,
      relation: le.relation || 'related',
      from_space: 'query_layer',
      to_space: 'query_layer',
    }))

    setQueryLayerNodes(ocNodes)
    setQueryLayerEdges(ocEdges)
  }

  return (
    <div style={{
      display: 'flex', height: '100vh', width: '100vw',
      background: '#111', overflow: 'hidden',
    }}>
      {/* Left — File Explorer */}
      <FileExplorer
        nodes={nodes}
        selectedId={selectedId}
        onNodeSelect={id => setSelectedId(id)}
        onIngestClick={() => setShowIngest(true)}
        connected={connected}
        apiKey={apiKey}
        onApiKeyChange={handleApiKeyChange}
      />

      {/* Center — Graph */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {/* Top bar */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10,
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '8px 14px',
          background: 'rgba(17,17,17,0.9)',
          borderBottom: '1px solid rgba(248,197,55,0.12)',
        }}>
          <span style={{ fontSize: 12, color: '#555' }}>그래프 뷰</span>
          <span style={{ fontSize: 11, color: '#3a3a3a' }}>|</span>
          <span style={{ fontSize: 11, color: '#7c6f64' }}>
            {nodes.length} nodes · {edges.length} edges
            {queryLayerNodes.length > 0 && ` · ${queryLayerNodes.length} layer nodes`}
          </span>
          <div style={{ flex: 1 }} />
          <input
            className="input-dark"
            value={controls.searchTerm}
            onChange={e => handleControlChange({ searchTerm: e.target.value })}
            placeholder="검색…"
            style={{ width: 180, fontSize: 11, padding: '4px 10px' }}
          />
          <button className="btn-gold" style={{ fontSize: 11, padding: '4px 10px' }} onClick={fetchData}>
            ↺ 새로고침
          </button>
        </div>

        {/* Graph canvas */}
        <div style={{ position: 'absolute', inset: 0, paddingTop: 42 }}>
          <GraphView
            nodes={nodes}
            edges={edges}
            selectedId={selectedId}
            searchTerm={controls.searchTerm}
            nodeSize={controls.nodeSize}
            linkStrength={controls.linkStrength}
            centerForce={controls.centerForce}
            repelForce={controls.repelForce}
            onNodeClick={handleNodeClick}
            layerNodes={queryLayerNodes}
            layerEdges={queryLayerEdges}
          />
        </div>

        {/* Legend */}
        <div style={{
          position: 'absolute', top: 50, right: 10, zIndex: 10,
          background: 'rgba(17,17,17,0.85)',
          border: '1px solid rgba(248,197,55,0.15)',
          borderRadius: 6, padding: '8px 12px',
        }}>
          {[
            ['Landscape', '#5ea85b'],
            ['AI', '#e38b2c'],
            ['Alex', '#d97ab5'],
            ['Fallback', '#7c6f64'],
          ].map(([s, c]) => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: c }} />
              <span style={{ fontSize: 10, color: '#bdae93' }}>{s}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Right — Controls & Detail */}
      <div style={{ width: 340, background: '#0f0f0f', borderLeft: '1px solid rgba(248,197,55,0.12)', overflowY: 'auto' }}>
        <div style={{ padding: 14 }}>
          <LayerPanel
            layers={layers}
            enabledLayerIds={enabledLayerIds}
            onToggle={handleLayerToggle}
            onRefresh={fetchLayers}
          />
          <QueryInput onRun={handleQueryRun} />
        </div>
        <RightPanel
          selectedNode={selectedNode}
          controls={controls}
          onControlChange={handleControlChange}
          apiKey={apiKey}
          onRefresh={fetchData}
        />
      </div>

      {/* Ingest Modal */}
      {showIngest && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
          onClick={() => setShowIngest(false)}
        >
          <div
            style={{
              background: '#1a1a1a', border: '1px solid rgba(248,197,55,0.3)',
              borderRadius: 8, padding: 24, width: 480, maxWidth: '90vw',
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ color: '#f8c537', fontWeight: 700, marginBottom: 16 }}>데이터 인제스트</div>
            <p style={{ color: '#7c6f64', fontSize: 12, marginBottom: 16 }}>
              오른쪽 패널의 인제스트 탭을 사용하거나 여기서 빠르게 추가할 수 있어.
            </p>
            <button className="btn-gold" onClick={() => setShowIngest(false)}>닫기</button>
          </div>
        </div>
      )}
    </div>
  )
}
