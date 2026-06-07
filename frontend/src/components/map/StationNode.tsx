import React, { useRef, useState, useCallback } from 'react'
import {
  Cog, Warehouse, Package, Wrench, FlaskConical, Truck, Layers,
  Hammer, Scissors, Printer, Cpu, Thermometer, Box, Building2,
  ScanSearch, ArrowLeftRight, Factory, Settings2,
  type LucideIcon,
} from 'lucide-react'
import type { Station } from '../../models'
import type { Viewport } from './MapCanvas'
import { useStationsStore } from '../../store'

// ─── Icon registry ────────────────────────────────────────────────────────────

export const STATION_ICONS: { id: string; label: string; Icon: LucideIcon }[] = [
  { id: 'Cog',           label: 'Machine',       Icon: Cog           },
  { id: 'Factory',       label: 'Assembly',       Icon: Factory       },
  { id: 'Warehouse',     label: 'Warehouse',      Icon: Warehouse     },
  { id: 'Box',           label: 'Storage',        Icon: Box           },
  { id: 'Package',       label: 'Packaging',      Icon: Package       },
  { id: 'Truck',         label: 'Transport',      Icon: Truck         },
  { id: 'Wrench',        label: 'Maintenance',    Icon: Wrench        },
  { id: 'Hammer',        label: 'Fabrication',    Icon: Hammer        },
  { id: 'Scissors',      label: 'Cutting',        Icon: Scissors      },
  { id: 'Printer',       label: 'Printing',       Icon: Printer       },
  { id: 'Cpu',           label: 'Automation',     Icon: Cpu           },
  { id: 'Thermometer',   label: 'Heat treatment', Icon: Thermometer   },
  { id: 'FlaskConical',  label: 'Lab / QC',       Icon: FlaskConical  },
  { id: 'ScanSearch',    label: 'Inspection',     Icon: ScanSearch    },
  { id: 'ArrowLeftRight',label: 'Transfer',       Icon: ArrowLeftRight},
  { id: 'Layers',        label: 'Stacking',       Icon: Layers        },
  { id: 'Building2',     label: 'Facility',       Icon: Building2     },
  { id: 'Settings2',     label: 'Processing',     Icon: Settings2     },
]

const ICON_MAP = Object.fromEntries(STATION_ICONS.map(({ id, Icon }) => [id, Icon]))

function getIcon(id: string | null): LucideIcon {
  return (id && ICON_MAP[id]) ? ICON_MAP[id] : Cog
}

// ─── Station node (HTML overlay) ─────────────────────────────────────────────

interface Props {
  station:   Station
  lotCount:  number
  selected:  boolean
  nodeSize:  number          // world-space side length in px
  viewport:  Viewport
  onSelect:  () => void
}

export default function StationNode({
  station, lotCount, selected, nodeSize, viewport, onSelect,
}: Props) {
  const updateStation = useStationsStore((s) => s.update)

  const dragRef  = useRef<{ cx: number; cy: number; ox: number; oy: number } | null>(null)
  const didDrag  = useRef(false)
  const [localPos, setLocalPos] = useState<{ x: number; y: number } | null>(null)

  const pos = localPos ?? station.position
  const screenX    = pos.x * viewport.scale + viewport.x
  const screenY    = pos.y * viewport.scale + viewport.y
  const screenSize = nodeSize * viewport.scale

  // All hooks must be called before any early return (Rules of Hooks)
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return
    e.stopPropagation()
    didDrag.current = false
    dragRef.current = { cx: e.clientX, cy: e.clientY, ox: pos.x, oy: pos.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [pos])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return
    const dx = (e.clientX - dragRef.current.cx) / viewport.scale
    const dy = (e.clientY - dragRef.current.cy) / viewport.scale
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) didDrag.current = true
    setLocalPos({ x: dragRef.current.ox + dx, y: dragRef.current.oy + dy })
  }, [viewport.scale])

  const handlePointerUp = useCallback(() => {
    if (!dragRef.current) return
    if (didDrag.current && localPos) {
      updateStation(station._id, {
        position: { ...station.position, x: Math.round(localPos.x), y: Math.round(localPos.y) },
      })
    } else if (!didDrag.current) {
      onSelect()
    }
    dragRef.current = null
    didDrag.current = false
    setLocalPos(null)
  }, [station, localPos, updateStation, onSelect])

  if (screenSize < 6) return null

  const stationColor = station.color ?? '#2D5B8E'
  const Icon = getIcon(station.icon)
  const iconSize = Math.max(12, screenSize * 0.44)
  const showLabel = screenSize >= 36

  const borderWidth = selected ? 2.5 : 1.5
  const bgOpacity   = selected ? 0.95 : 0.88

  return (
    <div
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      style={{
        position:     'absolute',
        left:         screenX,
        top:          screenY,
        width:        screenSize,
        height:       screenSize,
        borderRadius: Math.max(4, screenSize * 0.08),
        border:       `${borderWidth}px solid ${stationColor}`,
        background:   `rgba(13,27,46,${bgOpacity})`,
        boxShadow:    selected
          ? `0 0 0 2px ${stationColor}55, 0 4px 16px rgba(0,0,0,0.5)`
          : '0 2px 8px rgba(0,0,0,0.4)',
        cursor:       'grab',
        userSelect:   'none',
        display:      'flex',
        flexDirection: 'column',
        alignItems:   'center',
        justifyContent: 'center',
        gap:          showLabel ? Math.max(1, screenSize * 0.04) : 0,
        overflow:     'hidden',
        pointerEvents: 'all',
        // top accent stripe
        boxSizing:    'border-box',
      }}
    >
      {/* Top color stripe */}
      <div style={{
        position:  'absolute',
        top:       0,
        left:      0,
        right:     0,
        height:    Math.max(3, screenSize * 0.05),
        background: stationColor,
        opacity:   0.85,
        borderRadius: `${Math.max(3, screenSize * 0.08)}px ${Math.max(3, screenSize * 0.08)}px 0 0`,
      }} />

      {/* Icon */}
      <Icon
        size={iconSize}
        color={stationColor}
        strokeWidth={1.5}
        style={{ flexShrink: 0 }}
      />

      {/* Label */}
      {showLabel && (
        <span style={{
          fontSize:    Math.max(8, Math.min(13, screenSize * 0.13)),
          fontWeight:  600,
          color:       '#C5D3E2',
          fontFamily:  'Inter, system-ui, sans-serif',
          textAlign:   'center',
          lineHeight:  1.2,
          maxWidth:    screenSize - 8,
          overflow:    'hidden',
          textOverflow: 'ellipsis',
          whiteSpace:  screenSize > 80 ? 'normal' : 'nowrap',
          padding:     '0 3px',
        }}>
          {station.name}
        </span>
      )}

      {/* Lot count badge */}
      {lotCount > 0 && (
        <div style={{
          position:     'absolute',
          top:          Math.max(3, screenSize * 0.05) + 3,
          right:        3,
          background:   lotCount > 0 ? '#10B981' : '#2D5B8E',
          color:        '#fff',
          fontSize:     Math.max(7, Math.min(10, screenSize * 0.12)),
          fontWeight:   700,
          fontFamily:   '"JetBrains Mono", monospace',
          borderRadius: 999,
          padding:      '1px 5px',
          lineHeight:   1.4,
          minWidth:     16,
          textAlign:    'center',
        }}>
          {lotCount}
        </div>
      )}
    </div>
  )
}
