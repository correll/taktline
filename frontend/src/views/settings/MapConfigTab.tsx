import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useMapSettingsStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import { FieldLabel, inputStyle, primaryBtn, secondaryBtn, dangerBtn, ErrorMsg } from './shared'
import { client } from '../../api/client'

export default function MapConfigTab() {
  const settings  = useMapSettingsStore((s) => s.settings)
  const fetchMap  = useMapSettingsStore((s) => s.fetch)
  const updateMap = useMapSettingsStore((s) => s.update)
  const uploadMap = useMapSettingsStore((s) => s.upload)

  const [floorPlanUrl,     setFloorPlanUrl]     = useState('')
  const [pixelsPerUnit,    setPixelsPerUnit]    = useState('100')
  const [unit,             setUnit]             = useState<'ft' | 'm'>('ft')
  const [stationSizeUnits, setStationSizeUnits] = useState('1.0')
  const [mapWidthPx,       setMapWidthPx]       = useState<number | null>(null)
  const [mapHeightPx,      setMapHeightPx]      = useState<number | null>(null)
  const [saving,           setSaving]           = useState(false)
  const [uploading,        setUploading]        = useState(false)
  const [clearing,         setClearing]         = useState(false)
  const [error,            setError]            = useState<string | null>(null)
  const [saved,            setSaved]            = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!settings) { fetchMap(); return }
    setFloorPlanUrl(settings.floorPlanUrl ?? '')
    setPixelsPerUnit(String(settings.pixelsPerUnit))
    setUnit(settings.unit)
    setStationSizeUnits(String(settings.stationSizeUnits ?? 1))
    setMapWidthPx(settings.mapWidthPx ?? null)
    setMapHeightPx(settings.mapHeightPx ?? null)
  }, [settings])

  const handleSave = async () => {
    const ppu = parseFloat(pixelsPerUnit)
    const ssu = parseFloat(stationSizeUnits)
    if (isNaN(ppu) || ppu <= 0) { setError('Pixels per unit must be a positive number'); return }
    if (isNaN(ssu) || ssu <= 0) { setError('Station size must be a positive number'); return }
    setSaving(true); setError(null)
    try {
      await updateMap({
        floorPlanUrl: floorPlanUrl.trim() || undefined,
        pixelsPerUnit: ppu,
        unit,
        stationSizeUnits: ssu,
        mapWidthPx:  mapWidthPx  ?? undefined,
        mapHeightPx: mapHeightPx ?? undefined,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async () => {
    setSaving(true)
    try {
      await updateMap({ floorPlanUrl: null, mapWidthPx: null, mapHeightPx: null } as any)
      setFloorPlanUrl('')
      setMapWidthPx(null)
      setMapHeightPx(null)
    } finally {
      setSaving(false)
    }
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true); setError(null)
    try {
      const url = await uploadMap(file)
      setFloorPlanUrl(url)
    } catch (e) {
      setError(String(e))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const ppu       = parseFloat(pixelsPerUnit) || 100
  const activeUrl = floorPlanUrl

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>

      {/* ── Floor plan as background ────────────────────────── */}
      <FloorPlanBackground
        url={activeUrl}
        ppu={ppu}
        unit={unit}
        onDimsCapture={(w, h) => { setMapWidthPx(w); setMapHeightPx(h) }}
      />

      {/* ── Controls panel ──────────────────────────────────── */}
      <div style={{
        position:    'relative',
        zIndex:      10,
        width:       320,
        flexShrink:  0,
        overflowY:   'auto',
        background:  color.glass,
        backdropFilter: 'blur(8px)',
        borderRight: `1px solid ${color.border}`,
        padding:     `${size.sp6} ${size.sp5}`,
        display:     'flex',
        flexDirection: 'column',
        gap:         size.sp5,
      }}>
        <div style={{ fontSize: 11, fontFamily: font.mono, color: color.textDim, letterSpacing: '0.1em' }}>
          MAP CONFIGURATION
        </div>

        {/* Upload button */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <FieldLabel>FLOOR PLAN IMAGE</FieldLabel>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || saving}
            style={{
              ...secondaryBtn,
              width: '100%',
              justifyContent: 'center',
              opacity: uploading ? 0.6 : 1,
            }}
          >
            {uploading ? 'Uploading…' : '↑ Upload PNG / JPG'}
          </button>
          <span style={{ fontSize: 10, color: color.textDim }}>
            — or paste a URL below —
          </span>
          <input
            value={floorPlanUrl}
            onChange={(e) => setFloorPlanUrl(e.target.value)}
            placeholder="https://example.com/floor.png"
            style={inputStyle}
          />
        </div>

        {/* Scale settings */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp4 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>PIXELS PER UNIT</FieldLabel>
            <input
              type="number"
              min={1}
              value={pixelsPerUnit}
              onChange={(e) => setPixelsPerUnit(e.target.value)}
              style={{ ...inputStyle, fontFamily: font.mono }}
            />
            <span style={{ fontSize: 10, color: color.textDim }}>
              Image pixels that equal 1 {unit}. The scale bar in the preview updates live.
            </span>
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>UNIT</FieldLabel>
            <select
              value={unit}
              onChange={(e) => setUnit(e.target.value as 'ft' | 'm')}
              style={inputStyle}
            >
              <option value="ft">Feet (ft)</option>
              <option value="m">Meters (m)</option>
            </select>
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>STATION SIZE ({unit})</FieldLabel>
            <input
              type="number"
              min={0.1}
              step={0.5}
              value={stationSizeUnits}
              onChange={(e) => setStationSizeUnits(e.target.value)}
              style={{ ...inputStyle, fontFamily: font.mono }}
            />
            <span style={{ fontSize: 10, color: color.textDim }}>
              Side length of each location square on the map (in {unit}).
              Currently {(parseFloat(stationSizeUnits) * parseFloat(pixelsPerUnit) || 0).toFixed(0)} px.
            </span>
          </label>
        </div>

        <ErrorMsg msg={error} />

        <div style={{ display: 'flex', gap: size.sp2 }}>
          <button onClick={handleSave} disabled={saving || uploading} style={primaryBtn(saving || uploading)}>
            {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save'}
          </button>
          {floorPlanUrl && (
            <button onClick={handleClear} disabled={saving} style={dangerBtn}>
              Clear
            </button>
          )}
        </div>

        {/* Hint when no image yet */}
        {!activeUrl && (
          <div style={{ fontSize: 10, color: color.textDim, lineHeight: 1.5, marginTop: 'auto' }}>
            Upload a floor plan image to see it here as you adjust the scale.
          </div>
        )}

        {/* Export/import above the danger zone: shipping a line to a file is
            everyday work; deleting everything is not. Burying the file section
            underneath the delete button hid it below the fold — found the hard
            way, by its intended user asking where it was. */}
        <MapFileSection onError={setError} />

        {/* ── Clear map data ── */}
        <div style={{
          marginTop: 'auto', paddingTop: size.sp4,
          borderTop: `1px solid ${color.border}`,
        }}>
          <div style={{ fontSize: 10, color: color.textDim, marginBottom: size.sp2 }}>
            DANGER ZONE
          </div>
          <button
            onClick={async () => {
              if (!window.confirm('Delete ALL stations, routes, processes, templates, and cards? This cannot be undone.')) return
              setClearing(true)
              setError(null)
              try {
                await client.post('/admin/reset')
                window.location.reload()
              } catch (e) {
                setError(String(e))
                setClearing(false)
              }
            }}
            disabled={clearing}
            style={{ ...dangerBtn, width: '100%', justifyContent: 'center', opacity: clearing ? 0.6 : 1 }}
          >
            {clearing ? 'Clearing…' : '🗑 Clear Map Data'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── The line as a file ──────────────────────────────────────────────────────

/** Export the whole line definition — stations, processes, routes, products —
 *  as JSON, and import one back, replacing the current line.
 *
 *  The file is data, never instructions: the server re-validates everything
 *  through the same rules the editor uses (strict schema, allow-listed enums,
 *  re-minted ids, cycle/placement/weight checks), so nothing pasted into a
 *  file can execute or reach past this company. Lots, sessions, orders and
 *  the floor-plan image are deliberately not in the file — they are state or
 *  media, not the map. */
function MapFileSection({ onError }: { onError: (e: string | null) => void }) {
  const [busy, setBusy] = useState<'export' | 'import' | null>(null)
  const [summary, setSummary] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const doExport = async () => {
    setBusy('export'); onError(null)
    try {
      const doc = await client.get('/map-io/export')
      const blob = new Blob([JSON.stringify(doc, null, 2)],
                            { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'taktline-map.json'
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) { onError(String((e as Error)?.message ?? e)) }
    finally { setBusy(null) }
  }

  const doImport = async (file: File) => {
    onError(null); setSummary(null)
    let doc: unknown
    try {
      doc = JSON.parse(await file.text())
    } catch {
      onError('That file is not valid JSON.')
      return
    }
    if (!confirm(
      'Import this map?\n\nThis REPLACES the current line: all locations, '
      + 'processes, routes, products and lots. The floor-plan image and '
      + 'statistics history are kept. This cannot be undone.')) return
    setBusy('import')
    try {
      const d = await client.post('/map-io/import', doc) as {
        stations: number; processes: number; templates: number; routes: number }
      setSummary(`Imported: ${d.stations} locations, ${d.processes} processes, `
                 + `${d.templates} products, ${d.routes} routes.`)
      // Everything on screen refers to the old line — reload rather than
      // chase every store.
      setTimeout(() => window.location.reload(), 1200)
    } catch (e) {
      // client unwraps FastAPI's detail into the Error message already.
      onError(String((e as Error)?.message ?? e).slice(0, 500))
    } finally {
      setBusy(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${color.border}` }}>
      <div style={{ fontSize: 11, fontFamily: '"JetBrains Mono", monospace',
                    letterSpacing: '0.08em', color: color.textDim, marginBottom: 6 }}>
        MAP AS A FILE
      </div>
      <p style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.55, margin: '0 0 10px' }}>
        The whole line — locations, processes, routes, products — as a JSON file you can
        back up, share, or edit. Importing <b style={{ color: color.textSecondary }}>replaces
        the current line</b> (lots included); the floor-plan image and history stay. Every
        file is re-validated by the server exactly like edits made here, so a file can
        describe a map and nothing else.
      </p>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={doExport} disabled={busy !== null}
                style={{ ...secondaryBtn, flex: 1, justifyContent: 'center' }}>
          {busy === 'export' ? 'Exporting…' : '⬇ Export JSON'}
        </button>
        <button onClick={() => fileRef.current?.click()} disabled={busy !== null}
                style={{ ...secondaryBtn, flex: 1, justifyContent: 'center' }}>
          {busy === 'import' ? 'Importing…' : '⬆ Import JSON'}
        </button>
        <input ref={fileRef} type="file" accept=".json,application/json"
               style={{ display: 'none' }}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport(f) }} />
      </div>
      {summary && (
        <div style={{ fontSize: 12, color: color.statusRunning, marginTop: 8 }}>
          {summary} Reloading…
        </div>
      )}
    </div>
  )
}

// ─── Floor plan background with live scale bar ───────────────────────────────

function FloorPlanBackground({
  url,
  ppu,
  unit,
  onDimsCapture,
}: {
  url:            string
  ppu:            number
  unit:           'ft' | 'm'
  onDimsCapture?: (w: number, h: number) => void
}) {
  const imgRef = useRef<HTMLImageElement>(null)
  // displayScale = (CSS pixels per raw pixel) for the preview image
  const [displayScale, setDisplayScale] = useState(1)

  const handleLoad = useCallback(() => {
    const img = imgRef.current
    if (!img) return
    // Save raw dimensions so mapWidthPx is screen-independent (= naturalWidth)
    onDimsCapture?.(img.naturalWidth, img.naturalHeight)
    // Compute how the image is actually rendered in the preview container
    // (objectFit:contain — may be letterboxed)
    const ar  = img.naturalWidth / img.naturalHeight
    const acr = img.offsetWidth  / img.offsetHeight
    const renderedW = ar >= acr ? img.offsetWidth : Math.round(img.offsetHeight * ar)
    setDisplayScale(img.naturalWidth > 0 ? renderedW / img.naturalWidth : 1)
  }, [onDimsCapture])

  if (!url) {
    return (
      <div style={{
        flex:           1,
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        opacity:        0.18,
        fontSize:       13,
        color:          color.textDim,
        fontFamily:     font.mono,
        letterSpacing:  '0.06em',
        userSelect:     'none',
      }}>
        NO FLOOR PLAN
      </div>
    )
  }

  return (
    <div style={{
      flex:       1,
      position:   'relative',
      overflow:   'hidden',
      background: '#050C1A',
    }}>
      <img
        ref={imgRef}
        src={url}
        alt="Floor plan"
        style={{
          width:     '100%',
          height:    '100%',
          objectFit: 'contain',
          display:   'block',
        }}
        onLoad={handleLoad}
        onError={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = '0' }}
      />
      {/* Scale bar uses ppu scaled to CSS display pixels so it matches what you see */}
      <LiveScaleBar ppu={ppu * displayScale} unit={unit} />
    </div>
  )
}

// ─── Scale bar ────────────────────────────────────────────────────────────────

function LiveScaleBar({ ppu, unit }: { ppu: number; unit: 'ft' | 'm' }) {
  if (ppu <= 0) return null

  // Pick the largest "nice" count whose bar fits within ~200px
  const niceNumbers = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
  let count = niceNumbers[0]
  for (const n of niceNumbers) {
    if (n * ppu <= 200) count = n
  }
  const barLength = count * ppu
  if (barLength < 4) return null

  const AL = 8
  const AH = 5

  return (
    <div style={{
      position:      'absolute',
      bottom:        16,
      left:          16,
      background:    color.glass,
      border:        `1px solid ${color.glassBorder}`,
      borderRadius:  4,
      padding:       '5px 8px 6px',
      pointerEvents: 'none',
      userSelect:    'none',
    }}>
      <div style={{
        fontSize:      10,
        color:         color.glassText,
        textAlign:     'center',
        marginBottom:  3,
        fontFamily:    '"JetBrains Mono", monospace',
        letterSpacing: '0.05em',
      }}>
        {count} {unit}
      </div>
      <svg
        width={barLength + 2}
        height={AH * 2 + 4}
        style={{ display: 'block', overflow: 'visible' }}
      >
        <g transform={`translate(0,${AH + 2})`} stroke={color.textPrimary} fill={color.textPrimary}>
          <polygon points={`0,0 ${AL},${-AH} ${AL},${AH}`} />
          <line x1={AL} y1={0} x2={barLength - AL} y2={0} strokeWidth={1.5} />
          <polygon points={`${barLength},0 ${barLength - AL},${-AH} ${barLength - AL},${AH}`} />
        </g>
      </svg>
    </div>
  )
}
