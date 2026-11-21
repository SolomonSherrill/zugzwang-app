/**
 * The promotion picker's model (DESIGN.md fifth rulings, 3; UI-BUILD-4 D). Pure: which moves
 * need the picker, where its four squares go for either orientation, and what a key does. The
 * picker itself is drawn by Board.svelte, so every screen that takes a move from the board gets
 * the same one.
 *
 * Read of the ruling (build note): the pieces stack from the promotion square toward the
 * board's centre, queen nearest the square, then knight, rook, bishop (Lichess's order); the
 * rest of the board is dimmed; Q / R / B / N choose; Esc, or a click outside the picker,
 * cancels the move.
 */
import type { Key } from 'chessground/types'
import { isLightSquare } from './boardThemes'

export type PromotionRole = 'queen' | 'knight' | 'rook' | 'bishop'
/** The UCI suffix: e7e8q, e7e8n, e7e8r, e7e8b. */
export type PromotionPiece = 'q' | 'n' | 'r' | 'b'
export type Side = 'white' | 'black'

/** Queen nearest the promotion square, then knight, rook, bishop. */
export const PICKER_ORDER: readonly PromotionRole[] = ['queen', 'knight', 'rook', 'bishop']

export const ROLE_PIECE: Record<PromotionRole, PromotionPiece> = { queen: 'q', knight: 'n', rook: 'r', bishop: 'b' }

/** The piece letter on a square of a FEN's placement field ('P', 'n', ...), or null. */
export function pieceAt(fen: string, square: string): string | null {
  const file = square.charCodeAt(0) - 97
  const rank = Number(square[1])
  if (file < 0 || file > 7 || !(rank >= 1 && rank <= 8)) return null
  const rows = fen.split(' ')[0]?.split('/') ?? []
  const row = rows[8 - rank]
  if (row === undefined) return null
  let f = 0
  for (const ch of row) {
    if (ch >= '1' && ch <= '8') f += Number(ch)
    else {
      if (f === file) return ch
      f += 1
    }
    if (f > file) return null
  }
  return null
}

/** The side whose pawn promotes when it goes orig → dest, or null when the move is no promotion:
 *  a white pawn reaching the 8th rank from the 7th, or a black pawn the 1st from the 2nd, one file
 *  across at most. Legality is the board's: it only reports moves among its legal destinations,
 *  so a move this names that the board offered is a legal promotion. */
export function promotingSide(fen: string, orig: string, dest: string): Side | null {
  const p = pieceAt(fen, orig)
  if (Math.abs(orig.charCodeAt(0) - dest.charCodeAt(0)) > 1) return null
  if (p === 'P' && orig[1] === '7' && dest[1] === '8') return 'white'
  if (p === 'p' && orig[1] === '2' && dest[1] === '1') return 'black'
  return null
}

/** True when the move needs the picker: a pawn reaching the last rank, and the board offers it
 *  (dest is among orig's legal destinations). */
export function needsPicker(fen: string, orig: string, dest: string, dests?: Map<string, string[]>): boolean {
  if (dests && !(dests.get(orig) ?? []).includes(dest)) return false
  return promotingSide(fen, orig, dest) !== null
}

export interface PickerSquare {
  role: PromotionRole
  piece: PromotionPiece
  /** the board square the choice covers */
  square: Key
  /** 0–7 from the left and from the top, as the board is drawn */
  col: number
  row: number
  /** the square's own colour, from the board's theme */
  light: boolean
}

/** The four choices over the promotion square, running toward the board's centre: down from a
 *  square on the top edge, up from one on the bottom edge. With White at the bottom, White
 *  promotes at the top; with Black at the bottom the column flips. */
export function pickerSquares(dest: string, orientation: Side): PickerSquare[] {
  const file = dest.charCodeAt(0) - 97
  const rank = Number(dest[1]) - 1
  const col = orientation === 'white' ? file : 7 - file
  const row0 = orientation === 'white' ? 7 - rank : rank
  const dir = row0 < 4 ? 1 : -1
  return PICKER_ORDER.map((role, i) => {
    const row = row0 + dir * i
    const r = orientation === 'white' ? 7 - row : row
    const square = (String.fromCharCode(97 + file) + String(r + 1)) as Key
    return { role, piece: ROLE_PIECE[role], square, col, row, light: isLightSquare(square) }
  })
}

/** What a key does while the picker is open: a piece, 'cancel' (Esc), or null (not the
 *  picker's key). Q / R / B / N in either case; modified keys are not the picker's. */
export function pickerKey(e: { key: string; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean }): PromotionPiece | 'cancel' | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null
  if (e.key === 'Escape') return 'cancel'
  const k = e.key.toLowerCase()
  return k === 'q' || k === 'r' || k === 'b' || k === 'n' ? k : null
}

/** The UCI of a move, with its promotion piece when there is one. */
export function uciOf(orig: string, dest: string, piece?: PromotionPiece | null): string {
  return orig + dest + (piece ?? '')
}

/** The picker's state: closed, or open on one move of one position. */
export type PickerState = { orig: Key; dest: Key; side: Side; fen: string } | null

/** Open the picker for a move the board reports, or null when it is no promotion (the move
 *  goes straight through). */
export function openPicker(fen: string, orig: Key, dest: Key): PickerState {
  const side = promotingSide(fen, orig, dest)
  return side ? { orig, dest, side, fen } : null
}

/** The outcome of a key or a click while open: a move to send, or cancel (nothing sent, the
 *  pawn goes back). */
export type PickerOutcome = { kind: 'move'; orig: Key; dest: Key; piece: PromotionPiece; uci: string } | { kind: 'cancel' }

export function choose(state: NonNullable<PickerState>, piece: PromotionPiece | 'cancel'): PickerOutcome {
  if (piece === 'cancel') return { kind: 'cancel' }
  return { kind: 'move', orig: state.orig, dest: state.dest, piece, uci: uciOf(state.orig, state.dest, piece) }
}

/** The picker closes by itself (as a cancel) when the position under it changes, or the board
 *  stops taking moves (a game ended on the clock, the board left for another position). */
export function staleAfter(state: PickerState, fen: string, movable: boolean): boolean {
  return state !== null && (state.fen !== fen || !movable)
}
