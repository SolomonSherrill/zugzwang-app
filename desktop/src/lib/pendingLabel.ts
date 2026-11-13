/** Words for the bulk-analysis queue (W15). The queue holds two kinds of game, and
 *  the old label called both "unanalysed": games with no run at all, and games already
 *  analysed below the depth selected in Settings, which the action *re-analyses*. With
 *  the corpus at depth 10 and Settings above it, "Analyse all 2484 unanalysed" queued
 *  ~7 h of re-analysis of analysed games — work F17 measured does not improve labels. */

import type { SyncSourceCounts } from './api'

export interface PendingSplit {
  unanalysed: number
  belowDepth: number
  depth: number
}

export function pendingSplit(...sources: SyncSourceCounts[]): PendingSplit {
  return {
    unanalysed: sources.reduce((s, c) => s + c.unanalysed, 0),
    belowDepth: sources.reduce((s, c) => s + c.belowDepth, 0),
    depth: sources[0]?.depth ?? 0,
  }
}

const nf = new Intl.NumberFormat('en-US')

/** The Past Games button: says exactly what one click queues. */
export function pendingButtonLabel(p: PendingSplit): string | null {
  const { unanalysed: u, belowDepth: b, depth } = p
  if (u === 0 && b === 0) return null
  if (b === 0) return `Analyse ${nf.format(u)} unanalysed`
  const re = `re-analyse ${nf.format(b)} below depth ${depth}`
  return u === 0 ? `R${re.slice(1)}` : `Analyse ${nf.format(u)} unanalysed · ${re}`
}

/** The Settings sync line: "· 3 unanalysed · 2,481 below depth 14". */
export function pendingSummary(c: SyncSourceCounts): string {
  const parts = []
  if (c.unanalysed > 0) parts.push(`${nf.format(c.unanalysed)} unanalysed`)
  if (c.belowDepth > 0) parts.push(`${nf.format(c.belowDepth)} below depth ${c.depth}`)
  if (c.needsAttention > 0)
    parts.push(`${nf.format(c.needsAttention)} the engine keeps crashing on — not analysed`)
  return parts.map((p) => ` · ${p}`).join('')
}

/** "Analyse more" (BETA-PUB Q4, owner 2026-11-12): a sync analyses each account's 100 most
 *  recent games by itself; the rest wait for the user, newest first, in a step they choose
 *  or all. The step a typed value means: a whole number from 1 to everything pending, or
 *  null when the field holds nothing usable. */
export function analyseMoreStep(typed: number | string | null | undefined, total: number): number | null {
  const n = typeof typed === 'number' ? typed : Number(String(typed ?? '').trim())
  if (!Number.isFinite(n) || total <= 0) return null
  const whole = Math.floor(n)
  if (whole < 1) return null
  return Math.min(whole, total)
}

/** The button for one step: "Analyse the next 100", or "Analyse all 37" when the step
 *  covers everything left. */
export function analyseMoreLabel(step: number | null, total: number): string {
  if (step == null || step <= 0) return 'Analyse'
  if (step >= total) return `Analyse all ${nf.format(total)}`
  return `Analyse the next ${nf.format(step)}`
}
