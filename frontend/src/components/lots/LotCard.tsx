import React from 'react'
import { color, font, size } from '../../theme/tokens'
import type { Card, LotTemplate } from '../../models'

interface Props {
  card:       Card
  template:   LotTemplate | undefined
  stationId:  string
  onClick?:   () => void
  onMove?:    () => void
}

// Time since a date string, e.g. "2h ago"
function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const m  = Math.floor(ms / 60000)
  if (m < 1)  return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function LotCard({ card, template, stationId, onClick }: Props) {
  const count = card.bins[stationId]?.count ?? 0
  const accent = template?.color ?? color.bluePrimary

  return (
    <div
      onClick={onClick}
      style={{
        background:   color.bgCard,
        border:       `1px solid ${color.border}`,
        borderLeft:   `3px solid ${accent}`,
        borderRadius: size.radius,
        padding:      `${size.sp2} ${size.sp3}`,
        cursor:       onClick ? 'pointer' : 'default',
        transition:   'border-color 0.15s, background 0.15s',
        display:      'flex',
        alignItems:   'center',
        gap:          size.sp3,
        userSelect:   'none',
      }}
      onMouseEnter={(e) => { if (onClick) (e.currentTarget as HTMLElement).style.borderColor = color.borderActive }}
      onMouseLeave={(e) => { if (onClick) (e.currentTarget as HTMLElement).style.borderColor = color.border }}
    >
      {/* Template + lot number */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: color.textPrimary }} className="truncate">
          {template?.name ?? 'Unknown'}
        </div>
        {card.lotNum != null && (
          <div style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono }}>
            #{card.lotNum}
          </div>
        )}
      </div>

      {/* Count badge */}
      <div style={{ textAlign: 'right', flexShrink: 0 }}>
        <div style={{ fontFamily: font.mono, fontSize: 13, fontWeight: 700, color: color.textPrimary }}>
          {count}
          <span style={{ fontSize: 10, color: color.textDim, fontWeight: 400 }}>
            /{card.totalQuantity}
          </span>
        </div>
        <div style={{ fontSize: 9, color: color.textDim }}>
          {timeAgo(card.updatedAt)}
        </div>
      </div>

      {/* Flag */}
      {card.flagged && (
        <span style={{ color: color.statusWarning, fontSize: 12, flexShrink: 0 }}>⚑</span>
      )}
    </div>
  )
}
