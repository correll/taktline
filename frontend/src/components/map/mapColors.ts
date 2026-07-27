import type { MachineStatus } from '../../models'

export type StatusKey = MachineStatus | 'none'

export const STATUS_HEX: Record<StatusKey, number> = {
  running: 0x639922,
  idle:    0x888780,
  warning: 0xEF9F27,
  fault:   0xE24B4A,
  offline: 0x4A4741,
  none:    0x8A8781,
}

export const STATUS_CSS: Record<StatusKey, string> = {
  running: '#639922',
  idle:    '#888780',
  warning: '#EF9F27',
  fault:   '#E24B4A',
  offline: '#4A4741',
  none:    '#8A8781',   // no adapter → neutral (brand coral never on the map)
}
