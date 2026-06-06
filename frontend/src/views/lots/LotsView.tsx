import React from 'react'
import { color, font } from '../../theme/tokens'

// Phase 3: Lot card list, kanban board, merge modal
export default function LotsView() {
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 12,
      color: color.textDim,
    }}>
      <span style={{ fontSize: 32 }}>▤</span>
      <span style={{ fontFamily: font.mono, fontSize: 12, letterSpacing: '0.1em' }}>
        LOTS VIEW — PHASE 3
      </span>
    </div>
  )
}
