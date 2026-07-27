import React from 'react'

/** Taktline brand lockup — five takt bars (accent on the second) plus the
 * wordmark. Inlined as JSX (rather than an <img>) so `currentColor` inherits
 * the surrounding text color and the logo adapts to any background.
 * `mark` renders the bars alone (square-ish variant for tight spots). */
export function TaktlineLogo({ height = 22, mark = false, color = 'currentColor' }: {
  height?: number
  mark?: boolean
  color?: string
}) {
  return (
    <svg
      height={height}
      viewBox={`0 0 ${mark ? 54 : 196} 34`}
      style={{ color, display: 'block', flexShrink: 0 }}
      role="img"
      aria-label="Taktline"
    >
      <g fill="currentColor">
        <rect x="0" y="2" width="6" height="30" rx="1" />
        <rect x="24" y="2" width="6" height="30" rx="1" />
        <rect x="36" y="2" width="6" height="30" rx="1" />
        <rect x="48" y="2" width="6" height="30" rx="1" />
      </g>
      <rect x="12" y="2" width="6" height="30" rx="1" fill="#D85A30" />
      {!mark && (
        <text
          x="74" y="26"
          fontFamily="Inter, 'Helvetica Neue', Arial, sans-serif"
          fontSize="27" fontWeight={500} letterSpacing="-0.6"
          fill="currentColor"
        >
          taktline
        </text>
      )}
    </svg>
  )
}
