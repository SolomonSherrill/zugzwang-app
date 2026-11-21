/**
 * Analyse a position (UI-BUILD-3 E; mockup design/mockups/MinimalGames-position.html): read what
 * was pasted, a FEN or a PGN (the position after its last move), and say whether the position is
 * legal before anything is sent to the engine. The engine is never given an illegal position:
 * with no king Stockfish crashes, and with two kings, a pawn on the back rank or the side not to
 * move in check it answers with confident nonsense (CLAUDE.md, VAL-FEN).
 */
import { Chess, validateFen } from 'chess.js'

export const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

export type PositionRead =
  | {
      ok: true
      fen: string
      turn: 'white' | 'black'
      /** what the text was: nothing (the starting position), a FEN, or a PGN */
      from: 'start' | 'fen' | 'pgn'
      /** the position has no legal move (mate or stalemate): it can be analysed, not played */
      over: boolean
      check: boolean
    }
  | {
      ok: false
      reason: string
      /** the piece placement, when it could be read, for the preview */
      placement: string | null
    }

/** A board part with ranks split by "/" (any number of them: a wrong count is a FEN with a reason). */
const looksLikeFen = (s: string) => /^[pnbrqkPNBRQK1-8]+(\/[pnbrqkPNBRQK1-8]*)+(\s|$)/.test(s)

const FEN_WORDS: [RegExp, string][] = [
  [/missing white king/, 'White has no king.'],
  [/missing black king/, 'Black has no king.'],
  [/too many white kings/, 'White has more than one king.'],
  [/too many black kings/, 'Black has more than one king.'],
  [/pawns are on the edge rows/, 'A pawn stands on the first or last rank.'],
  [/en-passant/, 'The en passant square is not possible.'],
  [/castling/, 'The castling rights are not readable.'],
  [/side-to-move/, 'The side to move must be w or b.'],
  [/8 '\/'-delimited rows|too many squares|consecutive number|invalid piece/, 'The board part does not describe 8 ranks of 8 squares.'],
  [/move number|half move/, 'The move counters are not readable.'],
]

function fenReason(error: string): string {
  for (const [re, words] of FEN_WORDS) if (re.test(error)) return words
  return 'Not a legal FEN.'
}

function readFen(text: string): PositionRead {
  const tokens = text.trim().split(/\s+/)
  // A FEN with only its first four fields is common; the counters default as python-chess's do.
  if (tokens.length === 4) tokens.push('0', '1')
  const fen = tokens.join(' ')
  const placement = tokens[0]
  const v = validateFen(fen)
  const whole = /^[pnbrqkPNBRQK1-8]+(\/[pnbrqkPNBRQK1-8]+){7}$/.test(placement)
  if (!v.ok) return { ok: false, reason: fenReason(v.error ?? ''), placement: whole ? placement : null }
  // The side not to move in check: the side to move could take the king.
  const other = [tokens[0], tokens[1] === 'w' ? 'b' : 'w', tokens[2], '-', '0', '1'].join(' ')
  try {
    if (new Chess(other).inCheck())
      return {
        ok: false,
        reason: tokens[1] === 'w' ? 'Black is in check, but it is White to move.' : 'White is in check, but it is Black to move.',
        placement,
      }
  } catch {
    /* validated above */
  }
  let board: Chess
  try {
    board = new Chess(fen)
  } catch (e) {
    return { ok: false, reason: fenReason(String((e as Error).message ?? e)), placement }
  }
  return done(board, 'fen')
}

function done(board: Chess, from: 'start' | 'fen' | 'pgn'): PositionRead {
  return {
    ok: true,
    fen: board.fen(),
    turn: board.turn() === 'w' ? 'white' : 'black',
    from,
    over: board.moves().length === 0,
    check: board.inCheck(),
  }
}

/** The first game of a PGN that may hold several (the next one starts at a header after movetext). */
export function firstGame(pgn: string): string {
  const lines = pgn.split(/\r?\n/)
  let seenMoves = false
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i].trim()
    if (!l) continue
    if (l.startsWith('[')) {
      if (seenMoves) return lines.slice(0, i).join('\n')
    } else seenMoves = true
  }
  return pgn
}

const PGN_START = /^\[|\d+\s*\.|^(?:[NBRQK][a-h1-8]?x?[a-h][1-8]|[a-h]x?[a-h]?[1-8]|O-O)\b/

function readPgn(text: string): PositionRead {
  if (!PGN_START.test(text)) return { ok: false, reason: 'Not a FEN, and not a PGN that can be read.', placement: null }
  const board = new Chess()
  try {
    board.loadPgn(firstGame(text))
  } catch (e) {
    const msg = String((e as Error).message ?? e)
    const m = /Invalid move in PGN: (\S+)/.exec(msg)
    return { ok: false, reason: m ? `The PGN has an illegal move: ${m[1]}.` : 'Not a FEN, and not a PGN that can be read.', placement: null }
  }
  if (board.history().length === 0 && !/\[FEN\s/.test(text)) {
    return { ok: false, reason: 'Not a FEN, and not a PGN that can be read.', placement: null }
  }
  return done(board, 'pgn')
}

/** What the pasted text holds. Empty is the starting position. */
export function readPosition(text: string): PositionRead {
  const t = text.trim()
  if (!t) return done(new Chess(), 'start')
  if (looksLikeFen(t)) return readFen(t)
  return readPgn(t)
}

/** The preview's placement: the position's, or what could be read of an illegal one, or empty. */
export function previewPlacement(r: PositionRead): string {
  if (r.ok) return r.fen.split(' ')[0]
  return r.placement ?? '8/8/8/8/8/8/8/8'
}
