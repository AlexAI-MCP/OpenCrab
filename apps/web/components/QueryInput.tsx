'use client'

import { useState } from 'react'

interface Props {
  onRun: (query: string) => void
}

export default function QueryInput({ onRun }: Props) {
  const [query, setQuery] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (query.trim()) {
      onRun(query.trim())
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        display: 'flex',
        gap: 8,
        background: '#1a1a1a',
        border: '1px solid rgba(248,197,55,0.15)',
        borderRadius: 6,
        padding: 10,
        marginBottom: 12,
      }}
    >
      <input
        className="input-dark"
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Enter query to filter graph..."
        style={{ flex: 1, fontSize: 11, padding: '6px 10px' }}
      />
      <button
        type="submit"
        className="btn-gold"
        style={{ fontSize: 11, padding: '6px 12px' }}
      >
        Run
      </button>
    </form>
  )
}
