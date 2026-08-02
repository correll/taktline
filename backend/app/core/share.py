"""Shareable cards — the catalogue, and the PNG renderer.

Why any of this lives on the server rather than in the SPA: **LinkedIn's
crawler does not run JavaScript.** A share is a URL pasted into a post, and
what appears under it is whatever `<meta property="og:…">` the server returned
plus an image it could fetch by URL. Both have to exist as bytes before a
browser is involved, so the card is rendered here and the page is served here.

Three things are shareable, and the line between them is deliberate: a share
affordance only appears where the artifact is **already interesting to a
stranger and free of the sharer's data**.

- **tip** — one of the lean tips of the day. No customer data at all.
- **concept** — one of the flow-science results from the manual. Likewise.
- **improvement** — a before/after a company measured on its own line. This one
  *is* their data, so it only exists when someone explicitly presses Share, and
  it carries exactly what they saw in the preview (see `routers/share.py`).

The text of the first two is generated out of the frontend
(`frontend/src/help/{leanTips,concepts}.ts` → `data/share_catalog.json`), which
is where it is authored and read; `shareCatalog.test.ts` fails on drift.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_DATA = Path(__file__).resolve().parent.parent / "data"
_CATALOG_PATH = _DATA / "share_catalog.json"
_FONT_PATH = _DATA / "fonts" / "Inter-Variable.ttf"

# ── The catalogue ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ShareItem:
    """One thing with a permanent URL at `/i/<id>`."""

    id: str
    kind: str          # 'tip' | 'concept'
    eyebrow: str       # the small line above the claim
    headline: str      # the claim itself — the OG title, and the card
    body: str          # supporting paragraph; '' for a tip (the tip IS the claim)
    formula: str | None
    anchor: str | None  # manual section the "read more" opens

    @property
    def share_url_path(self) -> str:
        return f"/i/{self.id}"


@functools.lru_cache(maxsize=1)
def catalog() -> dict[str, ShareItem]:
    raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    items: dict[str, ShareItem] = {}
    for t in raw["tips"]:
        items[t["id"]] = ShareItem(
            id=t["id"], kind="tip", eyebrow=t["category"], headline=t["text"],
            body="", formula=None, anchor=None,
        )
    for c in raw["concepts"]:
        items[c["id"]] = ShareItem(
            id=c["id"], kind="concept", eyebrow=f"Flow science · {c['title']}",
            headline=c["claim"], body=c["body"], formula=c["formula"],
            anchor=c["anchor"],
        )
    return items


def find(item_id: str) -> ShareItem | None:
    return catalog().get(item_id)


ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")

# ── Palette ──────────────────────────────────────────────────────────────────
# The app's night theme, verbatim from `theme/global.css`. A share card is the
# first thing most people ever see of the product, so it should be the product.

BG = "#121110"
PANEL = "#1A1917"
BORDER = "#33312D"
CORAL = "#F0997B"
INK = "#EFEDE7"
INK_2 = "#B4B1A9"
INK_DIM = "#8A8781"
GOOD = "#5FA97F"

CARD_W, CARD_H = 1200, 630   # the size every social crawler expects
PAD = 76


@functools.lru_cache(maxsize=32)
def _font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    """Inter at a weight. Bundled (SIL OFL, `data/fonts/OFL.txt`) rather than
    taken from the host, so a card renders identically on a laptop and in
    production — and because Pillow's built-in face has no em dash, no ÷ and no
    ρ, all of which are in this copy and all of which render as tofu."""
    f = ImageFont.truetype(str(_FONT_PATH), size)
    f.set_variation_by_axes([min(32, max(14, size)), weight])
    return f


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if not cur or font.getlength(trial) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _fit(text: str, max_w: int, max_h: int, sizes: list[int], weight: int,
         leading: float) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Largest size at which the text fits the box. Tip lengths run from 90 to
    520 characters and a fixed size would either overflow the long ones or
    waste the card on the short ones."""
    font = _font(sizes[-1], weight)
    lines = _wrap(text, font, max_w)
    for size in sizes:
        font = _font(size, weight)
        lines = _wrap(text, font, max_w)
        if len(lines) * round(size * leading) <= max_h:
            return font, lines, round(size * leading)
    return font, lines, round(sizes[-1] * leading)


def _draw_lines(d: ImageDraw.ImageDraw, xy: tuple[int, int], lines: list[str],
                font: ImageFont.FreeTypeFont, step: int, fill: str) -> int:
    x, y = xy
    for line in lines:
        d.text((x, y), line, font=font, fill=fill)
        y += step
    return y


def _tracked(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
             font: ImageFont.FreeTypeFont, fill: str, tracking: float) -> None:
    """Letter-spaced small caps. Pillow has no tracking, and an eyebrow set
    solid at 20px reads as a word rather than a label."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking


def _chrome(d: ImageDraw.ImageDraw, footer_right: str) -> None:
    d.rectangle([0, 0, CARD_W, 7], fill=CORAL)
    d.line([(PAD, CARD_H - 108), (CARD_W - PAD, CARD_H - 108)], fill=BORDER, width=1)
    wordmark = _font(27, 600)
    d.text((PAD, CARD_H - 78), "taktline", font=wordmark, fill=INK)
    d.text((PAD + wordmark.getlength("taktline") + 2, CARD_H - 78), ".com",
           font=_font(27, 400), fill=CORAL)
    right = _font(22, 400)
    d.text((CARD_W - PAD - right.getlength(footer_right), CARD_H - 74),
           footer_right, font=right, fill=INK_DIM)


def _png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── The cards ────────────────────────────────────────────────────────────────


def render_card(item: ShareItem) -> bytes:
    img = Image.new("RGB", (CARD_W, CARD_H), BG)
    d = ImageDraw.Draw(img)
    _chrome(d, "Lean manufacturing, measured")

    y = PAD
    _tracked(d, (PAD, y), item.eyebrow.upper(), _font(20, 600), CORAL, 1.6)
    y += 56

    # The formula and the body each claim their own band; whatever is left is
    # the headline's, which is why it is measured last.
    body_h = 0
    if item.body:
        body_h = 130
    formula_h = 74 if item.formula else 0
    head_box = CARD_H - 108 - 34 - y - body_h - formula_h

    inner = CARD_W - 2 * PAD
    font, lines, step = _fit(item.headline, inner, head_box,
                             [56, 50, 46, 42, 38, 34, 31, 28], 600, 1.30)
    y = _draw_lines(d, (PAD, y), lines, font, step, INK)

    if item.formula:
        y += 22
        f = _font(25, 500)
        w = f.getlength(item.formula) + 40
        d.rounded_rectangle([PAD, y, PAD + min(w, inner), y + 52], radius=10,
                            fill=PANEL, outline=BORDER, width=1)
        d.text((PAD + 20, y + 12), item.formula, font=f, fill=INK_2)
        y += 74

    if item.body:
        y += 16
        bfont, blines, bstep = _fit(item.body, inner, body_h,
                                    [25, 23, 21, 19, 17], 400, 1.44)
        _draw_lines(d, (PAD, y), blines, bfont, bstep, INK_2)

    return _png(img)


@dataclass(frozen=True)
class Improvement:
    """A before/after a line actually measured. Every field is a formatted
    string: the numbers are computed once, shown to the person deciding whether
    to share, and stored — so the card can never say something different from
    the preview they approved."""

    metric: str      # "Lead time"
    before: str      # "4.1 h"
    after: str       # "2.6 h"
    delta: str       # "37% faster"
    caption: str     # "Crew neck · 14 days apart"
    headline: str    # "We cut lead time by 37% without buying anything"
    improved: bool


def render_improvement(imp: Improvement) -> bytes:
    img = Image.new("RGB", (CARD_W, CARD_H), BG)
    d = ImageDraw.Draw(img)
    _chrome(d, "Measured, not estimated")

    y = PAD
    _tracked(d, (PAD, y), imp.metric.upper(), _font(20, 600), CORAL, 1.6)
    y += 54

    font, lines, step = _fit(imp.headline, CARD_W - 2 * PAD, 150,
                             [46, 42, 38, 34, 31], 600, 1.28)
    y = _draw_lines(d, (PAD, y), lines, font, step, INK)

    y += 34
    accent = GOOD if imp.improved else CORAL
    big = _font(76, 700)
    label = _font(19, 500)

    def column(x: int, value: str, cap: str, fill: str) -> int:
        d.text((x, y + 22), value, font=big, fill=fill)
        _tracked(d, (x, y), cap.upper(), label, INK_DIM, 1.2)
        return x + int(big.getlength(value)) + 56

    x = column(PAD, imp.before, "before", INK_2)
    d.text((x - 26, y + 34), "→", font=_font(52, 400), fill=INK_DIM)
    x = column(x + 34, imp.after, "after", accent)

    pill = _font(27, 600)
    pw = pill.getlength(imp.delta) + 40
    d.rounded_rectangle([x, y + 38, x + pw, y + 92], radius=27,
                        fill=PANEL, outline=accent, width=2)
    d.text((x + 20, y + 51), imp.delta, font=pill, fill=accent)

    d.text((PAD, y + 128), imp.caption, font=_font(22, 400), fill=INK_DIM)
    return _png(img)
