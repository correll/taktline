import React from 'react'
import { color, size } from '../theme/tokens'

/**
 * Equations, typeset in plain CSS.
 *
 * The manual needs exactly four formulas, so a maths library would be almost
 * all dead weight: KaTeX is ~280 KB against the four fractions and a handful
 * of subscripts actually used, and it drags in its own fonts and stylesheet.
 * Stacked flexbox fractions, italic serif variables and true sub/superscripts
 * cover everything these equations contain, in under a hundred lines that
 * follow the app's own theme tokens — dark mode included, which a bundled
 * stylesheet would fight.
 *
 * `Term` renders the labelled underbrace: the factor above, a thin rule, and
 * the name below in small dim caps. That is what turns Kingman's formula from
 * three Greek letters into a sentence — utilisation × variability × work time
 * — which is the entire point of showing the equation at all.
 */

const MATH_FONT = 'Georgia, "Times New Roman", serif'

/** A display equation, centred in its own block. */
export const Eq: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div aria-hidden={false} style={{
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    gap: '0.45em', flexWrap: 'wrap',
    margin: `${size.sp5} 0`, padding: `${size.sp4} ${size.sp3}`,
    background: color.bgCard, border: `1px solid ${color.border}`,
    borderRadius: size.radius,
    fontFamily: MATH_FONT, fontSize: 17, color: color.textPrimary,
    overflowX: 'auto',
  }}>
    {children}
  </div>
)

/** An italic variable, the way maths sets it. */
export const V: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <i style={{ fontFamily: MATH_FONT }}>{children}</i>
)

export const Sub: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <sub style={{ fontSize: '0.66em' }}>{children}</sub>
)

export const Sup: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <sup style={{ fontSize: '0.66em' }}>{children}</sup>
)

/** A stacked fraction. */
export const Frac: React.FC<{ num: React.ReactNode; den: React.ReactNode }> = ({ num, den }) => (
  <span style={{
    display: 'inline-flex', flexDirection: 'column', alignItems: 'center',
    verticalAlign: 'middle', margin: '0 0.15em',
  }}>
    <span style={{ padding: '0 0.35em 0.12em' }}>{num}</span>
    <span style={{
      borderTop: `1.5px solid ${color.textPrimary}`,
      padding: '0.12em 0.35em 0', minWidth: '100%', textAlign: 'center',
    }}>
      {den}
    </span>
  </span>
)

/** A factor with its name beneath — the poor typesetter's underbrace. */
export const Term: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <span style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center' }}>
    <span style={{ display: 'inline-flex', alignItems: 'center' }}>{children}</span>
    <span style={{
      marginTop: 6, paddingTop: 3, borderTop: `1px solid ${color.borderStrong}`,
      fontFamily: 'inherit', fontSize: 10.5, fontStyle: 'normal',
      letterSpacing: '0.08em', textTransform: 'uppercase', color: color.textDim,
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  </span>
)

/** The multiplication sign, spaced as an operator. */
export const Times: React.FC = () => (
  <span style={{ color: color.textSecondary, margin: '0 0.1em' }}>×</span>
)
