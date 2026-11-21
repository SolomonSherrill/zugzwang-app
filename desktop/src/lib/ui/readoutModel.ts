/**
 * Chart readouts (owner ruling 12 of 2026-11-20, fourth): what a chart shows under the pointer
 * or for the focused point: a vertical guide, a dot on the line and a small label. This file is
 * the pure part: the point nearest the pointer, where the label goes (it flips at the right edge
 * and never leaves the chart's box), and the label's words for each kind of chart. The drawing is
 * ChartReadout.svelte. Nothing here computes a figure; every value is read off what the chart
 * already plots.
 */
import type { MoveAnalysisInfo } from '../api'
import { spentText } from '../report'
import { evalAfter, formatEval, moveLabel, toWhite } from '../review/reviewModel'
import { GRAPH_DOT_QUALITIES, isQualityClass, QUALITY, type QualityClass } from './moveQuality'

/** What a readout's label says: "24… Nxe4" [icon] "−1.4", or "Mar 2026" "76.4" (and a muted note). */
export interface Readout {
  title: string
  value: string
  /** a move-quality icon after the title (move charts, notable moves only) */
  cls?: QualityClass | null
  /** muted words after the value ("120 games") */
  note?: string
}

// ── the point under the pointer ─────────────────────────────────────────────

/** The index of the x nearest to `x` in ascending `xs`; -1 when there are none. Ties go left. */
export function nearestIndex(xs: number[], x: number): number {
  if (!xs.length) return -1
  let lo = 0
  let hi = xs.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (xs[mid] <= x) lo = mid
    else hi = mid
  }
  return Math.abs(xs[hi] - x) < Math.abs(xs[lo] - x) ? hi : lo
}

/** ←/→ through a series whose points share a date: one step moves to the next (or previous)
 *  date and lands on that date's last point (the day's closing rating); points with no shared
 *  keys step one at a time. Stays put at either end. */
export function stepIndex(keys: string[], i: number, dir: 1 | -1): number {
  const n = keys.length
  if (!n) return -1
  i = Math.max(0, Math.min(n - 1, i))
  if (dir > 0) {
    let j = i + 1
    while (j < n && keys[j] === keys[i]) j++
    if (j >= n) return i
    while (j + 1 < n && keys[j + 1] === keys[j]) j++
    return j
  }
  let j = i
  while (j > 0 && keys[j - 1] === keys[i]) j--
  return j > 0 ? j - 1 : i
}

// ── where the label goes ────────────────────────────────────────────────────

export interface Placement {
  left: number
  top: number
  /** true when the label sits left of the point because it would cross the right edge */
  flipped: boolean
}

/**
 * The label's top-left in the chart box's pixels.
 * - `side` (the full charts): right of the point by `gap`; left of it when it would cross the
 *   right edge; then held inside the box. `top` is the label's top.
 * - `above` (sparklines): centred over the point, above the box by `gap`, held inside the box's
 *   width; a label wider than the box is held to the box's right edge and grows left (the
 *   sparklines sit at the right of their cells, so the cell's own text is on the left).
 */
export function placeLabel(o: {
  x: number
  labelW: number
  labelH: number
  boxW: number
  placement: 'side' | 'above'
  top?: number
  gap?: number
}): Placement {
  const gap = o.gap ?? 8
  const hold = (l: number) => Math.max(Math.min(l, o.boxW - o.labelW), Math.min(0, o.boxW - o.labelW))
  if (o.placement === 'above') {
    return { left: hold(o.x - o.labelW / 2), top: -(gap + o.labelH), flipped: false }
  }
  let left = o.x + gap
  let flipped = false
  if (left + o.labelW > o.boxW) {
    left = o.x - gap - o.labelW
    flipped = true
  }
  return { left: hold(left), top: o.top ?? 4, flipped }
}

// ── the label's words ───────────────────────────────────────────────────────

const MINUS = '\u2212'

/** Material from White's side: "+2", "−1", "0". */
export function materialText(m: number): string {
  if (m === 0) return '0'
  return m > 0 ? `+${m}` : `${MINUS}${-m}`
}

export type MoveChartKind = 'eval' | 'material' | 'time'

/**
 * A move chart's readout for a position (0 = the start, i = after ply i − 1): the move as the
 * move list numbers it ("24. Nxe4", "24… Nxe4"; a game starting with Black starts at "1… "),
 * the move-quality icon when the move is one the charts mark (brilliant, great, miss, mistake,
 * blunder: the graph's dots), and the value: the eval from White's side as the app shows it
 * ("+1.4", "#−3"), material ("+2"), or the time spent on the move ("12 s").
 */
export function moveReadout(o: {
  position: number
  sans: string[]
  moves: ReadonlyMap<number, MoveAnalysisInfo>
  startsWhite: boolean
  kind: MoveChartKind
  material?: number[]
  spent?: (number | null)[]
}): Readout {
  const { position, startsWhite } = o
  let value = ''
  if (o.kind === 'material') value = materialText(o.material?.[position] ?? 0)
  if (position <= 0) {
    if (o.kind === 'eval') {
      const first = o.moves.get(0)
      value = first ? formatEval(toWhite(startsWhite ? 0 : 1, first.scoreBeforeCp, first.scoreBeforeMate)) : ''
    }
    return { title: 'Start', value, cls: null }
  }
  const ply = position - 1
  const a = o.moves.get(ply)
  const cls = a && isQualityClass(a.classification) && GRAPH_DOT_QUALITIES.has(a.classification) ? a.classification : null
  if (o.kind === 'eval') value = a ? formatEval(evalAfter(a, startsWhite)) : ''
  else if (o.kind === 'time') {
    const s = o.spent?.[ply]
    value = s === null || s === undefined ? '' : spentText(s)
  }
  return { title: moveLabel(ply, o.sans[ply] ?? '', startsWhite), value, cls }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-03" → "Mar 2026". */
export function monthText(key: string): string {
  const m = MONTHS[Number(key.slice(5, 7)) - 1]
  return m ? `${m} ${key.slice(0, 4)}` : key
}

/** "2026-11-14" or an ISO time → "14 Nov" (the local date), with the year when it is not this year's. */
export function dayText(s: string, now = new Date()): string {
  const plain = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  const d = plain ? new Date(Number(plain[1]), Number(plain[2]) - 1, Number(plain[3])) : new Date(s)
  if (isNaN(d.getTime())) return s
  const day = `${d.getDate()} ${MONTHS[d.getMonth()]}`
  return d.getFullYear() === now.getFullYear() ? day : `${day} ${d.getFullYear()}`
}

/** The local date an ISO time falls on, as "YYYY-MM-DD" (the key ←/→ step by). */
export function dayKey(s: string): string {
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** The readout as one line of text, for a slider's aria-valuetext. */
export function readoutText(r: Readout | null): string {
  if (!r) return ''
  const parts = [r.title]
  if (r.cls) parts.push(QUALITY[r.cls].name.toLowerCase())
  if (r.value) parts.push(r.value)
  if (r.note) parts.push(r.note)
  return parts.join(', ')
}
