/** Is a WebGL context obtainable at all?
 *
 *  PixiJS calls `autoDetectRenderer`, which **throws** when it cannot get one:
 *  Pixi 7 dropped the canvas renderer, so there is nothing to fall back to.
 *  That exception escapes into React's render, the error boundary catches it,
 *  and the whole view is replaced by an apology.
 *
 *  It happened on the public landing page, which renders the animated line
 *  demo — so the front door of the product broke for:
 *
 *  - **crawlers and link-preview bots** (the first report came from one), which
 *    is a marketing problem as much as a technical one;
 *  - anyone whose **privacy extension blocks WebGL** to defeat fingerprinting,
 *    a setting that is neither rare nor unreasonable;
 *  - machines on a **GPU blocklist**, remote desktops, and locked-down VMs —
 *    which describes plenty of shop-floor office PCs.
 *
 *  So: ask first, and render something honest when the answer is no.
 *  Memoised because the answer cannot change within a page load, and creating
 *  probe contexts is not free.
 */
let cached: boolean | null = null

export function hasWebGL(): boolean {
  if (cached !== null) return cached
  if (typeof document === 'undefined') return (cached = false)
  try {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('webgl2')
           || canvas.getContext('webgl')
           || canvas.getContext('experimental-webgl')
    // Release the probe context immediately — browsers cap how many a page may
    // hold, and a leaked one can starve the real renderer later.
    const lose = (ctx as WebGLRenderingContext | null)
      ?.getExtension?.('WEBGL_lose_context') as { loseContext?: () => void } | null
    lose?.loseContext?.()
    return (cached = !!ctx)
  } catch {
    return (cached = false)   // some hardened browsers throw rather than return null
  }
}
