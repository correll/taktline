import React, { useMemo, useState } from 'react'
import { color, font, size } from '../../theme/tokens'

/** Column-header sorting for the platform tables.
 *
 *  Each column supplies the *value* to sort on rather than a comparator, so a
 *  column reads "sort by the number" and cannot accidentally sort a formatted
 *  string ("1.2k" before "900"). Nulls always sink to the bottom whichever way
 *  the arrow points — "never seen" is not the most recent thing that happened,
 *  and it is not the oldest either; it is absent, and absent belongs last.
 */
export interface SortColumn<T> {
  label: string
  /** Omit to make the column unsortable (an actions column). */
  value?: (row: T) => string | number | null | undefined
  align?: 'left' | 'right'
  /** Pin this column to the right edge, so a wide table scrolls underneath it
   *  rather than carrying it out of reach. Used for action columns, where
   *  being scrolled off-screen makes the row's only controls unreachable
   *  without finding a scrollbar most people never look for. */
  sticky?: boolean
  /** Sort descending on first click — right for "most requests", wrong for names. */
  descFirst?: boolean
}

export function useSortable<T>(rows: T[], columns: SortColumn<T>[], initial?: string) {
  const [key, setKey] = useState<string | null>(initial ?? null)
  const [desc, setDesc] = useState(false)

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.label === key)
    if (!col?.value) return rows
    const dir = desc ? -1 : 1
    return [...rows].sort((a, b) => {
      const x = col.value!(a), y = col.value!(b)
      const xEmpty = x === null || x === undefined || x === ''
      const yEmpty = y === null || y === undefined || y === ''
      if (xEmpty || yEmpty) return xEmpty && yEmpty ? 0 : xEmpty ? 1 : -1   // absent last
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir
      return String(x).localeCompare(String(y), undefined, { numeric: true }) * dir
    })
  }, [rows, columns, key, desc])

  const toggle = (col: SortColumn<T>) => {
    if (!col.value) return
    if (key === col.label) setDesc((d) => !d)
    else { setKey(col.label); setDesc(!!col.descFirst) }
  }

  const header = (
    <tr>
      {columns.map((col) => {
        const active = key === col.label
        return (
          <th
            key={col.label}
            onClick={() => toggle(col)}
            aria-sort={active ? (desc ? 'descending' : 'ascending') : undefined}
            title={col.value ? `Sort by ${col.label.toLowerCase()}` : undefined}
            style={{
              textAlign: col.align ?? 'left',
              ...(col.sticky ? {
                position: 'sticky' as const, right: 0, zIndex: 2,
                background: color.bgCard,
                borderLeft: `1px solid ${color.border}`,
              } : {}),
              padding: `${size.sp2} ${size.sp4}`,
              fontSize: 10.5, fontFamily: font.mono, letterSpacing: '0.08em',
              color: active ? color.textPrimary : color.textDim,
              textTransform: 'uppercase', fontWeight: 500,
              cursor: col.value ? 'pointer' : 'default',
              userSelect: 'none', whiteSpace: 'nowrap',
            }}
          >
            {col.label}
            {col.value && (
              // The inactive caret is always rendered, just faint: without it
              // every header shifts sideways as the sort moves between them.
              <span style={{ marginLeft: 5, opacity: active ? 1 : 0.25 }}>
                {active && desc ? '▾' : '▴'}
              </span>
            )}
          </th>
        )
      })}
    </tr>
  )

  return { rows: sorted, header }
}
