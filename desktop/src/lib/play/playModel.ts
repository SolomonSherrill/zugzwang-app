/**
 * Play's model (DESIGN.md "Play: new game", "Play: game in progress", ruling 15): the ten time
 * controls grouped by speed, the labels the screen shows, the clock text, the plain move list's
 * rows and the result sentence. Pure functions; the screen is `PlayView.svelte`.
 */
import { describeTermination, type Color, type GameEndInfo } from '../api'

export type Speed = 'bullet' | 'blitz' | 'rapid' | 'classical'

export interface PlayTimeControl {
  initialS: number
  incrementS: number
}

/** The ten controls, in the order the old screen stored its preference index in (and as
 *  `config.TIME_CONTROLS` lists them). */
export const PLAY_TIME_CONTROLS: PlayTimeControl[] = [
  { initialS: 60, incrementS: 0 },
  { initialS: 120, incrementS: 1 },
  { initialS: 180, incrementS: 0 },
  { initialS: 180, incrementS: 2 },
  { initialS: 300, incrementS: 0 },
  { initialS: 300, incrementS: 3 },
  { initialS: 600, incrementS: 0 },
  { initialS: 600, incrementS: 5 },
  { initialS: 900, incrementS: 10 },
  { initialS: 1800, incrementS: 0 },
]
/** 10+0, as the mockup selects it. */
export const TIME_CONTROL_DEFAULT = 6
export const LEVEL_DEFAULT = 10
export const LEVEL_MAX = 20

export const SPEED_LABEL: Record<Speed, string> = {
  bullet: 'Bullet',
  blitz: 'Blitz',
  rapid: 'Rapid',
  classical: 'Classical',
}

/** The speed bucket as the database files a game under it (`database.speed_from_time_control`:
 *  the Lichess estimate, base + 40 x increment seconds). */
export function speedOf(tc: PlayTimeControl): Speed {
  const estimate = tc.initialS + 40 * tc.incrementS
  if (estimate < 180) return 'bullet'
  if (estimate < 480) return 'blitz'
  if (estimate < 1500) return 'rapid'
  return 'classical'
}

/** "10+0", "2+1": minutes + increment seconds. */
export function tcLabel(tc: PlayTimeControl): string {
  const m = tc.initialS / 60
  return `${Number.isInteger(m) ? m : m.toFixed(1)}+${tc.incrementS}`
}

/** The PGN TimeControl header ("600+0"): seconds + increment seconds. */
export function tcPgn(tc: PlayTimeControl): string {
  return `${tc.initialS}+${tc.incrementS}`
}

export interface TcGroup {
  speed: Speed
  label: string
  /** indexes into PLAY_TIME_CONTROLS */
  indexes: number[]
}

/** The controls grouped by speed, in speed order (Bullet 1+0, 2+1; Blitz 3+0, 3+2, 5+0, 5+3;
 *  Rapid 10+0, 10+5, 15+10; Classical 30+0). */
export const TC_GROUPS: TcGroup[] = (['bullet', 'blitz', 'rapid', 'classical'] as Speed[]).map((speed) => ({
  speed,
  label: SPEED_LABEL[speed],
  indexes: PLAY_TIME_CONTROLS.flatMap((tc, i) => (speedOf(tc) === speed ? [i] : [])),
}))

/** "9:12"; under ten seconds with tenths ("0:07.4"); past an hour "1:02:05". */
export function clockText(ms: number): string {
  const clamped = Math.max(0, ms)
  if (clamped < 10_000) {
    const tenths = Math.floor(clamped / 100)
    return `0:0${Math.floor(tenths / 10)}.${tenths % 10}`
  }
  const totalS = Math.floor(clamped / 1000)
  const h = Math.floor(totalS / 3600)
  const m = Math.floor((totalS % 3600) / 60)
  const s = String(totalS % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

/** The mover's clock after a move (UI-BUILD-3 F, ruling 9): the time left when they moved plus the
 *  increment, in whole ms, as chess.com's and Lichess's [%clk] count it (Review's time spent reads
 *  it that way). Sent with the user's move; the sidecar writes it into the saved game. */
export function clockAfterMove(leftMs: number, incrementMs: number): number {
  return Math.round(Math.max(0, leftMs) + Math.max(0, incrementMs))
}

/** The engine's clock after its move: the sidecar measures the engine's thinking and sends the
 *  clock it saved with the move, so the screen shows what the game records; with none (an older
 *  sidecar, or an untimed game) the screen keeps its own. */
export function engineClockAfter(reportedMs: unknown, ownMs: number): number {
  return typeof reportedMs === 'number' && Number.isFinite(reportedMs) && reportedMs >= 0 ? reportedMs : ownMs
}

/** The engine's player strip: "Stockfish (Level 10)". */
export function engineStrip(level: number): { name: string; rating: string } {
  return { name: 'Stockfish', rating: `Level ${level}` }
}

/** The breadcrumb's title: "Stockfish, level 10". */
export function crumbTitle(level: number): string {
  return `Stockfish, level ${level}`
}

/** The user's strip: their Chess.com name, else their Lichess name (the accounts in Settings);
 *  with neither, just "You". */
export function youStrip(accounts: { chesscom: string; lichess: string }): { name: string; you: boolean } {
  const name = accounts.chesscom.trim() || accounts.lichess.trim()
  return name ? { name, you: true } : { name: 'You', you: false }
}

/** The opening line under the panel's title: "B90, casual"; "casual" before the book names one. */
export function openingSub(eco: string | null): string {
  return eco ? `${eco}, casual` : 'casual'
}

export interface MoveCell {
  san: string
  /** 0-based ply index into the game's moves */
  ply: number
}
export interface MoveRow {
  number: number
  white: MoveCell | null
  black: MoveCell | null
}

/** The plain move list's rows, from the starting position's side to move and move number
 *  (a game from a set position can start with Black). */
export function moveRows(sans: string[], startFen: string): MoveRow[] {
  const parts = startFen.split(' ')
  const blackFirst = parts[1] === 'b'
  let number = Number(parts[5]) || 1
  const rows: MoveRow[] = []
  let i = 0
  if (blackFirst && sans.length) {
    rows.push({ number, white: null, black: { san: sans[0], ply: 0 } })
    number++
    i = 1
  }
  for (; i < sans.length; i += 2) {
    rows.push({
      number,
      white: { san: sans[i], ply: i },
      black: i + 1 < sans.length ? { san: sans[i + 1], ply: i + 1 } : null,
    })
    number++
  }
  return rows
}

/** What the game came to, in the player's terms: "You won by checkmate.", "You lost on time.",
 *  "Draw by stalemate.", "Draw agreed.". */
export function resultSentence(end: Pick<GameEndInfo, 'result' | 'termination'>, you: Color): string {
  const t = end.termination
  if (end.result === '*') return 'Game abandoned.'
  if (end.result === '1/2-1/2') return t === 'draw_agreed' ? 'Draw agreed.' : `Draw by ${describeTermination(t)}.`
  const won = (end.result === '1-0') === (you === 'white')
  if (t === 'resignation') return won ? 'Stockfish resigned.' : 'You resigned.'
  if (t === 'timeout') return won ? 'You won on time.' : 'You lost on time.'
  return `${won ? 'You won' : 'Stockfish won'} by ${describeTermination(t)}.`
}

/** The saved preferences (colour, level, time control), read defensively. */
export interface PlayPrefs {
  color: Color
  level: number
  tc: number
}
export function readPrefs(raw: string | null): PlayPrefs {
  let saved: Record<string, unknown> = {}
  try {
    saved = JSON.parse(raw ?? '{}') ?? {}
  } catch {
    saved = {}
  }
  const level = typeof saved.skill === 'number' && Number.isInteger(saved.skill) && saved.skill >= 0 && saved.skill <= LEVEL_MAX ? saved.skill : LEVEL_DEFAULT
  const tc = typeof saved.tc === 'number' && PLAY_TIME_CONTROLS[saved.tc] ? saved.tc : TIME_CONTROL_DEFAULT
  return { color: saved.color === 'black' ? 'black' : 'white', level, tc }
}
/** Written under the old screen's key and field names, so a saved choice carries over. */
export function writePrefs(p: PlayPrefs): string {
  return JSON.stringify({ color: p.color, skill: p.level, tc: p.tc })
}
