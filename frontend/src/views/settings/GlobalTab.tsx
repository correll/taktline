import React, { useEffect, useState } from 'react'
import { useGlobalSettingsStore } from '../../store/globalSettings.store'
import { COMMON_TIMEZONES } from '../../api/globalSettings.api'
import { color, font, size } from '../../theme/tokens'
import { FieldLabel, inputStyle, primaryBtn } from './shared'

export default function GlobalTab() {
  const { settings, loading, fetch, update } = useGlobalSettingsStore()
  const [timezone, setTimezone] = useState(settings.timezone)
  const [saved,    setSaved]    = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  useEffect(() => { fetch() }, [])
  useEffect(() => { setTimezone(settings.timezone) }, [settings.timezone])

  const handleSave = async () => {
    setError(null)
    setSaved(false)
    try {
      await update({ timezone })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div style={{ padding: size.sp6, maxWidth: 480 }}>
      <div style={{ marginBottom: size.sp6 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary, marginBottom: 4 }}>
          Global Settings
        </div>
        <div style={{ fontSize: 11, color: color.textDim }}>
          System-wide configuration for all users.
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp5 }}>
        {/* Timezone */}
        <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
          <FieldLabel>TIMEZONE</FieldLabel>
          <select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            disabled={loading}
            style={{ ...inputStyle, fontFamily: font.mono }}
          >
            {COMMON_TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
          <span style={{ fontSize: 10, color: color.textDim, marginTop: 2 }}>
            Used for displaying timestamps and statistics. IANA timezone name.
          </span>
        </label>

        <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3 }}>
          <button
            onClick={handleSave}
            disabled={loading}
            style={primaryBtn(loading)}
          >
            Save
          </button>
          {saved && (
            <span style={{ fontSize: 11, color: color.statusRunning, fontFamily: font.mono }}>
              ✓ Saved
            </span>
          )}
          {error && (
            <span style={{ fontSize: 11, color: color.statusFault }}>{error}</span>
          )}
        </div>
      </div>
    </div>
  )
}
