# Overview

Veridion is a browser-based digital Kanban system that allows model manufacturing flow as a graph. We are using the following conventions:

Locations: this is where manufacturing activities happen. 

Lot-cards (Kanban cards): are attached to physical products. One lot card can also be attached to a lot of products, i.e. it carries the number of products. Lot-cards travel with the lots through the stations. 

Process: manufacturing is organized as a graph with locations as nodes, and transfer between locations as edges.

Products: products can be both final products as well as intermediate product. The user can create templates for the lot cards that go with the different products. Each product has an origination location that is paired with a queue. 

Queues: the leafs of the manufacturing graph serve as queues where products either originate or end up. Each location at a leaf of a tree that has no incoming edges can serve as originating location, which is tied to the product template. Each location at a leaf of a tree that has no outgoing edges doubles as a warehouse.

Merging: some products are made from precursors. These result from merging two or or more precursor products. In this case, the precursor product lot cards are discarded (or optionally put back into the queue), and a new lot card is created. Only locations at ßwhich multiple branches come together can serve as originating stations for such lot cards. Conversely, such lot cards can not be created directly, and attempting to do so will create precursor lot cards in the queues that lead up to this location.

Edge weight: edges have weights that determine how many precursor products are required for a final assembly. For example, a final assembly might require one of product A, three of product B and 10 of product C. 

Map view: the map view shows all the locations and the process graph overlaid on a PNG image of a factory floor. A "heatmap" shows how busy individual stations are. The map is either in meters or in feet and the user can specify how many pixels correspond to a unit. A scale in the lower left corner indicates the actual scale. 

Kanban view: the kanban view shows a flattened version of the process graph. with one column per location. Each column shows all the lot-cards at this location. 

Dashboards: if the browser window is in vertical orientation such as on a phone or ipad, a dashboard view is shown. The dashboard view shows all available locations and allows a user to "log in". The user then sees a single column with all the lot cards that are at this location. The user can select a lot card, chose the number of products that they work on and press start. Then, a timer starts recording the time, until the user presses stop.

Statistics: the process collects timing based on lot and per product on each station. Relevant metrics are: Takt-Time, the average time per product at each station, Overall Equipment Efficiency (OEE) as the ratio of time where the timer at a location is running vs. total time, number of transport events when lot cards travel from one location to another and overal transport in meters. 

# Engineering conventions

## Datetime / timezone handling

Motor (MongoDB async driver) returns Python `datetime` objects **without timezone info** (naive), even though MongoDB always stores in UTC. This causes two classes of bugs if not handled:

1. **Arithmetic crashes**: subtracting a naive datetime from a UTC-aware `datetime.now(timezone.utc)` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`.
2. **Browser misparse**: Pydantic serializes naive datetimes without a `Z` or `+00:00` suffix. Browsers interpret bare ISO strings as **local time**, so a user in UTC-6 sees `startedAt` as 6 hours in the future, breaking any elapsed-time display.

**Rule**: always normalize Motor-returned datetimes to UTC-aware before use. The canonical place is the `_to_session()` (and equivalent `_to_*()`) helper in each router:

```python
for field in ("startedAt", "endedAt"):
    dt = d.get(field)
    if isinstance(dt, datetime) and dt is not None and dt.tzinfo is None:
        d[field] = dt.replace(tzinfo=timezone.utc)
```

**Frontend rule**: when parsing a datetime string received from the API, append `Z` if no timezone suffix is present, so the browser always treats it as UTC:

```ts
const iso = raw.endsWith('Z') || raw.includes('+') ? raw : raw + 'Z'
const date = new Date(iso)
```

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

