import type { WSEvent } from '../models'
import { useMachinesStore } from '../store/machines.store'
import { useCardsStore }    from '../store/cards.store'

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

export function connectWS(): void {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url   = `${proto}://${window.location.host}/ws/events`
  socket      = new WebSocket(url)

  socket.onopen = () => {
    useMachinesStore.getState().setConnected(true)
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  }

  socket.onmessage = (evt) => {
    try {
      handleEvent(JSON.parse(evt.data) as WSEvent)
    } catch { /* ignore malformed frames */ }
  }

  socket.onclose = () => {
    useMachinesStore.getState().setConnected(false)
    reconnectTimer = setTimeout(connectWS, 3000)
  }

  socket.onerror = () => socket?.close()
}

export function disconnectWS(): void {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  socket?.close()
  socket = null
}

function handleEvent(event: WSEvent): void {
  switch (event.type) {
    case 'machine_state':
      useMachinesStore.getState().upsertState(event.payload)
      break
    case 'card_update':
      useCardsStore.getState().upsert(event.payload)
      break
    case 'card_delete':
      // Phase 3: handle delete by removing from store
      break
  }
}
