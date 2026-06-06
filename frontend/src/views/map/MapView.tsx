import React, { useState, useMemo } from 'react'
import { useStationsStore, useProcessesStore, useCardsStore } from '../../store'
import MapCanvas from '../../components/map/MapCanvas'
import StationPanel from '../../components/map/StationPanel'

export default function MapView() {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const stations  = useStationsStore((s) => s.stations)
  const routes    = useProcessesStore((s) => s.routes)
  const cards     = useCardsStore((s) => s.cards)

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
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      <MapCanvas
        stations={stations}
        routes={routes}
        lotCounts={lotCounts}
        selectedStationId={selectedId}
        onSelectStation={setSelectedId}
      />
      {selectedId && stations[selectedId] && (
        <StationPanel stationId={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </div>
  )
}
