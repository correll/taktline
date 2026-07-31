#!/usr/bin/env python3
"""Write the two newer example lines as map documents.

The battery example was produced by the exporter itself; these are authored
here because they have no company to export from yet. Everything they emit has
to survive `POST /map-io/import`, which runs the same graph rules as the
editor — so `tests/test_example_lines.py` imports all three and runs an order
through each. An example that cannot be imported is worse than no example.

Two rules bite while authoring, and both are the app being right:

* A **weight only means something where the graph branches** — a split's
  branch, or a feed into a merge. The landing animation draws ×2 on
  glass→sealed units because it is a picture; a real line cannot, because
  nothing branches there. The window document carries its ratios on the
  glazing merge instead, which is where they actually belong.
* A **split branch's product is inferred** from the station it lands on, so
  none of these need to declare one.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "examples"


def station(ref, name, x, y, icon, *, storage=False, provider=None, role=None, desc=""):
    return {"ref": ref, "name": name, "description": desc,
            "position": {"x": x, "y": y, "width": 72, "height": 72},
            "color": None, "icon": icon, "isStorage": storage, "branchMode": None,
            "integrationProvider": provider, "integrationRole": role}


def route(process, load, unload, qty=1):
    return {"process": process, "load": load, "unload": unload,
            "quantity": qty, "outputTemplate": None}


def tmpl(ref, name, process, start):
    return {"ref": ref, "name": name, "description": "", "process": process,
            "startStation": start, "color": None, "fields": []}


def doc(name, stations, processes, templates, routes):
    return {"kind": "taktline-map", "version": 1, "name": name,
            "mapSettings": {"unit": "m", "pixelsPerUnit": 36, "stationSizeUnits": 2},
            "stations": stations, "processes": processes,
            "templates": templates, "routes": routes}


# ── Cut & sew ────────────────────────────────────────────────────────────────
# A wide fan into a deep chain: one lay cut into every panel a style needs, a
# merge that assembles the garment, then a sequence of finishing operations.
# The HOOD branch belongs to one style only, so the two processes over this
# cutting table do not use the same branches.
sweatshirt = doc(
    "Cut & sew — sweatshirts, crew neck and hooded",
    [
        station("s1", "Fleece rolls", 180, 640, "Layers", desc="Rolls arrive and are laid up here."),
        station("s2", "Spread & cut", 540, 640, "Scissors", desc="One lay becomes every panel the style needs."),
        station("s3", "Front & back", 900, 180, "Layers"),
        station("s4", "Sleeves", 900, 500, "Layers"),
        station("s5", "Ribbing", 900, 820, "Layers"),
        station("s6", "Hood panels", 900, 1140, "Layers", desc="Hooded styles only."),
        station("s7", "Sewing line", 1300, 640, "Cog", desc="The garment is assembled here."),
        station("s8", "Seam & hem", 1660, 640, "Cog"),
        station("s9", "Print & pack", 2020, 640, "Printer"),
        station("s10", "Offcuts", 900, 1460, "Box", storage=True, desc="Cut waste set aside."),
        station("s11", "Shopify", 1300, 240, "", provider="shopify", role="both"),
    ],
    [{"ref": "p1", "name": "Crew neck", "description": "", "desiredTaktSec": 900},
     {"ref": "p2", "name": "Hooded", "description": "", "desiredTaktSec": 1200}],
    [tmpl("t1", "Fleece roll (crew)", "p1", "s1"), tmpl("t2", "Crew front/back", "p1", "s3"),
     tmpl("t3", "Crew sleeve", "p1", "s4"), tmpl("t4", "Crew ribbing", "p1", "s5"),
     tmpl("t5", "Crew sweatshirt", "p1", "s7"),
     tmpl("t6", "Fleece roll (hooded)", "p2", "s1"), tmpl("t7", "Hood front/back", "p2", "s3"),
     tmpl("t8", "Hood sleeve", "p2", "s4"), tmpl("t9", "Hood ribbing", "p2", "s5"),
     tmpl("t10", "Hood panel", "p2", "s6"), tmpl("t11", "Hooded sweatshirt", "p2", "s7")],
    [
        # Crew neck: three panel types.
        route("p1", "s1", "s2"), route("p1", "s2", "s3"), route("p1", "s2", "s4"),
        route("p1", "s2", "s5"), route("p1", "s2", "s10"),
        route("p1", "s3", "s7"), route("p1", "s4", "s7"), route("p1", "s5", "s7"),
        route("p1", "s7", "s8"), route("p1", "s8", "s9"),
        # Hooded: the same table, plus a branch the crew line does not use.
        route("p2", "s1", "s2"), route("p2", "s2", "s3"), route("p2", "s2", "s4"),
        route("p2", "s2", "s5"), route("p2", "s2", "s6"), route("p2", "s2", "s10"),
        route("p2", "s3", "s7"), route("p2", "s4", "s7"), route("p2", "s5", "s7"),
        route("p2", "s6", "s7"),
        route("p2", "s7", "s8"), route("p2", "s8", "s9"),
        # Shopify raises the demand and takes the finished goods back.
        route("p1", "s11", "s7"), route("p2", "s11", "s7"),
        route("p1", "s9", "s11"), route("p2", "s9", "s11"),
    ],
)

# ── Window fabrication ───────────────────────────────────────────────────────
# Two chains converging on a glazing bench. The ratios live on the MERGE feeds,
# which is the only place they mean anything: a casement takes four mitred
# lengths and one sealed unit, a tilt-and-turn eight and two.
windows = doc(
    "Window fabrication — casement and tilt & turn",
    [
        station("s1", "uPVC profile", 180, 420, "Box"),
        station("s2", "Cut & mitre", 540, 420, "Scissors"),
        station("s3", "Weld & clean", 900, 420, "Thermometer"),
        station("s4", "Glass store", 540, 1000, "Layers"),
        station("s5", "Sealed units", 900, 1000, "Layers"),
        station("s6", "Glazing", 1300, 700, "Factory", desc="Frame and sealed unit come together."),
        station("s7", "Hardware", 1660, 700, "Wrench"),
        station("s8", "QC & load", 2020, 700, "Truck"),
        station("s9", "Cut-offs", 540, 60, "Box", storage=True),
        station("s10", "NetSuite", 1300, 300, "", provider="netsuite", role="both"),
    ],
    [{"ref": "p1", "name": "Casement", "description": "", "desiredTaktSec": 1800},
     {"ref": "p2", "name": "Tilt & turn", "description": "", "desiredTaktSec": 2400}],
    [tmpl("t1", "Profile bar (casement)", "p1", "s1"), tmpl("t2", "Casement frame", "p1", "s3"),
     tmpl("t3", "Glass sheet (casement)", "p1", "s4"), tmpl("t4", "Casement unit", "p1", "s5"),
     tmpl("t5", "Casement window", "p1", "s6"),
     tmpl("t6", "Profile bar (T&T)", "p2", "s1"), tmpl("t7", "T&T frame", "p2", "s3"),
     tmpl("t8", "Glass sheet (T&T)", "p2", "s4"), tmpl("t9", "T&T unit", "p2", "s5"),
     tmpl("t10", "Tilt & turn window", "p2", "s6")],
    [
        route("p1", "s1", "s2"), route("p1", "s2", "s3"), route("p1", "s2", "s9"),
        route("p1", "s4", "s5"),
        route("p1", "s3", "s6", 4), route("p1", "s5", "s6", 1),   # merge feeds carry the ratio
        route("p1", "s6", "s7"), route("p1", "s7", "s8"),
        route("p2", "s1", "s2"), route("p2", "s2", "s3"), route("p2", "s2", "s9"),
        route("p2", "s4", "s5"),
        route("p2", "s3", "s6", 8), route("p2", "s5", "s6", 2),
        route("p2", "s6", "s7"), route("p2", "s7", "s8"),
        route("p1", "s10", "s6"), route("p2", "s10", "s6"),
        route("p1", "s8", "s10"), route("p2", "s8", "s10"),
    ],
)

for filename, document in (("cut-and-sew-sweatshirts.json", sweatshirt),
                           ("window-fabrication.json", windows)):
    (OUT / filename).write_text(json.dumps(document, indent=2) + "\n")
    print(f"wrote examples/{filename}")
