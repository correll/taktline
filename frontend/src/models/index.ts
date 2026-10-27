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
  icon:  string | null
  /** Bound integration partner — set when this station is where work enters
   *  or leaves the business rather than a place manufacturing happens. */
  integrationProvider: string | null
  integrationRole: 'source' | 'sink' | 'both' | null
  /** Storage rather than work — finished goods rest here by design, so it is
   *  kept out of the heatmap, reports no utilisation, and is never flagged for
   *  accumulating. A property of the station, not a shape in the graph: a
   *  final test bench is a leaf that very much does work. */
  isStorage: boolean
  /** A supplier tracking link for the whole queue that lands here. */
  supplierUrl?: string | null
  /** What two or more outgoing routes mean here. 'split' (and null, the
   *  default): a disassembly — one lot fans out to every branch at once.
   *  'choice': either/or routing — each lot moves 1:1 down the one branch the
   *  worker picks. Same shape, opposite meaning, so it is declared. */
  branchMode?: 'split' | 'choice' | null
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
  outputTemplateId?: ID | null   // product this split branch yields (disassembly)
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
  /** The beat this line is meant to hold, in seconds: available time ÷ demand.
   *  A target someone sets — null until they do. Compare against measured
   *  cycle time; never confuse the two. */
  desiredTaktSec: number | null
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
  // Human lot code (e.g. "E4096A") — user-defined at creation or generated;
  // kept by every piece when a lot is split apart.
  lotNum: string | null
  totalQuantity: number
  bins: Record<ID, Bin>           // stationId → Bin
  fields: Record<string, unknown>
  flagged: boolean
  description: string
  status: 'idle' | 'working' | 'done'
  orderId?: ID | null
  /** Read-only link for the customer who ordered this lot. Always present; the
   *  page only answers while the company has customer order tracking on. */
  trackingUrl?: string | null
  /** A *supplier's* tracking link — the mirror of `trackingUrl`. Validated
   *  server-side before it is stored, and fetched from the browser only. */
  supplierUrl?: string | null
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
