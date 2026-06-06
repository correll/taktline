// ─── Primitives ──────────────────────────────────────────────────────────────

export type ID = string

// ─── Station ─────────────────────────────────────────────────────────────────

export interface StationPosition {
  x: number
  y: number
  width: number
  height: number
}

export type AdapterType = 'mock' | 'plc_modbus' | 'plc_opc_ua' | 'uav' | null

export interface Station {
  _id: ID
  name: string
  position: StationPosition
  adapterType: AdapterType
  adapterConfig: Record<string, unknown>
  description: string
  color: string | null
  createdAt: string
  updatedAt: string
}

// ─── Route ───────────────────────────────────────────────────────────────────

export interface Route {
  _id: ID
  processId: ID
  load: ID        // source station
  unload: ID      // destination station
  quantity: number
  createdAt: string
  updatedAt: string
}

// ─── Process ─────────────────────────────────────────────────────────────────

export interface Process {
  _id: ID
  name: string
  routes: ID[]
  mapId: ID | null
  description: string
  createdAt: string
  updatedAt: string
}

// ─── Lot Template ─────────────────────────────────────────────────────────────

export type FieldType = 'text' | 'number' | 'date' | 'select'

export interface FieldDefinition {
  key: string
  label: string
  type: FieldType
  options: string[]
  required: boolean
}

export interface LotTemplate {
  _id: ID
  name: string
  processId: ID | null
  startStationId: ID | null
  fields: FieldDefinition[]
  color: string | null
  description: string
  createdAt: string
  updatedAt: string
}

// ─── Card (Lot) ───────────────────────────────────────────────────────────────

export interface Bin {
  count: number
}

export interface Card {
  _id: ID
  lotTemplateId: ID
  processId: ID
  lotNum: number | null
  totalQuantity: number
  bins: Record<ID, Bin>           // stationId → Bin
  fields: Record<string, unknown>
  flagged: boolean
  description: string
  createdAt: string
  updatedAt: string
}

// ─── Machine State ────────────────────────────────────────────────────────────

export type MachineStatus = 'running' | 'idle' | 'warning' | 'fault' | 'offline'

export interface MachineMetric {
  value: number | string
  unit: string
  label: string
}

export interface MachineState {
  stationId: ID
  status: MachineStatus
  metrics: Record<string, MachineMetric>
  currentLotId: ID | null
  message: string
  lastUpdated: string
}

// ─── UAV ─────────────────────────────────────────────────────────────────────

export type UAVMissionStatus = 'pending' | 'dispatched' | 'in_flight' | 'delivered' | 'failed'

export interface UAVMission {
  _id: ID
  lotId: ID
  fromStationId: ID
  toStationId: ID
  status: UAVMissionStatus
  vehicleId: string | null
  createdAt: string
  updatedAt: string
}

// ─── WebSocket event envelope ─────────────────────────────────────────────────

export type WSEvent =
  | { type: 'machine_state'; payload: MachineState }
  | { type: 'card_update';   payload: Card }
  | { type: 'card_delete';   payload: { id: ID } }
  | { type: 'uav_update';    payload: UAVMission }
