/** Words for a sync run's `sync_warning` events (FIXPLAN SYNC-WARN). Until this, no screen
 *  listened for them, so a game skipped because the side you played could not be told, a
 *  game the analysis failed on, and the needs-attention notice were all invisible. A run
 *  can repeat one message many times ("Skipped a game: …"), so identical messages from the
 *  same source collapse into one line with a count, in the order first seen. */

import type { GameSource } from './api'

export interface SyncWarning {
  source: GameSource | string
  message: string
  count: number
}

export function addSyncWarning(
  list: SyncWarning[],
  ev: { source: GameSource | string; message: string },
): SyncWarning[] {
  const i = list.findIndex((w) => w.source === ev.source && w.message === ev.message)
  if (i < 0) return [...list, { source: ev.source, message: ev.message, count: 1 }]
  return list.map((w, j) => (j === i ? { ...w, count: w.count + 1 } : w))
}

export function syncWarningText(w: SyncWarning, label: (s: string) => string): string {
  const src = label(w.source)
  return `${src ? `${src}: ` : ''}${w.message}${w.count > 1 ? ` (×${w.count})` : ''}`
}

/** At most `max` lines, then one saying how many more: a sync skipping every game of an
 *  unattributable account would otherwise list hundreds. */
export function syncWarningLines(list: SyncWarning[], label: (s: string) => string, max = 5): string[] {
  const lines = list.slice(0, max).map((w) => syncWarningText(w, label))
  const rest = list.slice(max).reduce((n, w) => n + w.count, 0)
  if (rest > 0) lines.push(`… and ${rest} more warning${rest === 1 ? '' : 's'}`)
  return lines
}
