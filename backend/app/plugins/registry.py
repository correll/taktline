from typing import Dict, Type, Optional, Callable, Awaitable
from .base import StationAdapter
from .mock_adapter import MockAdapter
from ..models.machine_state import MachineState, StationCommand

# Register new adapter types here
ADAPTER_CLASSES: Dict[str, Type[StationAdapter]] = {
    "mock": MockAdapter,
    # "plc_modbus":  ModbusAdapter,   # Phase 4
    # "plc_opc_ua":  OpcUaAdapter,    # Phase 4
    # "uav":         UAVAdapter,       # Phase 5
}

BroadcastFn = Callable[[MachineState], Awaitable[None]]


class PluginRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, StationAdapter] = {}
        self._broadcast: Optional[BroadcastFn] = None

    def set_broadcast(self, fn: BroadcastFn) -> None:
        self._broadcast = fn

    async def register(self, station_id: str, adapter_type: str, config: Dict) -> None:
        cls = ADAPTER_CLASSES.get(adapter_type)
        if not cls:
            raise ValueError(f"Unknown adapter type: {adapter_type!r}")
        if station_id in self._adapters:
            await self.unregister(station_id)
        adapter = cls(station_id, config)
        adapter.set_state_callback(self._on_state)
        self._adapters[station_id] = adapter
        await adapter.connect()

    async def unregister(self, station_id: str) -> None:
        adapter = self._adapters.pop(station_id, None)
        if adapter:
            await adapter.disconnect()

    async def send_command(self, station_id: str, command: StationCommand) -> bool:
        adapter = self._adapters.get(station_id)
        if not adapter:
            return False
        return await adapter.send_command(command)

    async def notify_lot_arrive(self, station_id: str, lot_id: str, lot_data: dict) -> None:
        adapter = self._adapters.get(station_id)
        if adapter:
            await adapter.on_lot_arrive(lot_id, lot_data)

    async def notify_lot_depart(self, station_id: str, lot_id: str) -> None:
        adapter = self._adapters.get(station_id)
        if adapter:
            await adapter.on_lot_depart(lot_id)

    async def start_all(self) -> None:
        pass  # adapters are loaded from DB in main.py lifespan

    async def stop_all(self) -> None:
        for station_id in list(self._adapters):
            await self.unregister(station_id)

    async def _on_state(self, state: MachineState) -> None:
        if self._broadcast:
            await self._broadcast(state)


plugin_registry = PluginRegistry()
