/**
 * The redesigned Review's pure logic (UI-BUILD B1–B3): evals from White's side, chart
 * series, phase bands, the move table, the moments' words and the strips' clocks. Every
 * figure is read off the stored game, report and review_extras; nothing is estimated.
 */
import type { GameDetail, MoveAnalysisInfo, ReportMoment, ReportPattern, Band, EngineLine } from '../api'
import { GRAPH_DOT_QUALITIES, isQualityClass, type QualityClass } from '../ui/moveQuality'

export type Side = 'white' | 'black'

// ── evals (ruling 4: from White's side in lists and lines) ─────────────────────

export interface WhiteEval {
  cp: number | null
  /** moves to mate, + White mates, − Black mates; 0 = the game ended in mate */
  mate: number | null
}

/** A mover-POV score (as stored) at ply `ply` turned to White's side. */
export function toWhite(ply: number, cp: number | null, mate: number | null): WhiteEval {
  const sign = ply % 2 === 0 ? 1 : -1
  return { cp: cp === null ? null : cp * sign, mate: mate === null ? null : mate * sign }
}

/** The position after the move, from White's side (the depth-14 after-score). */
export function evalAfter(ma: MoveAnalysisInfo, startsWhite = true): WhiteEval {
  return toWhite(ma.ply + (startsWhite ? 0 : 1), ma.scoreAfterCp, ma.scoreAfterMate)
}

/** An engine line's score (mover-POV at the position before ply `ply`) from White's side. */
export function lineEval(ply: number, line: EngineLine, startsWhite = true): WhiteEval {
  return toWhite(ply + (startsWhite ? 0 : 1), line.cp, line.mate)
}

const MINUS = '\u2212'

/** "+0.3", "−4.2", "0.0", "#3", "#−3"; "#" for mate delivered; "" when unscored. */
export function formatEval(e: WhiteEval | null, matedSide?: Side): string {
  if (!e) return ''
  if (e.mate !== null) {
    if (e.mate === 0) return matedSide ? (matedSide === 'black' ? '1–0' : '0–1') : '#'
    return e.mate > 0 ? `#${e.mate}` : `#${MINUS}${-e.mate}`
  }
  if (e.cp === null) return ''
  const p = e.cp / 100
  if (Math.abs(p) < 0.05) return '0.0'
  return p > 0 ? `+${p.toFixed(1)}` : `${MINUS}${(-p).toFixed(1)}`
}

// ── move numbering ───────────────────────────────────────────────────────────

/** "34. b5" / "34… axb5" for ply (0 = White's first move), in the mockups' style. */
export function moveLabel(ply: number, san: string, startsWhite = true): string {
  const p = ply + (startsWhite ? 0 : 1)
  const n = Math.floor(p / 2) + 1
  return p % 2 === 0 ? `${n}. ${san}` : `${n}… ${san}`
}

export function sideOfPly(ply: number, startsWhite = true): Side {
  return (ply + (startsWhite ? 0 : 1)) % 2 === 0 ? 'white' : 'black'
}

/** A line of SANs from the position before `ply`, numbered: "34… Qa1+ 35. Kh2 Qe5+". */
export function numberedLine(ply: number, sans: string[], startsWhite = true, max = 99): string {
  const out: string[] = []
  sans.slice(0, max).forEach((san, i) => {
    const p = ply + i + (startsWhite ? 0 : 1)
    const n = Math.floor(p / 2) + 1
    if (p % 2 === 0) out.push(`${n}.`, san)
    else if (i === 0) out.push(`${n}…`, san)
    else out.push(san)
  })
  return out.join(' ')
}

/** The same line as tokens, for rendering numbers and moves apart. */
export function lineTokens(ply: number, sans: string[], startsWhite = true): { num?: string; san?: string }[] {
  const out: { num?: string; san?: string }[] = []
  sans.forEach((san, i) => {
    const p = ply + i + (startsWhite ? 0 : 1)
    const n = Math.floor(p / 2) + 1
    if (p % 2 === 0) out.push({ num: `${n}.` })
    else if (i === 0) out.push({ num: `${n}…` })
    out.push({ san })
  })
  return out
}

// ── the move table (Moves tab) ─────────────────────────────────────────────────

export interface MoveCell {
  ply: number
  san: string
  cls: QualityClass | null
  eval: string
}
export interface MoveRow {
  number: number
  white: MoveCell | null
  black: MoveCell | null
}

export function moveRows(game: GameDetail): MoveRow[] {
  const startsWhite = !game.startFen.includes(' b ')
  const byPly = new Map((game.analysis?.moves ?? []).map((m) => [m.ply, m]))
  const cells = game.plies.map((p, ply): MoveCell => {
    const a = byPly.get(ply)
    return {
      ply,
      san: p.san,
      cls: a && isQualityClass(a.classification) ? a.classification : null,
      eval: a ? formatEval(evalAfter(a, startsWhite)) : '',
    }
  })
  return cellRows(cells, startsWhite ? 0 : 1)
}

/** Cells (ply 0 first) as numbered rows; `base` is the absolute ply index of ply 0 (1 when
 *  Black moves first; Analyse a position counts from its FEN's move number). */
export function cellRows(cells: MoveCell[], base: number): MoveRow[] {
  const rows: MoveRow[] = []
  for (const cell of cells) {
    const abs = cell.ply + base
    const number = Math.floor(abs / 2) + 1
    if (abs % 2 === 0) rows.push({ number, white: cell, black: null })
    else {
      const last = rows[rows.length - 1]
      if (last && last.number === number && !last.black) last.black = cell
      else rows.push({ number, white: null, black: cell })
    }
  }
  return rows
}

// ── charts ─────────────────────────────────────────────────────────────────────

const VALUES: Record<string, number> = { p: 1, n: 3, b: 3, r: 5, q: 9 }

/** White's material minus Black's, in pawns, for one FEN's placement. */
export function materialBalance(fen: string): number {
  let v = 0
  for (const ch of fen.split(' ')[0]) {
    const low = ch.toLowerCase()
    if (low in VALUES) v += ch === low ? -VALUES[low] : VALUES[low]
  }
  return v
}

/** Material balance per position: 0 = the start, i = after ply i−1. */
export function materialSeries(game: GameDetail): number[] {
  return [materialBalance(game.startFen), ...game.plies.map((p) => materialBalance(p.fen))]
}

export interface Dot {
  ply: number
  /** position index on the graph: the position after the move */
  position: number
  cls: QualityClass
}

/** The Moves graph's dots: brilliant, great, miss, mistake, blunder (ruling 5). */
export function notableDots(game: GameDetail): Dot[] {
  return (game.analysis?.moves ?? [])
    .filter((m) => isQualityClass(m.classification) && GRAPH_DOT_QUALITIES.has(m.classification))
    .map((m) => ({ ply: m.ply, position: m.ply + 1, cls: m.classification as QualityClass }))
}

export interface PhaseBand {
  phase: 'Opening' | 'Middlegame' | 'Endgame'
  from: number
  to: number
}

/** The game's own phases (core/divider.py through review_extras) as position ranges. The
 *  division is over the board before each ply, so a phase that starts at ply i starts at
 *  position i. A phase the game never reached has no band. */
export function phaseBands(
  middlegame: number | null,
  endgame: number | null,
  positions: number,
): PhaseBand[] {
  const last = Math.max(0, positions - 1)
  const marks: [PhaseBand['phase'], number][] = [['Opening', 0]]
  if (middlegame !== null) marks.push(['Middlegame', middlegame])
  if (endgame !== null) marks.push(['Endgame', endgame])
  return marks.map(([phase, from], i) => ({
    phase,
    from,
    to: i + 1 < marks.length ? marks[i + 1][1] : last,
  }))
}

// ── moments (Report) ─────────────────────────────────────────────────────────────

const BAND_WORD: Record<Band, string> = {
  winning: 'winning',
  better: 'better',
  balanced: 'level',
  worse: 'worse',
  losing: 'losing',
}

/** "Level to winning", "Winning to level": the report's bands in the reader's terms
 *  (ruling 4: sentences in the player's terms; the bands are from the report's point of
 *  view, the user's when known). */
export function swingWords(m: Pick<ReportMoment, 'bandBefore' | 'bandAfter'>): string {
  const a = BAND_WORD[m.bandBefore]
  const b = BAND_WORD[m.bandAfter]
  const s = a === b ? a : `${a} to ${b}`
  return s[0].toUpperCase() + s.slice(1)
}

// ── the strips' clocks ─────────────────────────────────────────────────────────

/** Each side's clock at a position (0 = start, i = after ply i−1): the last reading at or
 *  before it, the base time before a side has moved; null with no clocks. */
export function clocksAt(
  clocks: (number | null)[],
  base: number | null,
  position: number,
  startsWhite = true,
): Record<Side, number | null> {
  const out: Record<Side, number | null> = { white: base, black: base }
  if (!clocks.length || base === null) return { white: null, black: null }
  for (let ply = 0; ply < position && ply < clocks.length; ply++) {
    const c = clocks[ply]
    if (c !== null) out[sideOfPly(ply, startsWhite)] = c
  }
  return out
}

/** The side to move at a position. */
export function toMoveAt(position: number, startsWhite = true): Side {
  return sideOfPly(position, startsWhite)
}

// ── players ───────────────────────────────────────────────────────────────────────

export interface PlayerInfo {
  name: string
  rating: number | string | null
  you: boolean
}

/** Ruling 6: "Name (rating)" with the rating at the time of the game, nothing if missing;
 *  a local game against Stockfish shows the engine's level instead. */
export function players(game: GameDetail): Record<Side, PlayerInfo> {
  const local = game.source === 'local'
  const mk = (side: Side): PlayerInfo => {
    const you = game.playerColor === side
    const elo = side === 'white' ? game.whiteElo : game.blackElo
    const name = (side === 'white' ? game.white : game.black) || (side === 'white' ? 'White' : 'Black')
    if (local && !you) return { name: 'Stockfish', rating: `Level ${game.skillLevel}`, you }
    return { name, rating: elo && elo > 0 ? elo : null, you }
  }
  return { white: mk('white'), black: mk('black') }
}

/** "3+2 blitz, 19 Nov": the time control, the speed and the date. */
export function gameMeta(tc: string | null, speed: string | null, playedAt: string, tcText: (s: string) => string | null): string {
  const parts: string[] = []
  const t = tc ? tcText(tc) : null
  if (t && speed) parts.push(`${t} ${speed}`)
  else if (t) parts.push(t)
  else if (speed) parts.push(speed[0].toUpperCase() + speed.slice(1))
  const d = new Date(playedAt)
  const date = isNaN(d.getTime())
    ? null
    : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' })
  return [parts.join(''), date].filter(Boolean).join(', ')
}

// ── the report's patterns (COACH-1 C; FIX-B7) ────────────────────────────────────

/** FIX-B7: "Your patterns in this game" keyed by ply and kind. One move can both miss a chance and deal with a
 *  threat (ruling HF1: both are listed), so the ply alone repeats; the sidecar gives at most one item per ply
 *  and kind (each kind's moment at a ply counts under one theme), measured over every analysed game
 *  (review/scratch/fixb7_keys.out). */
export function patternKey(p: Pick<ReportPattern, 'ply' | 'kind'>): string {
  return `${p.ply}:${p.kind}`
}

/** FIX-B7 (ruling HF1): the pattern each ply's key moment shows. Where a move both missed a chance and dealt with a
 *  threat, the missed one. */
export function patternsByPly<T extends Pick<ReportPattern, 'ply' | 'outcome'>>(items: readonly T[]): Map<number, T> {
  const out = new Map<number, T>()
  for (const p of items) {
    const had = out.get(p.ply)
    if (!had || (had.outcome !== 'missed' && p.outcome === 'missed')) out.set(p.ply, p)
  }
  return out
}
