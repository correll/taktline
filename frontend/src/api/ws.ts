import type { WSEvent } from '../models'
import { useMachinesStore } from '../store/machines.store'
import { useCardsStore }    from '../store/cards.store'
import { useStationsStore } from '../store/stations.store'
import { useProcessesStore } from '../store/processes.store'
import { ACTIVE_COMPANY_KEY } from './client'

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let hadConnection = false   // a later successful open is a REconnect → resync
let retryDelay = 3000       // backoff 3s → 15s so a rebooting host isn't hammered
let failedAttempts = 0      // amber only from the 2nd consecutive failure (or a
                            // dropped live link) — a lone handshake hiccup on
                            // page load isn't worth alarming the floor about
const RETRY_MAX = 15000

// Derive the WebSocket origin from VITE_API_URL when the API is cross-origin,
// otherwise use the current page origin (dev proxy / same-origin hosting).
function wsBase(): string {
  const api = import.meta.env.VITE_API_URL
  if (api && /^https?:\/\//.test(api)) {
    return api.replace(/^http/, 'ws').replace(/\/$/, '')
  }
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}`
}

export function connectWS(): void {
  const companyId = localStorage.getItem(ACTIVE_COMPANY_KEY)
  if (!companyId) return   // not authenticated / no active company yet

  const url  = `${wsBase()}/ws/events?companyId=${encodeURIComponent(companyId)}`
  socket     = new WebSocket(url)

  socket.onopen = () => {
    const wasStale = useMachinesStore.getState().staleSince != null
    useMachinesStore.getState().setConnection('live')
    useMachinesStore.getState().setStaleSince(null)
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    retryDelay = 3000
    failedAttempts = 0
    // Events broadcast while we were disconnected are gone for good — refetch
    // the cards so the board can't keep showing a lot at its old station. A
    // session that booted from the offline cache resyncs everything.
    if (hadConnection || wasStale) useCardsStore.getState().fetchAll()
    if (wasStale) {
      useStationsStore.getState().fetchAll()
      useProcessesStore.getState().fetchAll()
    }
    hadConnection = true
  }

  socket.onmessage = (evt) => {
    try {
      handleEvent(JSON.parse(evt.data) as WSEvent)
    } catch { /* ignore malformed frames */ }
  }

  socket.onclose = (evt) => {
    // 4401/4403 = auth/authorization failure — don't hammer with reconnects.
    if (evt.code === 4401 || evt.code === 4403) {
      useMachinesStore.getState().setConnection('off')
      return
    }
    // Server unreachable (reboot, network drop): retry with backoff. Amber
    // only when a live link dropped or a retry also failed — not on the very
    // first handshake blip of a fresh page load.
    failedAttempts += 1
    useMachinesStore.getState().setConnection(
      hadConnection || failedAttempts >= 2 ? 'reconnecting' : 'off')
    reconnectTimer = setTimeout(connectWS, retryDelay)
    retryDelay = Math.min(RETRY_MAX, Math.round(retryDelay * 1.5))
  }

  socket.onerror = () => socket?.close()
}

export function disconnectWS(): void {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  hadConnection = false   // deliberate teardown (company switch) refetches anyway
  retryDelay = 3000
  if (socket) {
    socket.onclose = null   // deliberate close must not trigger the retry path
    socket.close()
    socket = null
  }
  useMachinesStore.getState().setConnection('off')
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
      useCardsStore.getState().drop(event.payload.id)
      break
  }
}
