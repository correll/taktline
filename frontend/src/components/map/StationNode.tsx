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
import { useRole } from '../../auth/useRole'

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

export function getStationIcon(id: string | null): LucideIcon {
  return (id && ICON_MAP[id]) ? ICON_MAP[id] : Cog
}
const getIcon = getStationIcon

// ─── Station node (HTML overlay) ─────────────────────────────────────────────

export type MapTool = 'select' | 'location' | 'route'

interface Props {
  station:   Station
  lotCount:  number
  selected:  boolean
  nodeSize:  number          // world-space side length in px
  viewport:  Viewport
  tool:      MapTool
  routeArmed: boolean         // this node is the locked source of an in-progress route
  flashing?: boolean          // pulse to highlight an isolated-subgraph member
  onSelect:  () => void
  onRouteAnchor: () => void   // route tool: clicked to become source / target
  onContextMenu: (clientX: number, clientY: number) => void
}

export default function StationNode({
  station, lotCount, selected, nodeSize, viewport, tool, routeArmed, flashing,
  onSelect, onRouteAnchor, onContextMenu,
}: Props) {
  const updateStation = useStationsStore((s) => s.update)
  const nudgePosition = useStationsStore((s) => s.nudgePosition)
  const { canEdit } = useRole()   // only admins may reposition stations

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
    e.stopPropagation()                        // never let a node click pan the map
    if (tool === 'route') return               // route tool: acts on click (up), no drag
    didDrag.current = false
    dragRef.current = { cx: e.clientX, cy: e.clientY, ox: pos.x, oy: pos.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [pos, tool])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current || !canEdit) return   // members can't drag-reposition
    const dx = (e.clientX - dragRef.current.cx) / viewport.scale
    const dy = (e.clientY - dragRef.current.cy) / viewport.scale
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) didDrag.current = true
    const nx = dragRef.current.ox + dx
    const ny = dragRef.current.oy + dy
    setLocalPos({ x: nx, y: ny })
    // Push the transient position into the store (no API call) so route edges
    // and heat blobs track the node during the drag instead of snapping after.
    nudgePosition(station._id, nx, ny)
  }, [viewport.scale, canEdit, nudgePosition, station._id])

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    if (tool === 'route') {
      // Only a real release anchors — NOT pointerleave, which would otherwise
      // drop the in-progress route the instant the cursor leaves the source.
      if (e.type === 'pointerup') onRouteAnchor()
      return
    }
    if (!dragRef.current) return
    if (canEdit && didDrag.current && localPos) {
      updateStation(station._id, {
        position: { ...station.position, x: Math.round(localPos.x), y: Math.round(localPos.y) },
      })
    } else if (!didDrag.current) {
      onSelect()
    }
    dragRef.current = null
    didDrag.current = false
    setLocalPos(null)
  }, [station, localPos, updateStation, onSelect, canEdit, tool, onRouteAnchor])

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!canEdit || tool === 'route') return
    e.preventDefault()
    e.stopPropagation()
    onContextMenu(e.clientX, e.clientY)
  }, [canEdit, tool, onContextMenu])

  if (screenSize < 6) return null

  const stationColor = station.color ?? '#2D5B8E'
  const Icon = getIcon(station.icon)
  const iconSize = Math.max(12, screenSize * 0.44)
  const showLabel = screenSize >= 36

  const borderWidth = selected ? 2.5 : 1.5
  const bgOpacity   = selected ? 0.95 : 0.88

  return (
    <div
      className={flashing ? 'map-node-flash' : undefined}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      onContextMenu={handleContextMenu}
      style={{
        position:     'absolute',
        left:         screenX,
        top:          screenY,
        width:        screenSize,
        height:       screenSize,
        borderRadius: Math.max(4, screenSize * 0.08),
        border:       `${routeArmed ? 2.5 : borderWidth}px solid ${routeArmed ? '#A78BFA' : stationColor}`,
        background:   `rgba(var(--tk-map-node-bg-rgb), ${bgOpacity})`,
        boxShadow:    routeArmed
          ? '0 0 0 3px #A78BFA66, 0 4px 16px rgba(0,0,0,0.5)'
          : selected
            ? `0 0 0 2px ${stationColor}55, 0 4px 16px rgba(0,0,0,0.5)`
            : '0 2px 8px rgba(0,0,0,0.4)',
        cursor:       tool === 'route' ? 'crosshair' : 'grab',
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
          color:       'var(--tk-map-node-text)',
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
          background:   lotCount > 0 ? '#639922' : '#2D5B8E',
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
