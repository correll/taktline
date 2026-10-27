/**
 * Where everything in the manual lives — anchors, chapters, and the mapping
 * from a lean-tip category to the section that explains it.
 *
 * A module of its own, with no React and no store, so the tests can assert
 * coverage — every tip category has a home, every "Read more" lands on a
 * heading that exists — without importing the manual component, which drags
 * in Pixi and a store that touches localStorage at module load.
 */

export const CHAPTERS_META = [
  { id: 'basics', title: 'Basics', level: 'Start here' },
  { id: 'lean', title: 'The lean method', level: 'Foundations' },
  { id: 'toolkit', title: 'The improvement toolkit', level: 'Intermediate' },
  { id: 'science', title: 'Flow science', level: 'Advanced' },
  { id: 'integrations', title: 'Integrations & ERP', level: 'Reference' },
] as const

export type ChapterId = (typeof CHAPTERS_META)[number]['id']

/** Every deep-linkable section id → the chapter that renders it. */
export const MANUAL_ANCHORS: Record<string, ChapterId> = {
  // Basics
  concepts: 'basics',
  // The lean method
  'lean-method': 'lean',
  waste: 'lean',
  'muda-mura-muri': 'lean',
  timing: 'lean',
  'digital-lean': 'lean',
  statistics: 'lean',
  pull: 'lean',
  // The improvement toolkit
  'five-s': 'toolkit',
  'standard-work': 'toolkit',
  'visual-management': 'toolkit',
  layout: 'toolkit',
  flow: 'toolkit',
  'poka-yoke': 'toolkit',
  jidoka: 'toolkit',
  quality: 'toolkit',
  smed: 'toolkit',
  heijunka: 'toolkit',
  maintenance: 'toolkit',
  pdca: 'toolkit',
  'five-whys': 'toolkit',
  pareto: 'toolkit',
  people: 'toolkit',
  // Flow science
  'littles-law': 'science',
  kingman: 'science',
  balance: 'science',
  'flow-efficiency': 'science',
  variability: 'science',
  'matched-sets': 'science',
  monument: 'science',
  constraints: 'science',
  runout: 'science',
  // Integrations
  integrations: 'integrations',
}

/** Which section explains each tip category. Every category MUST appear here:
 *  the daily tip's "Read more" resolves through this table, and a tip whose
 *  link goes nowhere teaches the reader not to click. */
export const CATEGORY_ANCHORS: Record<string, string> = {
  'Lean method': 'lean-method',
  TIMWOOD: 'waste',
  Transport: 'waste',
  Inventory: 'waste',
  Motion: 'waste',
  Waiting: 'waste',
  'Over-processing': 'waste',
  Overproduction: 'waste',
  Defects: 'quality',
  Pull: 'pull',
  'Lead time': 'littles-law',
  Takt: 'timing',
  Utilisation: 'statistics',
  'Digital lean': 'digital-lean',
  '5S': 'five-s',
  SMED: 'smed',
  'Poka-yoke': 'poka-yoke',
  Jidoka: 'jidoka',
  Heijunka: 'heijunka',
  'Standard work': 'standard-work',
  'Muda·Mura·Muri': 'muda-mura-muri',
  PDCA: 'pdca',
  'Five whys': 'five-whys',
  Constraints: 'constraints',
  'Visual mgmt': 'visual-management',
  Quality: 'quality',
  Layout: 'layout',
  People: 'people',
  Maintenance: 'maintenance',
  Flow: 'flow',
  Sequencing: 'runout',
  Pareto: 'pareto',
  Taktline: 'concepts',
}

export function anchorForCategory(category: string): string | undefined {
  return CATEGORY_ANCHORS[category]
}
