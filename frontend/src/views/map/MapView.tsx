import React, { useState, useMemo, useRef } from 'react'
import { MousePointer2, MapPin, Waypoints } from 'lucide-react'
import { useStationsStore, useProcessesStore, useCardsStore } from '../../store'
import { useRole } from '../../auth/useRole'
import { color } from '../../theme/tokens'
import MapCanvas from '../../components/map/MapCanvas'
import type { MapTool } from '../../components/map/StationNode'
import StationPanel from '../../components/map/StationPanel'
import type { Process } from '../../models'

export default function MapView() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tool, setTool] = useState<MapTool>('select')
  const [routeProcessId, setRouteProcessId] = useState<string>('')

  const stations  = useStationsStore((s) => s.stations)
  const routes    = useProcessesStore((s) => s.routes)
  const processes = useProcessesStore((s) => s.processes)
  const createProcess = useProcessesStore((s) => s.createProcess)
  const cards     = useCardsStore((s) => s.cards)
  const { canEdit } = useRole()

  const processList = useMemo(
    () => Object.values(processes).sort((a, b) => a.name.localeCompare(b.name)),
    [processes],
  )
  const effProcessId = routeProcessId || processList[0]?._id || ''

  // Picking the route tool with no process yet auto-creates a default one, so a
  // whole line can be drawn on the map without a detour into Settings.
  const provisioningRef = useRef(false)
  const chooseTool = (t: MapTool) => {
    if (t === 'route' && processList.length === 0 && !provisioningRef.current) {
      provisioningRef.current = true
      createProcess({ name: 'Main Line' })
        .then((p) => setRouteProcessId(p._id))
        .finally(() => { provisioningRef.current = false })
    }
    setTool(t)
  }

  // Count distinct lot cards currently present at each station
  const lotCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const card of Object.values(cards)) {
      for (const [stationId, bin] of Object.entries(card.bins)) {
        if (bin.count > 0) counts[stationId] = (counts[stationId] ?? 0) + 1
      }
    }
    return counts
  }, [cards])

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
      <MapCanvas
        stations={stations}
        routes={routes}
        lotCounts={lotCounts}
        selectedStationId={selectedId}
        onSelectStation={setSelectedId}
        tool={canEdit ? tool : 'select'}
        routeProcessId={effProcessId}
      />
      {canEdit && (
        <MapToolbar
          tool={tool}
          setTool={chooseTool}
          processList={processList}
          routeProcessId={effProcessId}
          setRouteProcessId={setRouteProcessId}
          onCreateProcess={() => {
            createProcess({ name: `Line ${processList.length + 1}` }).then((p) => setRouteProcessId(p._id))
          }}
        />
      )}
      {selectedId && stations[selectedId] && (
        <StationPanel stationId={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </div>
  )
}

function MapToolbar({ tool, setTool, processList, routeProcessId, setRouteProcessId, onCreateProcess }: {
  tool: MapTool
  setTool: (t: MapTool) => void
  processList: Process[]
  routeProcessId: string
  setRouteProcessId: (id: string) => void
  onCreateProcess: () => void
}) {
  const btn = (t: MapTool, Icon: typeof MapPin, label: string) => (
    <button
      title={label}
      data-tour={`map-tool-${t}`}
      onClick={() => setTool(tool === t ? 'select' : t)}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center', width: 34, height: 34,
        borderRadius: 6, border: 'none', cursor: 'pointer',
        background: tool === t ? '#D85A30' : 'transparent',
        color: tool === t ? '#fff' : color.textSecondary,
      }}
    >
      <Icon size={18} />
    </button>
  )

  return (
    <div style={{ position: 'absolute', top: 14, left: 14, zIndex: 20, display: 'flex', gap: 8, alignItems: 'center' }}>
      <div style={{ display: 'flex', gap: 4, background: color.glass,
                    border: `1px solid ${color.border}`, borderRadius: 8, padding: 4 }}>
        {btn('select', MousePointer2, 'Select / pan')}
        {btn('station', MapPin, 'Add station — click the map to place one')}
        {btn('route', Waypoints, 'Add route — click source then target')}
      </div>
      {tool === 'route' && (
        processList.length > 0 ? (
          <select value={routeProcessId}
                  onChange={(e) => { if (e.target.value === '__new__') onCreateProcess(); else setRouteProcessId(e.target.value) }}
                  title="Process for new routes"
                  style={{ background: color.glass, border: `1px solid ${color.border}`, borderRadius: 8,
                           color: color.textPrimary, fontSize: 12, padding: '7px 10px', outline: 'none' }}>
            {processList.map((p) => <option key={p._id} value={p._id}>{p.name}</option>)}
            <option value="__new__">＋ New process…</option>
          </select>
        ) : (
          <div style={{ background: color.glass, border: '1px solid #EF9F2755', borderRadius: 8,
                        color: color.warnText, fontSize: 12, padding: '7px 10px' }}>
            Create a process first (Settings → Processes)
          </div>
        )
      )}
    </div>
  )
}
