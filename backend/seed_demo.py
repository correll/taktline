#!/usr/bin/env python3
"""
Seed script: Electric Bicycle manufacturing demo process

Graph structure
───────────────
Branch A — Frame (3 steps):
  Steel Inventory → Tube Cutting → Frame Welding → Frame Painting ─────────┐
                                                                             ↓
Branch B — Drivetrain (2 steps):                                    Frame Integration → Electrical Installation → Bike Testing ──────┐
  Parts Inventory → Drivetrain Assembly → Drivetrain QC ────────────────────┘                                                        ↓
                                                                                                                             Final Packaging → Finished Goods Warehouse
Branch C — Packaging (4 steps):                                                                                                      ↑
  Packaging Depot → Box Manufacturing → Print & Label → Accessories Packing → Packaging Inspection ──────────────────────────────────┘

Templates
─────────
  E-Bike Frame     — starts at Steel Inventory     (feeds merge 1)
  Drivetrain Kit   — starts at Parts Inventory      (feeds merge 1)
  E-Bike Assembly  — starts at Frame Integration    (created by merge 1, feeds merge 2)
  Packaging Set    — starts at Packaging Depot      (feeds merge 2)
  Complete E-Bike  — starts at Final Packaging      (created by merge 2, ends at warehouse)
"""

import argparse
import json
import urllib.request
import urllib.error
import sys

BASE = "http://localhost:8000"


def _call(method: str, path: str, data: dict | None = None) -> bytes:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        print(f"  ERROR {e.code} on {method} {path}: {detail}", file=sys.stderr)
        raise


def get(path: str) -> list:
    return json.loads(_call("GET", path))


def post(path: str, data: dict) -> dict:
    return json.loads(_call("POST", path, data))


def delete(path: str) -> None:
    try:
        _call("DELETE", path)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


def clear() -> None:
    print("Clearing existing data…\n")

    # Delete in dependency order so no references dangle
    for (label, path) in [
        ("session",  "/sessions/"),
        ("card",     "/cards/"),
        ("template", "/lot-templates/"),
        ("route",    "/routes/"),
        ("process",  "/processes/"),
        ("station",  "/stations/"),
    ]:
        items = get(path)
        for item in items:
            delete(f"{path}{item['_id']}")
        if items:
            print(f"  ✓ Deleted {len(items)} {label}(s)")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the E-Bike manufacturing demo.")
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Skip the pre-seed clear step and add on top of existing data.",
    )
    args = parser.parse_args()

    if not args.no_clear:
        clear()

    map_cfg = get("/map-settings/")
    M = map_cfg.get("pixelsPerUnit") or 36
    print(f"Map scale: {M} px/unit (from map settings)\n")

    print("Creating E-Bike manufacturing demo…\n")

    # ── Process ──────────────────────────────────────────────────────────────
    process = post("/processes/", {
        "name": "E-Bike Manufacturing",
        "description": "End-to-end electric bicycle assembly from raw materials to finished goods",
    })
    pid = process["_id"]
    print(f"✓ Process: {process['name']}  ({pid})\n")

    # ── Stations ─────────────────────────────────────────────────────────────
    # Station positions are in IMAGE PIXELS (= meters × pixelsPerUnit).
    # MapCanvas renders stations at position.x world pixels; world pixel = image pixel.
    # M is read from map settings above so positions stay correct for any floor plan.
    stations_spec = [
        # Branch A — Frame (3 steps)
        dict(name="Steel Inventory",          icon="Warehouse",       color="#64748B",
             description="Raw steel tubes and sheet stock",
             position=dict(x=5*M,  y=5*M)),
        dict(name="Tube Cutting",             icon="Scissors",        color="#94A3B8",
             description="CNC tube cutting to frame dimensions",
             position=dict(x=20*M, y=5*M)),
        dict(name="Frame Welding",            icon="Flame",           color="#F97316",
             description="MIG welding of frame triangle",
             position=dict(x=35*M, y=5*M)),
        dict(name="Frame Painting",           icon="Paintbrush",      color="#3B82F6",
             description="Powder-coat painting and quality inspection",
             position=dict(x=50*M, y=5*M)),

        # Branch B — Drivetrain (2 steps)
        dict(name="Parts Inventory",          icon="Package",         color="#F59E0B",
             description="Gears, chains, motors, and brake components",
             position=dict(x=5*M,  y=18*M)),
        dict(name="Drivetrain Assembly",      icon="Settings",        color="#D97706",
             description="Gear cluster, chain, and motor unit assembly",
             position=dict(x=20*M, y=18*M)),
        dict(name="Drivetrain QC",            icon="CheckCircle",     color="#10B981",
             description="Load test and torque verification",
             position=dict(x=35*M, y=18*M)),

        # Merge 1 — Frame Integration + 2 post-merge steps
        dict(name="Frame Integration",        icon="GitMerge",        color="#8B5CF6",
             description="Mount drivetrain into painted frame — MERGE STATION",
             position=dict(x=62*M, y=12*M)),
        dict(name="Electrical Installation",  icon="Zap",             color="#EAB308",
             description="Battery, motor controller, and wiring harness",
             position=dict(x=74*M, y=12*M)),
        dict(name="Bike Testing",             icon="FlaskConical",    color="#06B6D4",
             description="Full electronics and road-simulation test",
             position=dict(x=86*M, y=12*M)),

        # Branch C — Packaging (4 steps)
        dict(name="Packaging Depot",          icon="Truck",           color="#84CC16",
             description="Cardboard blanks, foam inserts, manuals stock",
             position=dict(x=5*M,  y=26*M)),
        dict(name="Box Manufacturing",        icon="Box",             color="#65A30D",
             description="Die-cut and fold corrugated shipping boxes",
             position=dict(x=20*M, y=26*M)),
        dict(name="Print & Label",            icon="Printer",         color="#4D7C0F",
             description="Print manuals, serial-number labels, and barcodes",
             position=dict(x=35*M, y=26*M)),
        dict(name="Accessories Packing",      icon="Gift",            color="#A3E635",
             description="Charger, tools, and quick-start guide into accessory bag",
             position=dict(x=50*M, y=26*M)),
        dict(name="Packaging Inspection",     icon="ScanSearch",      color="#22C55E",
             description="Verify box contents against checklist before merge",
             position=dict(x=62*M, y=26*M)),

        # Merge 2 — Final Packaging
        dict(name="Final Packaging",          icon="PackageCheck",    color="#EC4899",
             description="Bike into box with accessories — MERGE STATION",
             position=dict(x=91*M, y=20*M)),

        # Sink — Warehouse
        dict(name="Finished Goods Warehouse", icon="Building2",       color="#6B7280",
             description="Ready-to-ship finished e-bikes",
             position=dict(x=97*M, y=20*M)),
    ]

    sid: dict[str, str] = {}
    print("Stations:")
    for spec in stations_spec:
        s = post("/stations/", spec)
        sid[spec["name"]] = s["_id"]
        print(f"  ✓ {spec['icon']:18s} {spec['name']}")
    print()

    # ── Routes ───────────────────────────────────────────────────────────────
    routes_spec = [
        # Branch A — Frame
        ("Steel Inventory",         "Tube Cutting",              1),
        ("Tube Cutting",             "Frame Welding",             1),
        ("Frame Welding",            "Frame Painting",            1),
        # Branch B — Drivetrain
        ("Parts Inventory",          "Drivetrain Assembly",       1),
        ("Drivetrain Assembly",      "Drivetrain QC",             1),
        # Merge 1 inputs (1 frame + 1 drivetrain → 1 assembly)
        ("Frame Painting",           "Frame Integration",         1),
        ("Drivetrain QC",            "Frame Integration",         1),
        # Post-merge 1
        ("Frame Integration",        "Electrical Installation",   1),
        ("Electrical Installation",  "Bike Testing",              1),
        # Branch C — Packaging
        ("Packaging Depot",          "Box Manufacturing",         1),
        ("Box Manufacturing",        "Print & Label",             1),
        ("Print & Label",            "Accessories Packing",       1),
        ("Accessories Packing",      "Packaging Inspection",      1),
        # Merge 2 inputs (1 tested bike + 1 packaging set → 1 complete bike)
        ("Bike Testing",             "Final Packaging",           1),
        ("Packaging Inspection",     "Final Packaging",           1),
        # Sink
        ("Final Packaging",          "Finished Goods Warehouse",  1),
    ]

    print("Routes:")
    for load_name, unload_name, qty in routes_spec:
        post("/routes/", {
            "processId": pid,
            "load":     sid[load_name],
            "unload":   sid[unload_name],
            "quantity": qty,
        })
        print(f"  ✓ {load_name} → {unload_name}  (×{qty})")
    print()

    # ── Templates ────────────────────────────────────────────────────────────
    frame_fields = [
        {"key": "frame_size", "label": "Frame Size",  "type": "select",
         "options": ["XS", "S", "M", "L", "XL"],      "required": True},
        {"key": "material",   "label": "Material",     "type": "select",
         "options": ["Aluminium 6061", "Chromoly steel"], "required": True},
    ]
    drivetrain_fields = [
        {"key": "speeds",     "label": "Speed Count",  "type": "select",
         "options": ["7-speed", "9-speed", "11-speed"], "required": True},
        {"key": "motor_w",    "label": "Motor (W)",    "type": "number",
         "options": [],                                  "required": True},
    ]
    packaging_fields = [
        {"key": "language",   "label": "Manual Language", "type": "select",
         "options": ["EN", "DE", "FR", "ES", "ZH"],    "required": True},
    ]
    assembly_fields: list = []
    final_fields = [
        {"key": "serial",     "label": "Serial Number", "type": "text",
         "options": [],                                  "required": True},
        {"key": "color",      "label": "Frame Colour",  "type": "select",
         "options": ["Midnight Black", "Alpine White", "Ocean Blue", "Forest Green"],
         "required": True},
    ]

    templates_spec = [
        dict(name="E-Bike Frame",
             description="Welded and powder-coated frame, ready for drivetrain integration",
             processId=pid, startStationId=sid["Steel Inventory"],
             color="#3B82F6", fields=frame_fields),
        dict(name="Drivetrain Kit",
             description="Assembled and load-tested gears, chain, and motor unit",
             processId=pid, startStationId=sid["Parts Inventory"],
             color="#F59E0B", fields=drivetrain_fields),
        dict(name="E-Bike Assembly",
             description="Integrated frame + drivetrain unit awaiting electrification — created at merge 1",
             processId=pid, startStationId=sid["Frame Integration"],
             color="#8B5CF6", fields=assembly_fields),
        dict(name="Packaging Set",
             description="Printed box, manual, accessories bag, and charger — ready for final pack",
             processId=pid, startStationId=sid["Packaging Depot"],
             color="#22C55E", fields=packaging_fields),
        dict(name="Complete E-Bike",
             description="Fully assembled, tested, and packaged electric bicycle — created at final merge",
             processId=pid, startStationId=sid["Final Packaging"],
             color="#EC4899", fields=final_fields),
    ]

    print("Templates:")
    for spec in templates_spec:
        t = post("/lot-templates/", spec)
        print(f"  ✓ {spec['name']:22s}  starts at: {spec['description'][:50]}…")
    print()

    print("━" * 60)
    print(f"Demo seeded successfully!")
    print(f"  Process ID : {pid}")
    print(f"  Stations   : {len(stations_spec)}")
    print(f"  Routes     : {len(routes_spec)}")
    print(f"  Templates  : {len(templates_spec)}")
    print()
    print("Merge stations:")
    print(f"  • Frame Integration   — merges 1× E-Bike Frame + 1× Drivetrain Kit")
    print(f"  • Final Packaging     — merges 1× E-Bike Assembly + 1× Packaging Set")
    print()
    print("Source queues ('+create lot' enabled):")
    print(f"  • Steel Inventory   → E-Bike Frame lots")
    print(f"  • Parts Inventory   → Drivetrain Kit lots")
    print(f"  • Packaging Depot   → Packaging Set lots")
    print()
    print("Sink (warehouse, no create):")
    print(f"  • Finished Goods Warehouse")


if __name__ == "__main__":
    main()
