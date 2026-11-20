/** Pure helpers for the game report screen (core/game_report.py is the source of
 *  every claim; this file only lays them out). */

import type { GameReport, MoveAnalysisInfo, ReportFound, ReportMoment } from './api'
import { whiteWp } from './classification'

export type AnalysedReport = Extract<GameReport, { analysed: true }>

/** "3 of 7 moments" when the cap dropped some — a list of three must not read as a
 *  game that had three (owner ruling, 2026-10-21). Not "the 3 largest": the cards
 *  are the largest plus any moment a story line names. */
export function momentsHeading(total: number, shown: number): string | null {
  if (total === 0 || shown === 0) return null
  if (shown < total) return `${shown} of ${total} moments`
  // R5: a count in the context lines under the cards, no longer a heading above them, so
  // "1 moment" rather than "The moment".
  return shown === 1 ? '1 moment' : `${shown} moments`
}

/** Cards in game order: an error and the reply that failed to punish it share one. */
export function cards(report: AnalysedReport): ReportMoment[][] {
  const byPly = new Map(report.moments.shown.map((m) => [m.ply, m]))
  return report.moments.groups.map((g) => g.map((p) => byPly.get(p)!).filter(Boolean))
}

/** The report's cards and its "found it" moment (GR2-8) in game order: the cards keep
 *  their numbers, the found moment has none (it is marked ✓). */
export type ReportItem =
  | { kind: 'card'; group: ReportMoment[]; n: number }
  | { kind: 'found'; found: ReportFound }

export function reportItems(report: AnalysedReport): ReportItem[] {
  const items: ReportItem[] = cards(report).map((group, i) => ({ kind: 'card', group, n: i + 1 }))
  const f = report.found
  if (f) {
    const at = items.findIndex((it) => it.kind === 'card' && it.group[0].ply > f.ply)
    items.splice(at === -1 ? items.length : at, 0, { kind: 'found', found: f })
  }
  return items
}

export interface GraphMarker {
  /** Position index the marker sits on: the position after the moment's (first) move. */
  position: number
  /** The card's number; 0 for the "found it" moment, which shows a check mark. */
  n: number
  tone: 'you' | 'opponent' | 'neutral' | 'found'
}

export function graphMarkers(report: AnalysedReport): GraphMarker[] {
  const out: GraphMarker[] = cards(report).map((group, i) => {
    const first = group[0]
    return {
      position: first.ply + 1,
      n: i + 1,
      tone: first.yours === null ? 'neutral' : first.yours ? 'you' : 'opponent',
    }
  })
  if (report.found) out.push({ position: report.found.ply + 1, n: 0, tone: 'found' })
  return out
}

/** White's win probability per position while analysis is still streaming, by the
 *  report's own rule: a position's before-search, else the after-search of the move
 *  that led to it, else nothing — never a carried-forward value. */
export function liveSeries(
  plyCount: number,
  analyses: Record<number, MoveAnalysisInfo>,
): (number | null)[] {
  const out: (number | null)[] = []
  for (let j = 0; j <= plyCount; j++) {
    const here = analyses[j]
    const prev = analyses[j - 1]
    let v: number | null = null
    if (here && (here.scoreBeforeCp !== null || here.scoreBeforeMate !== null))
      v = whiteWp(j, here.scoreBeforeCp, here.scoreBeforeMate)
    if (v === null && prev && (prev.scoreAfterCp !== null || prev.scoreAfterMate !== null))
      v = whiteWp(j - 1, prev.scoreAfterCp, prev.scoreAfterMate)
    out.push(v)
  }
  return out
}

/** Length of the unscored stretch at the start of the series. Runs analysed before
 *  F4a have no scores on book moves; the graph draws nothing there (ruling 5). */
export function leadingGap(series: (number | null)[]): number {
  let k = 0
  while (k < series.length && series[k] === null) k++
  return k === series.length ? 0 : k
}

export function bandChange(m: ReportMoment): string {
  return m.bandBefore === m.bandAfter ? m.bandAfter : `${m.bandBefore} → ${m.bandAfter}`
}

export function basisText(report: AnalysedReport): string {
  const b = report.basis
  const span = b.complete
    ? `${b.gamePlies} half-moves`
    : `${b.analysedPlies} of ${b.gamePlies} half-moves`
  const tc = b.timeControl ? timeControlText(b.timeControl) : null
  return `Depth ${b.depth} · ${span} analysed` + (tc ? ` · ${tc}, clock times from the game` : '')
}

/** "600" → "10 min", "180+2" → "3+2", "15" → "15 s". */
export function timeControlText(tc: string): string | null {
  const m = /^(\d+)(?:\+(\d+))?$/.exec(tc.trim())
  if (!m) return null
  const base = Number(m[1])
  const inc = m[2] ? Number(m[2]) : 0
  const b = base % 60 === 0 ? `${base / 60}` : `${base}s`
  if (inc) return `${b}+${inc}`
  return base % 60 === 0 ? `${base / 60} min` : `${base} s`
}

/** A clock reading: "3:41", "0:09". */
export function clockText(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Time spent on one move: "2.4 s" under ten seconds, "12 s", "1:05" past a minute. */
export function spentText(seconds: number): string {
  if (seconds < 10) return `${seconds.toFixed(1)} s`
  if (seconds < 60) return `${Math.round(seconds)} s`
  return clockText(seconds)
}

/** The clock on a moment, shown and left to the reader: no claim about pace
 *  (owner ruling — moments take a median 1.56x the player's median move time). */
export function momentClock(m: ReportMoment): string | null {
  if (m.clockLeft === null) return null
  const left = `${clockText(m.clockLeft)} left`
  return m.spent === null ? left : `${spentText(m.spent)} · ${left}`
}

/** The graph tick for the book exit: "out of book" only where someone left it, "book
 *  ends" where the book had nothing more; none when every move was book. */
export function bookTick(
  op: { case: string; ply: number | null } | null | undefined,
): { position: number; label: string } | null {
  if (!op || op.ply === null) return null
  return { position: op.ply, label: op.case === 'deviated' ? 'out of book' : 'book ends' }
}

/** Whether a moment offers "Try it" (slice 5): only the user's own moments, and only
 *  where it can be judged honestly — any of them with an engine, and with none only
 *  those with a unique stored answer. Never degraded judging (owner ruling). */
export function canTry(m: ReportMoment, engineOk: boolean): boolean {
  return m.yours === true && (engineOk || (m.unique && m.bestUci !== null))
}

/** The reply line (GR2-6) names the engine's move for the user's next move, so it is
 *  hidden while that move's own card is being tried and not yet judged: it is the answer. */
export function replyHidden(
  m: ReportMoment,
  tryingPly: number | null,
  verdict: TryVerdict | null,
): boolean {
  return tryingPly === m.ply + 1 && (verdict === null || verdict.kind === 'judging')
}

export type TryVerdict =
  | { kind: 'judging' }
  | { kind: 'good'; san: string; bestSan: string | null; exact: boolean }
  | { kind: 'not-it'; san: string; bestSan: string; loss: number }
  /** No engine and not the stored answer: never called wrong, because a fresh search
   *  found another move as good on 4 of 593 unique-answer moments. */
  | { kind: 'unjudged'; san: string; bestSan: string }
  | { kind: 'error'; message: string }

/** No-engine judging: the stored unique answer is accepted; anything else is not
 *  judged, only compared. */
export function judgeOffline(m: ReportMoment, uci: string, san: string): TryVerdict {
  if (uci === m.bestUci) return { kind: 'good', san, bestSan: m.bestSan, exact: true }
  return { kind: 'unjudged', san, bestSan: m.bestSan ?? '' }
}

/** The sentence under a judged Try. Win-probability points, as the report speaks. */
export function verdictText(v: TryVerdict): string {
  switch (v.kind) {
    case 'judging':
      return 'Checking…'
    case 'good':
      return v.exact || v.bestSan === v.san || v.bestSan === null
        ? `${v.san} — that's the move.`
        : `${v.san} — good: within 5 points of the best line (${v.bestSan}).`
    case 'not-it':
      return `${v.san} gives up about ${Math.round(v.loss * 100)} points; the engine's move is ${v.bestSan}.`
    case 'unjudged':
      return `The analysis found ${v.bestSan} here. Other moves can't be checked without the engine.`
    case 'error':
      return v.message
  }
}
