'use client'

import type { LayerMetadata } from '../lib/api'

interface Props {
  layers: LayerMetadata[]
  enabledLayerIds: string[]
  onToggle: (layerId: string) => void
  onRefresh: () => void
}

export default function LayerPanel({ layers, enabledLayerIds, onToggle, onRefresh }: Props) {
  return (
    <div
      style={{
        background: '#1a1a1a',
        border: '1px solid rgba(248,197,55,0.15)',
        borderRadius: 6,
        padding: 12,
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <div style={{ color: '#f8c537', fontSize: 12, fontWeight: 600 }}>Query Layers</div>
        <button
          className="btn-gold"
          onClick={onRefresh}
          style={{ fontSize: 10, padding: '3px 8px' }}
          title="Refresh layer index"
        >
          ↺
        </button>
      </div>

      {layers.length === 0 && (
        <div style={{ color: '#555', fontSize: 11, padding: '8px 0' }}>No layers available</div>
      )}

      {layers.map((layer) => {
        const isEnabled = enabledLayerIds.includes(layer.id)
        return (
          <div
            key={layer.id}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              padding: '6px 0',
              borderBottom: '1px solid rgba(248,197,55,0.08)',
            }}
          >
            <input
              type="checkbox"
              checked={isEnabled}
              onChange={() => onToggle(layer.id)}
              style={{ marginTop: 2, cursor: 'pointer' }}
            />
            <div style={{ flex: 1 }}>
              <div style={{ color: '#bdae93', fontSize: 11, fontWeight: 500 }}>{layer.name}</div>
              {layer.description && (
                <div style={{ color: '#7c6f64', fontSize: 10, marginTop: 2 }}>{layer.description}</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
