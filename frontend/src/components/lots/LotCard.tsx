import React, { useMemo } from 'react'
import { color, font, size } from '../../theme/tokens'
import { useNow } from '../../motion/useNow'
import { useProcessesStore, useThemeStore } from '../../store'
import { processColorsFor } from '../../domain/processColors'
import type { Card, LotTemplate } from '../../models'

interface Props {
  card:      Card
  template:  LotTemplate | undefined
  stationId: string
  onClick?:  () => void
  onMove?:   () => void
}

/** How long this lot has been sitting, in the largest unit that still says
 *  something: seconds while someone is watching it move, then minutes, hours,
 *  days. Starting at seconds is the point — on a board refreshed live, "0s"
 *  ticking up is what tells you the card just landed. */
function ageLabel(iso: string, now: number): string {
  const raw = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'
  const secs = Math.max(0, Math.floor((now - new Date(raw).getTime()) / 1000))
  if (secs < 60)      return `${secs}s`
  const m = Math.floor(secs / 60)
  if (m < 60)         return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24)         return `${h}h`
  return `${Math.floor(h / 24)}d`
}

const STATUS_COLOR: Record<string, string> = {
  working: '#639922',
  done:    '#F0997B',
  idle:    color.textDim,
}
const STATUS_LABEL: Record<string, string> = {
  working: 'WORKING',
  done:    'DONE',
  idle:    '',
}

/** The lot's human identifier: its stored code (e.g. "E4096A"), `#`-prefixed
 * when it's a legacy numeric value, or a short id for un-coded cards. */
export const lotLabel = (card: Pick<Card, 'lotNum' | '_id'>): string => {
  const code = card.lotNum
  if (code == null || code === '') return card._id.slice(-6).toUpperCase()
  return /^\d+$/.test(code) ? `#${code}` : code
}

export default function LotCard({ card, template, stationId, onClick }: Props) {
  const now = useNow()
  const count  = card.bins[stationId]?.count ?? 0
  const accent = template?.color ?? color.lotBlue
  const pct    = card.totalQuantity > 0 ? count / card.totalQuantity : 0

  // Which line this lot belongs to — in the same colour the map's legend gives
  // that process, so the dot on the card and the routes on the floor plan agree.
  const processes   = useProcessesStore((s) => s.processes)
  const themeMode   = useThemeStore((s) => s.mode)
  const processName = processes[card.processId]?.name
  const processDot  = useMemo(
    () => processColorsFor(Object.keys(processes), themeMode)[card.processId],
    [processes, themeMode, card.processId],
  )

  return (
    <div
      onClick={onClick}
      style={{
        background:   color.bgCard,
        border:       `1px solid ${color.border}`,
        borderRadius: size.radiusMd,
        overflow:     'hidden',
        cursor:       onClick ? 'pointer' : 'default',
        userSelect:   'none',
        transition:   'border-color 0.12s, box-shadow 0.12s',
        boxShadow:    card.flagged ? `0 0 0 1.5px ${color.statusWarning}50` : 'none',
      }}
      onMouseEnter={(e) => {
        if (!onClick) return
        e.currentTarget.style.borderColor = accent + '70'
        e.currentTarget.style.boxShadow   = `0 2px 10px ${accent}20`
      }}
      onMouseLeave={(e) => {
        if (!onClick) return
        e.currentTarget.style.borderColor = card.flagged ? color.statusWarning + '50' : color.border
        e.currentTarget.style.boxShadow   = card.flagged ? `0 0 0 1.5px ${color.statusWarning}50` : 'none'
      }}
    >
      {/* Top color stripe — product identity */}
      <div style={{ height: 4, background: accent }} />

      <div style={{ padding: '8px 10px 7px' }}>

        {/* Row 1: product type + status badge + flag */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
          <span style={{
            flex: 1, fontSize: 9, fontFamily: font.mono, letterSpacing: '0.1em',
            color: color.textSecondary, textTransform: 'uppercase',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {template?.name ?? 'UNKNOWN'}
          </span>

          {card.status !== 'idle' && (
            <span style={{
              fontSize: 8, fontFamily: font.mono, letterSpacing: '0.08em', flexShrink: 0,
              color:      STATUS_COLOR[card.status],
              background: STATUS_COLOR[card.status] + '1A',
              border:     `1px solid ${STATUS_COLOR[card.status]}50`,
              borderRadius: size.radiusFull, padding: '1px 5px',
            }}>
              {STATUS_LABEL[card.status]}
            </span>
          )}

          {card.flagged && (
            <span style={{ color: color.statusWarning, fontSize: 10, flexShrink: 0 }}>⚑</span>
          )}
        </div>

        {/* Row 2: lot ID (left) + unit count (right) */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 5 }}>
          <div style={{
            fontFamily: font.mono, fontSize: 18, fontWeight: 700,
            color: color.textPrimary, lineHeight: 1,
          }}>
            {lotLabel(card)}
          </div>
          <div style={{ textAlign: 'right', lineHeight: 1 }}>
            <span style={{ fontFamily: font.mono, fontSize: 14, fontWeight: 700, color: color.textPrimary }}>
              {count}
            </span>
            <span style={{ fontFamily: font.mono, fontSize: 9, color: color.textDim }}>
              /{card.totalQuantity}
            </span>
          </div>
        </div>

        {/* Progress bar: units at this station vs total */}
        <div style={{
          height: 2, borderRadius: 1,
          background: color.bgElevated, overflow: 'hidden', marginBottom: 6,
        }}>
          <div style={{
            height: '100%',
            width: `${Math.max(3, pct * 100)}%`,
            background: accent, borderRadius: 1,
          }} />
        </div>

        {/* Row 3: age (left) + description + process. Age leads because on a
            Kanban board it is the number that matters — a card that has sat for
            two days is the one to ask about, and it should be in the same place
            on every card so a column can be scanned down rather than read. The
            process sits at the far right, where two lines sharing one station
            are told apart. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 9, color: color.textDim, fontFamily: font.mono, flexShrink: 0 }}>
            {ageLabel(card.updatedAt, now)}
          </span>
          {card.description && (
            <span style={{
              flex: 1, fontSize: 9, color: color.textDim, textAlign: 'right',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {card.description}
            </span>
          )}
          {processName && (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              minWidth: 0, maxWidth: '55%', flexShrink: 0,
              marginLeft: card.description ? 0 : 'auto',
            }}>
              {processDot && (
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: processDot, flexShrink: 0 }} />
              )}
              <span style={{
                fontSize: 9, color: color.textDim, fontFamily: font.mono,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {processName}
              </span>
            </span>
          )}
        </div>

      </div>
    </div>
  )
}
