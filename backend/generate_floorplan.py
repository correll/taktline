#!/usr/bin/env python3
"""
Generate factory floor plan PNG for the E-Bike manufacturing demo.

Coordinate system
─────────────────
All station positions are stored in METERS.
Image pixel = station_coord_m * M   (M = 36 pixels per meter)
Image size  = 3840 × 1200 px  →  represents ~106 m × 33 m

Map Settings to configure after upload
──────────────────────────────────────
  pixels-per-unit : 36
  unit            : meters

Factory envelope
────────────────
  Width   :  100 m   (stations span x = 5 … 97 m)
  Depth   :   28 m   (stations span y = 5 … 26 m)

Station layout (meters)
───────────────────────
  Frame Production  (y =  5) : x = 5, 20, 35, 50
  Drivetrain        (y = 18) : x = 5, 20, 35
  Assembly/Testing  (y = 12) : x = 62, 74, 86
  Packaging         (y = 26) : x = 5, 20, 35, 50, 62
  Final / Warehouse (y = 20) : x = 91, 97
"""

from PIL import Image, ImageDraw, ImageFont
import math, os

# ── Scale & canvas ──────────────────────────────────────────────────────────
M    = 36          # pixels per meter
W, H = 3840, 1200  # image dimensions

def m(meters):
    """Convert meters to image pixels."""
    return int(meters * M)

img  = Image.new("RGB", (W, H), "#B8B4AC")
draw = ImageDraw.Draw(img)

# ── Fonts ──────────────────────────────────────────────────────────────────
FONT_DIR = "/System/Library/Fonts/Supplemental/"
def fnt(name, size):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except Exception:
        return ImageFont.load_default()

f_zone    = fnt("Arial Bold.ttf", 20)
f_station = fnt("Arial Bold.ttf", 15)
f_sub     = fnt("Arial.ttf",      12)
f_label   = fnt("Arial Bold.ttf", 11)
f_tiny    = fnt("Arial.ttf",      10)

# ── Palette ─────────────────────────────────────────────────────────────────
C = dict(
    floor      = "#D4D0C8",
    wall       = "#2A2A2A",
    column     = "#3A3A3A",
    aisle      = "#E8C520",
    aisle_line = "#D4AE10",
    zone_fr    = "#D6E8F6",
    zone_dt    = "#F6E8D0",
    zone_as    = "#E8DDF6",
    zone_pk    = "#D4EED4",
    zone_fp    = "#F6D8E8",
    zone_wh    = "#E8E8E8",
    station    = "#FAFAFA",
    sta_border = "#404040",
    merge_acc  = "#7C3AED",
    arrow      = "#2A2A2A",
    arrow_merge= "#7C3AED",
    txt_zone   = "#1A1A2E",
    txt_sta    = "#1A1A1A",
    txt_sub    = "#555555",
    grid       = "#C8C4BC",
    conveyor   = "#8A8078",
)

# ── Helpers ─────────────────────────────────────────────────────────────────
def rect(x1, y1, x2, y2, fill, outline=None, width=1):
    draw.rectangle([x1, y1, x2, y2], fill=fill)
    if outline:
        draw.rectangle([x1, y1, x2, y2], outline=outline, width=width)

def ctext(x, y, text, font, color):
    bb = draw.textbbox((0, 0), text, font=font)
    draw.text((x - (bb[2]-bb[0])//2, y - (bb[3]-bb[1])//2), text, font=font, fill=color)

def arrow(x1, y1, x2, y2, color, width=3, head=12):
    draw.line([x1, y1, x2, y2], fill=color, width=width)
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1:
        return
    ux, uy = dx / length, dy / length
    lx, ly = -uy * head * 0.4, ux * head * 0.4
    draw.polygon([(x2, y2),
                  (x2 - ux*head + lx, y2 - uy*head + ly),
                  (x2 - ux*head - lx, y2 - uy*head - ly)], fill=color)

def harrow(x1, x2, y, color=None, **kw):
    arrow(x1, y, x2, y, color or C["arrow"], **kw)

# ── Station geometry ─────────────────────────────────────────────────────────
# Each workstation cell is 4 m × 2.2 m  →  144 × 80 px
SW2, SH2 = 72, 40   # half-width, half-height of station cell in pixels

def cx(xm): return m(xm)          # station centre pixel x
def cy(ym): return m(ym)          # station centre pixel y
def er(xm, ym): return (m(xm) + SW2, m(ym))   # right edge centre
def el(xm, ym): return (m(xm) - SW2, m(ym))   # left edge centre
def eb(xm, ym): return (m(xm), m(ym) + SH2)   # bottom edge centre
def et(xm, ym): return (m(xm), m(ym) - SH2)   # top edge centre

# ════════════════════════════════════════════════════════════════════════════
# 1. BUILDING FLOOR
# ════════════════════════════════════════════════════════════════════════════
WALL = 24   # outer wall thickness in pixels
MARG = 30   # image margin before the wall

rect(MARG, MARG, W - MARG, H - MARG, C["floor"])

TILE = m(3)   # 3 m floor tile grid
for gx in range(MARG + WALL, W - MARG - WALL, TILE):
    draw.line([gx, MARG+WALL, gx, H-MARG-WALL], fill=C["grid"], width=1)
for gy in range(MARG + WALL, H - MARG - WALL, TILE):
    draw.line([MARG+WALL, gy, W-MARG-WALL, gy], fill=C["grid"], width=1)

# ════════════════════════════════════════════════════════════════════════════
# 2. ZONE BACKGROUNDS
# ════════════════════════════════════════════════════════════════════════════
# Frame Production  x= 1– 55 m, y= 1–10 m
rect(m(1), m(1), m(55), m(10), C["zone_fr"], "#9FC8E0", 1)
# Drivetrain        x= 1– 42 m, y=14–22 m
rect(m(1), m(14), m(42), m(22), C["zone_dt"], "#D4A860", 1)
# Assembly/Testing  x=57– 92 m, y= 7–21 m
rect(m(57), m(7), m(92), m(21), C["zone_as"], "#9B72CF", 1)
# Packaging Line    x= 1– 68 m, y=22–30 m
rect(m(1), m(22), m(68), m(30), C["zone_pk"], "#5AAD5A", 1)
# Final Packaging   x=87– 95 m, y=15–25 m
rect(m(87), m(15), m(95), m(25), C["zone_fp"], "#D45A8A", 1)
# Warehouse         x=95–103 m, y=15–25 m
rect(m(95), m(15), m(103), m(25), C["zone_wh"], "#888888", 1)

# ════════════════════════════════════════════════════════════════════════════
# 3. SAFETY AISLES  (yellow hatched strips)
# ════════════════════════════════════════════════════════════════════════════
AW = m(1.2)   # aisle width in pixels ≈ 43 px

def hatch_aisle(x1, y1, x2, y2):
    """Fill rectangle with yellow hatch then border."""
    for ax in range(x1, x2, 18):
        draw.rectangle([ax, y1, min(ax+9, x2), y2], fill=C["aisle"])
    draw.rectangle([x1, y1, x2, y2], outline=C["aisle_line"], width=2)

def vhatch_aisle(x1, y1, x2, y2):
    for ay in range(y1, y2, 18):
        draw.rectangle([x1, ay, x2, min(ay+9, y2)], fill=C["aisle"])
    draw.rectangle([x1, y1, x2, y2], outline=C["aisle_line"], width=2)

# Between frame (y=5) and drivetrain (y=18) rows  →  aisle at y≈11 m
hatch_aisle(m(1), m(11), m(56), m(11)+AW)
# Between lower rows and packaging (y=26)  →  aisle at y≈22 m
hatch_aisle(m(1), m(22)-AW, m(68), m(22))
# Vertical aisle separating left area from assembly zone  →  x≈55 m
vhatch_aisle(m(55), m(1), m(55)+AW, m(30))

# ════════════════════════════════════════════════════════════════════════════
# 4. STRUCTURAL COLUMNS  (every 20 m horizontally, at zone seams vertically)
# ════════════════════════════════════════════════════════════════════════════
COL = 18
col_xs = [m(x) for x in [2, 20, 40, 55, 74, 92, 102]]
col_ys = [m(y) for y in [2, 11, 22, 30]]

for ccx in col_xs:
    for ccy in col_ys:
        rect(ccx-COL//2, ccy-COL//2, ccx+COL//2, ccy+COL//2, C["column"])
        draw.rectangle([ccx-COL//2+2, ccy+COL//2, ccx+COL//2+2, ccy+COL//2+4], fill="#1A1A1A")
        draw.rectangle([ccx+COL//2,   ccy-COL//2+2, ccx+COL//2+4, ccy+COL//2+2], fill="#1A1A1A")

# ════════════════════════════════════════════════════════════════════════════
# 5. CONVEYOR LINES  (drawn before station cells)
# ════════════════════════════════════════════════════════════════════════════
CONV_W = 8
CC = C["conveyor"]
draw.line([m(5), m(5),  m(50), m(5)],  fill=CC, width=CONV_W)   # frame row
draw.line([m(5), m(18), m(35), m(18)], fill=CC, width=CONV_W)   # drivetrain row
draw.line([m(62),m(12), m(86), m(12)], fill=CC, width=CONV_W)   # assembly row
draw.line([m(5), m(26), m(62), m(26)], fill=CC, width=CONV_W)   # packaging row
draw.line([m(91),m(20), m(97), m(20)], fill=CC, width=CONV_W)   # final/WH

# ════════════════════════════════════════════════════════════════════════════
# 6. FLOW ARROWS
# ════════════════════════════════════════════════════════════════════════════
AW_W = 3   # arrow line width

# Branch A – Frame
for a, b in [((5,5),(20,5)), ((20,5),(35,5)), ((35,5),(50,5))]:
    x1, y1 = er(*a);  x2 = el(*b)[0]
    harrow(x1, x2, y1, C["arrow"], width=AW_W)

# Branch B – Drivetrain
for a, b in [((5,18),(20,18)), ((20,18),(35,18))]:
    x1, y1 = er(*a);  x2 = el(*b)[0]
    harrow(x1, x2, y1, C["arrow"], width=AW_W)

# Merge 1: Frame Painting (50,5) + Drivetrain QC (35,18) → Frame Integration (62,12)
ex1, ey1 = er(50, 5)
ex2, ey2 = el(62, 12)
draw.line([ex1, ey1, ex2, ey1], fill=C["arrow_merge"], width=AW_W+1)
arrow(ex2, ey1, ex2, ey2, C["arrow_merge"], width=AW_W+1)

ex3, ey3 = er(35, 18)
draw.line([ex3, ey3, ex2, ey3], fill=C["arrow_merge"], width=AW_W+1)
arrow(ex2, ey3, ex2, ey2, C["arrow_merge"], width=AW_W+1)

# Post-merge 1
for a, b in [((62,12),(74,12)), ((74,12),(86,12))]:
    x1, y1 = er(*a);  x2 = el(*b)[0]
    harrow(x1, x2, y1, C["arrow"], width=AW_W)

# Branch C – Packaging
for a, b in [((5,26),(20,26)), ((20,26),(35,26)), ((35,26),(50,26)), ((50,26),(62,26))]:
    x1, y1 = er(*a);  x2 = el(*b)[0]
    harrow(x1, x2, y1, C["arrow"], width=AW_W)

# Merge 2: Bike Testing (86,12) + Packaging Inspection (62,26) → Final Packaging (91,20)
ex5, ey5 = er(86, 12)
ex6, ey6 = el(91, 20)
draw.line([ex5, ey5, ex6, ey5], fill=C["arrow_merge"], width=AW_W+1)
arrow(ex6, ey5, ex6, ey6, C["arrow_merge"], width=AW_W+1)

ex7, ey7 = er(62, 26)
draw.line([ex7, ey7, ex6, ey7], fill=C["arrow_merge"], width=AW_W+1)
arrow(ex6, ey7, ex6, ey6, C["arrow_merge"], width=AW_W+1)

# Final Packaging → Warehouse
x1, y1 = er(91, 20);  x2 = el(97, 20)[0]
harrow(x1, x2, y1, C["arrow"], width=AW_W)

# ════════════════════════════════════════════════════════════════════════════
# 7. STATION CELLS
# ════════════════════════════════════════════════════════════════════════════
stations = [
    # (x_m, y_m, label1,       label2,         is_merge, zone_color)
    ( 5,  5,  "Steel",       "Inventory",      False, C["zone_fr"]),
    (20,  5,  "Tube",        "Cutting",         False, C["zone_fr"]),
    (35,  5,  "Frame",       "Welding",         False, C["zone_fr"]),
    (50,  5,  "Frame",       "Painting",        False, C["zone_fr"]),
    ( 5, 18,  "Parts",       "Inventory",       False, C["zone_dt"]),
    (20, 18,  "Drivetrain",  "Assembly",        False, C["zone_dt"]),
    (35, 18,  "Drivetrain",  "QC",              False, C["zone_dt"]),
    (62, 12,  "Frame",       "Integration",     True,  C["zone_as"]),
    (74, 12,  "Electrical",  "Installation",    False, C["zone_as"]),
    (86, 12,  "Bike",        "Testing",         False, C["zone_as"]),
    ( 5, 26,  "Packaging",   "Depot",           False, C["zone_pk"]),
    (20, 26,  "Box",         "Manufacturing",   False, C["zone_pk"]),
    (35, 26,  "Print &",     "Label",           False, C["zone_pk"]),
    (50, 26,  "Accessories", "Packing",         False, C["zone_pk"]),
    (62, 26,  "Packaging",   "Inspection",      False, C["zone_pk"]),
    (91, 20,  "Final",       "Packaging",       True,  C["zone_fp"]),
    (97, 20,  "Finished",    "Goods WH",        False, C["zone_wh"]),
]

for (xm, ym, l1, l2, is_merge, zcolor) in stations:
    ccx, ccy = m(xm), m(ym)
    x1, y1 = ccx - SW2, ccy - SH2
    x2, y2 = ccx + SW2, ccy + SH2

    draw.rectangle([x1+4, y1+4, x2+4, y2+4], fill="#00000028")  # shadow

    border_color = C["merge_acc"] if is_merge else C["sta_border"]
    border_w     = 3              if is_merge else 2
    rect(x1, y1, x2, y2, C["station"], border_color, border_w)

    if is_merge:
        rect(x1, y1, x2, y1+7, C["merge_acc"])

    ctext(ccx, ccy - 10, l1, f_station, C["txt_sta"])
    ctext(ccx, ccy + 10, l2, f_sub,     C["txt_sub"])

    if is_merge:
        bw = 52
        rect(ccx-bw//2, y2-17, ccx+bw//2, y2-2, C["merge_acc"], C["merge_acc"])
        ctext(ccx, y2-10, "MERGE", f_label, "#FFFFFF")

# ════════════════════════════════════════════════════════════════════════════
# 8. ZONE LABELS
# ════════════════════════════════════════════════════════════════════════════
zone_labels = [
    (m(28),  m(2.5), "FRAME PRODUCTION",   f_zone),
    (m(22),  m(15),  "DRIVETRAIN",          f_zone),
    (m(74),  m(8.5), "ASSEMBLY & TESTING",  f_zone),
    (m(35),  m(23),  "PACKAGING LINE",      f_zone),
    (m(91),  m(16),  "FINAL PKG",           f_label),
    (m(97),  m(16),  "WAREHOUSE",           f_label),
]
for (lx, ly, text, font) in zone_labels:
    bb  = draw.textbbox((0, 0), text, font=font)
    tw  = bb[2] - bb[0]
    th  = bb[3] - bb[1]
    pad = 8
    rect(lx-tw//2-pad, ly-2, lx+tw//2+pad, ly+th+6, "#FFFFFF90")
    ctext(lx, ly+th//2+2, text, font, C["txt_zone"])

# ════════════════════════════════════════════════════════════════════════════
# 9. OUTER WALLS
# ════════════════════════════════════════════════════════════════════════════
def outer_wall(x1, y1, x2, y2):
    rect(x1, y1, x2, y2, C["wall"])

outer_wall(MARG, MARG, W-MARG, MARG+WALL)               # top
outer_wall(MARG, H-MARG-WALL, W-MARG, H-MARG)           # bottom
outer_wall(MARG, MARG, MARG+WALL, H-MARG)               # left
outer_wall(W-MARG-WALL, MARG, W-MARG, H-MARG)           # right

# Personnel doors (top wall)
for door_x in [m(20), m(58), m(84)]:
    rect(door_x, MARG, door_x+56, MARG+WALL, "#8C8880")

# Emergency exits (bottom wall)
for door_x in [m(25), m(70)]:
    rect(door_x, H-MARG-WALL, door_x+48, H-MARG, "#8C8880")

# Loading docks (left wall) – 3 docks aligned with production rows
for dock_y in [m(4), m(17), m(25)]:
    rect(MARG, dock_y, MARG+WALL, dock_y+80, "#6A6660")
    for s in range(5):
        sy_s = dock_y + 8 + s*13
        draw.line([MARG+4, sy_s, MARG+WALL-4, sy_s], fill="#9A9690", width=2)

# Shipping door (right wall)
rect(W-MARG-WALL, m(18), W-MARG, m(18)+90, "#6A6660")

# Dock labels
for (dock_y, label) in [(m(4)+22, "DOCK A"), (m(17)+22, "DOCK B"), (m(25)+22, "DOCK C")]:
    ctext(MARG+WALL+38, dock_y, label, f_tiny, "#666660")
ctext(W-MARG-WALL-36, m(18)+40, "SHIP", f_tiny, "#666660")

# ════════════════════════════════════════════════════════════════════════════
# 10. NORTH ARROW + SCALE BAR
# ════════════════════════════════════════════════════════════════════════════
NX, NY = W-MARG-WALL-70, H-MARG-WALL-70
draw.polygon([(NX, NY-28), (NX-11, NY+10), (NX, NY), (NX+11, NY+10)], fill=C["wall"])
ctext(NX, NY-42, "N", f_label, C["wall"])

# Scale bar: 10 m = 360 px, alternating black/white segments of 5 m (180 px)
SBX = MARG + WALL + 30
SBY = H - MARG - WALL - 38
BAR_10M = m(10)   # 360 px
for i in range(2):
    fill = C["wall"] if i % 2 == 0 else "#FFFFFF"
    draw.rectangle([SBX + i*BAR_10M//2, SBY, SBX + (i+1)*BAR_10M//2, SBY+10], fill=fill)
draw.rectangle([SBX, SBY, SBX+BAR_10M, SBY+10], outline=C["wall"], width=1)
ctext(SBX,           SBY+18, "0",   f_tiny, C["wall"])
ctext(SBX+BAR_10M//2, SBY+18, "5 m", f_tiny, C["wall"])
ctext(SBX+BAR_10M,   SBY+18, "10 m", f_tiny, C["wall"])
draw.text((SBX, SBY-14),
          f"Scale  36 px = 1 m  |  image = {W}×{H} px",
          font=f_tiny, fill=C["wall"])

# ── Title block ───────────────────────────────────────────────────────────
TX, TY = W-MARG-WALL-20, MARG+WALL+18
for i, (text, font) in enumerate([
    ("E-BIKE MANUFACTURING FACILITY",  f_zone),
    ("Floor Plan — Production Layout", f_sub),
    ("Taktline Demo  |  100 m × 28 m", f_tiny),
]):
    bb = draw.textbbox((0, 0), text, font=font)
    draw.text((TX-(bb[2]-bb[0]), TY+i*20), text, font=font, fill=C["txt_zone"])

# ════════════════════════════════════════════════════════════════════════════
# 11. SAVE
# ════════════════════════════════════════════════════════════════════════════
OUT = "factory_floorplan.png"
img.save(OUT, "PNG", optimize=False)
print(f"Saved: {OUT}  ({W}×{H} px)")
print()
print("Map Settings after upload:")
print("  pixels-per-unit : 36")
print("  unit            : meters")
print()
print("Station positions (meters) now match image pixels (coord × 36):")
print("  Steel Inventory   → (  5,  5) m  → pixel (180, 180)")
print("  Finished Goods WH → ( 97, 20) m  → pixel (3492, 720)")
print("  Factory width     : 97 m  (under the 100 m target)")
