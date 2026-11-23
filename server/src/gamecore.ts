/**
 * The rules of a live friend game (FRIENDS.md "FRIENDS-2", rulings P1–P4, C1), as pure functions over a
 * plain state object: the Game Durable Object (game.ts) stores the state, keeps the sockets and the alarm,
 * and calls these with the server's clock. Nothing here reads a clock of its own, so the tests drive time.
 *
 * Move legality is chess.js (BSD-2-Clause, compatible with GPL-3.0). Decided for the owner to confirm
 * (FRIENDS-2 report): the first move of each side has FIRST_MOVE_MS and no clock (P2: no first move in time
 * aborts the game); the clocks start with Black's first move; the increment is added after every move made
 * on a running clock; threefold repetition, the fifty-move rule, stalemate and insufficient material end the
 * game at once (no claim needed); a flag against a side with only a king, or a king and one minor piece,
 * is a draw; a declined draw offer blocks that player's next offer for DRAW_GAP_PLIES plies, and a move by
 * the player offered the draw declines it; no premoves, no takebacks (P4).
 */
import { Chess } from 'chess.js'

export type Colour = 'white' | 'black'
export const other = (c: Colour): Colour => (c === 'white' ? 'black' : 'white')

/** the ten live time controls of ruling C1, minutes + seconds */
export const TIME_CONTROLS = ['1+0', '2+1', '3+0', '3+2', '5+0', '5+3', '10+0', '10+5', '15+10', '30+0'] as const
export type TimeControl = (typeof TIME_CONTROLS)[number]
export const isTimeControl = (s: unknown): s is TimeControl => typeof s === 'string' && (TIME_CONTROLS as readonly string[]).includes(s)
export function parseTc(tc: TimeControl): { base: number; inc: number } {
  const [m, s] = tc.split('+').map(Number)
  return { base: m * 60_000, inc: s * 1000 }
}
/** Chess.com's rating for the mode (ruling R1, as read): bullet under 3 minutes, blitz under 10, rapid from 10 */
export function speedOf(tc: TimeControl): 'bullet' | 'blitz' | 'rapid' {
  const { base } = parseTc(tc)
  return base < 180_000 ? 'bullet' : base < 600_000 ? 'blitz' : 'rapid'
}

export interface Timing {
  firstMoveMs: number
  disconnectMs: number
  /** local end-to-end runs only (the FLAG_TEST_MS variable, never set in production): a 1+0 game's clocks */
  flagTestMs?: number
}
export const DEFAULT_TIMING: Timing = { firstMoveMs: 30_000, disconnectMs: 30_000 }
/** after a declined offer, plies to wait before the same player may offer again (draw-offer spam, decided) */
export const DRAW_GAP_PLIES = 10

export interface Player {
  id: number
  handle: string
  /** verified linked accounts, for the apps' ratings at the game's start (R1–R3) */
  linked: { site: string; username: string }[]
  /** the player's "Chat in friend games" switch (H3) */
  chat: boolean
}

export type Status = 'waiting' | 'playing' | 'over'
export type Termination =
  | 'checkmate' | 'resign' | 'timeout' | 'timeout_vs_insufficient' | 'agreed' | 'stalemate'
  | 'repetition' | 'fifty_moves' | 'insufficient' | 'abandoned' | 'abandoned_draw' | 'aborted'

export interface GameState {
  id: string
  white: Player
  black: Player
  tc: TimeControl
  base_ms: number
  inc_ms: number
  created: number
  moves: string[]
  sans: string[]
  /** each side's remaining time, as of turn_started for the side to move */
  clock: Record<Colour, number>
  /** when the side to move's turn began, once the clocks run (after Black's first move) */
  turn_started: number | null
  /** the deadline for the first move of the side to move (P2), while status is 'waiting' */
  first_deadline: number | null
  status: Status
  result: '1-0' | '0-1' | '1/2-1/2' | '*' | null
  termination: Termination | null
  winner: Colour | null
  ended: number | null
  draw_offer: Colour | null
  /** the ply count from which each player may offer a draw again */
  draw_ok_from: Record<Colour, number>
  /** when each player's last connection closed (null while connected or never connected) */
  gone: Record<Colour, number | null>
  /** each player has connected to the game at least once */
  seen: Record<Colour, boolean>
  /** set when one player blocked the other during the game: no chat either way */
  chat_blocked: boolean
  /** per-player mute of the opponent's messages, this game only (H3) */
  muted: Record<Colour, boolean>
  /** each app has saved the finished game to its library */
  acked: Record<Colour, boolean>
  /** a rematch offered from this game, by whom */
  rematch_from: Colour | null
  /** the first-move window this game was made with (P2) */
  first_window: number
  /** the current position, and how often each position (FEN without the move counters) has stood, so a
   *  message never replays the whole game: one replay costs several milliseconds, and the Free plan gives a
   *  Worker 10 ms of CPU per invocation (FRIENDS-2 report, "the free plan") */
  fen: string
  positions: Record<string, number>
  /** the PGN, written once when the game ends */
  pgn_text: string | null
}

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const positionKey = (fen: string) => fen.split(' ').slice(0, 4).join(' ')

export class RuleError extends Error {
  constructor(readonly code: string, message: string) {
    super(message)
  }
}

export function newGame(id: string, white: Player, black: Player, tc: TimeControl, now: number, timing: Timing = DEFAULT_TIMING): GameState {
  const parsed = parseTc(tc)
  const base = tc === '1+0' && timing.flagTestMs ? timing.flagTestMs : parsed.base
  const inc = parsed.inc
  return {
    id, white, black, tc, base_ms: base, inc_ms: inc, created: now,
    moves: [], sans: [],
    clock: { white: base, black: base },
    turn_started: null,
    first_deadline: now + timing.firstMoveMs,
    status: 'waiting', result: null, termination: null, winner: null, ended: null,
    draw_offer: null, draw_ok_from: { white: 0, black: 0 },
    gone: { white: null, black: null },
    seen: { white: false, black: false },
    chat_blocked: false, muted: { white: false, black: false },
    acked: { white: false, black: false }, rematch_from: null,
    first_window: timing.firstMoveMs,
    fen: START, positions: { [positionKey(START)]: 1 }, pgn_text: null,
  }
}

export function colourOf(s: GameState, accountId: number): Colour | null {
  return s.white.id === accountId ? 'white' : s.black.id === accountId ? 'black' : null
}

/** the position as a chess.js board, kept per state object while it lives in memory */
const boards = new WeakMap<GameState, Chess>()
export function board(s: GameState): Chess {
  let c = boards.get(s)
  if (!c || c.fen() !== s.fen) {
    c = new Chess(s.fen)
    boards.set(s, c)
  }
  return c
}

/** the whole game replayed from the start (the PGN only) */
function replay(s: GameState): Chess {
  const c = new Chess()
  for (const m of s.moves) c.move(uciToMove(m))
  return c
}

function uciToMove(uci: string): { from: string; to: string; promotion?: string } {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined }
}

export const turnOf = (s: GameState): Colour => (s.moves.length % 2 === 0 ? 'white' : 'black')

/** the side's time left at `now` */
export function remaining(s: GameState, c: Colour, now: number): number {
  if (s.status === 'playing' && s.turn_started !== null && turnOf(s) === c) return s.clock[c] - (now - s.turn_started)
  return s.clock[c]
}

function end(s: GameState, now: number, termination: Termination, winner: Colour | null): void {
  s.status = 'over'
  s.termination = termination
  s.winner = winner
  s.result = termination === 'aborted' ? '*' : winner === 'white' ? '1-0' : winner === 'black' ? '0-1' : '1/2-1/2'
  s.ended = now
  s.draw_offer = null
  // the clock of the side to move stops where it was
  if (s.turn_started !== null) {
    const c = turnOf(s)
    s.clock[c] = Math.max(0, s.clock[c] - (now - s.turn_started))
    s.turn_started = null
  }
  s.first_deadline = null
  if (s.result !== '*') s.pgn_text = makePgn(s)
}

/** a side that cannot mate however the other plays: a bare king, or a king and one knight or bishop */
export function cannotMate(fen: string, c: Colour): boolean {
  const placement = fen.split(' ')[0]
  const mine = [...placement].filter((ch) => /[a-zA-Z]/.test(ch) && (c === 'white' ? ch === ch.toUpperCase() : ch === ch.toLowerCase()))
  const rest = mine.map((ch) => ch.toLowerCase()).filter((ch) => ch !== 'k')
  return rest.length === 0 || (rest.length === 1 && (rest[0] === 'n' || rest[0] === 'b'))
}

/** Time-driven endings: an abort (P2) or a flag. Returns true when the state changed. */
export function tick(s: GameState, now: number): boolean {
  if (s.status === 'waiting' && s.first_deadline !== null && now >= s.first_deadline) {
    end(s, now, 'aborted', null)
    return true
  }
  if (s.status === 'playing') {
    const c = turnOf(s)
    if (remaining(s, c, now) <= 0) {
      const fen = s.fen
      const flagTime = (s.turn_started ?? now) + s.clock[c]
      if (cannotMate(fen, other(c))) end(s, flagTime, 'timeout_vs_insufficient', null)
      else end(s, flagTime, 'timeout', other(c))
      s.clock[c] = 0
      return true
    }
  }
  return false
}

export function move(s: GameState, c: Colour, uci: string, ply: number | undefined, now: number): void {
  tick(s, now)
  if (s.status === 'over') throw new RuleError('game_over', 'The game is over.')
  if (turnOf(s) !== c) throw new RuleError('not_your_turn', 'It is not your move.')
  if (ply !== undefined && ply !== s.moves.length) throw new RuleError('stale_ply', 'That move was for another position.')
  if (typeof uci !== 'string' || !/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci)) throw new RuleError('bad_move', 'That is not a move.')
  const b = board(s)
  let m
  try {
    m = b.move(uciToMove(uci))
  } catch {
    throw new RuleError('illegal', 'That move is not legal.')
  }
  if (s.status === 'playing' && s.turn_started !== null) {
    s.clock[c] = s.clock[c] - (now - s.turn_started) + s.inc_ms
  }
  s.moves.push(m.lan)
  s.sans.push(m.san)
  s.fen = b.fen()
  const key = positionKey(s.fen)
  s.positions[key] = (s.positions[key] ?? 0) + 1
  // a move by the player offered the draw declines it; the offerer's own move keeps it
  if (s.draw_offer === other(c)) declined(s, other(c))
  if (s.status === 'waiting') {
    if (s.moves.length === 1) s.first_deadline = now + s.first_window
    else {
      s.status = 'playing'
      s.first_deadline = null
      s.turn_started = now
    }
  } else {
    s.turn_started = now
  }
  if (b.isCheckmate()) end(s, now, 'checkmate', c)
  else if (b.isStalemate()) end(s, now, 'stalemate', null)
  else if (b.isInsufficientMaterial()) end(s, now, 'insufficient', null)
  else if (s.positions[key] >= 3) end(s, now, 'repetition', null)
  else if (b.isDrawByFiftyMoves()) end(s, now, 'fifty_moves', null)
}

function declined(s: GameState, offerer: Colour): void {
  s.draw_offer = null
  s.draw_ok_from[offerer] = s.moves.length + DRAW_GAP_PLIES
}

export function resign(s: GameState, c: Colour, now: number): void {
  tick(s, now)
  if (s.status === 'over') throw new RuleError('game_over', 'The game is over.')
  if (s.status === 'waiting') end(s, now, 'aborted', null)
  else end(s, now, 'resign', other(c))
}

export function canOfferDraw(s: GameState, c: Colour): boolean {
  return s.status === 'playing' && s.draw_offer === null && s.moves.length >= s.draw_ok_from[c]
}

export function offerDraw(s: GameState, c: Colour, now: number): void {
  tick(s, now)
  if (s.status !== 'playing') throw new RuleError(s.status === 'over' ? 'game_over' : 'not_started', 'A draw can be offered once both sides have moved.')
  if (s.draw_offer === other(c)) {
    end(s, now, 'agreed', null) // offering back accepts
    return
  }
  if (s.draw_offer === c) throw new RuleError('already_offered', 'You already offered a draw.')
  if (!canOfferDraw(s, c)) throw new RuleError('too_soon', 'You offered a draw recently: play on a few moves first.')
  s.draw_offer = c
}

export function answerDraw(s: GameState, c: Colour, accept: boolean, now: number): void {
  tick(s, now)
  if (s.status === 'over') throw new RuleError('game_over', 'The game is over.')
  if (s.draw_offer !== other(c)) throw new RuleError('no_offer', 'There is no draw offer to answer.')
  if (accept) end(s, now, 'agreed', null)
  else declined(s, other(c))
}

/** when `c` may claim the win or call a draw (P1): the opponent gone for disconnectMs, or null */
export function claimAt(s: GameState, c: Colour, connected: Record<Colour, boolean>, timing: Timing): number | null {
  const o = other(c)
  if (s.status !== 'playing' || connected[o] || !connected[c] || s.gone[o] === null) return null
  return s.gone[o]! + timing.disconnectMs
}

export function claim(s: GameState, c: Colour, win: boolean, connected: Record<Colour, boolean>, timing: Timing, now: number): void {
  tick(s, now)
  if (s.status === 'over') throw new RuleError('game_over', 'The game is over.')
  const at = claimAt(s, c, connected, timing)
  if (at === null) throw new RuleError('opponent_here', 'Your opponent is still connected.')
  if (now < at) throw new RuleError('too_soon', 'Wait until they have been gone 30 seconds.')
  end(s, now, win ? 'abandoned' : 'abandoned_draw', win ? c : null)
}

/** a player whose account is deleted mid-game resigns it (an abort before the first moves) */
export function abandon(s: GameState, c: Colour, now: number): void {
  if (s.status === 'over') return
  if (s.status === 'waiting') end(s, now, 'aborted', null)
  else end(s, now, 'resign', other(c))
}

/** the next time the game needs the alarm: an abort deadline, a flag, a claim becoming available */
export function nextWake(s: GameState, connected: Record<Colour, boolean>, timing: Timing): number | null {
  const times: number[] = []
  if (s.status === 'waiting' && s.first_deadline !== null) times.push(s.first_deadline)
  if (s.status === 'playing' && s.turn_started !== null) {
    const c = turnOf(s)
    times.push(s.turn_started + s.clock[c])
  }
  for (const c of ['white', 'black'] as Colour[]) {
    const at = claimAt(s, c, connected, timing)
    if (at !== null) times.push(at)
  }
  return times.length ? Math.min(...times) : null
}

const TERMINATION_TEXT: Record<Termination, string> = {
  checkmate: 'checkmate', resign: 'resignation', timeout: 'time forfeit', timeout_vs_insufficient: 'time forfeit, insufficient material',
  agreed: 'draw by agreement', stalemate: 'stalemate', repetition: 'threefold repetition', fifty_moves: 'fifty-move rule',
  insufficient: 'insufficient material', abandoned: 'abandoned', abandoned_draw: 'abandoned, called a draw', aborted: 'aborted',
}

/** The PGN both apps save (G2): standard headers, the handles as names, no ratings (unrated, C1). */
export function pgn(s: GameState): string {
  return s.pgn_text ?? makePgn(s)
}

function makePgn(s: GameState): string {
  const b = replay(s)
  const d = new Date(s.created)
  const date = `${d.getUTCFullYear()}.${String(d.getUTCMonth() + 1).padStart(2, '0')}.${String(d.getUTCDate()).padStart(2, '0')}`
  const { base, inc } = parseTc(s.tc)
  const headers: [string, string][] = [
    ['Event', 'Zugzwang friend game'], ['Site', 'Zugzwang'], ['Date', date], ['Round', '-'],
    ['White', s.white.handle], ['Black', s.black.handle], ['Result', s.result ?? '*'],
    ['Rated', 'false'], ['TimeControl', `${base / 1000}+${inc / 1000}`], ['Termination', s.termination ? TERMINATION_TEXT[s.termination] : 'unterminated'],
    ['ZugzwangGameId', s.id],
  ]
  for (const [k, v] of headers) b.setHeader(k, v)
  return b.pgn()
}

export function terminationText(t: Termination | null): string | null {
  return t ? TERMINATION_TEXT[t] : null
}
