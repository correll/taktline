"""The runout rule: which line does a shared station feed next?

FIFO is fair to *lots*, and nobody cares about fairness to lots. A station
several lines flow through exists to keep those lines fed, so the honest
question when it frees up is not "which lot arrived first" but "which line
starves first". Each line's clock is one division:

    runout = units buffered at the next station ÷ its consumption rate

where the consumption rate is the next station's measured **line cycle time**
— the interval between its actual departures, waste included — because a
buffer is eaten at the rate work really leaves, not the rate it theoretically
could. Both numbers already exist: the buffer is the board, the rate is the
statistics page. Nothing new is recorded.

Deliberate edges, each of which is a way to give confident wrong advice:

- **A storage branch never starves.** A warehouse is meant to fill; ranking a
  line urgent because its shelf is empty would invert the accumulation
  warning's whole logic. Branches into storage are ignored, and a line whose
  only onward branch is storage gets no clock at all.
- **No measured rate → no clock.** Null is not zero (`test_metric_sanity`'s
  rule): a next station nobody has run a timer at yields `runout=None`, and
  the picker falls back to FIFO for those lots rather than sorting them on an
  invented number.
- **A fan takes the tightest branch.** Where one process leaves the station
  down several routes, the line's clock is the branch that starves first —
  min over the branches that have one.
- **Boundary links are not branches** — an ERP node cannot starve. Routes are
  read through `analysis._real_routes`, the same boundary-filtered view every
  other graph judgement uses.

Pure over `analysis.Snapshot`, like the line doctor's rules and for the same
reason: so the arithmetic is testable against hand-built lines with planted
states, without a database anywhere near it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import analysis


@dataclass(frozen=True)
class LineRunout:
    process_id: str
    process_name: str
    #: The branch this clock is read from (the one that starves first).
    next_station_id: str
    next_station_name: str
    buffer_units: int
    #: Seconds per piece at the next station; None = nobody has measured it.
    line_cycle_sec: Optional[float]
    #: Seconds until the next station has nothing left to work on. 0 = it is
    #: starving now. None = no clock (unmeasured), sort FIFO instead.
    runout_sec: Optional[float]


def station_runout(s: analysis.Snapshot, station_id: str) -> dict[str, LineRunout]:
    """Per process flowing out of `station_id`: how long until that line
    starves. Keyed by process id; a process with no non-storage onward route
    from here is absent (there is nothing downstream to starve)."""
    stations = {st.id: st for st in s.stations}
    names = {p.id: p.name for p in s.processes}

    out: dict[str, LineRunout] = {}
    for process_id, routes in analysis._by_process(s).items():
        branches = [r.unload for r in routes
                    if r.load == station_id
                    and not stations.get(r.unload, analysis.StationIn(id="", name="")).is_storage]
        if not branches:
            continue

        best: Optional[LineRunout] = None
        for next_id in branches:
            buffer_units = int((s.wip_station_process.get(next_id) or {})
                               .get(process_id, 0))
            metrics = s.metrics.get(next_id)
            rate = metrics.line_cycle_sec if metrics else None
            runout = buffer_units * rate if rate else None
            candidate = LineRunout(
                process_id=process_id,
                process_name=names.get(process_id, ""),
                next_station_id=next_id,
                next_station_name=stations[next_id].name if next_id in stations else "",
                buffer_units=buffer_units,
                line_cycle_sec=rate,
                runout_sec=runout,
            )
            if best is None:
                best = candidate
            elif candidate.runout_sec is not None and (
                    best.runout_sec is None or candidate.runout_sec < best.runout_sec):
                best = candidate
        if best is not None:
            out[process_id] = best
    return out
