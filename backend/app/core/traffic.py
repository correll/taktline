"""In-process web-traffic counters for the platform dashboard.

A tiny per-minute ring buffer updated by an HTTP middleware in main.py.
Deliberately in-memory: it answers "is the platform busy right now / over the
last hours", resets on restart, and adds no I/O to the request path. History
that must survive restarts belongs in a real metrics stack, not here.
"""

import time
from collections import deque
from typing import Optional

WINDOW_MINUTES = 180


class TrafficStats:
    def __init__(self) -> None:
        self.started_epoch: float = time.time()
        self.total: int = 0
        # deque of [epoch_minute, count], newest last
        self._buckets: deque[list[int]] = deque(maxlen=WINDOW_MINUTES)

    def hit(self) -> None:
        minute = int(time.time() // 60)
        if self._buckets and self._buckets[-1][0] == minute:
            self._buckets[-1][1] += 1
        else:
            self._buckets.append([minute, 1])
        self.total += 1

    def per_minute(self, minutes: int = 60) -> list[dict]:
        """The last `minutes` one-minute buckets (gaps filled with 0)."""
        now_minute = int(time.time() // 60)
        counts = {m: c for m, c in self._buckets}
        return [
            {"minute": m, "requests": counts.get(m, 0)}
            for m in range(now_minute - minutes + 1, now_minute + 1)
        ]

    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_epoch)


traffic: Optional[TrafficStats] = TrafficStats()
