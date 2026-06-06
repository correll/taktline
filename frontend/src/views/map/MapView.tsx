import React from 'react'
import { color, font } from '../../theme/tokens'

// Phase 2: PixiJS floor-plan canvas, draggable stations, animated route flows
export default function MapView() {
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
      <span style={{ fontSize: 32 }}>⬡</span>
      <span style={{ fontFamily: font.mono, fontSize: 12, letterSpacing: '0.1em' }}>
        MAP VIEW — PHASE 2
      </span>
    </div>
  )
}
