import React from 'react'

/** Keeps a PixiJS failure inside the picture it belongs to.
 *
 *  The WebGL probe (`hasWebGL`) covers the reason we actually saw in
 *  production, but it is not the only way Pixi can fail at mount:
 *
 *  - **Context limits.** Browsers cap how many live WebGL contexts a page may
 *    hold — around 8–16 in Chrome. The user manual stacks several animated
 *    figures on one page, and each one is its own Stage. Crossing that line
 *    fails in exactly the same way as having no WebGL at all.
 *  - **A lost context**: the GPU process crashes, a driver resets, a laptop
 *    switches graphics cards.
 *
 *  Whatever the cause, the failure arrives twice. The Stage's constructor
 *  throws, so its internal application is never assigned; React then unmounts
 *  the subtree, cleanup reaches for `app.stage`, and a second error — `Cannot
 *  read properties of null (reading 'stage')` — follows the first. Both were
 *  reported from the same crawler visit, at the same millisecond.
 *
 *  This boundary catches the render-time failure and swaps in a drawing that
 *  needs no GPU, so one figure going dark costs a figure rather than the page.
 */
type Props = { children: React.ReactNode; fallback: React.ReactNode }
type State = { failed: boolean }

export class PixiBoundary extends React.Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error) {
    // Not reported to /client-errors: this is a handled degradation with a
    // visible result, and a page of figures on a context-starved browser would
    // otherwise post one report per figure. The console still carries it for
    // anyone actually debugging.
    console.warn('[taktline] canvas unavailable, drawing without it:', error?.message)
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

export default PixiBoundary
