# Taktline — brand and color system

Reference for the frontend, the printed lot cards, and the marketing site.
Name: **Taktline** (lowercase in the wordmark, capitalized in prose).
Origin: *Taktlinie* is German for the barline in music — the vertical stroke that
marks each measure. It doubles as takt intervals, Kanban columns, and stations on a line.

---

## 1. The one rule that governs everything

On a factory floor, orange is already a status color. Andon convention is
red / amber / green, and an operator glancing at a screen reads warm hues as
"pay attention."

**Two color vocabularies, no overlap:**

| Vocabulary | Where it appears | Never appears |
| --- | --- | --- |
| **Brand coral** | Logo, nav, links, primary buttons, marketing | Lot board, map, cards, station tiles |
| **Andon status** | Lot board, map, cards, station tiles | Logo, nav, buttons, marketing chrome |
| **Heatmap violet** | Map station heat only | Anywhere status is implied |

Corollary: **never encode state with color alone.** Roughly 8% of men have
red-green color deficiency, a meaningful fraction of any operator population.
Every state carries an icon or a word alongside the hue.

---

## 2. Tokens

### Light mode

```css
:root {
  /* Ink — warm neutrals (not blue-grey; blue-grey fights coral) */
  --ink-900: #1A1917;   /* primary text, logo */
  --ink-700: #3D3B37;
  --ink-500: #6B6862;   /* secondary text */
  --ink-300: #B4B1A9;   /* strong border */
  --ink-200: #D8D5CD;   /* hairline border */
  --ink-100: #EFEDE7;   /* raised surface */
  --ink-50:  #F7F6F2;   /* page background */
  --white:   #FFFFFF;   /* cards */

  /* Coral — brand only */
  --coral-600: #993C1D;  /* accent text + links (AA on white) */
  --coral-400: #D85A30;  /* mark, fills, primary button */
  --coral-200: #F0997B;  /* use on dark surfaces */
  --coral-50:  #FAECE7;  /* tint background */

  /* Andon status — reserved */
  --status-running: #639922;
  --status-starved: #EF9F27;
  --status-blocked: #E24B4A;
  --status-idle:    #888780;

  /* Semantic aliases */
  --page:            var(--ink-50);
  --surface:         var(--white);
  --surface-raised:  var(--ink-100);
  --text-primary:    var(--ink-900);
  --text-secondary:  var(--ink-500);
  --border:          var(--ink-200);
  --border-strong:   var(--ink-300);
  --brand:           var(--coral-400);
  --brand-text:      var(--coral-600);
}
```

### Dark mode

Not optional — assembly areas are dim, tablets glare, and operators work night shifts.

```css
@media (prefers-color-scheme: dark) {
  :root {
    --page:           #121110;
    --surface:        #1D1C1A;
    --surface-raised: #2A2825;
    --text-primary:   #EFEDE7;
    --text-secondary: #B4B1A9;
    --border:         #33312D;
    --border-strong:  #4A4741;
    --brand:          var(--coral-200);
    --brand-text:     var(--coral-200);
  }
}
```

### Contrast notes

- `#D85A30` on white is ~3.6:1 — **fails AA for body text.** Use it for graphics,
  fills, and large type only.
- `#993C1D` on white is ~5.1:1 — passes AA. Use for links and accent copy.
- On dark surfaces both invert to `#F0997B`.

---

## 3. Heatmap ramp

Station busyness gets its own hue so it never reads as an alarm. This matters
semantically: a high-OEE bottleneck and a starved station are opposite problems,
and warm colors for both makes them indistinguishable at a glance.

```css
--heat-0: #EEEDFE;
--heat-1: #CECBF6;
--heat-2: #AFA9EC;
--heat-3: #7F77DD;
--heat-4: #534AB7;
--heat-5: #26215C;
```

For the PixiJS `MapCanvas` sprite tints:

```ts
export const HEAT_RAMP = [0xEEEDFE, 0xCECBF6, 0xAFA9EC, 0x7F77DD, 0x534AB7, 0x26215C] as const

export function heatTint(load: number): number {
  const i = Math.min(HEAT_RAMP.length - 1, Math.max(0, Math.floor(load * HEAT_RAMP.length)))
  return HEAT_RAMP[i]
}
```

---

## 4. Logo

### Horizontal lockup

`currentColor` for the primary strokes so the mark inherits from context and
collapses to pure black for single-color printing.

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="196" height="34" viewBox="0 0 196 34" role="img" aria-label="Taktline">
  <g fill="currentColor">
    <rect x="0" y="2" width="6" height="30" rx="1"/>
    <rect x="24" y="2" width="6" height="30" rx="1"/>
    <rect x="36" y="2" width="6" height="30" rx="1"/>
    <rect x="48" y="2" width="6" height="30" rx="1"/>
  </g>
  <rect x="12" y="2" width="6" height="30" rx="1" fill="#D85A30"/>
  <text x="74" y="26" font-family="Inter, 'Helvetica Neue', Arial, sans-serif" font-size="27" font-weight="500" letter-spacing="-0.6" fill="currentColor">taktline</text>
</svg>
```

### Mark only (favicon, app icon, edge box)

Crop to the left 54 units: `viewBox="0 0 54 34"`.

### Print rule

Lot cards come off cheap laser and thermal printers in pure monochrome, and the
coral bar disappears. Two acceptable resolutions:

1. Ship an all-black lockup and let the rhythm carry the idea, **or**
2. Give the second bar 3–4 units of extra height so the accent survives without color.

Pick one and use it consistently — do not send a coral lockup to a mono printer.

### Wordmark

- Lowercase `taktline` in the mark; **Taktline** in prose.
- Weight 500. Never 600 or 700 — too heavy against the industrial neutrals.
- Convert the text to outlines before production use; it's live text in the SVG above.

---

## 5. Typography and copy

- Sentence case everywhere: buttons, headings, tabs, labels. Never Title Case, never ALL CAPS.
- Two weights only: 400 regular, 500 medium.
- Body 16px / line-height 1.7. Station and card labels 14px. Metadata 12px.
- Operator-facing text must be legible at arm's length on a wall-mounted tablet —
  do not go below 14px anywhere on the Operator view.

---

## 6. Rejected options, and why

- **Notre Dame blue as brand.** Navy is the default B2B software color, so it
  buys no distinctiveness — and courting iNDustry Labs while wearing their palette
  can read as implying an affiliation that doesn't exist.
- **Amber as brand accent.** Collides directly with the andon "starved" state.
- **Cool blue-grey neutrals.** Fight the coral and lose the paper/card-stock feel.
- **Orange anywhere on the lot board.** See section 1.

---

## 7. Rename checklist (Veridion → Taktline)

Renaming cookies invalidates every existing session and clears the active-company
selection. Fine pre-launch — do it before there are users.

- [ ] `veridion_session` cookie → `taktline_session`
- [ ] `veridion_csrf` cookie → `taktline_csrf`
- [ ] `VERIDION_DEV` env var → `TAKTLINE_DEV`
- [ ] `DATABASE_URL` default `postgresql+asyncpg://localhost:5432/veridion` → `/taktline`
- [ ] `localStorage['veridion.activeCompanyId']` → `taktline.activeCompanyId`
- [ ] `/ws/events` handshake — confirm nothing references the old name
- [ ] `seed_demo.py`, `generate_floorplan.py`
- [ ] `CLAUDE.md`, README, repo name
- [ ] Alembic history — check no migration hardcodes the database name

Database rename is cosmetic: either create a fresh DB and re-run
`alembic upgrade head`, or leave the old name in place.

---

## 8. Open items

- Trademark clearance on TAKTLINE before anything is printed. Ask counsel to look
  specifically at **TAKKT AG** (listed German B2B industrial distributor,
  `takkt.com`) and **Taktile** (fintech decision engines) US registrations.
- A small existing "Taktline" holds a LinkedIn company page — check handle
  availability there first.
- Register `taktline.com` plus a defensive `taktline.io`, and the Indiana entity.
