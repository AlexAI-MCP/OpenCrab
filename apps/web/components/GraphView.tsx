'use client'

import { useCallback, useEffect, useRef } from 'react'
import type { OcEdge, OcNode } from '../lib/api'

const SPACE_COLORS: Record<string, string> = {
  subject: '#f8c537',
  resource: '#83a598',
  concept: '#b8bb26',
  evidence: '#bdae93',
  outcome: '#fb4934',
  lever: '#d3869b',
  policy: '#fabd2f',
  claim: '#fe8019',
  community: '#8ec07c',
}

const THEME_COLORS = {
  landscape: '#5ea85b',
  ai: '#e38b2c',
  alex: '#d97ab5',
  default: '#7c6f64',
} as const

const THEME_LABELS = {
  landscape: 'Landscape',
  ai: 'AI',
  alex: 'Alex',
  default: 'Default',
} as const

const LANDSCAPE_TERMS = [
  'landscape',
  'garden',
  'park',
  'greenery',
  'greenspace',
  'green space',
  'tree',
  'shrub',
  'plant',
  'biophilic',
  'ecology',
  'horticulture',
  'prugio',
  'zelkova',
  'ginkgo',
  'forsythia',
  'asla',
  'landezine',
  '조경',
]

const AI_TERMS = [
  'ai',
  'artificial intelligence',
  'agent',
  'llm',
  'rag',
  'model',
  'automation',
  'digital twin',
  'generative',
  'prediction',
  'forecasting',
  'buildots',
  'procore',
]

const ALEX_TERMS = [
  'alex',
  'alexai',
  'opencrab',
  'crabharness',
  'langent',
  'designontol',
  'codex',
]

type ThemeKey = keyof typeof THEME_COLORS

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function propertyText(properties: Record<string, unknown>) {
  const keys = ['name', 'title', 'summary', 'text', 'domain', 'source', 'oc_type', 'oc_space', 'label']
  return keys
    .map((key) => properties[key])
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .join(' ')
}

function containsTerm(text: string, term: string) {
  if (term.includes(' ')) return text.includes(term)
  return new RegExp(`\\b${escapeRegex(term)}\\b`, 'i').test(text)
}

function matchesAny(text: string, terms: string[]) {
  return terms.some((term) => containsTerm(text, term))
}

function nodeTheme(node: OcNode): ThemeKey {
  const explicitTheme = node.properties?.viz_theme
  if (typeof explicitTheme === 'string' && explicitTheme in THEME_COLORS) {
    return explicitTheme as ThemeKey
  }

  const haystack = [
    node.id,
    node.space,
    node.node_type,
    propertyText(node.properties),
  ].join(' ').toLowerCase()

  if (matchesAny(haystack, ALEX_TERMS)) return 'alex'
  if (matchesAny(haystack, LANDSCAPE_TERMS)) return 'landscape'
  if (matchesAny(haystack, AI_TERMS)) return 'ai'
  return 'default'
}

function nodeColor(node: OcNode) {
  const explicitColor = node.properties?.viz_color
  if (typeof explicitColor === 'string' && explicitColor.length > 0) {
    return explicitColor
  }

  const theme = nodeTheme(node)
  if (theme !== 'default') return THEME_COLORS[theme]
  return SPACE_COLORS[node.space] ?? THEME_COLORS.default
}

function themeLabel(node: OcNode) {
  return THEME_LABELS[nodeTheme(node)]
}

function nodeRadius(degree: number) {
  return Math.min(20, Math.max(5, 5 + Math.sqrt(degree) * 2.5))
}

interface Props {
  nodes: OcNode[]
  edges: OcEdge[]
  selectedId: string | null
  searchTerm: string
  nodeSize: number
  linkStrength: number
  centerForce: number
  repelForce: number
  onNodeClick: (node: OcNode) => void
}

export default function GraphView({
  nodes,
  edges,
  selectedId,
  searchTerm,
  nodeSize,
  linkStrength,
  centerForce,
  repelForce,
  onNodeClick,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const simRef = useRef<unknown>(null)

  const draw = useCallback(async () => {
    if (!svgRef.current) return

    const d3 = await import('d3')
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const rect = svgRef.current.getBoundingClientRect()
    const width = rect.width || 800
    const height = rect.height || 600

    const g = svg.append('g')
    svg.call(
      d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.1, 8])
        .on('zoom', (event) => g.attr('transform', event.transform)),
    )

    if (nodes.length === 0) return

    const idMap = new Map(nodes.map((node, index) => [node.id, index]))

    type SimNode = OcNode & d3.SimulationNodeDatum
    type SimLink = { source: SimNode; target: SimNode; relation: string }

    const simNodes: SimNode[] = nodes.map((node) => ({ ...node }))
    const simLinks: SimLink[] = edges
      .filter((edge) => idMap.has(edge.from_id) && idMap.has(edge.to_id))
      .map((edge) => ({
        source: simNodes[idMap.get(edge.from_id)!],
        target: simNodes[idMap.get(edge.to_id)!],
        relation: edge.relation,
      }))

    if (simRef.current) {
      ;(simRef.current as d3.Simulation<SimNode, SimLink>).stop()
    }

    const sim = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((node) => node.id)
          .distance(80)
          .strength(linkStrength),
      )
      .force('charge', d3.forceManyBody<SimNode>().strength(-repelForce))
      .force('center', d3.forceCenter<SimNode>(width / 2, height / 2).strength(centerForce))
      .force('collision', d3.forceCollide<SimNode>((node) => nodeRadius(node.degree) * nodeSize + 4))

    simRef.current = sim

    const link = g
      .append('g')
      .selectAll('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', '#3a3a3a')
      .attr('stroke-width', linkStrength * 2)
      .attr('opacity', 0.6)

    const node = g
      .append('g')
      .selectAll<SVGCircleElement, SimNode>('circle')
      .data(simNodes)
      .join('circle')
      .attr('r', (d) => nodeRadius(d.degree) * nodeSize)
      .attr('fill', (d) => nodeColor(d))
      .attr('stroke', (d) => (d.id === selectedId ? '#fff' : 'transparent'))
      .attr('stroke-width', 2)
      .attr('opacity', (d) => {
        if (!searchTerm) return 1
        const name = typeof d.properties?.name === 'string' ? d.properties.name : ''
        return d.id.toLowerCase().includes(searchTerm.toLowerCase()) || name.toLowerCase().includes(searchTerm.toLowerCase())
          ? 1
          : 0.15
      })
      .style('cursor', 'pointer')
      .call(
        d3
          .drag<SVGCircleElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) sim.alphaTarget(0)
            d.fx = null
            d.fy = null
          }),
      )
      .on('click', (_, d) => onNodeClick(d))
      .on('mouseover', (event, d) => {
        const tip = tooltipRef.current
        if (!tip) return
        tip.style.display = 'block'
        tip.style.left = `${event.clientX + 14}px`
        tip.style.top = `${event.clientY - 10}px`
        tip.innerHTML = [
          `<span style="color:${nodeColor(d)};font-weight:600">${themeLabel(d)}</span>`,
          `<span style="color:#faf2d6">${d.id}</span>`,
          `<span style="color:#bdae93;font-size:11px">${d.node_type} | ${d.degree} links | ${d.space}</span>`,
        ].join('<br/>')
      })
      .on('mousemove', (event) => {
        const tip = tooltipRef.current
        if (!tip) return
        tip.style.left = `${event.clientX + 14}px`
        tip.style.top = `${event.clientY - 10}px`
      })
      .on('mouseout', () => {
        if (tooltipRef.current) tooltipRef.current.style.display = 'none'
      })

    const label = g
      .append('g')
      .selectAll('text')
      .data(simNodes)
      .join('text')
      .text((d) => (d.id.length > 18 ? `${d.id.slice(0, 16)}..` : d.id))
      .attr('font-size', 9)
      .attr('fill', '#bdae93')
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => nodeRadius(d.degree) * nodeSize + 12)
      .style('pointer-events', 'none')
      .attr('opacity', (d) => {
        if (!searchTerm) return 0.7
        return d.id.toLowerCase().includes(searchTerm.toLowerCase()) ? 1 : 0.1
      })

    sim.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as SimNode).x!)
        .attr('y1', (d) => (d.source as SimNode).y!)
        .attr('x2', (d) => (d.target as SimNode).x!)
        .attr('y2', (d) => (d.target as SimNode).y!)

      node.attr('cx', (d) => d.x!).attr('cy', (d) => d.y!)
      label.attr('x', (d) => d.x!).attr('y', (d) => d.y!)
    })
  }, [nodes, edges, selectedId, searchTerm, nodeSize, linkStrength, centerForce, repelForce, onNodeClick])

  useEffect(() => {
    draw()
  }, [draw])

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', background: '#111' }}>
      <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
      {nodes.length === 0 && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#7c6f64',
            gap: 12,
          }}
        >
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#3a3a3a" strokeWidth="1.5">
            <circle cx="12" cy="12" r="3" />
            <circle cx="4" cy="6" r="2" />
            <circle cx="20" cy="6" r="2" />
            <circle cx="4" cy="18" r="2" />
            <circle cx="20" cy="18" r="2" />
            <line x1="12" y1="9" x2="4" y2="7" />
            <line x1="12" y1="9" x2="20" y2="7" />
            <line x1="12" y1="15" x2="4" y2="17" />
            <line x1="12" y1="15" x2="20" y2="17" />
          </svg>
          <div style={{ fontSize: 14 }}>Graph is empty</div>
          <div style={{ fontSize: 12, color: '#555' }}>Ingest data from the left panel to populate the graph.</div>
        </div>
      )}
      <div ref={tooltipRef} className="graph-tooltip" style={{ display: 'none' }} />
    </div>
  )
}
