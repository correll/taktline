import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Map, TabletSmartphone, TrendingUp, Boxes, GitMerge, GitBranch, Gauge, Receipt } from 'lucide-react'
import { track } from '../../analytics'
import { authApi } from '../../api/auth.api'
import { ACTIVE_COMPANY_KEY } from '../../api/client'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { ContactForm } from './ContactForm'
import { featuredTips } from '../../help/leanTips'
import { LANGUAGES, LANGUAGE_CODES } from '../../i18n/languages'
import { LEGAL_ENTITY } from '../../legal/terms'
import { useAuthStore } from '../../store/auth.store'
import { useThemeStore } from '../../store/theme.store'
import { color, font, size, shadow } from '../../theme/tokens'
import LiveLineDemo from './LiveLineDemo'
import DeviceSyncDemo from './DeviceSyncDemo'
import KanbanDemo from './KanbanDemo'
import DoctorDemo from './DoctorDemo'

/** "Take the five-minute tutorial" — one click into an anonymous sandbox
 *  account (server-restricted: no uploads, invites, API keys, or orders). */
function SandboxButton({ style, where, variant = 'primary', children }: {
  style?: React.CSSProperties; where: string
  variant?: 'primary' | 'ghost'; children: React.ReactNode
}) {
  const navigate = useNavigate()
  const refresh = useAuthStore((s) => s.refresh)
  const resuming = useAuthStore((s) => s.user?.isSandbox === true)
  const [busy, setBusy] = useState(false)

  const start = async () => {
    setBusy(true)
    track('cta_click', { cta: 'sandbox', where, resumed: resuming })
    try {
      // The endpoint is idempotent: an existing sandbox comes back as-is, so a
      // visitor never loses the line they built by clicking twice.
      const { companyId } = await authApi.sandbox()
      localStorage.setItem(ACTIVE_COMPANY_KEY, companyId)
      await refresh()
      track(resuming ? 'sandbox_resume' : 'sandbox_start', { where })
      navigate('/map')
    } catch {
      setBusy(false)
    }
  }

  return (
    <button onClick={start} disabled={busy}
            style={{ ...(variant === 'primary' ? primaryBtn : ghostBtn),
                     cursor: busy ? 'wait' : 'pointer', ...style }}>
      {busy ? (resuming ? 'Opening your line…' : 'Building your line…')
            : resuming ? 'Back to my line' : children}
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

/** On a phone, the landing page is not the product — the sign-in button is.
 *  A worker opening taktline.com on an iPhone is almost never a prospect
 *  reading marketing; they are trying to reach their line. So a narrow
 *  viewport gets a native-feeling gate: one full-width Sign in, and a small
 *  way out to the full site for the visitor who really is browsing.
 *  Session-scoped, so choosing the desktop version sticks for the visit and
 *  resets on the next one. */
// Captured at module load: Chrome fires `beforeinstallprompt` once, early —
// waiting until a component mounts to listen is how the event gets missed.
let _installPrompt: any = null
if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    _installPrompt = e
  })
}

/** The install path, per platform. Chrome hands us a real prompt; iOS Safari
 *  has no API, so the honest thing is the two-tap instruction. Neither shows
 *  once the app already runs standalone — the hint would be pointing at
 *  itself. */
function AddToHomeScreen() {
  const [ios] = useState(() => /iPhone|iPad|iPod/.test(navigator.userAgent))
  const [showHow, setShowHow] = useState(false)
  const standalone = window.matchMedia('(display-mode: standalone)').matches
    || (navigator as any).standalone
  if (standalone) return null

  const install = async () => {
    if (_installPrompt) {
      track('cta_click', { cta: 'a2hs', where: 'mobile-gate' })
      _installPrompt.prompt()
      _installPrompt = null
    } else {
      setShowHow(true)
    }
  }

  if (showHow && ios) {
    return (
      <div style={{ fontSize: 13, color: color.textSecondary, textAlign: 'center',
                    lineHeight: 1.6, maxWidth: 300 }}>
        Tap <b style={{ color: color.textPrimary }}>Share</b>
        <span aria-hidden="true"> ⎙</span> in Safari&rsquo;s toolbar, then{' '}
        <b style={{ color: color.textPrimary }}>Add to Home Screen</b>.
        Taktline opens full-screen, like an app.
      </div>
    )
  }
  return (
    <button onClick={install} style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: 'transparent', border: `1px solid ${color.border}`,
      color: color.textSecondary, borderRadius: size.radiusMd,
      padding: '10px 18px', fontSize: 14, cursor: 'pointer',
    }}>
      <span aria-hidden="true" style={{ fontSize: 16 }}>＋</span>
      Add to Home Screen
    </button>
  )
}

function MobileGate({ onDesktop }: { onDesktop: () => void }) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', gap: size.sp6, background: color.bgDeep,
      padding: `calc(${size.sp6} + env(safe-area-inset-top, 0px)) ${size.sp5}
                calc(${size.sp6} + env(safe-area-inset-bottom, 0px))`,
      minHeight: '100dvh',
    }}>
      <TaktlineLogo height={34} color={color.textPrimary} />
      <div style={{ fontSize: 14.5, color: color.textSecondary, textAlign: 'center',
                    maxWidth: 300, lineHeight: 1.5 }}>
        Your whole shop floor, at a glance.
      </div>
      <Link to="/login"
            onClick={() => track('cta_click', { cta: 'login', where: 'mobile-gate' })}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: '100%', maxWidth: 420, padding: '18px 24px',
              background: color.bluePrimary, color: '#fff',
              borderRadius: size.radiusMd, textDecoration: 'none',
              fontSize: 17, fontWeight: 600,
            }}>
        Sign in
      </Link>
      <AddToHomeScreen />
      <button onClick={onDesktop} style={{
        background: 'none', border: 'none', color: color.textDim,
        fontSize: 13, cursor: 'pointer', textDecoration: 'underline',
        padding: size.sp2,
      }}>
        Go to the desktop version
      </button>
    </div>
  )
}

const DESKTOP_KEY = 'taktline.landing-desktop'

export default function LandingView() {
  const [wantDesktop, setWantDesktop] = useState(
    () => sessionStorage.getItem(DESKTOP_KEY) === '1')
  const [narrow, setNarrow] = useState(
    () => window.matchMedia('(max-width: 640px)').matches)
  React.useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)')
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  if (narrow && !wantDesktop) {
    return <MobileGate onDesktop={() => {
      sessionStorage.setItem(DESKTOP_KEY, '1')
      setWantDesktop(true)
    }} />
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: color.bgDeep }}>
      <TopNav />
      <main>
        <Hero />
        <Thesis />
        <Outcomes />
        <TheBoard />
        <Steps />
        <OnEveryDevice />
        <FloorLanguages />
        <TheDoctor />
        <Features />
        <Integrations />
        <Founder />
        <WhyTrustUs />
        <FromTheBook />
        <Pricing />
        <Questions />
        <FinalCta />
      </main>
      <ContactForm />
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
          <a href="#pricing" className="nav-secondary"
             style={{ color: color.textSecondary, textDecoration: 'none', fontSize: 14, padding: '8px 10px' }}>
            Pricing
          </a>
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
        {/* Credibility at the top, where the doubt is. The founder section three
            screens down is the strongest trust signal on the page and a cold
            visitor was meeting it far too late to help. */}
        <p style={{ margin: `${size.sp2} auto 0`, fontSize: 13.5, color: color.textDim }}>
          By the author of{' '}
          <a href="https://www.amazon.com/dp/B09B1PPF91/" target="_blank" rel="noopener noreferrer"
             style={{ color: color.textSecondary, textDecoration: 'underline',
                      textDecorationColor: color.border, textUnderlineOffset: 3 }}
             onClick={() => track('outbound_click', { to: 'book-seven-deadly-wastes', where: 'hero' })}>
            The Seven Deadly Wastes
          </a>
          {' '}— the lean method this is built on.
        </p>
        <div style={{ marginTop: size.sp8, display: 'flex', gap: size.sp3, justifyContent: 'center', flexWrap: 'wrap' }}>
          <SandboxButton where="hero" style={{ fontSize: 16, padding: '12px 28px' }}>
            Try a live line — no signup
          </SandboxButton>
          <SignupLink where="hero" style={{ fontSize: 16, padding: '12px 24px' }}>
            Start free
          </SignupLink>
        </div>
        <div style={{ marginTop: size.sp4, fontSize: 13, color: color.textDim }}>
          Free up to 7 stations · no card · no expiry
        </div>
        <div style={{ marginTop: size.sp3, fontSize: 13, color: color.textSecondary }}>
          Runs in the browser on <strong style={{ color: color.textPrimary }}>iPhone, iPad and
          Android</strong> as well as the desktop — nothing to install, no app store.
        </div>

        {/* Live demo — three lines from three trades, rotating, drawn with the
            app's own map primitives: animated routes in each value stream's
            colour, station tiles pulsing at their own beat, weight badges, and
            a heatmap that breathes as material banks up and drains. A battery
            teardown, a lay of fleece and a mitred window frame are the same
            graph, which is the argument the page is making and the reason
            there are three rather than one. */}
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
              live demo · three real lines, simulated
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
//
// Two beats, and the order is the argument: measure, then optimise, then
// automate. Automation goes last because it is the destination — and because
// putting it first is the expensive mistake this product exists to prevent.
// Automating an unmeasured process buys you a robot doing the wrong thing
// faster; the shop that maps its flow first knows what the robot should
// actually do before it signs the order. The same claim is one of the lean tips
// ("Lean first, then automate"), which is where it came from.

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
          You can’t optimize a process nobody has measured — and you can’t
          automate one nobody has optimized.
        </p>
      </div>
    </section>
  )
}

// ─── What you actually get ───────────────────────────────────────────────────
// Placed straight after the thesis, because outcomes are what a buyer shops
// for and everything below this is mechanism. The page could previously say
// how fast it is to set up and nothing at all about what changes afterwards.
// Each of these is a pain someone feels weekly, and each names the part of the
// product that delivers it — a benefit nobody can trace back to a feature
// reads as a slogan.

const OUTCOMES = [
  {
    Icon: Boxes,
    title: 'Never search for a lot again',
    body: `“Where is job 4471?” costs somebody a walk of the floor, two interruptions and a
           guess — several times a day, usually the people whose time is worth most. Every lot
           is on the board and on the floor plan, live, with the history of everywhere it has
           been. This one needs no data and no setup: it is true the hour you draw your line.`,
  },
  {
    Icon: TrendingUp,
    title: 'Continuous improvement starts immediately',
    body: `Lean normally begins with a value-stream map, which means a study, which means weeks
           and often a consultant. Here the map is the thing you already drew, and it is live
           from the first lot that moves. Map your line exactly as it runs today — change
           nothing — and the bottleneck shows itself within a week, usually somewhere nobody
           expected.`,
  },
  {
    Icon: Gauge,
    title: 'Workers who understand the line they are in',
    body: `Most shop-floor software points downward: it measures people for somebody else to
           read. Here the operator sees the whole flow — what feeds their bench, what waits on
           it, and where the constraint actually is. The line doctor is readable by every
           member on purpose. People who can see the system improve it; people who are only
           measured by it learn to manage the measurement.`,
  },
]

function Outcomes() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 104px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={eyebrowStyle}>What changes</div>
          <h2 style={h2Style}>Three things that are true by the end of the first week</h2>
        </div>
        <div style={{
          display: 'grid', gap: size.sp5, marginTop: size.sp8,
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        }}>
          {OUTCOMES.map(({ Icon, title, body }) => (
            <div key={title} style={cardStyle}>
              <Icon size={20} color={color.blueBright} strokeWidth={1.6} />
              <div style={{ marginTop: size.sp3, fontSize: 16, fontWeight: 500, color: color.textPrimary }}>
                {title}
              </div>
              <p style={{ margin: `${size.sp2} 0 0`, fontSize: 14, lineHeight: 1.65, color: color.textSecondary }}>
                {body}
              </p>
            </div>
          ))}
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
    body: 'Draw your stations and routes right on the floor plan — the same graph your material actually follows, splits and merges included.',
  },
  {
    Icon: TabletSmartphone,
    title: 'Log in using smartphones or tablets',
    body: 'Every station becomes a dashboard. Workers pick a lot, press start, and timing records itself — no keyboards, no training day.',
  },
  {
    Icon: TrendingUp,
    title: 'Start maximizing your flow',
    body: 'Check the board each morning instead of walking the floor asking. The heatmap, cycle time and OEE show where work piles up — and what each job really cost you.',
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

/**
 * A CTA to close a section with.
 *
 * The page ran nine screens between the hero's buttons and the footer's — the
 * whole persuasive middle, with no way to act inside it. People convert at the
 * moment they are convinced, not at the moment they reach the bottom, and a
 * button in the sticky nav is the one thing every visitor has trained
 * themselves not to see.
 *
 * Deliberately lighter than the hero: one line, one primary button, a text
 * link beside it. Repeating the full hero block three times reads as nagging
 * and stops being read at all.
 */
function InlineCta({ line, where }: { line: string; where: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      gap: size.sp4, flexWrap: 'wrap', textAlign: 'center',
      marginTop: size.sp8, paddingTop: size.sp6,
      borderTop: `1px solid ${color.border}`,
    }}>
      <span style={{ fontSize: 15, color: color.textSecondary }}>{line}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3, flexWrap: 'wrap' }}>
        <SandboxButton where={where}>Try a live line — no signup</SandboxButton>
        <SignupLink where={where} style={{ border: 'none', padding: '8px 4px' }}>
          or start free
        </SignupLink>
      </div>
    </div>
  )
}

// ─── The line doctor ─────────────────────────────────────────────────────────
// The findings shown are verbatim what the engine produces for a line of that
// shape. A page that paraphrases its own product's output promises something
// warmer and vaguer than what arrives, and the first real report reads as a
// let-down.

function TheDoctor() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={eyebrowStyle}>The line doctor</div>
          <h2 style={h2Style}>It reads your line and tells you what is wrong</h2>
          <p style={{
            margin: `${size.sp4} auto 0`, maxWidth: 660, fontSize: 16,
            lineHeight: 1.7, color: color.textSecondary,
          }}>
            Click the bulb and Taktline reports the constraint, where work piles up, how much of
            your lead time is actually work, and what to do first — in the language of lean, with
            the arithmetic shown. It works from the shape of your graph before anyone has run a
            timer, and lights up once there is enough data to talk about pace.
          </p>
        </div>

        <div style={{ marginTop: size.sp8 }}>
          <DoctorDemo />
        </div>

        <InlineCta where="doctor" line="Point it at your line and see what it finds." />

        <div style={{
          display: 'grid', gap: size.sp4, marginTop: size.sp8,
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        }}>
          {[
            ['Nothing leaves your building',
             'It is a rule engine on your own server — Little’s law, Kingman, Goldratt, Shewhart — not a chatbot. No production data is sent to anyone, because none needs to be.'],
            ['It says when it cannot see',
             '“Nobody has run a timer yet” is an answer it gives. A report that invents advice from three sessions is worse than one that admits it cannot see.'],
            ['Useful on day one',
             'A line that can never complete an order, a split feeding six pieces into a bench that takes one, a station every order must cross — all visible from the graph alone, before any work is recorded.'],
          ].map(([title, body]) => (
            <div key={title} style={cardStyle}>
              <div style={{ fontSize: 15, fontWeight: 500, color: color.textPrimary }}>{title}</div>
              <p style={{ margin: `${size.sp2} 0 0`, fontSize: 14, lineHeight: 1.65, color: color.textSecondary }}>
                {body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── The board ───────────────────────────────────────────────────────────────
// Every task board moves a card one column right, so showing that proves
// nothing. What a manufacturing board does that a task board cannot is carry
// material: cards hold counts, several are consumed to make one, one becomes
// several. So the loop is a teardown and a merge, not a drag.

function TheBoard() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1000, margin: '0 auto' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={eyebrowStyle}>The lots board</div>
          <h2 style={h2Style}>A card is attached to real material</h2>
          <p style={{
            margin: `${size.sp4} auto 0`, maxWidth: 640, fontSize: 16,
            lineHeight: 1.7, color: color.textSecondary,
          }}>
            One column per station, every lot where it actually is. The difference
            from a task board is that a card is tied to material and follows a
            recipe: tearing a pack down retires its card and puts a new one on each
            branch — modules on one, busbars on another — and assembling the pack
            consumes those cards again.
          </p>
        </div>
        <div style={{ marginTop: size.sp8 }}>
          <KanbanDemo />
        </div>

        <InlineCta where="board" line="Your own board, with your own stations, in five minutes." />
      </div>
    </section>
  )
}

// ─── On every device ─────────────────────────────────────────────────────────
// The page had one feature card saying "smartphones or tablets", which is a
// sentence every SaaS site has. What a shop floor wants to know is whether the
// phone in their hand is a real terminal or a read-only viewer, so this shows
// a lot being advanced by thumb and every other screen following.

function OnEveryDevice() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={eyebrowStyle}>On the floor</div>
          <h2 style={h2Style}>The whole graph, in a back pocket</h2>
          <p style={{
            margin: `${size.sp4} auto 0`, maxWidth: 640, fontSize: 16,
            lineHeight: 1.7, color: color.textSecondary,
          }}>
            Every station is a web address, so an iPhone is a full terminal — not a
            viewer. Start and stop work, merge precursors, scan a lot label, advance
            it down the line. Hold a phone upright and it becomes the operator
            dashboard by itself; the floor plan and the board are the same app on the
            tablet at the cell and the screen in the office.
          </p>
        </div>

        <div style={{ marginTop: size.sp10 }}>
          <DeviceSyncDemo />
        </div>

        <div style={{
          display: 'grid', gap: size.sp4, marginTop: size.sp10,
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        }}>
          {[
            ['No app store', 'A browser is the whole install. Add it to the home screen and it opens full-screen like a native app, because it is a progressive web app.'],
            ['Bring any device', 'iPhone, iPad, Android, an old laptop, the shop PC. Nothing has to match, and a device that dies is replaced by whatever is to hand.'],
            ['Keeps working offline', 'A phone that loses the wifi keeps showing the board from its own snapshot and reconnects on its own. Nothing is silently queued — changes fail loudly rather than replaying out of order.'],
          ].map(([title, body]) => (
            <div key={title} style={cardStyle}>
              <div style={{ fontSize: 15, fontWeight: 500, color: color.textPrimary }}>{title}</div>
              <p style={{ margin: `${size.sp2} 0 0`, fontSize: 14, lineHeight: 1.65, color: color.textSecondary }}>
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
    body: 'A violet heatmap shows where work piles up, with cycle time and OEE per station. Usually a one-time revelation; then it just keeps you honest.' },
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

// ─── Languages ────────────────────────────────────────────────────────────────

/** The names come from the i18n catalogue itself, so this section can never
 *  advertise a language the picker does not offer — i18n.test.ts already pins
 *  that catalogue to the backend's allowlist. */
function FloorLanguages() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 820, margin: '0 auto', textAlign: 'center' }}>
        <div style={eyebrowStyle}>In their language</div>
        <h2 style={h2Style}>The floor doesn’t work in English only</h2>
        <p style={{
          margin: `${size.sp4} auto 0`, maxWidth: 640, fontSize: 16,
          lineHeight: 1.7, color: color.textSecondary,
        }}>
          The operator’s screen — start, done, move — speaks the language the person
          holding the tablet thinks in. Everyone picks their own language when they
          join and can change it any time; you choose which languages your company
          runs in, so nobody is handed a screen their supervisor can’t read over
          their shoulder.
        </p>
        <div style={{
          margin: `${size.sp6} auto 0`, display: 'flex', gap: size.sp2,
          flexWrap: 'wrap', justifyContent: 'center',
        }}>
          {LANGUAGE_CODES.map((code) => (
            <span key={code} style={{
              fontSize: 14, color: color.textPrimary, background: color.bgCard,
              border: `1px solid ${color.border}`, borderRadius: size.radiusFull,
              padding: '7px 16px',
            }}>
              {LANGUAGES[code]}
            </span>
          ))}
        </div>
        <p style={{ margin: `${size.sp4} auto 0`, fontSize: 13, color: color.textDim }}>
          A worker who can read the system improves it — in any of these.
        </p>
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

/** The price list, on the page.
 *
 *  One number, a floor, and a ceiling — see pricing.md for the argument. The
 *  ceiling is the best line on the page ("you will never pay more than $399"),
 *  and linear pricing exists so nobody models 10 stations instead of their
 *  actual 14 to duck a band; everything the product computes rests on the
 *  graph being a faithful map of the floor.
 *
 *  Prices are duplicated here rather than fetched: this section renders for
 *  signed-out visitors and for crawlers, and a pricing table that arrives after
 *  a round trip is a pricing table search engines never see. `test_billing.py`
 *  pins the same numbers on the server.
 */
const TIERS = [
  {
    name: 'Free', price: '$0', per: 'up to 7 stations',
    line: 'A real line, not a demo. No card, no expiry — and never deleted.',
    points: ['The live board and floor plan', 'Cycle time, line cycle time and OEE',
             'The line doctor', 'Unlimited operators',
             'Come back in six months and it is still here'],
  },
  {
    name: 'Taktline', price: '$2', per: 'per station /month', featured: true,
    line: 'Unlimited stations. Never less than $29, never more than $399 — however big you get.',
    points: ['Every ERP and shop connector included: Odoo, NetSuite, Shopify, QuickBooks, ShipStation and more',
             'Unlimited operators — we price the line, not the people',
             'Scan-to-advance, label printing, reporting API',
             '50 stations = $100 · 100 = $200 · 200+ = $399, capped'],
  },
]

const ADD_ONS = [
  ['On-premise', '+$199/month',
   'On your own hardware, at any size. Your database, your network, your backups.'],
  ['New connector build', '$750 once',
   'An ERP or store we have not written yet. Once built it enters the catalogue — free for everyone, including you.'],
  ['Taktline Box', '$2,900 once',
   'A pre-configured fanless PC that plugs into your network and runs the server. Includes the first year.'],
]

function Pricing() {
  return (
    <section id="pricing" style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1060, margin: '0 auto' }}>
        <h2 style={{ ...h2Style, textAlign: 'center' }}>
          One price for the whole floor
        </h2>
        <p style={{
          margin: `${size.sp4} auto 0`, maxWidth: 620, textAlign: 'center',
          fontSize: 15.5, lineHeight: 1.7, color: color.textSecondary,
        }}>
          Priced per line, not per person. Per-seat pricing pushes a shop to buy
          screens for supervisors only, and a system the operators can&apos;t see stops
          being a tool and becomes surveillance. Every operator and every tablet is
          included, always. $2 a station, and you will never pay more than $399 a month.
        </p>

        <div style={{
          margin: `${size.sp8} 0 0`, display: 'grid', gap: size.sp4,
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        }}>
          {TIERS.map((t) => (
            <div key={t.name} style={{
              border: `1px solid ${t.featured ? color.bluePrimary : color.border}`,
              borderRadius: size.radiusLg, background: color.bgCard,
              padding: size.sp6, display: 'flex', flexDirection: 'column',
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: t.featured ? color.blueBright : color.textDim,
                            textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                {t.name}
              </div>
              <div style={{ margin: `${size.sp3} 0 0`, display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <span style={{ fontSize: 38, fontWeight: 600, color: color.textPrimary }}>{t.price}</span>
                <span style={{ fontSize: 15, color: color.textDim }}>{t.per}</span>
              </div>
              <p style={{ margin: `${size.sp3} 0 0`, fontSize: 14, lineHeight: 1.6, color: color.textSecondary }}>
                {t.line}
              </p>
              <ul style={{ margin: `${size.sp4} 0 0`, padding: 0, listStyle: 'none',
                           display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
                {t.points.map((pt) => (
                  <li key={pt} style={{ fontSize: 13.5, lineHeight: 1.5, color: color.textSecondary,
                                        display: 'flex', gap: size.sp2 }}>
                    <span aria-hidden="true" style={{ color: color.blueBright }}>·</span>
                    {pt}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div style={{
          margin: `${size.sp6} 0 0`, display: 'grid', gap: size.sp3,
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        }}>
          {ADD_ONS.map(([name, price, line]) => (
            <div key={name} style={{
              border: `1px dashed ${color.border}`, borderRadius: size.radiusMd,
              padding: size.sp4,
            }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp2,
                            flexWrap: 'wrap' }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary }}>
                  {name}
                </span>
                <span style={{ fontSize: 13, color: color.blueBright }}>{price}</span>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: 12.5, lineHeight: 1.55,
                          color: color.textDim }}>
                {line}
              </p>
            </div>
          ))}
        </div>

        {/* Why the number is a fraction of the category, said out loud. A
            cautious buyer reads "implausibly cheap" as "will they exist in
            three years?", and the honest answer is a different cost structure
            rather than a thinner product — which is also the same argument the
            product makes about factories, applied to us. */}
        <p style={{
          margin: `${size.sp8} auto 0`, maxWidth: 640, textAlign: 'center',
          fontSize: 15, lineHeight: 1.7, color: color.textSecondary,
        }}>
          We run lean ourselves: no sales team, no ad spend, no funnel. You found
          this through the manual, the book, or somebody who uses it — so what you
          pay for is the product, not the cost of being sold to.
        </p>

        <p style={{
          margin: `${size.sp5} auto 0`, maxWidth: 700, textAlign: 'center',
          fontSize: 13.5, lineHeight: 1.7, color: color.textDim,
        }}>
          The price follows your floor by itself: draw a station, pay $2 more next month;
          remove one, pay $2 less. Nothing to renegotiate, no band to fall out of.
          Everything exports at any time in a format you can read, and if you ever stop,
          your line is here waiting if you change your mind.
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
              can’t automate a process nobody has measured — an observation earned across
              a decade of building automation for high-mix, low-volume (re)manufacturers.
              Taktline is a fresh start on that idea, written from scratch — and now
              carrying the part that was always the point: <strong style={{ color: color.textPrimary }}>AI and advanced analytics on the
              shop floor</strong>, reading
              a line the way an experienced engineer would and saying what is wrong with it
              in plain language.
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

// ─── We are new ──────────────────────────────────────────────────────────────
// There is no logo wall, and pretending otherwise would be the one thing this
// audience punishes hardest. A manufacturing buyer asks "who else runs this?"
// early, and silence answers it worse than the truth does. So the objection is
// stated first, in the heading, and then answered with the four things that
// actually make a new tool a low-risk bet — every one of them already true and
// checkable, not a promise.

function WhyTrustUs() {
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 900, margin: '0 auto' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={eyebrowStyle}>The honest bit</div>
          <h2 style={h2Style}>Taktline is new — so we made it cheap to find out</h2>
          <p style={{
            margin: `${size.sp4} auto 0`, maxWidth: 640, fontSize: 16,
            lineHeight: 1.7, color: color.textSecondary,
          }}>
            There is no wall of customer logos on this page, because it would be a wall of
            logos we have not earned yet. What we can tell you is why trying it is a small
            decision, and why the thinking behind it is not new at all.
          </p>
        </div>

        <div style={{
          display: 'grid', gap: size.sp4, marginTop: size.sp8,
          // Two across, so four cards square off rather than falling 3 + 1 and
          // leaving an orphan beside a gap.
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        }}>
          {[
            ['Little to lose',
             'Free for seven stations with no card and no expiry, then $2 a station a month. Every operator and every tablet is included — there is no seat count, no budget to defend and no procurement to survive.'],
            ['Nothing to install',
             'It runs in a browser on the phones and tablets you already own. No server, no IT project, no shop-floor hardware to buy before you know whether it helps.'],
            ['Nothing to lock you in',
             'Your whole line exports as a file and your history as a spreadsheet, any time, in one click. If you leave, you leave with everything — which is the only promise that makes “try it” safe.'],
            ['The method is a century old',
             'Lean is not our invention: takt time, pull, the seven wastes and the theory of constraints all predate us by decades. Taktline is a faithful implementation of a well-proven method, not a new theory of manufacturing.'],
          ].map(([title, body]) => (
            <div key={title} style={cardStyle}>
              <div style={{ fontSize: 15, fontWeight: 500, color: color.textPrimary }}>{title}</div>
              <p style={{ margin: `${size.sp2} 0 0`, fontSize: 14, lineHeight: 1.65, color: color.textSecondary }}>
                {body}
              </p>
            </div>
          ))}
        </div>

        {/* No prior-product claim here. An earlier draft credited a
            value-stream-mapping system built at another company — work that
            belongs to that company and its owners, none of whom are involved in
            Taktline. Borrowed credibility is the one kind this section must not
            trade in, since the whole point of it is that we say what is true.
            What is ours to claim is the founder's own record, and that is
            already in the section above. */}
        <p style={{
          margin: `${size.sp6} auto 0`, maxWidth: 640, textAlign: 'center',
          fontSize: 14, lineHeight: 1.7, color: color.textDim,
        }}>
          The method is not new, the problem is not new, and neither is the person who
          built this — only the product is. Try it on your own line for an afternoon and
          judge it on what it does there.
        </p>

        <InlineCta where="trust" line="Five minutes, no signup, and you will know." />
      </div>
    </section>
  )
}

// ─── Three lines from the book ───────────────────────────────────────────────

// Deliberately three fixed tips, not the app's rotating tip of the day: a
// visitor sees the page once, so the argument has to be the same every time —
// and half the rotation is Taktline UI advice that reads as jargon to someone
// who has never seen the product.
function FromTheBook() {
  const tips = featuredTips()
  return (
    <section style={{ padding: `clamp(56px, 9vw, 110px) ${size.sp6} 0` }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={eyebrowStyle}>From the book</div>
          <h2 style={h2Style}>The thinking underneath</h2>
        </div>
        <div style={{
          marginTop: size.sp8, display: 'grid', gap: size.sp4,
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        }}>
          {tips.map((tip) => (
            <blockquote key={tip.category} style={{
              ...cardStyle, margin: 0, display: 'flex', flexDirection: 'column',
              gap: size.sp3, textAlign: 'left',
            }}>
              <span style={{
                alignSelf: 'flex-start', fontSize: 10, fontFamily: font.mono,
                letterSpacing: '0.08em', textTransform: 'uppercase',
                color: color.blueBright, background: `${color.bluePrimary}18`,
                border: `1px solid ${color.bluePrimary}40`,
                borderRadius: size.radiusFull, padding: '2px 10px',
              }}>
                {tip.category}
              </span>
              <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.7, color: color.textSecondary }}>
                {tip.text}
              </p>
            </blockquote>
          ))}
        </div>
        <p style={{
          marginTop: size.sp5, fontSize: 13.5, lineHeight: 1.7,
          color: color.textDim, textAlign: 'center',
        }}>
          From{' '}
          <a href="https://www.amazon.com/dp/B09B1PPF91/" target="_blank" rel="noopener noreferrer"
             style={bookLink}
             onClick={() => track('outbound_click', { to: 'book-seven-deadly-wastes', where: 'from-the-book' })}>
            The Seven Deadly Wastes
          </a>. A new one greets you in the app each morning.
        </p>
      </div>
    </section>
  )
}

// ─── Questions a plant manager actually asks ─────────────────────────────────

const FAQ: { q: string; a: React.ReactNode }[] = [
  {
    q: 'Is it safe to let operators use their own phones?',
    a: <>An operator account is the lowest tier there is: it can run a timer, merge at
      its own bench and advance a lot along a route you defined. It cannot change the
      line, delete lots or move material anywhere it likes — so a lost handset is a
      low-privilege credential, not the keys to your shop. Passwords are hashed with
      argon2id and never stored; session tokens are held only as a hash, so even a
      database leak yields nothing you could sign in with. Sessions are cookie-based,
      unreadable to JavaScript, and expire after eight idle hours — about a shift.
      Changing a password signs every device out at once.</>,
  },
  { q: 'How long until it is running?',
    a: <>Minutes. Draw your stations and routes on the floor plan and the board is live —
        there is nothing to print or install. The five-minute tutorial builds a line end
        to end so you can see the shape of it before touching your own.</> },
  { q: 'Is my data mine?',
    a: <>Yes, and you can prove it: the whole line — stations, routes, products, lot
        history and every timing — exports at any time as JSON and as a spreadsheet, in
        a shape you can read without us. On-premise goes further and keeps the database
        itself on your hardware.</> },
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
    a: <>Free for up to 7 stations, with no card and no expiry. Beyond that,
        <strong> $2 per station a month</strong> — never less than $29, never more than
        $399, and every ERP connector is included. Every operator and every tablet is
        included too — we price the line, not the people, because a worker who can see
        the system improves it. Running it on your own hardware adds $199 a month.</> },
  { q: 'What happens if I stop paying?',
    a: <>Your line is waiting for you if you come back. Payment stops, the board goes
        read-only for a week so you can still see and export everything, and then it
        rests — we do not delete it. Start paying again whenever you like and it is
        exactly as you left it, down to the lot cards. And you can take it with you at
        any time: everything exports in a format you can read.</> },
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
            Start free
          </SignupLink>
        </div>
        <div style={{ marginTop: size.sp3, fontSize: 13, color: color.textDim }}>
          Free up to 7 stations · $2 a station beyond, capped at $399 · cancel any time
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
          © {new Date().getFullYear()} {LEGAL_ENTITY} — digital kanban for real factories
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: size.sp5, fontSize: 13 }}>
          <Link to="/manual" style={{ color: color.textSecondary, textDecoration: 'none' }}>User manual</Link>
          <Link to="/terms" style={{ color: color.textSecondary, textDecoration: 'none' }}>Terms</Link>
          <Link to="/login" style={{ color: color.textSecondary, textDecoration: 'none' }}>Sign in</Link>
          <Link to="/signup" style={{ color: color.blueBright, textDecoration: 'none' }}
                onClick={() => track('cta_click', { cta: 'signup', where: 'footer-nav' })}>Start free</Link>
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
