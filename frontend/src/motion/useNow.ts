import { useEffect, useState } from 'react'

/** One clock for every card on the board.
 *
 *  Lot age now starts in seconds, which only means anything if it advances —
 *  a card reading "3s" ten minutes later is worse than one reading "just now",
 *  because it looks live and is lying. But a board can show a hundred cards,
 *  and a hundred intervals firing every second is a hundred re-renders a
 *  second.
 *
 *  So there is a single interval, shared by every subscriber and running only
 *  while at least one card is mounted. It also stops when the tab is hidden
 *  and catches up on return: a wall display left overnight should not have
 *  burned 30,000 renders behind a screensaver.
 */
type Listener = (now: number) => void

const listeners = new Set<Listener>()
let timer: ReturnType<typeof setInterval> | null = null

function tick() {
  const now = Date.now()
  for (const l of listeners) l(now)
}

function start() {
  if (timer !== null || typeof document === 'undefined') return
  if (document.visibilityState === 'hidden') return
  timer = setInterval(tick, 1000)
}

function stop() {
  if (timer !== null) { clearInterval(timer); timer = null }
}

function onVisibility() {
  if (document.visibilityState === 'hidden') stop()
  else if (listeners.size > 0) { tick(); start() }   // catch up, then resume
}

export function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    listeners.add(setNow)
    if (listeners.size === 1) {
      document.addEventListener('visibilitychange', onVisibility)
      start()
    }
    return () => {
      listeners.delete(setNow)
      if (listeners.size === 0) {
        document.removeEventListener('visibilitychange', onVisibility)
        stop()
      }
    }
  }, [])
  return now
}
