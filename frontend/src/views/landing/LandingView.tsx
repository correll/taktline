import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Map, TabletSmartphone, TrendingUp, Boxes, GitMerge, GitBranch, Gauge, Receipt } from 'lucide-react'
import { track } from '../../analytics'
import { authApi } from '../../api/auth.api'
import { ACTIVE_COMPANY_KEY } from '../../api/client'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { useAuthStore } from '../../store/auth.store'
import { useThemeStore } from '../../store/theme.store'
import { color, font, size, shadow } from '../../theme/tokens'
import LiveLineDemo from './LiveLineDemo'

/** "Take the five-minute tutorial" — one click into an anonymous sandbox
 *  account (server-restricted: no uploads, invites, API keys, or orders). */
function SandboxButton({ style, where, variant = 'primary', children }: {
  style?: React.CSSProperties; where: string
  variant?: 'primary' | 'ghost'; children: React.ReactNode
}) {
  const navigate = useNavigate()
  const refresh = useAuthStore((s) => s.refresh)
  const [busy, setBusy] = useState(false)

  const start = async () => {
    setBusy(true)
    track('cta_click', { cta: 'sandbox', where })
    try {
      const { companyId } = await authApi.sandbox()
      localStorage.setItem(ACTIVE_COMPANY_KEY, companyId)
      await refresh()
      track('sandbox_start', { where })
      navigate('/map')
    } catch {
      setBusy(false)
    }
  }

  return (
    <button onClick={start} disabled={busy}
            style={{ ...(variant === 'primary' ? primaryBtn : ghostBtn),
                     cursor: busy ? 'wait' : 'pointer', ...style }}>
      {busy ? 'Building your line…' : children}
    </button>
  )
}

/** A tracked link to the signup form. */
function SignupLink({ style, where, children }: {
  style?: React.CSSProperties; where: string; children: React.ReactNode
}) {
  return (
    <Link to="/signup" style={{ ...ghostBtn, ...style }}
          onClick={() => track('cta_click', { cta: 'signup', where })}>
      {children}
    </Link>
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
        <Thesis />
        <Steps />
        <Features />
        <Integrations />
        <Founder />
        <BusinessModel />
        <Questions />
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
      <div className="landing-nav" style={{ ...rowStyle, width: '100%', maxWidth: 1120, margin: '0 auto' }}>
        <TaktlineLogo height={22} color={color.textPrimary} />
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: size.sp2 }}>
          <Link to="/manual" className="nav-secondary"
                style={{ color: color.textSecondary, textDecoration: 'none', fontSize: 14, padding: '8px 10px' }}>
            Manual
          </Link>
          <Link to="/login" style={{ ...ghostBtn, whiteSpace: 'nowrap' }}>Sign in</Link>
          <SandboxButton where="nav" style={{ whiteSpace: 'nowrap' }}>Try it live</SandboxButton>
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
          Your whole shop floor, <span style={{ color: color.blueBright }}>at a glance.</span>
        </h1>
        <p style={{
          margin: `${size.sp5} auto 0`, maxWidth: 620, fontSize: 17, lineHeight: 1.7,
          color: color.textSecondary,
        }}>
          Every lot, every station, live on your own floor plan — so you know what is
          where, what is late, and what a job actually costs. Your material splits and
          merges on the board exactly as it does in the shop. No installs, no consultants.
        </p>
        <p style={{ margin: `${size.sp3} auto 0`, fontSize: 14, color: color.textDim }}>
          Built for job shops, assembly and remanufacturing lines of 5–200 people.
        </p>
        <div style={{ marginTop: size.sp8, display: 'flex', gap: size.sp3, justifyContent: 'center', flexWrap: 'wrap' }}>
          <SandboxButton where="hero" style={{ fontSize: 16, padding: '12px 28px' }}>
            Try a live line — no signup
          </SandboxButton>
          <SignupLink where="hero" style={{ fontSize: 16, padding: '12px 24px' }}>
            Create a free account
          </SignupLink>
        </div>
        <div style={{ marginTop: size.sp4, fontSize: 13, color: color.textDim }}>
          Free forever · no credit card · your data exports any time
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

// ─── The thesis ───────────────────────────────────────────────────────────────
// The one sentence the whole product rests on, given room to land before the
// page starts explaining how it works.

function Thesis() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 104px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 780, margin: '0 auto', textAlign: 'center' }}>
        <TaktlineLogo mark height={20} color={color.bluePrimary} />
        <p style={{
          margin: `${size.sp5} 0 0`, fontSize: 'clamp(22px, 3.2vw, 30px)',
          lineHeight: 1.35, letterSpacing: '-0.01em', fontWeight: 500,
          color: color.textPrimary, textWrap: 'balance',
        }}>
          You can’t optimize a process nobody has measured.
        </p>
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
    body: 'Check the board each morning instead of walking the floor asking. The heatmap, takt time and OEE show where work piles up — and what each job really cost you.',
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
  { Icon: Map,       title: 'The whole floor on one screen',
    body: 'Your real floor plan with every lot on it, updating as work moves. Walk in, glance at the board, and know what is where and what is waiting — before anyone has to ask.' },
  { Icon: Boxes,     title: 'Lot cards without the paperwork',
    body: 'The card lives on the station’s own screen, so in most cases you never print anything. When a physical card does help, barcode labels come off an ordinary thermal printer and a scan moves the lot on.' },
  { Icon: GitMerge,  title: 'Merges: assemblies done right',
    body: 'A merge station consumes precursors by your edge weights — one frame + three motors = one e-bike, never “a few extra”.' },
  { Icon: GitBranch, title: 'Splits: one input, many pieces',
    body: 'Disassembly is the mirror image: a battery teardown yields modules, busbars and cables — each its own product, on its own card. Ask for four cables and Taktline orders one battery, not four.' },
  { Icon: Receipt,   title: 'Know what a job really costs',
    body: 'Every lot carries its own timing, so you quote from what the work actually took — not a guess. Nobody argues you down on price when you have the numbers.' },
  { Icon: Gauge,     title: 'And yes — it finds the bottleneck',
    body: 'A violet heatmap shows where work piles up, with takt time and OEE per station. Usually a one-time revelation; then it just keeps you honest.' },
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

// ─── How we make money ───────────────────────────────────────────────────────

function BusinessModel() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{
        maxWidth: 820, margin: '0 auto', textAlign: 'center',
        border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
        background: color.bgCard, padding: `${size.sp8} ${size.sp6}`,
      }}>
        <h2 style={{ ...h2Style, fontSize: 'clamp(20px, 2.8vw, 26px)' }}>
          Free forever — and here is how we stay in business
        </h2>
        <p style={{ margin: `${size.sp4} auto 0`, maxWidth: 620, fontSize: 15.5, lineHeight: 1.7, color: color.textSecondary }}>
          Running Taktline on your own line costs nothing, with no seat limits and no
          feature held back. We earn our living from the things a factory actually wants
          help with:
        </p>
        <div style={{
          margin: `${size.sp5} auto 0`, display: 'flex', gap: size.sp2,
          flexWrap: 'wrap', justifyContent: 'center',
        }}>
          {['Premium support', 'Hosted instances', 'Hardware integration', 'Robotics'].map((item) => (
            <span key={item} style={{
              fontSize: 13, color: color.textPrimary, background: color.bgPanel,
              border: `1px solid ${color.border}`, borderRadius: size.radiusFull,
              padding: '6px 14px',
            }}>{item}</span>
          ))}
        </div>
        <p style={{ margin: `${size.sp5} auto 0`, maxWidth: 560, fontSize: 13.5, lineHeight: 1.65, color: color.textDim }}>
          Nothing in the free product expires, and your data exports any time — so
          choosing us is never a lock-in.
        </p>
      </div>
    </section>
  )
}

// ─── Who is behind it ────────────────────────────────────────────────────────

function Founder() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 820, margin: '0 auto' }}>
        <h2 style={h2Style}>Who is behind Taktline</h2>
        <div style={{
          marginTop: size.sp8, display: 'flex', gap: size.sp6, alignItems: 'flex-start',
          flexWrap: 'wrap', justifyContent: 'center', textAlign: 'left',
        }}>
          <img
            src="/landing/nikolaus-correll.jpg"
            alt="Nikolaus Correll"
            width={160} height={160}
            style={{
              width: 160, height: 160, borderRadius: size.radiusLg, objectFit: 'cover',
              objectPosition: 'center 22%', border: `1px solid ${color.border}`, flexShrink: 0,
            }}
          />
          <div style={{ flex: '1 1 380px', minWidth: 280 }}>
            <div style={{ fontSize: 17, fontWeight: 500, color: color.textPrimary }}>
              Nikolaus Correll
            </div>
            <p style={{ margin: `${size.sp3} 0 0`, fontSize: 14.5, lineHeight: 1.7, color: color.textSecondary }}>
              Professor of Aerospace and Mechanical Engineering at the University of Notre
              Dame, and Adjoint Professor of Computer Science at the University of Colorado
              Boulder. Author of{' '}
              <a href="https://www.amazon.com/dp/B09B1PPF91/" target="_blank" rel="noopener noreferrer"
                 style={bookLink}
                 onClick={() => track('outbound_click', { to: 'book-seven-deadly-wastes' })}>
                The Seven Deadly Wastes
              </a>{' '}— the lean thinking this product is built on — and{' '}
              <a href="https://www.amazon.com/Introduction-Autonomous-Robots-Mechanisms-Algorithms/dp/0262047551"
                 target="_blank" rel="noopener noreferrer" style={bookLink}
                 onClick={() => track('outbound_click', { to: 'book-autonomous-robots' })}>
                Introduction to Autonomous Robots
              </a>{' '}(MIT Press).
            </p>
            <p style={{ margin: `${size.sp3} 0 0`, fontSize: 14.5, lineHeight: 1.7, color: color.textSecondary }}>
              He works on automation, and Taktline comes out of a simple observation: you
              can’t automate a process nobody has measured. At Robotic Materials Inc
              (2016–2022), he and a small team built Optio, a digital value-stream-mapping
              system for high-mix, low-volume (re)manufacturers. Taktline is a fresh start
              on the same idea, rebuilt from scratch.
            </p>
            <p style={{ margin: `${size.sp3} 0 0`, fontSize: 13, lineHeight: 1.6, color: color.textDim }}>
              His research has been funded by NSF, NIST, NASA, ARPA-E, ARO, AFOSR and DARPA.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── Questions a plant manager actually asks ─────────────────────────────────

const FAQ: { q: string; a: React.ReactNode }[] = [
  { q: 'How long until it is running?',
    a: <>Minutes. Draw your locations and routes on the map and the board is live —
        there is nothing to print or install. The five-minute tutorial builds a line end
        to end so you can see the shape of it before touching your own.</> },
  { q: 'Is my data mine?',
    a: <>Yes. Everything exports at any time, and Taktline is free to run on your own
        server — so nothing is held hostage by a subscription.</> },
  { q: 'What happens when the Wi-Fi drops?',
    a: <>Tablets keep showing the board from a local snapshot and reconnect on their
        own, with an amber banner naming how old the data is. Changes are never queued
        silently — they fail loudly rather than reordering your lot movements later.</> },
  { q: 'Do I need scanners or special hardware?',
    a: <>No. A phone or tablet browser is enough, and you don’t even have to print lot
        cards in most cases — the card is already at the station on screen. If a printed
        card does earn its keep, labels come off ordinary Zebra or Brother thermal
        printers and a scanner can advance a lot without anyone logging in.</> },
  { q: 'Can it talk to my ERP or shop system?',
    a: <>Odoo, NetSuite, Shopify, WooCommerce, QuickBooks, Xero and ShipStation have
        ready-made connectors; anything else goes through one small order API, a CSV
        import, or Zapier and Make.</> },
  { q: 'What does it cost?',
    a: <>The product is free forever, with no seat limits. We charge only for premium
        support, hosted instances, hardware integration and robotics work.</> },
]

function Questions() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 820, margin: '0 auto' }}>
        <h2 style={h2Style}>Questions worth asking</h2>
        <div className="landing-faq" style={{ marginTop: size.sp8, display: 'grid', gap: size.sp3 }}>
          {FAQ.map(({ q, a }) => (
            <details key={q} style={{
              background: color.bgCard, border: `1px solid ${color.border}`,
              borderRadius: size.radiusMd, padding: `${size.sp4} ${size.sp5}`,
            }}>
              <summary style={{
                cursor: 'pointer', fontSize: 15, fontWeight: 500, color: color.textPrimary,
                listStyle: 'none',
              }}>
                {q}
              </summary>
              <p style={{ margin: `${size.sp3} 0 0`, fontSize: 14, lineHeight: 1.7, color: color.textSecondary }}>
                {a}
              </p>
            </details>
          ))}
        </div>
        <p style={{ marginTop: size.sp5, fontSize: 13.5, color: color.textDim, textAlign: 'center' }}>
          Still deciding? The <Link to="/manual" style={{ color: color.blueBright }}>full user manual</Link> is
          public — philosophy, lean method and every screen, no sign-in.
        </p>
      </div>
    </section>
  )
}

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
        <div style={{ marginTop: size.sp6, display: 'flex', gap: size.sp3, justifyContent: 'center', flexWrap: 'wrap' }}>
          <SandboxButton where="footer" style={{ fontSize: 16, padding: '13px 32px' }}>
            Try a live line — no signup
          </SandboxButton>
          <SignupLink where="footer" style={{ fontSize: 16, padding: '13px 26px' }}>
            Create a free account
          </SignupLink>
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
          <Link to="/signup" style={{ color: color.blueBright, textDecoration: 'none' }}
                onClick={() => track('cta_click', { cta: 'signup', where: 'footer-nav' })}>Create account</Link>
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

const bookLink: React.CSSProperties = {
  color: color.blueBright, textDecoration: 'underline',
  textUnderlineOffset: 2, textDecorationThickness: 1,
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
