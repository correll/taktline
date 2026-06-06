import type { MachineStatus } from '../../models'

export type StatusKey = MachineStatus | 'none'

export const STATUS_HEX: Record<StatusKey, number> = {
  running: 0x10B981,
  idle:    0x6B7280,
  warning: 0xF59E0B,
  fault:   0xEF4444,
  offline: 0x374151,
  none:    0x2D6EDF,
}

export const STATUS_CSS: Record<StatusKey, string> = {
  running: '#10B981',
  idle:    '#6B7280',
  warning: '#F59E0B',
  fault:   '#EF4444',
  offline: '#374151',
  none:    '#2D6EDF',
}
