'use client'

import { useState } from 'react'
import type { OcNode } from '../lib/api'

const PARA_FOLDERS = [
  { key: '00_Inbox',     label: '00_Inbox',     icon: '📥' },
  { key: '01_Projects',  label: '01_Projects',  icon: '📁' },
  { key: '02_Areas',     label: '02_Areas',     icon: '📁' },
  { key: '03_Resources', label: '03_Resources', icon: '📁' },
  { key: '04_Outputs',   label: '04_Outputs',   icon: '📁' },
  { key: '05_System',    label: '05_System',    icon: '⚙️' },
  { key: 'Daily Notes',  label: 'Daily Notes',  icon: '📅' },
  { key: '99_Archive',   label: '99_Archive',   icon: '🗄️' },
]

const SPACE_DOT: Record<string, string> = {
  subject: '#f8c537', resource: '#83a598', concept: '#b8bb26',
  evidence: '#bdae93', outcome: '#fb4934', lever: '#d3869b',
  policy: '#fabd2f', claim: '#fe8019', community: '#8ec07c',
}

interface Props {
  nodes: OcNode[]
  selectedId: string | null
  onNodeSelect: (id: string) => void
  onIngestClick: () => void
  connected: boolean
  apiKey: string
  onApiKeyChange: (key: string) => void
}

export default function FileExplorer({
  nodes, selectedId, onNodeSelect, onIngestClick, connected, apiKey, onApiKeyChange,
}: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ '03_Resources': true })
  const [showKey, setShowKey] = useState(false)

  // Group nodes into folders by source_id prefix or space
  function nodesForFolder(folderKey: string): OcNode[] {
    return nodes.filter(n => {
      const src = (n.properties?.source_id as string) || (n.properties?.folder as string) || ''
      return src.includes(folderKey) || n.space === folderKey.toLowerCase().replace(/\d+_/, '')
    })
  }

  // All nodes not matching any folder → root level by space
  const spaceGroups: Record<string, OcNode[]> = {}
  nodes.forEach(n => {
    if (!spaceGroups[n.space]) spaceGroups[n.space] = []
    spaceGroups[n.space].push(n)
  })

  function toggle(key: string) {
    setExpanded(p => ({ ...p, [key]: !p[key] }))
  }

  return (
    <div style={{
      width: 260, minWidth: 260, background: '#1a1a1a',
      borderRight: '1px solid rgba(248,197,55,0.15)',
      display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{ padding: '12px 14px 8px', borderBottom: '1px solid rgba(248,197,55,0.15)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ color: '#f8c537', fontWeight: 700, fontSize: 13, letterSpacing: '0.05em' }}>
            OPENCRAB
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
              width: 7, height: 7, borderRadius: '50%',
              background: connected ? '#8ec07c' : '#fb4934',
              boxShadow: connected ? '0 0 6px #8ec07c' : 'none',
            }} />
            <span style={{ fontSize: 10, color: '#7c6f64' }}>{connected ? 'connected' : 'offline'}</span>
          </div>
        </div>
        {/* API Key */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 12, color: '#7c6f64' }}>🔑</span>
          <input
            type={showKey ? 'text' : 'password'}
            className="input-dark mono"
            value={apiKey}
            onChange={e => onApiKeyChange(e.target.value)}
            placeholder="API Key…"
            style={{ fontSize: 11, padding: '4px 8px' }}
          />
          <button
            onClick={() => setShowKey(p => !p)}
            style={{ background: 'none', border: 'none', color: '#7c6f64', cursor: 'pointer', fontSize: 12, padding: '0 2px' }}
          >
            {showKey ? '🙈' : '👁'}
          </button>
        </div>
      </div>

      {/* Ingest button */}
      <div style={{ padding: '8px 14px', borderBottom: '1px solid rgba(248,197,55,0.12)' }}>
        <button className="btn-gold" style={{ width: '100%', fontSize: 12 }} onClick={onIngestClick}>
          + 인제스트
        </button>
      </div>

      {/* File tree */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {/* PARA folders */}
        {PARA_FOLDERS.map(f => {
          const folderNodes = nodesForFolder(f.key)
          const isExpanded = expanded[f.key]
          return (
            <div key={f.key}>
              <div
                onClick={() => toggle(f.key)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '4px 14px', cursor: 'pointer',
                  color: '#bdae93', fontSize: 12,
                  userSelect: 'none',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = '#252525')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                <span style={{ fontSize: 10, color: '#555', width: 10 }}>
                  {isExpanded ? '▼' : '▶'}
                </span>
                <span style={{ fontSize: 13 }}>{f.icon}</span>
                <span style={{ flex: 1 }}>{f.label}</span>
                {folderNodes.length > 0 && (
                  <span className="badge" style={{ fontSize: 10 }}>{folderNodes.length}</span>
                )}
              </div>
              {isExpanded && (
                <div>
                  {folderNodes.length === 0 ? (
                    <div style={{ padding: '2px 14px 2px 36px', fontSize: 11, color: '#555' }}>비어있음</div>
                  ) : (
                    folderNodes.map(n => (
                      <div
                        key={n.id}
                        onClick={() => onNodeSelect(n.id)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 6,
                          padding: '3px 14px 3px 36px', cursor: 'pointer',
                          background: selectedId === n.id ? 'rgba(248,197,55,0.1)' : 'transparent',
                          fontSize: 11, color: selectedId === n.id ? '#f8c537' : '#bdae93',
                        }}
                        onMouseEnter={e => { if (selectedId !== n.id) e.currentTarget.style.background = '#252525' }}
                        onMouseLeave={e => { if (selectedId !== n.id) e.currentTarget.style.background = 'transparent' }}
                      >
                        <div style={{
                          width: 6, height: 6, borderRadius: '50%',
                          background: SPACE_DOT[n.space] ?? '#666', flexShrink: 0,
                        }} />
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {n.id}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )
        })}

        {/* Space groups for unmatched nodes */}
        <div style={{ margin: '8px 14px 4px', borderTop: '1px solid rgba(248,197,55,0.1)', paddingTop: 8 }}>
          <div style={{ fontSize: 10, color: '#555', letterSpacing: '0.08em', marginBottom: 4 }}>ALL SPACES</div>
        </div>
        {Object.entries(spaceGroups).map(([space, snodes]) => (
          <div key={space}>
            <div
              onClick={() => toggle(`space_${space}`)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '3px 14px', cursor: 'pointer',
                color: '#bdae93', fontSize: 11, userSelect: 'none',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = '#252525')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <div style={{
                width: 7, height: 7, borderRadius: '50%',
                background: SPACE_DOT[space] ?? '#666', flexShrink: 0,
              }} />
              <span style={{ flex: 1, color: SPACE_DOT[space] ?? '#bdae93' }}>{space}</span>
              <span className="badge" style={{ fontSize: 10 }}>{snodes.length}</span>
            </div>
            {expanded[`space_${space}`] && snodes.map(n => (
              <div
                key={n.id}
                onClick={() => onNodeSelect(n.id)}
                style={{
                  padding: '2px 14px 2px 32px', cursor: 'pointer', fontSize: 10,
                  color: selectedId === n.id ? '#f8c537' : '#7c6f64',
                  background: selectedId === n.id ? 'rgba(248,197,55,0.08)' : 'transparent',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}
              >
                {n.id}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
