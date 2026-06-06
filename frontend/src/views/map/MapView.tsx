import React, { useState } from 'react'
import { useStationsStore, useProcessesStore, useMachinesStore } from '../../store'
import MapCanvas from '../../components/map/MapCanvas'
import StationPanel from '../../components/map/StationPanel'

export default function MapView() {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const stations     = useStationsStore((s) => s.stations)
  const routes       = useProcessesStore((s) => s.routes)
  const machineStates= useMachinesStore((s) => s.states)

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      <MapCanvas
        stations={stations}
        routes={routes}
        machineStates={machineStates}
        selectedStationId={selectedId}
        onSelectStation={setSelectedId}
      />
      {selectedId && stations[selectedId] && (
        <StationPanel stationId={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </div>
  )
}
