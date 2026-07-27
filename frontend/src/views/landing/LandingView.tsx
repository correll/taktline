import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Map, TabletSmartphone, TrendingUp, Boxes, Timer, Printer, GitMerge, GitBranch, WifiOff, Gauge } from 'lucide-react'
import { authApi } from '../../api/auth.api'
import { ACTIVE_COMPANY_KEY } from '../../api/client'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { useAuthStore } from '../../store/auth.store'
import { useThemeStore } from '../../store/theme.store'
import { color, font, size, shadow } from '../../theme/tokens'
import LiveLineDemo from './LiveLineDemo'

/** "Take the five-minute tutorial" — one click into an anonymous sandbox
 *  account (server-restricted: no uploads, invites, API keys, or orders). */
function SandboxButton({ style, children }: { style?: React.CSSProperties; children: React.ReactNode }) {
  const navigate = useNavigate()
  const refresh = useAuthStore((s) => s.refresh)
  const [busy, setBusy] = useState(false)

  const start = async () => {
    setBusy(true)
    try {
      const { companyId } = await authApi.sandbox()
      localStorage.setItem(ACTIVE_COMPANY_KEY, companyId)
      await refresh()
      navigate('/map')
    } catch {
      setBusy(false)
    }
  }

  return (
    <button onClick={start} disabled={busy}
            style={{ ...ghostBtn, cursor: busy ? 'wait' : 'pointer', ...style }}>
      {busy ? 'Preparing your sandbox…' : children}
    </button>
  )
}

// Public landing page (anonymous visitors on "/"). Signed-in users never see
// this — RootGate sends them straight into the app.

export default function LandingView() {
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: color.bgDeep }}>
      <TopNav />
      <main>
        <Hero />
        <Steps />
        <Features />
        <Integrations />
        <FinalCta />
      </main>
      <Footer />
    </div>
  )
}

// ─── Nav ──────────────────────────────────────────────────────────────────────

function TopNav() {
  return (
    <header style={{
      position: 'sticky', top: 0, zIndex: 50,
      background: color.bgPanel, borderBottom: `1px solid ${color.border}`,
      padding: `0 ${size.sp6}`, height: 56, display: 'flex', alignItems: 'center',
    }}>
      <div style={{ ...rowStyle, width: '100%', maxWidth: 1120, margin: '0 auto' }}>
        <TaktlineLogo height={24} color={color.textPrimary} />
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: size.sp3 }}>
          <Link to="/manual" style={{ color: color.textSecondary, textDecoration: 'none', fontSize: 14, padding: '8px 10px' }}>
            Manual
          </Link>
          <Link to="/login" style={ghostBtn}>Sign in</Link>
          <Link to="/signup" style={primaryBtn}>Start free</Link>
        </div>
      </div>
    </header>
  )
}

// ─── Hero ─────────────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section style={{ padding: `clamp(48px, 8vw, 96px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1120, margin: '0 auto', textAlign: 'center' }}>
        <div style={eyebrowStyle}>Digital kanban · MES for small manufacturers</div>
        <h1 style={{
          margin: '0 auto', maxWidth: 720, fontSize: 'clamp(34px, 5.5vw, 58px)',
          lineHeight: 1.06, letterSpacing: '-0.02em', fontWeight: 500, color: color.textPrimary,
        }}>
          Digitize your shop floor <span style={{ color: color.blueBright, whiteSpace: 'nowrap' }}>in minutes.</span>
        </h1>
        <p style={{
          margin: `${size.sp5} auto 0`, maxWidth: 600, fontSize: 17, lineHeight: 1.7,
          color: color.textSecondary,
        }}>
          Taktline models your production as a living graph — locations, routes, and lot
          cards that flow through them, splitting and merging exactly like your material
          does. Takt time and OEE update as work moves. No installs, no consultants.
        </p>
        <div style={{ marginTop: size.sp8, display: 'flex', gap: size.sp3, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Link to="/signup" style={{ ...primaryBtn, fontSize: 16, padding: '12px 28px' }}>
            Start free
          </Link>
          <SandboxButton style={{ fontSize: 16, padding: '12px 24px' }}>
            Take the five-minute tutorial
          </SandboxButton>
        </div>
        <div style={{ marginTop: size.sp4, fontSize: 13, color: color.textDim }}>
          No credit card needed · free forever
        </div>

        {/* Live demo — an e-bike line drawn with the app's own map primitives:
            animated routes, station tiles, and a heatmap that breathes as the
            simulated material piles up at the merge and drains again. */}
        <div style={{
          margin: `${size.sp10} auto 0`, maxWidth: 1000,
          border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
          boxShadow: shadow.lg, overflow: 'hidden', background: color.bgPanel,
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px',
            borderBottom: `1px solid ${color.border}`, background: color.bgPanel,
          }}>
            {[0, 1, 2].map((i) => (
              <span key={i} style={{ width: 10, height: 10, borderRadius: '50%', background: color.border }} />
            ))}
            <span style={{ marginLeft: 'auto', fontSize: 11, fontFamily: font.mono, color: color.textDim }}>
              live demo · an e-bike line, simulated
            </span>
          </div>
          <LiveLineDemo />
        </div>
      </div>
    </section>
  )
}

// ─── Three steps ──────────────────────────────────────────────────────────────

const STEPS = [
  {
    Icon: Map,
    title: 'Map your value stream in minutes',
    body: 'Draw your locations and routes right on the floor plan — the same graph your material actually follows, splits and merges included.',
  },
  {
    Icon: TabletSmartphone,
    title: 'Log in using smartphones or tablets',
    body: 'Every station becomes a dashboard. Workers pick a lot, press start, and timing records itself — no keyboards, no training day.',
  },
  {
    Icon: TrendingUp,
    title: 'Start maximizing your flow',
    body: 'The live heatmap, takt time and OEE per station show the bottleneck while it forms — not in next month’s spreadsheet.',
  },
]

function Steps() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <h2 style={h2Style}>Three moves to a live line</h2>
        <div style={{
          marginTop: size.sp8, display: 'grid', gap: size.sp4,
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        }}>
          {STEPS.map(({ Icon, title, body }, i) => (
            <div key={title} style={cardStyle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3 }}>
                <span style={{
                  fontFamily: font.mono, fontSize: 13, color: color.blueBright,
                  border: `1px solid ${color.borderActive}55`, borderRadius: size.radiusFull,
                  width: 28, height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                }}>{i + 1}</span>
                <Icon size={20} color={color.bluePrimary} strokeWidth={1.8} />
              </div>
              <h3 style={{ margin: `${size.sp4} 0 0`, fontSize: 18, fontWeight: 500, color: color.textPrimary }}>
                {title}
              </h3>
              <p style={{ margin: `${size.sp2} 0 0`, fontSize: 14.5, lineHeight: 1.65, color: color.textSecondary }}>
                {body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Features ─────────────────────────────────────────────────────────────────

const FEATURES = [
  { Icon: Boxes,    title: 'Lot cards, digital and printed', body: 'Kanban cards travel with the material — on the board and as barcode labels off a thermal printer.' },
  { Icon: GitMerge,  title: 'Merges: assemblies done right', body: 'A merge station consumes precursors by your edge weights — one frame + three motors = one e-bike, never “a few extra”.' },
  { Icon: GitBranch, title: 'Splits: one input, many pieces', body: 'A split station multiplies a lot the other way: one steel bar becomes four tubes, and pulling four tubes orders exactly one bar.' },
  { Icon: Timer,    title: 'Timing without timekeeping', body: 'Start/stop at the station drives takt time and OEE per location. No stopwatch, no forms.' },
  { Icon: Gauge,    title: 'The bottleneck, visibly', body: 'A violet heatmap over your floor plan shows where work piles up — status colors stay reserved for status.' },
  { Icon: Printer,  title: 'Print & scan to advance', body: 'Scan a lot label and it moves down the route. A scanner and a phone are all a station needs.' },
  { Icon: WifiOff,  title: 'Survives bad Wi-Fi', body: 'Tablets keep showing the board through outages and resync automatically when the network returns.' },
]

function Features() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <h2 style={h2Style}>Built for the floor, not the back office</h2>
        <div style={{
          marginTop: size.sp8, display: 'grid', gap: size.sp4,
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
        }}>
          {FEATURES.map(({ Icon, title, body }) => (
            <div key={title} style={{ ...cardStyle, display: 'flex', gap: size.sp4 }}>
              <Icon size={22} color={color.bluePrimary} strokeWidth={1.8} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <h3 style={{ margin: 0, fontSize: 15.5, fontWeight: 500, color: color.textPrimary }}>{title}</h3>
                <p style={{ margin: `${size.sp1} 0 0`, fontSize: 14, lineHeight: 1.6, color: color.textSecondary }}>{body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Integrations ─────────────────────────────────────────────────────────────

function Integrations() {
  const mode = useThemeStore((s) => s.mode)
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1120, margin: '0 auto', textAlign: 'center' }}>
        <h2 style={h2Style}>Plays well with your stack</h2>
        <p style={{ margin: `${size.sp3} auto 0`, maxWidth: 620, fontSize: 15.5, lineHeight: 1.7, color: color.textSecondary }}>
          Orders release from your ERP, store, or accounting system; finished lots report back
          and ship. Label printers and barcode scanners close the loop on the floor —
          all through one small API contract.
        </p>
        <img
          src={mode === 'night' ? '/landing/integrations-dark.png' : '/landing/integrations-light.png'}
          alt="Integration map: Odoo, NetSuite, Shopify, WooCommerce, QuickBooks and Xero release orders into Taktline; ShipStation, store fulfilment and ERP completion take finished lots out; label printers and scanners above; Zapier, Make, webhooks, Power BI and Grafana below"
          style={{ display: 'block', width: '100%', maxWidth: 980, margin: `${size.sp8} auto 0`, borderRadius: size.radiusLg }}
        />
        <div style={{ marginTop: size.sp4, fontSize: 12.5, fontFamily: font.mono, color: color.textDim }}>
          Odoo · NetSuite · Shopify · WooCommerce · QuickBooks · Xero · ShipStation · Zapier · Power BI · Grafana
        </div>
      </div>
    </section>
  )
}

// ─── Final CTA + footer ───────────────────────────────────────────────────────

function FinalCta() {
  return (
    <section style={{ padding: `clamp(64px, 10vw, 120px) ${size.sp6}` }}>
      <div style={{
        maxWidth: 760, margin: '0 auto', textAlign: 'center',
        background: color.bgCard, border: `1px solid ${color.borderActive}55`,
        borderRadius: size.radiusLg, padding: `clamp(36px, 6vw, 64px) ${size.sp6}`,
        boxShadow: shadow.md,
      }}>
        <h2 style={{ ...h2Style, fontSize: 'clamp(24px, 3.6vw, 34px)' }}>
          Your line, live before lunch
        </h2>
        <p style={{ margin: `${size.sp3} auto 0`, maxWidth: 480, fontSize: 15.5, lineHeight: 1.7, color: color.textSecondary }}>
          Create an account, take the five-minute tutorial, and watch your first
          lot move across your own floor plan.
        </p>
        <div style={{ marginTop: size.sp6 }}>
          <Link to="/signup" style={{ ...primaryBtn, fontSize: 16, padding: '13px 32px' }}>
            Start free
          </Link>
        </div>
        <div style={{ marginTop: size.sp3, fontSize: 13, color: color.textDim }}>
          No credit card needed — Taktline is free, and stays free
        </div>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer style={{ borderTop: `1px solid ${color.border}`, padding: `${size.sp6}`, background: color.bgPanel }}>
      <div style={{ ...rowStyle, maxWidth: 1120, margin: '0 auto', flexWrap: 'wrap', gap: size.sp4 }}>
        <TaktlineLogo height={18} mark color={color.textSecondary} />
        <span style={{ fontSize: 12.5, color: color.textDim }}>
          © {new Date().getFullYear()} Taktline — digital kanban for real factories
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: size.sp5, fontSize: 13 }}>
          <Link to="/manual" style={{ color: color.textSecondary, textDecoration: 'none' }}>User manual</Link>
          <Link to="/login" style={{ color: color.textSecondary, textDecoration: 'none' }}>Sign in</Link>
          <Link to="/signup" style={{ color: color.blueBright, textDecoration: 'none' }}>Create account</Link>
        </div>
      </div>
    </footer>
  )
}

// ─── Shared styles ────────────────────────────────────────────────────────────

const rowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center' }

const eyebrowStyle: React.CSSProperties = {
  fontFamily: font.mono, fontSize: 12, letterSpacing: '0.22em', textTransform: 'uppercase',
  color: color.blueBright, marginBottom: size.sp5,
}

const h2Style: React.CSSProperties = {
  margin: 0, fontSize: 'clamp(24px, 3.4vw, 32px)', fontWeight: 500,
  letterSpacing: '-0.01em', color: color.textPrimary, textAlign: 'center',
}

const cardStyle: React.CSSProperties = {
  background: color.bgCard, border: `1px solid ${color.border}`,
  borderRadius: size.radiusLg, padding: size.sp6, boxShadow: shadow.sm,
  textAlign: 'left',
}

const primaryBtn: React.CSSProperties = {
  display: 'inline-block', background: color.bluePrimary, color: '#fff',
  borderRadius: size.radiusMd, padding: '9px 20px', fontSize: 14, fontWeight: 600,
  textDecoration: 'none', border: '1px solid transparent',
}

const ghostBtn: React.CSSProperties = {
  display: 'inline-block', background: 'transparent', color: color.textPrimary,
  borderRadius: size.radiusMd, padding: '9px 18px', fontSize: 14, fontWeight: 500,
  textDecoration: 'none', border: `1px solid ${color.border}`,
}
