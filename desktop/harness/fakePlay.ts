/**
 * The fake sidecar's side of Play (UI-BUILD-2): new_game, user_move, resign, draw, flag and
 * get_state answered with chess.js, and Stockfish replaced by a scripted line (the mockup's
 * Najdorf, then the first legal move) so a harness game can be played by clicking squares.
 * As the real sidecar (UI-BUILD-3 F), user_move takes the user's clock_ms and engine_move
 * carries the engine's clockMs (its clock less the reply time plus the increment; null untimed).
 * Sample data for screenshots only; nothing here is measured.
 */
import { Chess } from 'chess.js'

type Emit = (event: string, data: Record<string, unknown>) => void
type Handler = (params: Record<string, unknown>, emit: Emit) => unknown

const REPLIES = ['e4', 'c5', 'Nf3', 'd6', 'd4', 'cxd4', 'Nxd4', 'Nf6', 'Nc3', 'a6', 'Be3', 'e5']
const OPENINGS: Record<number, [string, string]> = {
  2: ['B20', 'Sicilian Defense'],
  4: ['B50', 'Sicilian Defense: Modern Variations'],
  10: ['B90', 'Sicilian Defense: Najdorf Variation'],
  11: ['B90', 'Sicilian Defense: Najdorf Variation, English Attack'],
}

export interface FakePlayOptions {
  /** the saved game's id the end of a game reports (the fixtures' main game, so Review opens) */
  gameId: number
  /** ms before the engine replies */
  replyMs?: number
  /** the engine's reply ends the game: Stockfish mates (for the "ended while away" state) */
  engineEnds?: boolean
  /** the engine fails instead of replying (engine_error) */
  engineFails?: boolean
}

export function playHandlers(o: FakePlayOptions): Record<string, Handler> {
  let board = new Chess()
  let you: 'white' | 'black' = 'white'
  let over = false
  // the engine's clock, as the sidecar keeps it (null: untimed)
  let tc: { baseMs: number; incMs: number } | null = null
  let engineLeft = 0
  const end = (result: string, termination: string) => {
    over = true
    return { result, termination, gameId: o.gameId }
  }
  const opening = (emit: Emit) => {
    const named = OPENINGS[board.history().length]
    if (named) emit('opening', { eco: named[0], name: named[1] })
  }
  const engineMove = (emit: Emit) =>
    setTimeout(() => {
      if (over) return
      if (o.engineFails) {
        emit('engine_error', { message: 'Stockfish stopped responding.' })
        return
      }
      const want = REPLIES[board.history().length]
      const legal = board.moves()
      const san = want && legal.includes(want) ? want : legal[0]
      const mv = board.move(san)
      opening(emit)
      let clockMs: number | null = null
      if (tc) {
        engineLeft = Math.max(0, engineLeft - (o.replyMs ?? 250)) + tc.incMs
        clockMs = engineLeft
      }
      emit('engine_move', {
        uci: mv.from + mv.to + (mv.promotion ?? ''),
        san: mv.san,
        fen: board.fen(),
        end: o.engineEnds ? end(you === 'white' ? '0-1' : '1-0', 'checkmate') : null,
        clockMs,
      })
    }, o.replyMs ?? 250)
  return {
    new_game: (p, emit) => {
      board = p.fen ? new Chess(String(p.fen)) : new Chess()
      you = p.color === 'black' ? 'black' : 'white'
      over = false
      const m = /^(\d+)\+(\d+)$/.exec(String(p.time_control ?? ''))
      tc = m ? { baseMs: Number(m[1]) * 1000, incMs: Number(m[2]) * 1000 } : null
      engineLeft = tc?.baseMs ?? 0
      const engineToMove = (board.turn() === 'w') !== (you === 'white')
      if (engineToMove) engineMove(emit)
      return { fen: board.fen(), engineToMove }
    },
    user_move: (p, emit) => {
      const uci = String(p.uci)
      let mv
      try {
        mv = board.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] })
      } catch {
        return { ok: false, fen: board.fen() }
      }
      opening(emit)
      if (board.isCheckmate()) return { ok: true, san: mv.san, fen: board.fen(), end: end(you === 'white' ? '1-0' : '0-1', 'checkmate') }
      engineMove(emit)
      return { ok: true, san: mv.san, fen: board.fen(), end: null }
    },
    resign: () => ({ end: end(you === 'white' ? '0-1' : '1-0', 'resignation') }),
    draw: () => ({ end: end('1/2-1/2', 'draw_agreed') }),
    flag: (p) => ({ end: end(p.loser === 'white' ? '0-1' : '1-0', 'timeout') }),
    abandon: () => ({ end: end('*', 'abandoned') }),
    get_state: () => ({ active: !over, fen: board.fen(), playerColor: you, skill: 10 }),
  }
}
