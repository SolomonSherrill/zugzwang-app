/**
 * Engine lines as the Moves tab and Analyse a position show them (UI-BUILD B2, UI-BUILD-3 C/D):
 * stored lines for a game position, live ones (the sidecar's `fen_analyzed`) for a variation,
 * a position no run covers, or a FEN. Evals from White's side (ruling 4). Each line keeps its
 * UCI moves so a click on a move plays the line up to it.
 */
import { Chess } from 'chess.js'
import type { FenAnalyzedEvent, GameDetail, MoveAnalysisInfo } from '../api'
import { whiteWp } from '../classification'
import { evalAfter, formatEval, lineEval, toWhite } from './reviewModel'

/** What the engine-lines panel shows. */
export type LinesStatus =
  | { kind: 'lines' }
  /** a sentence where lines would be (the game is over, nothing stored, hidden for Try it) */
  | { kind: 'note'; text: string }
  | { kind: 'pending' }
  | { kind: 'error'; text: string; retry: () => void }
  | { kind: 'no-engine'; onsettings: () => void }

export interface LineRow {
  key: string
  eval: string
  sans: string[]
  ucis: string[]
  best: boolean
  played: boolean
}

/** The stored lines of the ply played from position `current`, with the played move's line
 *  added (from its after-score and the next ply's best line) when it is not among them. */
export function storedRows(game: GameDetail, byPly: Map<number, MoveAnalysisInfo>, current: number): LineRow[] {
  const startsWhite = !game.startFen.includes(' b ')
  const a = byPly.get(current)
  if (!a) return []
  const played = game.plies[current]?.uci
  const out: LineRow[] = a.lines.map((l, i) => ({
    key: `l${i}`,
    eval: formatEval(lineEval(current, l, startsWhite)),
    sans: l.san,
    ucis: l.uci,
    best: i === 0,
    played: l.uci[0] === played,
  }))
  if (played && !out.some((l) => l.played)) {
    const next = byPly.get(current + 1)
    out.push({
      key: 'played',
      eval: formatEval(evalAfter(a, startsWhite)),
      sans: [game.plies[current].san, ...(next?.lines[0]?.san ?? [])],
      ucis: [played, ...(next?.lines[0]?.uci ?? [])],
      best: false,
      played: true,
    })
  }
  return out
}

/** A live search's lines (scores are the side to move's) from White's side. */
export function liveRows(ev: FenAnalyzedEvent): LineRow[] {
  const whiteToMove = ev.fen.split(' ')[1] !== 'b'
  return ev.lines.map((l, i) => ({
    key: `v${i}`,
    eval: formatEval(toWhite(whiteToMove ? 0 : 1, l.cp, l.mate)),
    sans: l.san,
    ucis: l.uci,
    best: i === 0,
    played: false,
  }))
}

/** White's win probability from a live search's top score (classification.whiteWp: Lichess's
 *  sigmoid, 1 / 0 for a mate). Null when the search gave no score. */
export function liveWp(ev: FenAnalyzedEvent | null): number | null {
  if (!ev) return null
  return whiteWp(ev.fen.split(' ')[1] !== 'b' ? 0 : 1, ev.cp, ev.mate)
}

/** Why a position has no lines: the game is over on the board. Null while moves remain or
 *  the FEN cannot be read. */
export function positionEnd(fen: string): string | null {
  let c: Chess
  try {
    c = new Chess(fen)
  } catch {
    return null
  }
  if (c.isCheckmate()) return 'Checkmate.'
  if (c.isStalemate()) return 'Stalemate.'
  if (c.isInsufficientMaterial()) return 'A draw: neither side can mate.'
  if (c.moves().length === 0) return 'No legal moves.'
  return null
}

/** The side to move, as words. */
export function sideToMove(fen: string): 'White' | 'Black' {
  return fen.split(' ')[1] === 'b' ? 'Black' : 'White'
}
