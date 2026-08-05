import { useMemo, useState } from 'react'
import { color, font, size } from '../../theme/tokens'

/**
 * Type-to-filter for the platform tables.
 *
 * Two decisions worth stating.
 *
 * **It searches every field the caller names, not just the first column.**
 * Support is usually working from a fragment — half an email, a plan code, a
 * company someone said on the phone — and a filter that only matched the name
 * column would send them back to Cmd-F.
 *
 * **It filters, it does not query.** Both tables are already fully loaded (the
 * platform view fetches them whole), so filtering client-side is instant and
 * cannot get out of step with what is on screen. If these ever grow past a few
 * thousand rows this becomes a server-side search; until then a round trip per
 * keystroke would be slower and worse.
 */
export function useFilter<T>(rows: T[], fields: (row: T) => (string | null | undefined)[],
                             placeholder: string) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return rows
    // Every word must appear somewhere, in any order — so "acme paid" finds the
    // paying Acme without anyone having to guess the column order.
    const words = needle.split(/\s+/)
    return rows.filter((row) => {
      const hay = fields(row).filter(Boolean).join(' ').toLowerCase()
      return words.every((w) => hay.includes(w))
    })
  }, [rows, query, fields])

  const input = (
    <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2 }}>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        style={{
          background: color.bgCard, border: `1px solid ${color.border}`,
          borderRadius: size.radius, color: color.textPrimary,
          padding: '6px 10px', fontSize: 13, fontFamily: 'inherit', width: 260,
        }}
      />
      {query && (
        <>
          <button
            onClick={() => setQuery('')}
            aria-label="Clear filter"
            style={{
              background: 'none', border: 'none', color: color.textDim,
              cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
            }}
          >
            ×
          </button>
          <span style={{ fontSize: 11.5, fontFamily: font.mono, color: color.textDim }}>
            {filtered.length} of {rows.length}
          </span>
        </>
      )}
    </div>
  )

  return { rows: filtered, input, query }
}
