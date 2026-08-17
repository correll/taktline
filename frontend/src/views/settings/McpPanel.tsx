import React, { useEffect, useState } from 'react'
import { apiKeysApi, type ApiKey } from '../../api/integrations.api'
import { useGlobalSettingsStore } from '../../store/globalSettings.store'
import { color, font, size } from '../../theme/tokens'

const mono: React.CSSProperties = { fontFamily: font.mono, fontSize: 12 }

/** Where an agent should point, spelled out rather than described.
 *
 *  In dev the app is on :3000 and the API behind Vite's `/api` proxy, so the
 *  page's own origin is the wrong answer; in a cross-origin deployment the API
 *  is on another host entirely. Both are exactly what VITE_API_URL already
 *  records, so the URL is derived from it instead of guessed. */
function serverUrl(): string {
  const base = import.meta.env.VITE_API_URL as string | undefined
  if (base === undefined) return `${window.location.origin.replace(/:\d+$/, ':8000')}/mcp`
  if (base === '') return `${window.location.origin}/mcp`
  return `${base.replace(/\/$/, '')}/mcp`
}

function Row({ children }: { children: React.ReactNode }) {
  return <div style={{ display: 'flex', gap: size.sp2, alignItems: 'center' }}>{children}</div>
}

export default function McpPanel() {
  const settings = useGlobalSettingsStore((s) => s.settings)
  const update   = useGlobalSettingsStore((s) => s.update)
  const fetch    = useGlobalSettingsStore((s) => s.fetch)
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr]   = useState('')
  const [copied, setCopied] = useState(false)
  const [copiedCli, setCopiedCli] = useState(false)

  useEffect(() => {
    fetch().catch(() => {})
    apiKeysApi.list().then(setKeys).catch(() => {})
  }, [fetch])

  const on = settings.mcpEnabled
  const url = serverUrl()
  const isLocal = url.startsWith('http://')
  const cliCommand =
    `claude mcp add --transport http taktline ${url} --header "Authorization: Bearer <your key>"`
  // Only a live key with the scope can actually connect, so the panel says
  // whether one exists rather than leaving the admin to switch the toggle on
  // and wonder why nothing happens.
  const agentKeys = keys.filter((k) => !k.revoked && k.scopes.includes('mcp'))
  const canWrite = (scope: string) => agentKeys.some((k) => k.scopes.includes(scope))

  async function toggle() {
    setBusy(true); setErr('')
    try { await update({ mcpEnabled: !on }) } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  return (
    <div>
      <p style={{ color: color.textSecondary, fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
        Lets an AI assistant read your line and answer questions about it — where a lot is,
        which station is the constraint, what the statistics say. It speaks the{' '}
        <b style={{ color: color.textPrimary }}>Model Context Protocol</b>, so it works with
        Claude and any other MCP client.
      </p>

      <label style={{ display: 'flex', gap: size.sp3, alignItems: 'flex-start',
                      cursor: busy ? 'wait' : 'pointer', marginBottom: size.sp4 }}>
        <input
          type="checkbox" checked={on} disabled={busy} onChange={toggle}
          style={{ marginTop: 3, width: 16, height: 16, flexShrink: 0 }}
        />
        <span style={{ fontSize: 13, color: color.textPrimary, lineHeight: 1.55 }}>
          Answer requests from AI agents
          <span style={{ display: 'block', fontSize: 11.5, color: color.textDim, marginTop: 2 }}>
            Off by default. Turning this off again shuts every agent out immediately,
            without having to revoke keys one at a time.
          </span>
        </span>
      </label>

      {err && <div style={{ color: color.statusFault, fontSize: 13, marginBottom: size.sp3 }}>{err}</div>}

      {on && (
        <div style={{ background: color.bgCard, border: `1px solid ${color.border}`,
                      borderRadius: size.radius, padding: size.sp4, marginBottom: size.sp4 }}>
          <div style={{ fontSize: 11, color: color.textDim, textTransform: 'uppercase',
                        letterSpacing: '0.06em', marginBottom: size.sp2 }}>
            Server URL
          </div>
          <Row>
            <code style={{ flex: 1, ...mono, color: color.blueBright, wordBreak: 'break-all' }}>{url}</code>
            <button
              onClick={() => { navigator.clipboard?.writeText(url); setCopied(true) }}
              style={{ background: 'transparent', border: `1px solid ${color.border}`,
                       color: color.textSecondary, borderRadius: size.radius,
                       padding: `${size.sp1} ${size.sp3}`, fontSize: 12, cursor: 'pointer' }}>
              {copied ? 'Copied' : 'Copy'}
            </button>
          </Row>
          <div style={{ fontSize: 11.5, color: color.textDim, marginTop: size.sp3, lineHeight: 1.6 }}>
            Add it to your client as a remote MCP server, authenticating with{' '}
            <span style={mono}>Authorization: Bearer &lt;your key&gt;</span>.
          </div>

          <div style={{ fontSize: 11, color: color.textDim, textTransform: 'uppercase',
                        letterSpacing: '0.06em', margin: `${size.sp4} 0 ${size.sp2}` }}>
            Connecting a client
          </div>
          <p style={{ fontSize: 12.5, color: color.textSecondary, lineHeight: 1.65, margin: 0 }}>
            <b style={{ color: color.textPrimary }}>Claude, and most other clients</b> — paste the
            URL above into the custom-connector dialog and give it your key.
          </p>
          <p style={{ fontSize: 12.5, color: color.textSecondary, lineHeight: 1.65,
                      margin: `${size.sp2} 0 ${size.sp1}` }}>
            <b style={{ color: color.textPrimary }}>Claude Code</b>, from a terminal:
          </p>
          <Row>
            <code style={{ flex: 1, ...mono, color: color.textSecondary, wordBreak: 'break-all' }}>
              {cliCommand}
            </code>
            <button
              onClick={() => { navigator.clipboard?.writeText(cliCommand); setCopiedCli(true) }}
              style={{ background: 'transparent', border: `1px solid ${color.border}`,
                       color: color.textSecondary, borderRadius: size.radius,
                       padding: `${size.sp1} ${size.sp3}`, fontSize: 12, cursor: 'pointer',
                       flexShrink: 0 }}>
              {copiedCli ? 'Copied' : 'Copy'}
            </button>
          </Row>

          {/* Only when it applies. A connector dialog refuses a non-HTTPS URL
              before it sends anything, which reads as "your server is broken"
              — it is not, and the way round it is a one-line bridge. On a
              deployed instance this whole paragraph is untrue, so it is absent
              rather than hedged. */}
          {isLocal && (
            <div style={{ marginTop: size.sp3, padding: size.sp3, borderRadius: size.radius,
                          background: `${color.statusWarning}12`,
                          border: `1px solid ${color.statusWarning}35` }}>
              <div style={{ fontSize: 12, color: color.textPrimary, lineHeight: 1.6 }}>
                This address is <span style={mono}>http://</span>, so the connector dialogs will
                refuse it — they require HTTPS, and the web client also needs a public host it can
                actually reach. Claude Code (above) has no such rule. For the Claude desktop app,
                bridge it as a local command instead:
              </div>
              <code style={{ display: 'block', ...mono, color: color.textSecondary,
                             marginTop: size.sp2, wordBreak: 'break-all' }}>
                npx -y mcp-remote@latest {url} --allow-http --header "Authorization: Bearer &lt;your key&gt;"
              </code>
              <div style={{ fontSize: 11.5, color: color.textDim, marginTop: size.sp2, lineHeight: 1.55 }}>
                Once this instance is deployed behind HTTPS, none of that is needed — the URL
                above works in the dialogs directly.
              </div>
            </div>
          )}
        </div>
      )}

      {on && (
        <div style={{ marginBottom: size.sp4 }}>
          <div style={{ fontSize: 11, color: color.textDim, textTransform: 'uppercase',
                        letterSpacing: '0.06em', marginBottom: size.sp2 }}>
            What an agent may do
          </div>
          <p style={{ color: color.textSecondary, fontSize: 12.5, lineHeight: 1.65, margin: `0 0 ${size.sp3}` }}>
            An agent can only ever do what the key you give it says. A key with just{' '}
            <span style={mono}>mcp</span> can look and not touch. It can never edit stations,
            routes, processes or products, delete a lot, or reach members, billing or other keys —
            those are not offered to it at all.
          </p>
          <ul style={{ margin: 0, paddingLeft: 18, color: color.textSecondary,
                       fontSize: 12.5, lineHeight: 1.9 }}>
            <li>
              <span style={mono}>mcp</span> — read the line, the lots, the orders, the
              statistics, and the line doctor's diagnosis.
              {agentKeys.length === 0 && (
                <span style={{ color: color.statusWarning }}>
                  {' '}No key has this scope yet — create one above to connect anything.
                </span>
              )}
            </li>
            <li style={{ opacity: canWrite('orders') ? 1 : 0.55 }}>
              <span style={mono}>+ orders</span> — release production orders, and cancel them
              (cancelling scraps the lots still in flight).
              {!canWrite('orders') && <span style={{ color: color.textDim }}> Not granted.</span>}
            </li>
            <li style={{ opacity: canWrite('cards:advance') ? 1 : 0.55 }}>
              <span style={mono}>+ cards:advance</span> — move a lot forward along a route
              that already exists.
              {!canWrite('cards:advance') && <span style={{ color: color.textDim }}> Not granted.</span>}
            </li>
          </ul>
          <p style={{ color: color.textDim, fontSize: 11.5, lineHeight: 1.6,
                      margin: `${size.sp3} 0 0` }}>
            Lot tracking links, supplier links and the customer details your ERP sends with an
            order are never included in what an agent reads. Everything an agent changes shows up
            in the same places a person's changes do.
          </p>
        </div>
      )}
    </div>
  )
}
