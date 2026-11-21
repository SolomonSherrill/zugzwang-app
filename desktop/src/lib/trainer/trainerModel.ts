/**
 * The opening trainer's words and options (UI-BUILD-2 E3; DESIGN.md rulings 18, 21 and ruling 9
 * of 2026-11-20, third). Pure, so it can be tested.
 */
import { Chess } from 'chess.js'
import { TRAINER_DIFFICULTY_PRESETS, type Color, type TrainerLineProgress } from '../api'

/** Accept (ruling 9): This line only / Popular moves (today's Normal, the default) / Any book
 *  move (today's Loose). Strict is dropped. */
export type Accept = 'line' | 'popular' | 'any'
export const ACCEPT_OPTIONS: { value: Accept; label: string }[] = [
  { value: 'line', label: 'This line only' },
  { value: 'popular', label: 'Popular moves' },
  { value: 'any', label: 'Any book move' },
]
export const ACCEPT_DEFAULT: Accept = 'popular'
const preset = (name: string) => TRAINER_DIFFICULTY_PRESETS.find(([n]) => n === name)![1]
/** The weight threshold a book move needs (a share of the top move's weight). */
export const ACCEPT_THRESHOLD: Record<Exclude<Accept, 'line'>, number> = {
  popular: preset('Normal'),
  any: preset('Loose'),
}

/** Replies (ruling 21): Popular = varied (weighted by the book), Any book move = random
 *  (uniform over book replies), Main line = pinned (the top reply). */
export type Replies = 'varied' | 'random' | 'pinned'
export const REPLIES_OPTIONS: { value: Replies; label: string }[] = [
  { value: 'varied', label: 'Popular' },
  { value: 'random', label: 'Any book move' },
  { value: 'pinned', label: 'Main line' },
]
export const REPLIES_WORDS: Record<Replies, string> = {
  varied: 'popular replies',
  random: 'any book reply',
  pinned: 'main-line replies',
}

export type ColorRecord = NonNullable<TrainerLineProgress['byColor']>['white']

/** Ruling 18: the progress word for one colour, each a fact the record holds. */
export function progressWord(rec: ColorRecord | null | undefined): { word: string; detail: string | null } {
  if (!rec) return { word: 'Not tried', detail: null }
  const ends = rec.distinctLines > 1 ? `${rec.distinctLines} ends` : null
  if (rec.mastered) return { word: 'Mastered', detail: ends }
  if (rec.completions > 0) return { word: 'Finished', detail: ends }
  if (rec.attempts > 0) return { word: 'Tried', detail: null }
  return { word: 'Not tried', detail: null }
}

/** The options folded into one line (ruling 21): "As Black, popular replies, this line only, from move 1". */
export function summaryLine(color: Color, replies: Replies, accept: Accept, fromMove1: boolean): string {
  const parts = [`As ${color === 'white' ? 'White' : 'Black'}`]
  if (accept !== 'line') parts.push(REPLIES_WORDS[replies])
  parts.push(ACCEPT_OPTIONS.find((o) => o.value === accept)!.label.toLowerCase())
  parts.push(fromMove1 ? 'from move 1' : 'from the line start')
  return parts.join(', ')
}

/** A line's name without its family prefix. */
export function shortName(family: string, name: string): string {
  for (const prefix of [`${family}: `, `${family}, `, `${family} `]) {
    if (name.startsWith(prefix)) return name.slice(prefix.length)
  }
  return name === family ? 'Main line' : name
}

/** SAN of a move list from the start position, numbered ("1. e4 d5 2. exd5"). */
export function movesText(uci: string[], startFen?: string): string {
  const c = startFen ? new Chess(startFen) : new Chess()
  const out: string[] = []
  for (const u of uci) {
    const white = c.turn() === 'w'
    const n = c.moveNumber()
    const m = c.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] as 'q' | undefined })
    if (white) out.push(`${n}. ${m.san}`)
    else out.push(out.length === 0 ? `${n}… ${m.san}` : m.san)
  }
  return out.join(' ')
}

/** The last full move of a line, as the line list shows it ("3. Nc3 Qd8" or "2… Nf6 3. d4"). */
export function lineTail(uci: string[]): string {
  if (uci.length === 0) return ''
  const all = movesText(uci).split(' ')
  // keep from the last move number that starts a white move, or the last two tokens
  const lastNum = all.map((t, i) => (/^\d+\.$/.test(t) ? i : -1)).filter((i) => i >= 0).pop() ?? 0
  const tail = all.slice(Math.max(0, lastNum - (uci.length % 2 === 1 ? 0 : 0)))
  return tail.join(' ')
}

/** Full moves in a line ("9 moves"): the move number its last ply belongs to. */
export function fullMoves(plies: number): number {
  return Math.ceil(plies / 2)
}

/** "4… Nf6" / "5. Nf3": a ply's label from the move number and side. */
export function plyLabel(moveNumber: number, white: boolean, san: string): string {
  return white ? `${moveNumber}. ${san}` : `${moveNumber}… ${san}`
}

/** The Moves column of the families list (UI-BUILD-3 B2): the moves the family's lines share,
 *  not its most popular line (the Italian read "3. Bc4 h6"); sampleMoves stays for search. */
export function familyMovesText(f: { sharedMoves?: string }): string {
  return f.sharedMoves && f.sharedMoves.trim() ? f.sharedMoves : 'Several move orders'
}
