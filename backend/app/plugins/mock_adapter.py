import asyncio
from typing import Dict, Any
from ..models.machine_state import MachineState, StationCommand, MachineMetric
from .base import StationAdapter
from ..models.common import utcnow


class MockAdapter(StationAdapter):
    """
    Simulates a machine with realistic-looking metrics.
    Useful for dev, demo, and integration testing without real hardware.

    Config keys (all optional):
      poll_interval_s  – seconds between state broadcasts (default 2.0)
      fault_rate       – probability [0–1] of a random fault per poll (default 0.01)
    """

    def __init__(self, station_id: str, config: Dict[str, Any]) -> None:
        super().__init__(station_id, config)
        self._running = False
        self._status: str = "idle"
        self._cycle_count = 0
        self._poll_task: asyncio.Task | None = None

    async def connect(self) -> bool:
        self._poll_task = asyncio.create_task(self._poll_loop())
        return True

    async def disconnect(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

    async def read_state(self) -> MachineState:
        return MachineState(
            stationId=self.station_id,
            status=self._status,  # type: ignore[arg-type]
            metrics={
                "cycles": MachineMetric(
                    value=self._cycle_count,
                    unit="",
                    label="Cycle Count",
                ),
            },
            lastUpdated=utcnow(),
        )

    async def send_command(self, command: StationCommand) -> bool:
        if command.type == "start":
            self._running = True
            self._status = "running"
        elif command.type == "stop":
            self._running = False
            self._status = "idle"
        return True

    async def on_lot_arrive(self, lot_id: str, lot_data: Dict[str, Any]) -> None:
        await self.send_command(StationCommand(type="start"))

    async def on_lot_depart(self, lot_id: str) -> None:
        self._cycle_count += 1
        await self.send_command(StationCommand(type="stop"))

    async def _poll_loop(self) -> None:
        interval: float = self.config.get("poll_interval_s", 2.0)
        fault_rate: float = self.config.get("fault_rate", 0.01)
        while True:
            await asyncio.sleep(interval)
            if self._running and random.random() < fault_rate:
                self._status = "fault"
                self._running = False
            state = await self.read_state()
            await self._emit_state(state)
