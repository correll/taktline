from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, Awaitable
from ..models.machine_state import MachineState, StationCommand

StateCallback = Callable[[MachineState], Awaitable[None]]


class StationAdapter(ABC):
    """
    Contract every hardware driver must implement.

    Subclass this for each physical device type: PLCs, CNCs, conveyors, UAV dispatchers.
    The registry wires up the state callback; adapters call _emit_state() whenever
    the machine's condition changes.
    """

    def __init__(self, station_id: str, config: Dict[str, Any]) -> None:
        self.station_id = station_id
        self.config = config
        self._on_state_change: Optional[StateCallback] = None

    def set_state_callback(self, callback: StateCallback) -> None:
        self._on_state_change = callback

    async def _emit_state(self, state: MachineState) -> None:
        if self._on_state_change:
            await self._on_state_change(state)

    # ── Required ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> bool:
        """Open the connection to the physical device. Return True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection cleanly."""
        ...

    @abstractmethod
    async def read_state(self) -> MachineState:
        """Return the current machine state (called on-demand or from a poll loop)."""
        ...

    @abstractmethod
    async def send_command(self, command: StationCommand) -> bool:
        """Send a control command. Return True if acknowledged."""
        ...

    # ── Lifecycle hooks (optional overrides) ─────────────────────────────────

    async def on_lot_arrive(self, lot_id: str, lot_data: Dict[str, Any]) -> None:
        """Called when a card's bin count goes from 0 → >0 at this station."""
        pass

    async def on_lot_depart(self, lot_id: str) -> None:
        """Called when a card's bin count goes from >0 → 0 at this station."""
        pass
