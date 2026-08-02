import { Link, useParams } from 'react-router-dom'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { CONCEPTS, conceptById } from '../../help/concepts'
import { LEAN_TIPS } from '../../help/leanTips'
import { anchorForCategory } from '../../help/manualAnchors'
import { ConceptAnimation } from '../../share/ConceptAnimation'
import { cardUrl } from '../../share/shareLinks'
import { color, font, size } from '../../theme/tokens'

/**
 * Where a shared link lands. Public, no sign-in.
 *
 * The Open Graph tags for this URL are written by the *server*
 * (`backend/app/routers/share.py`) because LinkedIn's crawler never runs this
 * code. What this component owes the visitor is the thing the preview promised,
 * plus a reason to keep reading — so a concept gets its animation and a tip
 * gets its manual section, and both get one honest call to action rather than a
 * wall of them.
 *
 * An id it does not recognise is an improvement card published by some company:
 * the numbers live server-side, and the rendered card image is the whole
 * content, so it is shown directly. That also makes this view degrade correctly
 * for anything added to the catalogue after this build was deployed.
 */

export default function ShareView() {
  const { itemId = '' } = useParams()
  const concept = conceptById(itemId)
  const tip = LEAN_TIPS.find((t) => t.id === itemId)

  return (
    <div style={{ flex: 1, overflowY: 'auto', background: color.bgDeep, minHeight: '100vh' }}>
      <header style={{
        background: color.bgPanel, borderBottom: `1px solid ${color.border}`,
        padding: `0 ${size.sp6}`, height: 56, display: 'flex', alignItems: 'center',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', width: '100%', maxWidth: 780,
          margin: '0 auto', gap: size.sp4,
        }}>
          <Link to="/" style={{ display: 'flex', color: color.textPrimary }} aria-label="Taktline home">
            <TaktlineLogo height={24} color={color.textPrimary} />
          </Link>
          <Link to="/manual" style={{ color: color.textDim, fontSize: 13, textDecoration: 'none' }}>
            User manual
          </Link>
          <Link
            to="/signup"
            style={{
              marginLeft: 'auto', background: color.bluePrimary, color: '#fff',
              textDecoration: 'none', fontSize: 14, fontWeight: 600,
              borderRadius: size.radiusMd, padding: '8px 18px',
            }}
          >
            Start free
          </Link>
        </div>
      </header>

      <main style={{
        maxWidth: 780, margin: '0 auto', padding: `${size.sp8} ${size.sp6} ${size.sp12}`,
        fontFamily: font.sans,
      }}>
        {concept ? (
          <>
            <Eyebrow>
              {concept.chapter === 'science' ? 'Flow science' : 'The improvement toolkit'}
              {' · '}{concept.title}
            </Eyebrow>
            <h1 style={h1}>{concept.claim}</h1>
            {concept.animation && (
              <div style={{
                margin: `${size.sp6} 0`, padding: size.sp5, background: color.bgPanel,
                border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
              }}>
                <ConceptAnimation kind={concept.animation} />
              </div>
            )}
            {concept.formula && (
              <div style={{
                display: 'inline-block', padding: '10px 18px', marginBottom: size.sp5,
                background: color.bgCard, border: `1px solid ${color.border}`,
                borderRadius: size.radius, fontFamily: font.mono, fontSize: 14,
                color: color.textSecondary,
              }}>
                {concept.formula}
              </div>
            )}
            <p style={{ ...body, marginTop: concept.animation ? 0 : size.sp5 }}>
              {concept.body}
            </p>
            <Related
              title={concept.chapter === 'science'
                ? 'The rest of the flow science'
                : 'More from the improvement toolkit'}
              items={CONCEPTS.filter((c) => c.id !== concept.id
                                         && c.chapter === concept.chapter)
                             .slice(0, 4)
                             .map((c) => ({ id: c.id, text: c.claim }))}
            />
            <Cta
              to={`/manual#${concept.anchor}`}
              linkLabel="Read the full explanation in the manual"
              pitch="Taktline measures all of this on your own line — cycle time, line cycle time, WIP and lead time — and its line doctor tells you which one to fix first."
            />
          </>
        ) : tip ? (
          <>
            <Eyebrow>Lean tip · {tip.category}</Eyebrow>
            <h1 style={{ ...h1, fontSize: 30 }}>{tip.text}</h1>
            <Related
              title={`More on ${tip.category.toLowerCase()}`}
              items={siblings(itemId, tip.category)}
            />
            <Cta
              to={`/manual#${anchorForCategory(tip.category) ?? ''}`}
              linkLabel="Read more in the manual"
              pitch="One of ninety-four lean tips Taktline shows on the shop floor, one a day — alongside the live board, the floor plan and the statistics they come from."
            />
          </>
        ) : (
          <>
            <Eyebrow>Measured in Taktline</Eyebrow>
            <img
              src={cardUrl(itemId)}
              alt="A before-and-after measured on a production line"
              style={{
                width: '100%', display: 'block', marginTop: size.sp5,
                borderRadius: size.radiusLg, border: `1px solid ${color.border}`,
              }}
            />
            <Cta
              to="/manual#statistics"
              linkLabel="How Taktline measures this"
              pitch="Every number here was recorded by operators doing their normal work — start, stop, move the lot. Nobody filled in a form."
            />
          </>
        )}
      </main>
    </div>
  )
}

const h1 = {
  fontSize: 34, lineHeight: 1.25, fontWeight: 600, color: color.textPrimary,
  margin: `${size.sp3} 0 0`,
} as const

const body = {
  fontSize: 16, lineHeight: 1.7, color: color.textSecondary, margin: 0,
} as const

/** Other tips in the same category, so a visitor who found one useful has
 *  somewhere to go that is not the sign-up button. Three is the whole list for
 *  most categories; the cap only bites on Takt. */
function siblings(currentId: string, category: string) {
  return LEAN_TIPS.filter((t) => t.category === category && t.id !== currentId)
                  .slice(0, 3)
                  .map((t) => ({ id: t.id, text: t.text }))
}

function Related({ title, items }: { title: string; items: { id: string; text: string }[] }) {
  if (items.length === 0) return null
  return (
    <section style={{ marginTop: size.sp8 }}>
      <div style={{
        fontSize: 11, fontFamily: font.mono, letterSpacing: '0.1em',
        textTransform: 'uppercase', color: color.textDim, marginBottom: size.sp3,
      }}>
        {title}
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {items.map((it) => (
          <li key={it.id} style={{ borderTop: `1px solid ${color.border}` }}>
            <Link
              to={`/i/${it.id}`}
              style={{
                display: 'block', padding: `${size.sp3} 0`, fontSize: 14, lineHeight: 1.55,
                color: color.textSecondary, textDecoration: 'none',
              }}
            >
              {it.text}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontFamily: font.mono, letterSpacing: '0.12em',
      textTransform: 'uppercase', color: color.blueBright,
    }}>
      {children}
    </div>
  )
}

function Cta({ to, linkLabel, pitch }: { to: string; linkLabel: string; pitch: string }) {
  return (
    <>
      <div style={{ marginTop: size.sp5 }}>
        <Link to={to} style={{ color: color.blueBright, fontSize: 15 }}>{linkLabel} →</Link>
      </div>
      <div style={{
        marginTop: size.sp8, padding: size.sp6, background: color.bgCard,
        border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
      }}>
        <p style={{ ...body, fontSize: 15, margin: 0 }}>{pitch}</p>
        <div style={{ marginTop: size.sp4, display: 'flex', alignItems: 'center', gap: size.sp4 }}>
          <Link
            to="/signup"
            style={{
              background: color.bluePrimary, color: '#fff', textDecoration: 'none',
              fontSize: 15, fontWeight: 600, borderRadius: size.radiusMd, padding: '11px 26px',
            }}
          >
            Start free
          </Link>
          <span style={{ fontSize: 12.5, color: color.textDim }}>
            Two weeks free · every operator included on every plan
          </span>
        </div>
      </div>
    </>
  )
}
