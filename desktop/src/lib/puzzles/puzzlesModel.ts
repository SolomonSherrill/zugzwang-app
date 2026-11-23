/** Puzzles' pure wording and shaping (UI-BUILD-2 E2; DESIGN.md "Puzzles", "Puzzles: rated
 *  session", ruling 19). Every figure is read off stored fields or this session's own results. */
import type { PuzzleSessionRow, PuzzleSummary } from '../api'
import { Chess, type Square } from 'chess.js'
import { changeText } from '../home/homeModel'

/** Lichess theme tags in sentence case (design system, Words). */
const THEME_LABELS: Record<string, string> = {
  advancedPawn: 'Advanced pawn',
  anastasiaMate: "Anastasia's mate",
  arabianMate: 'Arabian mate',
  attackingF2F7: 'Attacking f2 or f7',
  backRankMate: 'Back rank mate',
  bodenMate: "Boden's mate",
  capturingDefender: 'Capturing the defender',
  defensiveMove: 'Defensive move',
  discoveredAttack: 'Discovered attack',
  doubleBishopMate: 'Double bishop mate',
  doubleCheck: 'Double check',
  dovetailMate: 'Dovetail mate',
  enPassant: 'En passant',
  exposedKing: 'Exposed king',
  hangingPiece: 'Hanging piece',
  hookMate: 'Hook mate',
  kingsideAttack: 'Kingside attack',
  mate: 'Checkmate',
  mateIn1: 'Mate in 1',
  mateIn2: 'Mate in 2',
  mateIn3: 'Mate in 3',
  mateIn4: 'Mate in 4',
  mateIn5: 'Mate in 5',
  queenRookEndgame: 'Queen and rook endgame',
  queensideAttack: 'Queenside attack',
  quietMove: 'Quiet move',
  smotheredMate: 'Smothered mate',
  superGM: 'Super GM game',
  trappedPiece: 'Trapped piece',
  underPromotion: 'Underpromotion',
  xRayAttack: 'X-ray attack',
  oneMove: 'One move',
  veryLong: 'Very long',
  masterVsMaster: 'Master vs master',
}

export function themeLabel(tag: string): string {
  if (THEME_LABELS[tag]) return THEME_LABELS[tag]
  const words = tag.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** The themes Rated offers (today's theme mode, ruling 19), in the order shown. */
export const RATED_THEMES: string[] = [
  'fork', 'pin', 'skewer', 'discoveredAttack', 'backRankMate', 'mateIn2',
  'doubleCheck', 'mate', 'mateIn1', 'sacrifice', 'deflection', 'attraction', 'clearance',
  'xRayAttack', 'hangingPiece', 'trappedPiece', 'quietMove', 'promotion', 'underPromotion',
  'enPassant', 'endgame', 'rookEndgame', 'pawnEndgame', 'queenEndgame', 'knightEndgame',
  'bishopEndgame', 'middlegame', 'opening', 'crushing', 'advantage', 'zugzwang',
]
/** How many show before "N more" (the mockup draws six). */
export const RATED_THEMES_SHOWN = 6

/** Tags that say how long a puzzle is, how big its win, where it came from or its phase:
 *  not what the puzzle is about, so a puzzle's own list leaves them out (the phase stays
 *  when nothing else is left). */
const META_TAGS = new Set([
  'oneMove', 'short', 'long', 'veryLong', 'advantage', 'crushing', 'equality',
  'master', 'masterVsMaster', 'superGM',
])
const PHASE_TAGS = new Set(['opening', 'middlegame', 'endgame'])

/** A puzzle's themes for display: "fork pin middlegame short" → ["Fork", "Pin"]. */
export function puzzleThemes(themes: string | null | undefined): string[] {
  const tags = (themes ?? '').split(/\s+/).filter(Boolean)
  const motifs = tags.filter((t) => !META_TAGS.has(t) && !PHASE_TAGS.has(t))
  const shown = motifs.length ? motifs : tags.filter((t) => PHASE_TAGS.has(t))
  return shown.map(themeLabel)
}

const SIDE = { w: 'White', b: 'Black' } as const

/** The side to move in a FEN, as a word. */
export function sideOf(fen: string): 'White' | 'Black' {
  return fen.split(' ')[1] === 'b' ? 'Black' : 'White'
}

/** The opponent's last move, named: the puzzle FEN is the position before the setup move,
 *  so its side and move number are the mover's ("Black played 21… e6"). */
export function opponentMoveText(fenBefore: string, san: string): string {
  const f = fenBefore.split(' ')
  const side = f[1] === 'b' ? 'b' : 'w'
  const n = Number(f[5]) || 1
  return `${SIDE[side]} played ${n}${side === 'b' ? '…' : '.'} ${san}`
}

/** "Rated", "Rated, themes", "Rush, 3 min", "Survival". */
export function sessionModeLabel(row: Pick<PuzzleSessionRow, 'mode' | 'timeLimit'>): string {
  if (row.mode === 'rated') return 'Rated'
  if (row.mode === 'theme') return 'Rated, themes'
  if (row.mode === 'rush') return row.timeLimit ? `Rush, ${Math.round(row.timeLimit / 60)} min` : 'Rush'
  if (row.mode === 'survival') return 'Survival'
  return row.mode
}

export interface Tone {
  text: string
  tone: 'win' | 'loss' | null
}

/** The Solved column: "14 of 19" for a rated session, the score for Rush and Survival. */
export function sessionSolvedText(row: PuzzleSessionRow): string {
  if (row.mode === 'rush' || row.mode === 'survival') return String(row.score ?? 0)
  return `${row.solved} of ${row.tried}`
}

/** The Rating column: a rated session's change, "Best" for a best Rush or Survival score. */
export function sessionRatingText(row: PuzzleSessionRow): Tone | null {
  if (row.mode === 'rush' || row.mode === 'survival') return row.best ? { text: 'Best', tone: 'win' } : null
  return signed(row.ratingChange)
}

/** "+7" in win, "−11" in loss, "0" plain; null for no change. */
export function signed(c: number | null): Tone | null {
  const t = changeText(c)
  if (t === null) return null
  return { text: t, tone: c! > 0 ? 'win' : c! < 0 ? 'loss' : null }
}

/** "81% of tries". */
export function shareOfTries(solved: number, tries: number): string | null {
  if (!tries) return null
  return `${Math.round((solved / tries) * 100)}% of tries`
}

/** The rating cell's line under the figure: a new peak only on the day (ruling 8), else the
 *  30-day change as on Home (none when the first attempt is inside the window, ruling 5). */
export function ratingSubLine(s: PuzzleSummary): Tone | null {
  const r = s.rating
  if (!r) return s.tries === 0 ? { text: 'Starting rating', tone: null } : null
  if (r.newPeak) return { text: '↑ New peak today', tone: 'win' }
  const c = signed(r.change)
  return c ? { text: `${c.text} in 30 days`, tone: c.tone } : null
}

/** Best score for a Rush length in seconds; null when no finished session. */
export function rushBest(s: PuzzleSummary, seconds: number): number | null {
  return s.rushBest[String(seconds)] ?? null
}

/** One puzzle of this session, as the panel lists it. */
export interface SessionResult {
  id: string
  /** the puzzle's own rating, shown once it is done */
  rating: number
  themes: string
  /** solved without a miss */
  clean: boolean
  /** the user's rating change from this puzzle (rated only) */
  change: number | null
}

/** Streak (clean solves at the end), solved without a miss, and tried. */
export function tally(results: SessionResult[]): { streak: number; solved: number; tried: number } {
  let streak = 0
  for (let i = results.length - 1; i >= 0 && results[i].clean; i--) streak++
  return { streak, solved: results.filter((r) => r.clean).length, tried: results.length }
}

/** "2:41" for a Rush clock. */
export function clockText(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// ── the move list (UI-BUILD-3 J; DESIGN.md fourth rulings, 11) ──────────────────────────

/** Who put a move in the list: the opponent's setup move, a move played on the board (yours or
 *  the puzzle's reply), or the rest of the solution, shown once the solution is asked for. */
export type PlyKind = 'setup' | 'played' | 'solution'

export interface PuzzlePly {
  uci: string
  san: string
  /** the position after the move */
  fen: string
  kind: PlyKind
}

/** A puzzle's moves so far. Wrong tries are kept beside the line, never in it: the board took
 *  them back, so they are not positions to step to. */
export interface PuzzleLine {
  /** the puzzle's FEN: the position before the setup move */
  startFen: string
  plies: PuzzlePly[]
  /** wrong moves tried (SAN), by the index of the ply they were tried for, in order */
  tries: Record<number, string[]>
}

export function newLine(startFen: string): PuzzleLine {
  return { startFen, plies: [], tries: {} }
}

export function uciToMove(uci: string): { from: Square; to: Square; promotion?: string } {
  return { from: uci.slice(0, 2) as Square, to: uci.slice(2, 4) as Square, promotion: uci[4] || undefined }
}

const lastFen = (line: PuzzleLine) => line.plies.at(-1)?.fen ?? line.startFen

/** The line with one more move; throws on an illegal move. */
export function withPly(line: PuzzleLine, uci: string, kind: PlyKind): PuzzleLine {
  const b = new Chess(lastFen(line))
  const m = b.move(uciToMove(uci))
  return { ...line, plies: [...line.plies, { uci, san: m.san, fen: b.fen(), kind }] }
}

/** The line with the rest of the solution after it. */
export function withSolution(line: PuzzleLine, ucis: string[]): PuzzleLine {
  return ucis.reduce((l, u) => withPly(l, u, 'solution'), line)
}

/** A wrong move tried for the next ply, kept as SAN beside the line. */
export function withTry(line: PuzzleLine, uci: string): PuzzleLine {
  let san = uci
  try {
    san = new Chess(lastFen(line)).move(uciToMove(uci)).san
  } catch {
    // an illegal "try" cannot come from the board; keep the UCI if it ever does
  }
  const at = line.plies.length
  return { ...line, tries: { ...line.tries, [at]: [...(line.tries[at] ?? []), san] } }
}

/** Where the list is looked at: a ply index, or null for the end (following play). */
export type View = number | null

/** A step through the moves: one back or forward, the setup move (Home), the end (End). */
export type Step = -1 | 1 | 'start' | 'end'

export function stepOf(key: string): Step | null {
  if (key === 'ArrowLeft') return -1
  if (key === 'ArrowRight') return 1
  if (key === 'Home') return 'start'
  if (key === 'End') return 'end'
  return null
}

/** The index of the ply on the board; -1 before the setup move is played. */
export function shownIndex(line: PuzzleLine, view: View): number {
  const last = line.plies.length - 1
  return view === null ? last : Math.max(0, Math.min(last, view))
}

/** Look at a ply: clamped to the list, and null (back to play) at its end. The earliest is the
 *  setup move: the position before it is not one of the puzzle's. */
export function selectView(line: PuzzleLine, index: number): View {
  const last = line.plies.length - 1
  if (last < 0) return null
  const i = Math.max(0, Math.min(last, index))
  return i === last ? null : i
}

export function stepView(line: PuzzleLine, view: View, step: Step): View {
  if (step === 'end') return null
  if (step === 'start') return selectView(line, 0)
  return selectView(line, shownIndex(line, view) + step)
}

/** Looking at an earlier move than the last one: the board cannot be moved. */
export function lookingBack(line: PuzzleLine, view: View): boolean {
  return view !== null && view < line.plies.length - 1
}

/** The user may move only on their turn and only at the end of the list. */
export function canMove(state: string, line: PuzzleLine, view: View): boolean {
  return state === 'awaiting' && !lookingBack(line, view)
}

/** The position and last move to draw for a view (null before the setup move). */
export function shownPly(line: PuzzleLine, view: View): PuzzlePly | null {
  return line.plies[shownIndex(line, view)] ?? null
}

/** In the solution, the arrow shows the move after the one on the board. */
export function nextUci(line: PuzzleLine, view: View): string | null {
  return line.plies[shownIndex(line, view) + 1]?.uci ?? null
}

/** One cell of the list. `san` is null for the move still to find, shown only when it has
 *  wrong tries. */
export interface MoveCell {
  index: number
  san: string | null
  kind: PlyKind | null
  tries: string[]
}
export interface PuzzleMoveRow {
  number: number
  white: MoveCell | null
  black: MoveCell | null
}

/** The list's rows, numbered from the puzzle's FEN (the setup move's mover and number). */
export function puzzleMoveRows(line: PuzzleLine): PuzzleMoveRow[] {
  const cells: MoveCell[] = line.plies.map((p, i) => ({ index: i, san: p.san, kind: p.kind, tries: line.tries[i] ?? [] }))
  const pending = line.tries[line.plies.length]
  if (pending?.length) cells.push({ index: line.plies.length, san: null, kind: null, tries: pending })
  const f = line.startFen.split(' ')
  let number = Number(f[5]) || 1
  let white = f[1] !== 'b'
  const rows: PuzzleMoveRow[] = []
  for (const c of cells) {
    if (white) rows.push({ number, white: c, black: null })
    else if (rows.length && rows[rows.length - 1].black === null && rows[rows.length - 1].number === number) rows[rows.length - 1].black = c
    else rows.push({ number, white: null, black: c })
    if (!white) number++
    white = !white
  }
  return rows
}

// ── the puzzle database: where it came from, a download's progress (FIX-B6 B, ruling PZ1) ─────────

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** "1 November 2026" from an ISO date-time, in UTC (Lichess's Last-Modified is UTC). */
export function longDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`
}

const n = (x: number) => x.toLocaleString('en-US')
/** Megabytes as the progress shows them: whole MB, 1 MB = 1,000,000 bytes. */
export const mb = (bytes: number) => `${n(Math.round(bytes / 1e6))} MB`

/** The copy you have: its count from the import, its date from the file (never hard-coded). */
export function copyLine(s: { count: number; source?: string | null; sourceDate?: string | null; importedAt?: string | null }): string {
  const count = `${n(s.count)} ${s.count === 1 ? 'puzzle' : 'puzzles'}`
  const date = longDate(s.sourceDate)
  if (s.source === 'lichess' && date) return `${count}, from Lichess's puzzle database of ${date}.`
  const on = longDate(s.importedAt)
  return on ? `${count}, imported from a file on ${on}.` : `${count}.`
}

export interface ImportProgress {
  kind: 'lichess' | 'file'
  bytes: number
  totalBytes: number | null
  imported: number
}

/** 0..1 of the file read, or null when its size is unknown. */
export function progressShare(p: ImportProgress | null): number | null {
  if (!p || !p.totalBytes) return null
  return Math.min(0.99, p.bytes / p.totalBytes)
}

export function progressLine(p: ImportProgress | null, finishing: boolean): string {
  if (finishing) return 'Building the puzzle index…'
  const verb = p?.kind === 'file' ? 'Reading the file' : 'Downloading from Lichess'
  if (!p || p.bytes === 0) return `${verb}…`
  const of = p.totalBytes ? `${mb(p.bytes)} of ${mb(p.totalBytes)}` : mb(p.bytes)
  return `${verb}: ${of}, ${n(p.imported)} puzzles so far.`
}

export interface ImportDone {
  count: number
  added: number
  removed: number
  removedAttempted: number
}

/** What an import changed, said once it is done. */
export function doneLine(d: ImportDone): string {
  if (d.removed === 0 && d.added === d.count) return `${n(d.count)} puzzles imported.`
  const parts = [`${n(d.added)} new`]
  if (d.removed > 0) {
    const tried = d.removedAttempted > 0 ? ` (${n(d.removedAttempted)} you had tried; your results are kept)` : ''
    parts.push(`${n(d.removed)} removed by Lichess${tried}`)
  }
  return `Puzzles updated: ${parts.join(', ')}. ${n(d.count)} in all.`
}

/** The answer to "Check for new puzzles". */
export function updateLine(u: { date: string | null; bytes: number | null; newer: boolean }): string {
  const date = longDate(u.date)
  if (!u.newer) return date ? `You have the newest: Lichess's puzzle database of ${date}.` : 'You have the newest puzzles.'
  const size = u.bytes ? ` (${mb(u.bytes)} to download)` : ''
  return date ? `Lichess has puzzles of ${date}${size}.` : `Lichess has new puzzles${size}.`
}
