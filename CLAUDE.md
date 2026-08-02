# Overview

Taktline is a browser-based digital Kanban system that allows model manufacturing flow as a graph. We are using the following conventions:

Locations: this is where manufacturing activities happen. 

Lot-cards (Kanban cards): are attached to physical products. One lot card can also be attached to a lot of products, i.e. it carries the number of products. Lot-cards travel with the lots through the stations. 

Process: manufacturing is organized as a graph with locations as nodes, and transfer between locations as edges.

Products: products can be both final products as well as intermediate product. The user can create templates for the lot cards that go with the different products. Each product has an origination location that is paired with a queue. 

Queues: the leafs of the manufacturing graph serve as queues where products either originate or end up. Each location at a leaf of a tree that has no incoming edges can serve as originating location, which is tied to the product template. Each location at a leaf of a tree that has no outgoing edges doubles as a warehouse.

Splitting is reversible: moving pieces **back** down a branch onto the split
location re-forms the source lot rather than moving units, because a split is a
transformation, not a move. The branch weight divides on the way back exactly as
it multiplied on the way out, and the twins on every sibling branch are consumed
in the ratio the weights describe (`cards._unsplit_back`). A bare move sent four
tubes back as four *bars* and left the offcut standing — advance those and you
get four more tubes and a second offcut, minting material on every round trip.
A partial move back (three of four tubes) is refused rather than rounded, and so
is one whose twins have already gone elsewhere.

Choice stations (`station.branchMode`): two or more outgoing routes are the SAME SHAPE for two opposite intents, so the meaning is **declared on the station**, never inferred. `'split'` (and null, the default) is a disassembly; `'choice'` is true either/or routing — every lot leaves **1:1 down the one branch the worker picks** (the operator's MOVE panel becomes one button per destination), nothing is minted or relabelled, and moving back is a plain move with nothing to un-split. Split-only meanings are refused or retired on a choice station: a branch weight is only legal when the *target* is a merge (that weight belongs to the merge), `outputTemplateId` is refused, and flipping a split to a choice strips stale branch weights/products while preserving merge-feed weights. The pull walk treats a choice fan as **additive**: a choice diamond orders the SUM of its branches' demands (each unit goes one way), where a split diamond orders the max — `merge._coalesce_sources` tags demand `via_choice`. The map and board auto-label stations MERGE / SPLIT / CHOICE (per process, distinct stations, boundary links excluded — `domain/graph.stationRoles`), the question is asked **once as a pop-up** when a station gains its second outgoing route (dismissing stores 'split'), and the answer is editable on the station and carried by the map file. Ship-or-stock is still two processes — a choice routes material, it does not change where an order completes.

Splitting: the mirror of merging. Within a process, a location with **two or more outgoing routes** (and no `branchMode='choice'` declaration) is a split — a disassembly. Advancing a lot out of it consumes the source units and mints one new lot per branch, each pinned to that branch's originating template and inheriting the lot code, with the branch's edge weight saying how many pieces it yields (one steel bar → four tubes + one offcut). Each branch may name the product it yields (`route.outputTemplateId`) — a disassembly turns one product into several, so a battery teardown yields modules, busbars and cables rather than three copies of one thing; the merge downstream matches that product as the branch's precursor. Settings → Templates offers the choice directly: at a station that is both a split target and a merge, a template can be "loc3" (assembled here) or "loc3 (from loc1)" (disassembled from that branch), and saving binds it to the branch. Without a declared product it is inferred. A branch that lands on a **merge station** is then pinned to its *source* station's template instead of the target's: the merge matches precursors by their template's origin, and the target's own template is the one it mints assemblies with — a piece wearing it would be invisible as a precursor and would masquerade as finished output. Alternative "either/or" routing is **not** a split: it is modelled as a **separate process**, so branches only ever count within the card's own process. That scoping is global: merges, pulls, unmerges, the precursor gate, route-following on `/advance` and weight eligibility are all judged **within one process** — a sibling process feeding a shared physical station neither becomes a merge partner nor has its queues seeded by a pull (a station hosting two processes' merges resolves deterministically: most feeds, then process id). And only **source material** fans out: a card already wearing one of the branches' product templates *is* a piece of a previous disassembly, so it relocates 1:1 along the chosen branch — which is what lets surplus (two spare modules of the eight a teardown yields) be set aside to a warehouse without being relabelled or duplicated. Pulling through a split recombines demand — four tubes order one bar, and a diamond (one source feeding two branches that merge again) pulls a single source lot.

Precursors may not leave a merge station unmerged. `cards._assert_not_unmerged_precursor` refuses it on `/advance` **and** on the board's `/move` — but only for *forward* moves (`_is_forward_move`), so dragging a lot back to correct a mistake, or to start an unmerge, still works.

The gate is judged purely on **the topology of the card's own process**: within one process, two feeds converging on a location *is* a merge, because that is what a merge is. A shared paint booth is not a counter-example — it is two *processes* sharing a location, and each has a single feed, so process scoping already lets work through. It briefly also required that a product template start there, excused as protecting the booth; it protected nothing and left a hole exactly where the product is newest, since until someone named the assembly every precursor could walk out of the station meant to consume it.

When two processes both merge at one bench, resolution is no longer blind: the worker's **selected cards name the process** (a selection spanning two processes is refused), an explicit `processId` may be passed, and AUTO prefers — in the deterministic order — a process that can actually assemble now. Before this, the tie-winner won every call: the losing line's merge was unreachable, its worker's selection 400'd, and AUTO consumed the winner's material.

Merge order is **FIFO**: `_cards_with_bin` returns candidates oldest-first, and the proposal and the consumption both read that one order so they cannot disagree. The query used to have no ORDER BY and both callers sorted by bin count (smallest first, to avoid breaking a full lot) — but lots at one station usually hold identical counts, so that sort was one long tie decided by whatever physical row order Postgres returned, and where counts did differ it actively reached past older material. A running line showed module lots aging 10–14 minutes at the bench while lots minted seconds earlier were consumed in front of them.

A merge **sees through pass-through stations**. A station with exactly one
production route in and one out — a transport leg, a staging area, an
inspection bench — does not transform anything: what leaves it is what entered
it. `_precursor_template_ids` therefore walks the feed back along such a chain
and accepts products originating anywhere on it. Without that,
`iron ore → shipment → smeltery` broke the merge outright, because nothing
originates at a shipment leg and so the branch accepted no product at all — the
furnace sat with iron ore and carbon on it reporting nothing to assemble, and
the only visible thing to blame was the assembly template, which was fine. The
walk stops **in front of** any station that branches (checked on the *previous*
station's outgoing count, not the current one's): from Module Test the chain
reaches Teardown, which is a split, so the busbar feed cannot reach past it and
start eating modules. A declared branch product stops it too — that feed has
already said what it carries.

Merging: some products are made from precursors. These result from merging two or or more precursor products. In this case, the precursor product lot cards are discarded (or optionally put back into the queue), and a new lot card is created. Only locations at ßwhich multiple branches come together can serve as originating stations for such lot cards. Conversely, such lot cards can not be created directly, and attempting to do so will create precursor lot cards in the queues that lead up to this location.

Weight ownership at a combined split+merge: a split branch can land on a merge station (the battery example's wash — Teardown's busbar branch plus a cleaning-solution feed both enter Busbar Clean), and one number cannot mean yield AND consumption. **The split owns the weight**: the branch still yields its declared pieces per source unit, and the merge consumes ONE piece per assembly from a split-fed branch — a weight's meaning must never flip because someone drew a new feed into its target (that flip is exactly what once double-booked the ×2 and reported phantom accumulation upstream). A merge that truly consumes several split pieces per assembly is modelled with a buffer station between. `merge._feed_consumption` is the single authority — split/merge/pull/unmerge/preview and the frontend accumulation math all read it or mirror it. Corollary (`_validate_output_template`): a branch into a merge may not declare the merge's own assembly template as its product — a piece wearing it would masquerade as finished output — so the wash's input is a distinct "dirty" product, typically with no start station at all (a pure intermediate pollutes no origination lookup). The pull walk (`_leaf_sources`) is demand propagation over the process DAG, downstream-first: each fan combines its branches' demands by what it is (split → max, one unit feeds every branch; choice → sum, each unit feeds one), which replaced a per-path recursion whose terminal dedup could not tell WHY two demands reconverged. Accumulation warnings name the process (`Module Test (LFP) +5`), a choice's storage branches pull nothing, and a station with its own branch to storage is never flagged — it has the relief valve the warning exists to recommend. `tests/test_cleaning_line.py` pins the wash; `tests/test_fuzz_line.py` is a seeded random-abuse walk asserting after every op that a 4xx changed nothing, no unit sits on a partner node, and plain moves conserve material — its first two runs found a self-move that minted units and a pull aimed at a partner node that seeded a lot there.

Edge weight: a weight only means something where the graph branches. On a **merge feed** (a route into a station with 2+ incoming routes) it is how many precursor units one assembly consumes — a final assembly might need one of product A, three of product B and 10 of product C. On a **split branch** (a route out of a station with 2+ outgoing routes) it is the mirror image: how many pieces one upstream unit becomes, so advancing a lot along it multiplies the card (one steel bar cut into four tubes) and pulling four tubes orders exactly one bar. Elsewhere a lot moves 1:1 and the weight is forced to 1. 

Accumulation warning: the map compares, per process and per cycle, how many units the weights deliver to a location against how many the next step consumes. Where more arrives than leaves — loc1 --(x3)--> loc2 --> loc4 delivers three but the merge takes one — the map names the location and the surplus so the extra can be routed to a warehouse. Merge stations (their inputs are consumed there) and warehouses (meant to fill up) are never flagged.

Warehouses / storage: a location **declared** as storage (`station.isStorage`, a checkbox on the location). Finished goods rest there by design, so it is excluded from the heatmap (including its scale, which it would otherwise flatten), from accumulation warnings, and reports no OEE — shelf time is not utilisation. Cycle time and throughput are still measured.

This used to be *inferred* from the graph — "receives routes but sends none" — which quietly swallowed every leaf where real work happens: a final test bench, a paint booth, the last cell on a line all vanished from the heatmap, hiding a queue exactly where one matters most. Storage is a fact about the location, not its shape, so it is now declared. The migration marks every location that was a leaf at upgrade time, so no existing heatmap changes; leaves added afterwards default to being work locations. It can also be declared mid-graph, for a buffer that has outgoing routes but is still a shelf.

Map view: the map view shows all the locations and the process graph overlaid on a PNG image of a factory floor. Each **process draws its routes in its own colour**, with a legend naming them (`domain/processColors.ts`). Where two processes connect the same **pair** of locations — in either direction — the lines are **shifted apart perpendicular to the run**, centred on the true path, with the normal taken in a canonical frame so a route and its reverse move to opposite sides rather than each to its own left — drawn on top of each other the second line is invisible, and so is the fact that there are two, which no colour can fix. Weight badges are sorted above every edge line (a later sibling's dashes otherwise cross the number out), and when several lanes of one pair carry weights the badges are staggered *along* the run — the lane gap is a few px against a 9+ px badge radius, so the perpendicular shift alone cannot separate them. The palette is three colours, not more: coral is the brand, green/amber/red are andon and the violet ramp is the heatmap, and what is left cannot yield a fourth that survives colour-vision deficiency. It is validated all-pairs against each theme's own surface (day ΔE 10.2 deutan / 16.7 normal; night 12.2 / 19.9), and the legend means identity never rests on hue alone. Slots are hashed but **de-collided** (`processColorSlots`): a plain hash puts two processes on one colour once in three, which defeats the whole feature. A "heatmap" shows how busy individual stations are. The map is either in meters or in feet and the user can specify how many pixels correspond to a unit. A scale in the lower left corner indicates the actual scale. 

Kanban view: the kanban view shows a flattened version of the process graph. with one column per location. Each column shows all the lot-cards at this location. 

Dashboards: if the browser window is in vertical orientation such as on a phone or ipad, a dashboard view is shown. The dashboard view shows all available locations and allows a user to "log in". The user then sees a single column with all the lot cards that are at this location. The user can select a lot card, chose the number of products that they work on and press start. Then, a timer starts recording the time, until the user presses stop.

Statistics: the process collects timing based on lot and per product on each station. Three timing terms are deliberately kept apart, because conflating them is the most expensive confusion in the product:

- **Takt time** — the beat the line is *meant* to hold: available time ÷ customer demand. A **target the user sets**, per process (`process.desiredTaktSec`, Settings → Processes → "Desired takt time"). Never measured, never inferred; null until someone sets it.
- **Cycle time** — how long the work actually takes: what Start/Stop records, divided by the units in the lot (`cycleTimeSec`). This is what used to be called "takt time" in the UI and API, and the rename is complete — the map's beat is the **cycle pulse**, the operator's gauge is the **cycle arc** (`globalSettings.showCycleArc`).
- **Line cycle time** — the actual exit rate: the interval between a station's departures, **per piece** (`lineCycleTimeSec`, `sessions._line_cycle_times`). The clock starts when work *could* have moved — a shift opening, from `core.schedule.shift_starts` — and re-anchors at every departure, so a lot finished after hours is charged to the next shift rather than to the night. Without that reset the first departure of a Monday carries the whole weekend and the number is worthless. A lot of ten leaving counts as ten pieces. Departures include the per-branch events a **split** records — pieces leaving a teardown are the departures that matter most in a reman shop — and a **handoff**, which is how goods leave a make-to-order line (without it the shipping bench, the one station you most want an exit rate for, reported none; a plain deletion is scrap and still does not count, since it records no station to leave from). The clock also never starts before the station's **first activity** — a shift opening earlier than that is time before the line existed, and charging it made every station on a new company report thousands of seconds per piece while pieces visibly left each minute. The metric is computed even for stations **without any work session**, since it is built from departures, not sessions — and `/sessions/stats` now *lists* such stations too, or a shipping bench where nobody runs a timer is missing from the statistics table entirely. 30-day lookback.

The gap between cycle time and line cycle time is the waste, in seconds: work that takes 2 minutes but only ships every 9 is queueing, blocking or transport, and speeding up the operator wins nothing. The Statistics table shows both side by side and tints line cycle time amber when it exceeds cycle time by >50%.

Also collected: Overall Equipment Efficiency (OEE) as the ratio of time where the timer at a location is running vs. open work time, number of transport events when lot cards travel from one location to another and overall transport in meters. 

## Taking the statistics away, and starting them over

`GET /reports/export.xlsx` (reports scope / member session) returns the whole
picture as a workbook — **About, Stations, Work sessions, Lot history, Lots
now, Orders**, one sheet each, with `?window=` narrowing the Stations sheet the
same way the page's trend picker does. xlsx rather than CSV because a CSV is
one flat table of strings: it cannot carry six tables, and every value arrives
as text that Excel then guesses at — turning lot code `0042` into `42` and
disagreeing about decimal separators between locales. The workbook carries
typed cells (timestamps are datetimes; OEE is a fraction *formatted* as a
percent, so it still works in a pivot), frozen headers and filters, and opens
natively in Excel, LibreOffice, Numbers and Sheets.
`tests/test_export_and_reset.py` opens the produced file and reads cells — a
corrupt xlsx is still a 200.

`POST /admin/reset-statistics` (super-admin) clears the measured history: work
sessions and card events, which is everything the Statistics view computes
from. It deliberately does NOT touch stations, routes, processes, products, the
lots on the floor or production orders — `/admin/reset` is the one that clears
those, and conflating them would make "clean up my test data" delete a
customer's factory. Both live behind the same document icon the floor plan uses
for its line file.

## UI vocabulary

The UI says **station** (not "location") and **Floor plan** (not "Map") — the
nav entry, the settings tab, tour, manual, statistics headings and backend
error messages all follow. Internal names were already `station`; routes stay
`/map`. "Heatmap" and "value stream map" are terms of art and keep their names.
The line export/import lives behind the file icon in the floor plan's
lower-right corner (super-admin), not in Settings — the file carries the whole
line, not just that tab's configuration.

## Running the line for real (`backend/simulate_line.py`)

A live simulator that staffs the line from N tablets against a **running
server**, over the public HTTP API — log in, start a work session, wait out the
cycle, stop, then advance / merge / hand off. Because it uses the same
endpoints the Operator view does, every movement broadcasts on the websocket
(an open board shows lots moving without a reload) and every session feeds the
real cycle-time / line-cycle-time / OEE statistics. Defaults are 8 tablets, a
5 s cycle, one order a minute, one hour.

    .venv/bin/python simulate_line.py                      # fresh dev company + the shipped line
    .venv/bin/python simulate_line.py --email you@… --company "My line"

Tablets are independent coroutines with their own `operatorId`, so they race
for the same lots exactly as real tablets do; a losing race is a 4xx and the
tablet retries next tick (serialising them would prove nothing). Each reads its
own station's role from the graph: merge → work a cycle and merge the
**proposal**; choice → deal units by what the downstream merge actually needs,
surplus to the storage branch; split → one advance fans out; a sink link →
hand off. At a merge station only lots whose template *starts there* may be
advanced — the parts waiting to be consumed are not movable work, and a tablet
that tried would spin on 409 forever. `--mistakes` makes a worker occasionally
carry only part of a lot; the line self-heals, which is the point.

Cycle times come from a **pace model** (`Pace`), not a flat jitter band, because
a flat band made every station report the same number and every window match
the one before — the statistics page had no spread, no bottleneck and no trend
to show. Four independent sources, each of which a real floor has: a fixed
factor per **station** (a teardown bench is not a scanner), a smaller one per
**operator**, a **lognormal** per piece (task times are right-skewed, not
uniform — `--variance` is its sigma), and a rare **hiccup** (`--hiccup`) that
multiplies a cycle severalfold, which is what actually pushes line cycle time
away from cycle time. On top, `--drift` moves the whole shift's pace from start
to end so consecutive windows differ and the trend arrows have a direction. The
random parts and the station factors are normalised against the loaded line, so
`--cycle 5` still means about five seconds on this floor rather than five
times whatever the station names happened to hash to.

# Engineering conventions

## Persistence layer (PostgreSQL + SQLAlchemy async)

The backend uses **PostgreSQL** via **SQLAlchemy 2.0 async ORM + asyncpg**, with **Alembic** for migrations. (It was previously MongoDB/Motor.)

- **ORM tables** live in `app/db/tables.py`; **Pydantic models** in `app/models/` remain the API request/response schemas. Each router has small `_to_*(row)` helpers that map an ORM row to its Pydantic model.
- **IDs** are UUID primary keys (app-generated via `uuid.uuid4`), serialized to the API as opaque `_id` strings. The frontend treats them as opaque, so nothing there changed. Router path params / FK fields arrive as strings and are parsed with `parse_uuid` / `require_uuid` / `optional_uuid` from `app/db/connection.py`.
- **Transactions**: `get_session` (the FastAPI dependency) wraps each request in one transaction — commit on success, rollback on any exception. This is what makes multi-write endpoints (`/merge`, `/cards/{id}/move`, session start auto-close) atomic. Endpoints `session.add(...)` / mutate ORM objects and `await session.flush()`; the commit happens once at request end.
- **Constraints move into the DB**: FKs with `ON DELETE CASCADE`/`SET NULL`, `CHECK` constraints (`quantity >= 1`, route `load <> unload`, card `totalQuantity >= 1`, status/unit enums), and a unique `(processId, load, unload)` route edge. The one invariant still enforced only in Pydantic is `sum(card.bins) <= totalQuantity` (a `CHECK` can't sum JSONB without a subquery).
- **Audit log exception**: `card_events.cardId` is a plain indexed string with **no FK** — it must retain the `'deleted'` event recorded *after* a card is removed.
- **Schema changes**: edit `app/db/tables.py`, then `alembic revision --autogenerate -m "..."` and `alembic upgrade head`. `DATABASE_URL` (env, default `postgresql+asyncpg://localhost:5432/taktline`) drives both the app and Alembic.

## Production orders & ERP integration (outbox)

`ProductionOrder` is the anchor for external integration and the completion loop; **connectors** map ERP/store orders onto it — no ERP code lives in the core. The integration surface is a **frozen canonical contract** so connectors stay thin: `POST /orders` (release), `GET /orders/outbox?status=pending` + `POST /orders/outbox/{id}/ack` (drain completions), `POST /orders/cancel` (cancel by `{source, externalRef}`).

- **Release** (`POST /orders`): wraps the merge **pull** — whenever the product's origin has upstream feeds — a merge assembling it or a disassembly yielding it — it seeds precursor lots at the leaf source queues (ordering 8 modules orders the one pack they are torn from); only a true source product (origin is a leaf queue) is minted directly. Every created lot is tagged with `card.orderId` and stamped with a **lot code** (`card.lotNum`) taken from the order: an explicit `lotCode` if the connector sent one (a human ERP reference like Shopify `#1001` / Odoo `MO/00042`), else the `externalRef`, so every physical Kanban card traces back to its ERP order (bare manual releases with neither get a generated code). The code carries through the merge — when every consumed precursor shares one code the finished assembly keeps it. **Idempotent** on `(companyId, source, externalRef)` — a redelivered ERP webhook returns the existing order, never a second run. Core release/cancel logic is factored into `orders._release_order` / `orders._cancel_order` (reused by the endpoints, CSV import, and cancel-by-ref).
- **Attribution through merges**: `merge.perform_merge` propagates `orderId` onto the new assembly card when all consumed precursors agree on one order (ambiguous → null). This is how a finished good stays attributed across multi-level merges.
- **Completion**: `cards._record_order_progress` (called from `move_card` and `advance_card`) fires when order-tagged units arrive at a **finished-goods leaf** (a station with no outgoing routes). It credits `quantityDone`, flips status to `completed`, and writes an **`IntegrationOutbox`** row — in the *same transaction* as the move (transactional outbox = no lost/duplicate "done" events, which in an ERP means double inventory posting).
- **Delivery**: a connector polls `GET /orders/outbox?status=pending&source=<its own source>`, delivers to the ERP, then `POST /orders/outbox/{id}/ack` — or `POST /orders/outbox/{id}/fail`, which counts the attempt and parks the event as `failed` after `MAX_DELIVERY_ATTEMPTS` (10). Both the **source filter** and the **fail counter** exist to protect the drain: events no connector can ack (a manual UI release, a CSV import) stay pending forever, and the window is `LIMIT 500`, so without them a backlog of un-ackable or undeliverable rows eventually hides a connector's own completions. `/orders/{id}/cancel` (or `/orders/cancel` by ref) scraps in-flight lots and emits `order.cancelled`; ack is idempotent and re-cancelling is a no-op, so redelivered webhooks are safe. `POST /orders` answers **201** when it released the order and **200** when it returned an existing one, which is how a polling connector tells a real release from its own re-post.

### Integration locations — where work enters and leaves

The integration boundary used to be **implicit in the graph's shape**: any leaf
with no incoming routes could originate lots, and *any* leaf with no outgoing
routes completed orders. Nothing knew a dock belonged to Shopify, so a
completion could only be addressed to whichever connector released the order —
which is why a manual/CSV release produced an event (`source='manual'`) no
connector could ack, and why the outbox needs a source filter and fail counter
to stop those orphans burying real completions.

A station may now be **bound to a partner** (`stations.integrationProvider` +
`integrationRole` ∈ `source|sink|both`; catalog `core/integrations.py`, frontend
registry with brand colours and letter marks `domain/integrations.ts`), created
from Settings → Integrations → *Integration locations*.

**Integration nodes never hold cards.** This is the whole model, and it is now *enforced* at every endpoint that places units (`cards._assert_units_stay_off_partner_nodes`: create, update-bins, move, advance) — a handoff link is a real route row, so `/advance` used to walk finished goods onto the ShipStation node, where they credited the order as an unbound leaf and bypassed the handoff. A handoff link is also excluded from split detection, or one production route plus one handoff read as a split and minted a phantom piece onto the node. Moving *out* of a bound station stays possible as the rescue path.

- An **edge touching a bound station is a boundary link, not material flow**,
  and is excluded from every piece of graph reasoning — `_incoming_routes` and
  `_outgoing_count` in `merge.py` (which covers merge detection, split
  detection, the pull walk and the release decision) and `_process_edges` in
  `routes.py` (the cycle check). Without the last one, the commonest ERP wiring
  there is — Odoo raises demand *and* takes the goods back — is impossible to
  draw, because it looks like a loop.
- **Source = demand.** An ERP node wired to a queue makes a release fire the
  same pull the "create precursors" button does: the lots appear **at the
  queue**. No release-path change was needed — excluding the demand edge from
  `_incoming_routes` keeps the queue a leaf, so the existing mint-at-origin
  branch runs.
- **Sink = an explicit handoff.** `POST /cards/{id}/handoff` — "Send back to
  Odoo", "Send to ShipStation" — consumes the units and credits the order.
  Shipping is a decision, not an arrival: crediting when a card *reached* a
  location would report work finished while it sat on a bench. A location with
  a handoff link is therefore skipped by `_record_order_progress`, or every
  unit would count twice.
- **Capability is enforced**: `PROVIDERS` maps a partner to what it can *be*.
  ShipStation is `sink` — a shipper cannot raise demand — so binding one as a
  source is a 400, not a dead control.
- **Completion fans out** to the releasing connector *and* the partner whose
  node the goods left through, deduped when equal, with `sinkProvider` in the
  payload. Connectors need **no change** (they already filter on
  `payload.source`), and a manually released order handed to ShipStation
  becomes drainable by ShipStation.
- **An unbound leaf still completes on arrival** — the deliberate migration
  rule, so binding is purely additive.
- Bound locations are excluded from the heatmap, accumulation warnings, OEE and
  the takt pulse (`_warehouse_ids` unions them in). Related fix:
  `/sessions/stats/{id}` used to report `isWarehouse: false` for any station
  with no sessions yet.
- Marks are one or two letters in the partner's colour, not logos — trademarked
  artwork, illegible at 14px, re-licensed at every rebrand. Two letters where
  the initial collides (Shopify `S` vs ShipStation `SS`).

**The ERP's data rides on the card** (`order.attributes`): a release may carry a
flat scalar map — customer, due date, ship-to, priority (≤32 keys, values ≤500
chars) — which is stored on the `ProductionOrder`, stamped onto **every seeded
lot's `fields`**, and echoed back to the sink in the outbox payload. The
invariant, enforced by `tests/test_integration_data.py`: **no transformation
drops the data.** Merge re-stamps from the order when attribution is
unambiguous (single source of truth — precursor cards' own fields describe
parts, not the finished good); split pieces and unmerged precursors inherit
`fields` *and* `orderId` (unmerge dropping the orderId would strand the order at
partially-done). Sink payloads carry `lotCode`, `attributes`, and `units` — the
units in *this* event, because `quantityDone` is cumulative and useless for
building one shipment. An **orderless handoff** (hand-made lot, surplus) emits
`lot.handoff` addressed to the sink; the connector core acks unknown event
types without delivering, so this is additive on the wire. CSV import maps any
unrecognised column into attributes — the spreadsheet's extra columns end up
printed on the card. Shopify's connector maps `customer` and `shipTo`; other
clients pass an `attributes` dict on their order rows and the core forwards it
(only when present — the strict mocks refuse unknown kwargs). The lot detail
modal shows non-template keys as a read-only ORDER DATA block.

**One node or two:** a partner that both raises demand and takes goods back can
be one node with two links or two separate nodes — both wirings work. The node
wears direction arrows read from the drawn links (↓ = raises demand into the
line, ↑ = receives finished goods), so either wiring is readable at a glance.
Boundary nodes are also excluded from the Lots board's columns (cards never sit
on them, so the column would be permanently empty).

**Where an integration may attach** (`routes._check_boundary_placement`): an
order asks for **one finished product**, so a demand link must target the
location where *that product is made* — a station some lot template starts at
(Settings → Templates). For an assembled product that is the merge location;
for one made from raw material it is the queue, so both pass the same test.
Creating the order there starts a pull, which orders every precursor down to
the material queues by itself. An earlier version required the link to land
where *material enters*, which was wrong: a line can have many material entry
points and only one finished product, so pointing the ERP at an entry point
picks an arbitrary branch and says nothing about what was ordered. The check is
skipped while a company has no products defined, so a line can be drawn before
its products are named. Handoffs are the mirror — a link into an integration may only leave the **end of its own process's flow**: a station that sends work nowhere else *in that process* (and once a process hands off at a station, adding an onward production route to it in the same process is refused — the mirror rule). **Ship-or-stock is two processes, not a branch**: one pulled by the warehouse (make-to-stock, completing on arrival there) and one pulled by the shipper (make-to-order, completing at the handoff), sharing the same physical stations with each flow deterministic in its own process — the same convention as all either/or routing. Every placement judgement is scoped to the link's own process; an earlier storage carve-out that allowed both destinations inside one process smuggled in exactly the either/or the convention forbids, and has been removed.

**Setup information is in the app**, not in a wiki: `domain/integrations.ts`
carries a per-provider `setup` spec — every value to fetch from the partner,
*where in their UI to find it*, the env var it goes into, what to configure
inside the partner, and the caveats. Selecting an integration location on the
map shows it (`StationIntegrationPanel`) along with its wiring and activity.
`connectors/tests/test_config_contract.py` fails if those env names drift from
what `config.py` actually reads — the failure mode it prevents is someone
following our instructions, setting the wrong variable, and getting an auth
error that points at the ERP rather than at us.

Product → template mapping still lives in the **connector's** config: the ERP
owns the BoM, Taktline owns the flow graph.

### Scoped API keys & the auth model for integrations

`ApiKey` rows (`tk_…`, SHA-256 hashed at rest, prefix shown for display, revocable, company-scoped) authenticate integrations — no admin login. `deps/auth.require_scope(scope, session_role=…)` is the dependency factory: it accepts a Bearer/`X-Api-Key` key carrying `scope`, **or** a session (a key resolves its own company, so `X-Company-Id` is ignored and tenant isolation is automatic). A key with no cookie skips CSRF. Scope catalog (`models/apikey.AVAILABLE_SCOPES`, surfaced at `GET /api-keys/scopes`):
- `orders` — release / drain / cancel (`require_orders_access` = `require_scope("orders")`).
- `cards:advance` — `POST /cards/{id}/advance` (**scan-to-advance**: a scanner/print station hits it after reading a lot label) and `GET /cards/{id}/label` (ZPL with a Code128 of the card id).
- `reports` — read-only BI feeds `GET /reports/orders` + `/reports/throughput` (Power BI/Grafana).

Other on-ramps: **CSV import** (`POST /orders/import`, multipart) releases a batch from a spreadsheet — each row in its own SAVEPOINT so one bad row is reported, not fatal; idempotent per `(source, externalRef)`.

### Connectors (`connectors/taktline_connect/`)

A standalone package (its own venv; only `requests` + `requests-oauthlib`), **not** imported by the backend. `core.Connector` is ERP-agnostic: each cycle it **releases** (`list_orders` → `POST /orders`), **cancels** (optional `list_cancellations` → `POST /orders/cancel`, the Shopify/Woo refund path), then **drains** completions. An ERP client is one file implementing `list_orders` (+ optional `list_cancellations`/`mark_done`/`cancel`) and a `build(cfg)`; parsing is factored into a pure `orders_from_*` for unit tests. Shipped: `odoo`, `netsuite`, `shopify`, `woocommerce`, `qbo`, `xero`, `shipstation`, `generic` (poll any JSON endpoint) — run `python -m taktline_connect <name>`. Products map by config (`PRODUCT_MAPPING`: ERP ref → Taktline template **id**), so a key only ever needs the `orders` scope. Tests: `tests/test_core.py` (orchestration), `test_clients.py` (parsing), `test_integration_http.py` (all eight real clients + `Connector` over a live in-process mock of the ERP + Taktline, incl. pagination, OAuth refresh/401-retry and token rotation). The HTTP mock is deliberately **strict** — it enforces each ERP's real calling convention rather than accepting whatever the client sends, because a lenient mock is how the Odoo client shipped with every `execute_kw` call malformed.

Two invariants every client must hold: **walk all pages** (page one alone silently starves the backlog, and an order that never releases never leaves the ERP's open set either), and **make `mark_done` idempotent** (delivery is at-least-once, so a lost ack re-sends it — NetSuite checks for an existing assemblyBuild first, or the finished goods post to inventory twice). `sync_orders` guards each order individually: one rejected order must not abort the cycle, or the releases behind it and the whole completion drain stop until a human notices.

- **Boundaries**: the ERP owns the BoM + inventory; Taktline owns the flow graph + execution. Keep them joined only through the product→template mapping (in the connector), not by auto-generating the graph from the BoM.

## Order tracking, and the supply chain either side of it

Two features that are one idea: **the same link, pointed in both directions.**
Downstream it answers your customer's "where is my order?"; upstream it answers
yours. A shop that publishes status to its customers and reads its suppliers'
sits in a chain it can see through, and each end of that chain is a company who
now has a reason to be on Taktline — which is the growth loop, and the only one
here that is not a favour being asked.

**The customer half** (`core/tracking.py`, `routers/tracking.py`). One URL
resolves **either an order or a lot card**, because "where is job 4471?" is
asked about the thing on the floor and an order only exists if an ERP or a CSV
made one — a hand-made lot was untrackable, which is most lots on most floors.

- `/o/{id}/{token}` — a server-rendered page carrying Open Graph tags, because
  LinkedIn's crawler does not run JavaScript, and `noindex`, because a customer's
  order is not for search results.
- `/track/{id}/{token}` — the JSON. **Not** `/api/track`: `/api` exists only in
  the Vite dev proxy, and shipping it that way would 404 in production.
- `/o/{id}/{token}/qr.svg` — the printable code. One sticker on the bin serves
  both readers: a customer scanning it gets progress, and an operator **signed in
  to Taktline** gets a *Start work* button straight to that lot at that bench
  (`_viewer_is_a_member` returns a card/station handle only for a member — the
  page is otherwise identical, so nothing leaks to the customer holding it).

The token is **HMAC-derived, never stored**: no column, no enumeration, and
nothing to migrate. Steps come from the graph with boundary links filtered out —
an ERP node is not a manufacturing step, and counting it inflated the
denominator so every job read as further behind than it was. Completion is
derived from *position* (the lot is at the last step), never from `flagged`.
Off by default, per company (`globalSettings.orderTracking`).

**The supplier half** (`core/network.py`, `routers/network.py`). Paste a
supplier's tracking link onto a lot or onto a goods-in station and their
progress renders on your board (`SupplierLinkField`); invite one from
Settings → Integrations.

- **The fetch happens in the browser, never on our server.** The URL comes from
  a user, and a server that follows user-supplied URLs is the whole SSRF class —
  doing it client-side avoids the class rather than fencing it. Cross-origin
  requests carry no cookies, so it can only ever read the public view, which is
  exactly the intent. Making that fetch *possible* takes
  `core/public_cors.PublicReadCORSMiddleware`, added **last so it wraps the
  ordinary `CORSMiddleware`**: the strict origin allowlist answers preflights
  itself and 400s a stranger before any route runs, so headers set on the route
  are never reached. It stamps `*` and **strips** allow-credentials — that
  pairing is the security property, not a shortcut, and browsers reject the two
  together. The dev proxy needs `/track` too, or the panel fetches Vite's
  index.html and reports every supplier unreachable in dev only.
- **Any host is allowed, deliberately.** A supplier may run Taktline on their own
  hardware; restricting this to taktline.com would break the loop for exactly
  the customers who bought the on-premise tier. Safety comes from
  `parse_tracking_url` (http(s) only, a tracking path only, no credentials in
  the URL, query and fragment stripped) plus React escaping what comes back.
- **An invitation grants the inviter nothing** — attribution, never access. It
  is the property a supplier will ask about before signing up, and
  `test_supplier_network.py` pins it: the inviter is not a member of the
  accepted company and reads 403 on everything.
- **No referral fee, no credit, no discount.** Paying for introductions turns a
  supplier's inbox into spam addressed by a customer they cannot ignore, and
  changes the ask from "here is a better way to answer me" into "do me a favour
  so I get a month free". The visibility is the reward.
- **Not carried by `/map-io`.** A line file is meant to be shared — it is the
  shipped examples, the support hand-off, the "send me your line" — and a
  supplier's tracking URL is a bearer credential for *their* order status. The
  export schema is `extra="forbid"` on a fixed field list, so this is excluded by
  construction rather than by remembering; it is written down because the next
  person to add a station field will wonder why it is missing.
- The marker rides in `sessionStorage`, not through the component tree: a
  company is created on a *later page load* than the click (email verification
  happens in between), and a supplier may read the manual first. It is attributed
  at **both** doors — `POST /companies/` and the adopt-sandbox signup path, which
  is the one the invitation email actually recommends.

One wrinkle worth knowing: `PUT /cards/{id}` and `PUT /stations/{id}` both build
their patch with `if v is not None`, so a null is indistinguishable from an
omission and **no nullable field there could ever be cleared**. `supplierUrl`
reads `model_fields_set` instead. Scoped to that one field on purpose — for
every other column, null already means "leave it alone", and changing that
wholesale would make a partial update erase what it did not mention.

## What the tests are for

The suite is 331 backend tests plus a frontend one, and it is organised around
the ways this codebase has actually been wrong rather than around its modules.
Five of these files were written after auditing where the bugs came from, and
each of them found one on its first run:

- **`test_fuzz_line.py` carries a material ledger.** After every operation it
  checks the delta against the three shapes a step is allowed to have — a 1:1
  transfer, a forward fan (a split minting `n × weight` down every branch), or
  a backward fan (the mirror). Anything else is material from nowhere. It used
  to assert conservation only between two non-fan stations, which is the one
  case that has never been wrong. **Measure the coverage, not just the pass:**
  the walk crossed a fan once in 220 random steps and never at all on the
  battery line, so it now aims at fans deliberately and asserts it got there.
- **`test_inverses.py`** does a thing and undoes it — split/un-split,
  advance/merge/unmerge — exactly on a purpose-built line and by product across
  every shipped example. The two halves are written by different code and read
  the weights for opposite reasons, which is how they came to disagree.
- **`test_concurrency.py`** fires genuinely parallel requests (threads, so
  separate event loops and separate transactions). The code is full of
  `with_for_update` and nothing exercised any of it. A race usually returns two
  200s and corrupts the floor, so the assertions are about the *outcome* being
  one of the legal serial ones.
- **`test_tenancy_sweep.py`** and **`test_authz_matrix.py`** enumerate the
  app's own routing table, so an endpoint added next month is covered the day
  it lands. The tenancy property is **indistinguishability**, not a status
  code: several endpoints answer 2xx for another company's id and are perfectly
  safe doing it, and what must never happen is a *different* answer for a real
  foreign id than for one that exists nowhere. The authz expectations are
  **derived from each route's declared dependency**, so the only way to be
  wrong is to declare the wrong thing.
- **`test_graph_reads.py`** keeps an inventory, with a reason per entry, of who
  may read the route table without the boundary-filtered helpers. Four bugs
  have had one shape — a graph question that counted an edge touching an
  integration node — and the rule lived only in people's heads.
- **`test_migrations.py`** runs the migrations on a scratch database. The suite
  builds its schema from the ORM metadata, which is the one path production
  never takes, so nothing had ever executed a `downgrade`.
- **`contracts/station-roles.json`** is the backend's own view of the shipped
  lines, checked in where the frontend's `graph.test.ts` reads it. The frontend
  re-derives graph judgements the backend owns — it must, to draw labels
  without asking about every station — and the two have drifted three times.
  Neither side can move alone now.

A second round went after *safety* rather than correctness — the ways a wrong
answer reaches the floor or a customer loses something:

- **`test_fuzz_line.py` also checks product identity now.** The ledger counted
  units by place, which is only half of what is conserved: a lot card carries a
  physical label, and relabelling one mislabels a real part while conserving
  the count perfectly. So a surviving card id must keep its product and its
  line, one operation may never consume across two processes, and a minted lot
  must belong to a line its inputs came from. On the battery line the two
  chemistries are physically interchangeable and electrically incompatible.
- **`test_destructive.py`** deletes things a running floor is still using, and
  checks the blast radius of every destructive endpoint against a second
  company that must come through untouched. It also pins that `/map-io/import`
  clears the floor — not a bug, but it is the closest thing to a restore and it
  is not one.
- **`test_metric_sanity.py`** asserts every reported number stays in its
  physical range under randomised work, and that **null is not zero**: `oee: 0`
  reads as *idle machine, go and look*, `oee: null` reads as *nobody ran a
  timer here*, and they send someone to different ends of the building.
- **`test_limits.py`** covers what no reasonable person types — quantities past
  int32, a split whose multiply overflows, a line 200 stations deep, and a
  stack of diamonds with billions of distinct paths. Scale matters because the
  server is shared: one customer's pathological graph must not stall it for
  everyone.

Ceilings live in `models/common.py` (`MAX_UNITS`, `MAX_WEIGHT`), deliberately
far below int32 so that the split multiply has headroom and the refusal happens
where the person can still see what they typed.

Two habits worth keeping. **Guard the guard:** a glob that matches nothing, a
sweep whose substitution silently skipped every route, a ledger that only ever
saw the easy shape — each turns a green suite into a decorative one, so each of
these files asserts its own coverage. And **a test that passes before the fix
is worth nothing**: check it fails first.

## The manual (`help/UserManual.tsx`)

Five chapters ordered by difficulty rather than one long scroll — **Basics**
(what the app is, core concepts, setting up and running a line), **The lean
method** (five steps, TIMWOOD, muda/mura/muri, the three timing numbers),
**The improvement toolkit** (5S, standard work, SMED, jidoka, heijunka, PDCA,
five whys, Pareto…), **Flow science** (Little, Kingman, balance efficiency,
flow efficiency, Shewhart, matched sets, monuments, theory of constraints) and
**Integrations**. One page buried the basics under queueing theory once there
were thirty sections.

Deep links survive the split: `manualAnchors.ts` maps every anchor to its
chapter, so `openManual('kingman')` switches chapter *then* scrolls. That file
also maps every **lean-tip category** to a section, and
`tips.test.ts` fails if a category has no home, if an anchor is in no chapter,
or if a registered anchor has no heading carrying it — a "Read more" that lands
nowhere teaches the reader not to click.

Equations are typeset in plain CSS (`help/Equation.tsx`): stacked flexbox
fractions, italic serif variables, and a `Term` component that draws the
labelled underbrace turning Kingman's formula into a sentence — utilisation ×
variability × work time. KaTeX would be ~280 KB and its own stylesheet for four
formulas, and would fight the theme tokens in dark mode.

**Vocabulary is enforced: lots contain products.** WIP, throughput, cycle time
and every equation count *products*; a lot is the card a group of them travels
on.

## The line doctor (`core/analysis.py`, `GET /analysis/`)

A deterministic expert system that reads a line and says what is wrong with it,
in the manual's vocabulary. **No model, no network, nothing leaves the
building** — which is what makes it safe to point at a customer's production
data, and testable against lines with planted faults.

Two kinds of finding, and the first matters most. **Topology** findings need no
measurements at all: a line that can never complete an order, a split
delivering six pieces into a bench that consumes one, a station every order
must cross, one move far longer than the rest. Those are visible the moment the
graph is drawn — which is exactly when a new user has no data and most needs to
be told their line cannot work. **Timing** findings need sessions and
departures: the constraint (slowest line cycle time), the cycle-vs-line-cycle
gap (the manual's own framing of where waste lives), takt adherence, balance,
WIP concentration read through Little's law, unevenness (Mura) from the spread
of individual sessions, and operator spread as the sign that standard work is
missing.

**Every rate is normalized to finished-unit equivalents** (`_per_unit_need`,
the same walk the accumulation warning uses). Busbar Clean touches 32 pieces
per pack, so its per-piece interval is structurally ~32× shorter on a healthy
day — conservation of flow equalizes *finished-unit* throughput along a steady
line, never piece throughput. Raw per-piece comparison names the end of any
split-heavy line the constraint, forever. The constraint, demand-limited,
over-takt, balance and flow-efficiency rules all work in per-unit terms.

The timing rules carry the science they rest on: the constraint is
**triangulated** (slowest normalized exit + queue in front + highest share of
open hours + starvation downstream) and its advice follows Goldratt's focusing
steps — exploit before elevate. The **waiting gap** is differentiated into
queueing vs starvation by whether WIP is standing at the bench, because the
remedies point in opposite directions. **Over-takt** does the arithmetic
(⌈work-per-unit ÷ takt⌉ benches, OEE-adjusted when known); **no-headroom**
warns at ≥85% of takt with the Kingman load/(1−load) queue multiplier;
**imbalance** reports balance efficiency (Σwork ÷ n·max) and names a concrete
pair of benches whose combined work still fits under the slowest step;
**flow-efficiency** is Little's law per value stream — lead time = WIP ÷
throughput against touch time, the number value-stream mapping exists to
expose; **unmatched-feeds** flags a merge paced by its slowest branch (matched
sets, not full bins); **shared-monument** names a machine serving several value
streams at the highest utilisation on the floor; and **uneven-work** separates
special-cause spikes from common-cause spread (Shewhart), because chasing the
wrong one moves nothing.

Findings carry the TIMWOOD name and a manual anchor, and every number is on the
finding, so a client renders values from data rather than parsing prose.
`readiness` is `no-data` / `partial` / `ready` — and saying *"nobody has run a
timer, so there is nothing to say about pace"* is a feature, not a fallback: a
report that invents advice from three sessions is worse than one that admits it
cannot see.

`tests/test_analysis.py` builds lines whose fault is known and asserts the
diagnosis names it — and asserts a **healthy line stays quiet**, because a
checker that reports something on every input is a horoscope. It caught its
first bug immediately: the WIP rule gated on total stock including shelves, so
a full warehouse opened the question and answered it about the two units
actually in production.

The UI is a large, transparent bulb in the top right (`help/LineDoctor.tsx`),
dark until there is enough data and glowing after. It is clickable while dark
on purpose. The map's process legend steps aside for it: a global control owns
its corner, and that is the legend's problem to solve, not the control's.

## Undo / redo (`core/undo.py`, `POST /undo` · `/redo`)

**Stations and routes. Deliberately NOT lots.** A lot card records a physical
fact — where the material actually is. Undoing a move does not carry the
material back down the shop, so the board would start disagreeing with the
floor, which is the one thing it exists not to do. Drawing the line is
configuration: a mis-clicked delete destroys work with no physical counterpart,
and putting it back is simply correct. (An earlier pass built this for lot
movements; that was the wrong scope, and the physical-fact argument is why.)

Server-side, because a client-side stack is only correct with one author. Two
people can edit one line from different rooms, and the route you deleted a
minute ago may since have been redrawn.

**A snapshot, not a hand-written inverse per edit.** Hand-writing "the inverse
of deleting a station" keeps a second description of what a station is, which
drifts the first time a field is added. `undo_entries` holds
`beforeState`/`afterState` for **only the rows an edit changed**, found by
diffing a snapshot either side, so no endpoint declares what it is about to
touch. Restores order themselves around the foreign keys: routes deleted before
stations, stations recreated before routes, and a deleted row comes back under
its own id so a template's start station still resolves.

**The rule that makes a blunt restore safe:** an edit may only be undone while
the rows it touched are *still as it left them*. Anything else is refused as a
**409** with a sentence someone can act on ("those lots have moved on since") —
the request was reasonable and the line moved. Stacks are **per user** (25
deep); doing something new drops the redo branch.

## Commit before the response (SESSION_SCOPE)

Every `Depends(get_session)` carries `**SESSION_SCOPE` (`scope="function"`). FastAPI closes *request*-scoped dependency stacks only **after** the response has been sent, so a commit living there races the client's next request — a tablet 404s the card whose creation it just saw succeed, or a fresh login 401s on its first authenticated call (reproduced ~2 times per 120 writes on a keep-alive connection). Function scope closes the stack **before** the response bytes leave the server: commit first, respond second. The first declaration FastAPI solves decides which stack the shared session lands in, so one stray unscoped `Depends(get_session)` reintroduces the race — `tests/test_reman_line.py::test_every_session_dependency_commits_before_the_response` walks the app and fails on any.

## Datetime / timezone handling

Postgres `TIMESTAMP WITH TIME ZONE` columns come back **tz-aware** through asyncpg, so the naive-datetime normalization the old Motor code needed (`.replace(tzinfo=timezone.utc)` in every `_to_*()` helper) is **no longer required** — datetime arithmetic and Pydantic serialization (`+00:00` suffix) just work.

**Rule**: keep datetime columns as `DateTime(timezone=True)` and generate values with `utcnow()` (`datetime.now(timezone.utc)`) so everything stays UTC-aware end to end.

**Frontend rule (belt-and-suspenders)**: when parsing a datetime string from the API, append `Z` if no timezone suffix is present. With tz-aware backend datetimes this is now a no-op, but it costs nothing and guards against any bare string:

```ts
const iso = raw.endsWith('Z') || raw.includes('+') ? raw : raw + 'Z'
const date = new Date(iso)
```

## Authentication & multi-tenancy

The app is authenticated and multi-tenant. Users belong to one or more **companies** with a per-company **role**, one of three tiers ordered by privilege — `user` < `admin` < `super_admin` (see `deps/auth.ROLE_RANK`); every domain row carries a `companyId`.

- **Sessions**: httpOnly cookie (`taktline_session`) holding an opaque token; only its SHA-256 hash is stored (`auth_sessions`). Rotated on login, revoked on logout/password-reset. Config, hashing (argon2id), the mailer, CSRF, and rate limiting live in `app/core/`.
- **CSRF**: double-submit. `app/core/csrf.py` middleware requires header `X-CSRF-Token` to equal the readable `taktline_csrf` cookie on unsafe methods **when a session cookie is present** (public auth calls are exempt). The frontend axios interceptor (`src/api/client.ts`) attaches it automatically.
- **Request dependencies** (`app/deps/auth.py`), composed with `get_session`:
  - `get_current_user` — resolves the session cookie → `User` (401).
  - `get_active_company` — validates the `X-Company-Id` header against membership → `CompanyContext(company_id, role, user)` (403 non-member).
  - `require_admin` — `CompanyContext` but 403 unless `role ≥ 'admin'` (admin **or** super_admin); `require_super_admin` — 403 unless `role == 'super_admin'`. Both delegate to `ctx.at_least(role)` over `ROLE_RANK`.
  - `load_membership(session, user, company_id, min_role=)` — same rank check for endpoints whose company comes from the URL path (companies/members/invitations); member management passes `min_role="super_admin"`.
- **Scoping pattern** (every domain router): reads use `Depends(get_active_company)` + `.where(Row.companyId == ctx.company_id)`; path fetches also verify `row.companyId == ctx.company_id` → **404 on mismatch** (no cross-tenant probing). Writes use `Depends(require_super_admin)` for config / structural ops, `Depends(require_admin)` for lot & order management, or `get_active_company` for operator actions; new rows set `companyId=ctx.company_id`.
- **Role matrix** (three tiers):
  - **super_admin** — all config (stations/routes/processes/templates/floorplan/settings/API keys) + member management, card create/**delete**/**update**, unconstrained `POST /cards/{id}/move` (the lot-board drag, forward **or** backward), and `POST /cards/{id}/unmerge` (backward-dragging a merged assembly dissolves it into precursors — recreated at each direct-upstream station's originating template, or, if it has none, at the leaf source queues feeding that branch). The company creator is the super_admin.
  - **admin** (middle) — everything a user can do **plus** create lots (`POST /cards`), pull precursors (`POST /merge/{station}/pull`), and release/cancel production orders (`POST /orders`, `/orders/cancel`, `/orders/import`). No config, no member management, no structural lot ops (move/unmerge/delete). A production-planner / line-lead tier.
  - **user** — read-only on the Lots board (cards aren't draggable; attempting a drag flashes the lock) but on the **Operator** view may run work sessions (`/sessions/*`), set a card's working/done state (`PATCH /cards/{id}/status`, status-only), **merge** (`POST /merge/{station}` — assembling precursors is the first step of working at a merge station; the worker selects the precursor lot cards to consume (`cardIds` in the body) or presses AUTO to let the system pick — no body), and **advance a lot forward** along a defined route via `POST /cards/{id}/advance` (route-constrained). The operator lot picker also lists lots still at the stations **feeding** the current one; tapping one switches the view to that station (finished lots land straight on the MOVE panel) so a worker can go fetch material themselves.
  - A company-scoped **API key** authenticates as the `admin` tier (release orders / reports / scan-to-advance), never super_admin. **Server-side checks are authoritative** — frontend gating (`useRole()` → `isSuperAdmin` / `canManageLots` / `canEdit`) is UX only.
- **Guards**: the last **super_admin** can't be removed or demoted; `admin/reset` and all deletes are company-scoped.
- **Input hardening**: all queries are SQLAlchemy-parameterized (no raw SQL with user input) and the React frontend has no `dangerouslySetInnerHTML` (user text is auto-escaped). Floor-plan uploads are restricted to a raster-image extension whitelist (`map_settings._ALLOWED_IMAGE_EXT`, no `.svg`/`.html`) so a spoofed content-type can't get served as active content (stored XSS) from `/uploads`. Outbound-email subjects strip CR/LF to prevent header injection via user-controlled values (e.g. company name).
- **card_events**: carries `companyId` set at write time (still no FK to the card, so audit rows survive deletion — see [[persistence-layer]] note above).
- **Dev flow**: `TAKTLINE_DEV=1` returns verification/invite links in API responses and enables `POST /auth/dev/bootstrap` (a verified admin + company in one call), used by `seed_demo.py` and tests. Never enable in production.
- **Frontend**: `AuthProvider` bootstraps `/auth/me`; `RequireAuth`/`RequireAdmin` guard routes; the active company is a header (persisted to `localStorage['taktline.activeCompanyId']`, read by the client + WS). The `/ws/events` handshake authenticates via the session cookie + `?companyId=` and broadcasts per company.

### Public sandbox (landing-page "five-minute tutorial")

`POST /auth/sandbox` (unauthenticated, rate-limited) mints a throwaway user + company so a visitor can try Taktline without signing up. The account is flagged `users.isSandbox` and is **permanently restricted server-side** — `deps/auth.ensure_full_account` 403s floor-plan uploads, invitations, API keys, order release/import, and creating further companies; `deps/auth.ensure_sandbox_quota` caps rows per sandbox company (`SANDBOX_LIMITS`: stations/cards/templates/processes) so the public endpoint can't be used as free storage. Accounts self-expire after 7 days (`core/sandbox_gc.py`, swept at startup + daily), and the visitor's line **persists** until then: `POST /auth/sandbox` is idempotent (an existing sandbox session resumes its own company rather than minting a new one) and a sandbox session idles for the same 7 days instead of the usual 8 hours, so "try it" survives a night. The in-app logo links to `/`, which shows sandbox visitors the marketing site — they are still prospects — while real accounts are redirected into the app. Frontend: a standing "create a free account" chip in the topbar, and locked Settings tabs (Map / Members / Integrations) that route to `/signup` — UX only, the server is authoritative.

### Offline resilience (reads only — never writes)

Tri-state connection indicator (live / amber reconnecting / off) with backoff retry. Company-scoped **read** snapshots go to `localStorage` (`store/offlineCache.ts`) and are served when a fetch fails at the network level (or 502/503/504), with a banner naming the snapshot's age; a service worker (`public/sw.js`) caches the app shell + hashed assets so a reload during an outage still renders. **Mutations are never queued or replayed** — they fail loudly, because silent replay would reorder lot movements. Snapshots (and cached floor plans) are wiped whenever the server confirms the session is gone (logout or a real 401) but kept through network failures — that's the whole feature.

### Per-company usage metering

`usage_counters` (API requests + WS messages per calendar month) is accumulated in memory and flushed every 30 s (`core/usage.py`). **Attribution happens in `deps/auth` after membership/API-key verification, never from the raw `X-Company-Id` header** — otherwise anyone could inflate another tenant's meter (regression-tested in `tests/test_sandbox.py`).

### Platform staff (customer service) — orthogonal to tenant roles

Instance-level tier for support, entirely separate from company roles: **owner** (emails in the `PLATFORM_OWNER_EMAILS` env / `backend/.env` — deliberately env-only, no API can mint one) and **support** (`users.platformRole`, grantable only by an owner via `PUT /platform/users/{id}/platform-role`). All `/platform/*` endpoints (`routers/platform.py`) are session-only (never API keys) and return **404 to non-staff**; deps are `require_platform_staff` / `require_platform_owner`.

- **Impersonation** is an explicit time-boxed `SupportGrant` (default 60 min, max 8 h): `get_active_company`, `load_membership`, and the WS handshake fall back to an active grant with role `super_admin` when membership is missing. `/auth/me` surfaces grant companies flagged `impersonated: true` so the switcher/banner ("Supporting <name> · End") just work.
- **Destructive ops**: `DELETE /platform/companies/{id}` needs the exact name in `confirmName`; `DELETE /platform/users/{id}` may remove a company super_admin (deliberately bypassing the tenant-side last-super-admin guard) but never an owner or yourself.
- **Everything is audited** in `platform_audit` (no FKs — rows survive actor/target deletion).
- **Client crash reports**: the frontend error boundary POSTs every caught
  render error to `POST /client-errors/` (no auth required — a 401 on the
  report would lose the crash twice; attribution is session-verified or absent,
  never taken from the raw header) and stashes it in
  `localStorage['taktline.lastError']`. Staff read them at
  `GET /platform/client-errors` (newest first, `?companyId=` filter). FK-free
  rows, 30-day rolling retention enforced at write time, hard truncation +
  10/min/IP rate limit.
- **Metrics**: `GET /platform/status` (uptime, req/min ring buffer from `core/traffic.py`, live WS connections, session/work/event counts); `GET /platform/companies` adds per-company activeUsers, devices (live sockets), and monthly `usage_counters` (API requests + WS messages, accumulated in-memory in `core/usage.py`, flushed every 30 s).
- Frontend: `/platform` route (`RequirePlatformStaff`, UX-only), nav entry appears when `user.platformRole` is set.

## Motion (`src/motion/`)

Every animation reports something the data actually says. The rule that shapes
all of them: **never fake a path or a period.**

- **`motion.store.ts`** derives *what happened* from what changed. The wire
  protocol only carries `card_update` / `card_delete` with the whole card, so
  the observer diffs each card's bins against its previous copy and names the
  transition: lost at A + gained at B → a **transit**; gained with no previous
  copy → an **appearance** (origin genuinely unknown); several consumed at X +
  one new card at X → a **merge**; one consumed at X + several new elsewhere →
  an **unmerge**. Changes are batched (`BATCH_MS`) because one merge arrives as
  several messages, and a bulk resync (`BULK_THRESHOLD`) is skipped — a
  reconnect refetch is not movement. The "have we loaded yet" guard is a
  `primed` flag, **not** "is the previous map empty": unmerging the last
  assembly on a line empties the store for one tick, and the emptiness test
  swallowed the first precursor recreated after it.
- **Board** (`useLotFlip`): 180ms FLIP between columns, flown as a **clone** in
  a fixed overlay — each column is its own `overflow-y: auto` scroller, so a
  plain transform is clipped at the column edge and the travel is lost. A card
  with no known previous position fades in over 150ms where it is. New cards
  are held invisible for `SETTLE_MS` first, because at layout time "a new card"
  is ambiguous until the observer has classified the batch it arrived in.
- **Map** (`MotionLayer`): a token runs the real edge geometry, in the **lot's**
  colour (never brand coral, which everywhere else means "the app is doing
  something"). Duration is `clamp(400, 120·log2(1+metres), 900)` from the floor
  plan's own scale, which is what makes transport distance legible and the
  transport-metres metric believable.
- **Takt pulse**: each station pulses at its measured takt, opacity 0.14→0.75,
  ease-in-out. Periods come from **one shared compression factor**, never a
  per-station clamp — clamping each station independently maps every real takt
  to the same period and destroys the only thing the display is for, which is
  whether the line is *in step*. Ratios survive; the factor and the verdict are
  shown in the legend. Phase is anchored to the wall clock so every station and
  every tablet share one beat. A station without enough sessions does not pulse.
- **Operator takt arc** (`showTaktArc`, **default off**, per company): pace
  against the **station's** takt, never the operator's, and nothing extra is
  recorded. Over 100% it shifts to the starved colour and says "often the sign
  of a constraint here" — information about the line, not an accusation.
- `prefers-reduced-motion: reduce` disables all of it; state still updates and
  the pulse ring settles at its own midpoint.

## WebGL is not guaranteed

PixiJS 7 has no canvas renderer, so `autoDetectRenderer` **throws** when it
cannot get a WebGL context. That exception escapes into React's render, the
error boundary catches it, and the entire view is replaced by an apology —
which is how the **public landing page** broke for a crawler (`Mozilla/5.0
(compatible; Dataprovider.com)`), reported by the client-error pipeline.

It is not only bots: privacy extensions block WebGL to defeat fingerprinting,
GPU blocklists and remote desktops disable it, and locked-down office PCs are
exactly the machines a shop-floor prospect browses from.

So every Pixi surface asks first (`components/demo/webgl.ts::hasWebGL`,
memoised, releases its probe context):

- **`FlowScene`** (landing hero + manual figures) draws the same scene in SVG
  instead — background, heat, routes and weight badges; the station tiles were
  always HTML. Static on purpose: the animation was never the message.
- **`MapCanvas`** skips the Stage and says what is missing. Station tiles are an
  HTML overlay, so locations and lot counts still work; the floor plan, routes
  and heatmap do not.

Verified with `getContext('webgl*')` stubbed to null: no crash screen, the SVG
scene renders, no canvas is attempted, and the page keeps its content — while a
browser with WebGL still gets the real canvas.

## What crawlers see

The landing page is an SPA, so a bot that does not run JavaScript used to get an
empty `<div id="root">`. Four things now carry the story without it:

- **`<noscript>`** — the same pitch in plain HTML: what Taktline is, what it
  does, how it is priced, links to the manual and signup.
- **JSON-LD** (`SoftwareApplication`) — name, category, price, feature list and
  audience, in a form machines parse rather than guess at.
- **`public/robots.txt`** — crawl freely; the signed-in routes are disallowed to
  save crawl budget, not to hide anything (they all need a session anyway).
- **`public/sitemap.xml`** — `/`, `/manual`, `/signup`, `/login`.

`PixiBoundary` backs up the WebGL probe: the manual stacks several animated
figures on one page and browsers cap live WebGL contexts at roughly 8–16, so a
Stage can fail for reasons the probe cannot predict. One figure falling back to
SVG costs a figure rather than the page.

**Crash reports can be dismissed** (`DELETE /platform/client-errors/{id}`, or
`?message=` for every copy of one message — the same crash from twenty browsers
is twenty rows saying one thing). Staff-only, audited, idempotent.

## The map as a file (`/map-io`)

`GET /map-io/export` serializes the **line definition** — stations (with
positions, storage flags, integration bindings), processes (with desired takt),
products (with fields), routes (with weights and declared branch products), and
the map scale — as a versioned JSON document; `POST /map-io/import`
**replaces** the current line with one (super-admin; sessions/lots go with it,
child-before-parent like `/admin/reset`; `card_events` and the floor-plan image
survive). Settings → Map has the buttons.

A file is data, never instructions — four walls: strict Pydantic schema with
`extra="forbid"` and hard caps; every id re-minted server-side from opaque
local refs; enums allow-listed (providers, roles, field types) and free text
stored inert; and the same graph rules as the editor, run in the same order
(production routes, then boundary links, then weights — the mirror rule makes
creation order matter). One transaction: a failing file leaves the old line
untouched. `examples/` ships three lines, each a different SHAPE rather than a re-skin:
`battery-remanufacturing.json` (a split whose weights multiply, into a merge),
`cut-and-sew-sweatshirts.json` (a wide four-branch fan into a deep finishing
chain, where one branch belongs to only one of the two processes), and
`window-fabrication.json` (two parallel chains converging on a merge that
carries the ratios). The battery one came out of the exporter; the other two are
authored by `backend/make_examples.py`. `tests/test_example_lines.py` walks the
whole folder — imports each, round-trips it through the exporter, and releases
an order into it — and `tests/test_fuzz_line.py` runs its random-abuse walk over
all three, so a rule that only held for the shape it was written against fails
loudly.

## Map scale calibration

The map view renders the floor plan sprite at its **raw image pixel dimensions** (`naturalWidth × naturalHeight`). Station positions are stored in real-world units (meters or feet). The `pixelsPerUnit` setting tells the map how many raw image pixels equal one real-world unit.

**Rule**: `pixelsPerUnit` must equal the scale factor `M` used when generating the floor plan PNG — i.e. how many pixels per meter (or foot) the image was drawn at.

For the E-Bike demo floor plan (`generate_floorplan.py`):

```
M = 36  →  pixelsPerUnit = 36  (36 image pixels = 1 meter)
```

**How `mapWidthPx` / `mapHeightPx` are captured**: `MapConfigTab` reads `img.naturalWidth` / `img.naturalHeight` on image load and stores them as `mapWidthPx` / `mapHeightPx` in the database. `MapCanvas` then sizes the PixiJS sprite at exactly those pixel dimensions in world coordinates. This makes `pixelsPerUnit` screen-independent — it must match the generator's `M`, not any CSS or display size.

**Station position units**: `station.position.x` / `.y` are stored in **image pixels** (= world coordinates), **not** in meters. `MapCanvas` renders stations at `position.x` directly with no conversion. To place a station at `(x_m, y_m)` meters, store `position.x = x_m * M` (e.g. 35 m × 36 = 1260 px). `seed_demo.py` reads `M` from `GET /map-settings/` at startup (`pixelsPerUnit`) so positions stay correct for any floor plan scale.

**Common mistake**: storing positions in meters (small values like 5–97) causes all stations to appear packed in the top-left corner of the canvas. If stations cluster near the origin after a seed run, check that positions are multiplied by `M` before being sent to the API.

