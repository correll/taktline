import React from 'react'

/** Views are code-split, and a code-split app has one failure mode that a
 *  bundled one does not: the document outlives the build it came from.
 *
 *  Vite names chunks by content hash, and a deploy replaces the whole set. A
 *  tab that was open across the deploy still holds the previous index.html, so
 *  the first navigation to a view whose chunk was never fetched asks for a
 *  filename the server no longer has. The import rejects, React re-throws it
 *  during render, and — with nothing catching it — the entire tree unmounts.
 *  The result is a blank page in the body's background colour, cured by a
 *  reload, which is exactly what it looks like from the outside.
 *
 *  This is not rare in the way it feels: it is one per open tab per deploy.
 */

const RELOAD_FLAG = 'taktline.staleBuildReload'

/** A dynamic import that failed to load. There is no error `name` to switch
 *  on — every engine words this differently — so the message is all we have. */
export function isChunkLoadError(err: unknown): boolean {
  const msg = String((err as Error)?.message ?? err)
  return /failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed|chunkloaderror|unable to preload/i
    .test(msg)
}

/** Reload at most once per tab. Without the guard, a chunk that is genuinely
 *  missing (a bad deploy, not a stale one) would reload forever. */
function reloadOnceForStaleBuild(): boolean {
  try {
    if (sessionStorage.getItem(RELOAD_FLAG)) return false
    sessionStorage.setItem(RELOAD_FLAG, '1')
  } catch {
    return false                     // Safari private mode: fall through to the UI
  }
  window.location.reload()
  return true
}

/** Called after any chunk loads, so a later deploy gets its own attempt. */
export function clearStaleBuildFlag() {
  try { sessionStorage.removeItem(RELOAD_FLAG) } catch { /* not worth reporting */ }
}

/** React.lazy that survives a deploy.
 *
 *  Retry once — a shop-floor tablet on marginal wifi drops requests, and one
 *  extra request is cheap next to a blank screen. If it still fails, reload:
 *  the new index.html points at chunk names that exist. Only if that has
 *  already been tried does the error reach the boundary and become UI.
 */
// `any` matches React.lazy's own constraint; narrowing it breaks variance for
// every component whose props are not `never`.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyView<T extends React.ComponentType<any>>(
  load: () => Promise<{ default: T }>,
): React.LazyExoticComponent<T> {
  return React.lazy(async () => {
    try {
      const mod = await load()
      clearStaleBuildFlag()
      return mod
    } catch (err) {
      if (!isChunkLoadError(err)) throw err
      try {
        const mod = await load()
        clearStaleBuildFlag()
        return mod
      } catch (again) {
        // Suspend forever while the reload takes over — resolving or rejecting
        // here would flash the error UI on the way out.
        if (reloadOnceForStaleBuild()) return new Promise<{ default: T }>(() => {})
        throw again
      }
    }
  })
}
