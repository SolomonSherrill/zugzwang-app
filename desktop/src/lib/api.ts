/**
 * Typed surface over the sidecar protocol, plus the chess display constants
 * shared by screens. Display constants mirror zugzwang/config.py.
 */
import { Sidecar, type SidecarStatus } from './sidecar'

export type { SidecarStatus }

export const sidecar = new Sidecar()

// ── protocol types ──────────────────────────────────────────────────────────

export type Color = 'white' | 'black'

export type GameSource = 'local' | 'imported' | 'lichess' | 'chesscom' | 'friends'

export interface GameEndInfo {
  result: string // '1-0' | '0-1' | '1/2-1/2' | '*'
  termination: string
  gameId: number
}

export interface MoveResult {
  ok: boolean
  san?: string
  fen: string
  end: GameEndInfo | null
}

export interface NewGameResult {
  fen: string
  engineToMove: boolean
}

export interface ReadyEvent {
  ok: boolean
  error?: string
  protocol?: number
  stockfish?: string
}

export interface EngineMoveEvent {
  uci: string
  san: string
  fen: string
  end: GameEndInfo | null
  /** the engine's clock after this move, increment included, as the sidecar measured it
   *  (UI-BUILD-3 F); null in an untimed game, absent from an older sidecar */
  clockMs?: number | null
}

export interface MoveAnalysisInfo {
  ply: number
  playedUci: string
  // null when no best move was established — not the same as "the played move
  // was best". Every consumer must handle it; the type is what enforces that.
  bestUci: string | null
  pvUci: string
  scoreBeforeCp: number | null
  scoreBeforeMate: number | null
  scoreAfterCp: number | null
  scoreAfterMate: number | null
  classification: string
  // The book probe: the move is in the book in use. Not the label: past the game's book
  // prefix (BOOK-PREFIX) a move the book holds is not labelled book.
  isBook: boolean
  lines: EngineLine[]
}

// ── move explanations ──────────────────────────────────────────────────────
//
// The rule layer emits structured findings and renders them to sentences; both
// cross the wire because the sentences are what the screen shows and the findings
// are what makes a sentence checkable against the position. Nothing here is
// generated text — see `zugzwang/core/explain_text.py`.

export interface FindingPiece {
  piece: 'P' | 'N' | 'B' | 'R' | 'Q' | 'K'
  square: string
  color: Color
}

export interface FindingMove {
  uci: string
  san: string
}

export interface Finding {
  kind: string
  // "played" | "best" — which move the finding is about. Not which move the
  // *sentence* names: `missed_material` is about the played move and its sentence
  // names the best one.
  subject: string
  basis: string
  pieces: FindingPiece[]
  moves: Record<string, FindingMove>
  material: number | null
  mateIn: number | null
  pattern: string | null
  ruleVersion: number
}

// Layer 5 (ANALYSIS_ARCHITECTURE.md §2): the two kinds of text are different types,
// so a description can never be handed to the component that shows claims. A claim
// says what a move did and passed a proof (the rules, or gate P on a forcing engine
// line); a description is a board fact about the two branches, with no causation.
export type ClaimText = string & { readonly __brand: 'ClaimText' }
export type DescriptionText = string & { readonly __brand: 'DescriptionText' }

export interface ExplainClaim {
  type: 'claim'
  source: 'rules' | 'engine_line' | 'only_move'
  text: ClaimText
  line?: string[]
}

export interface ExplainDescription {
  type: 'description'
  descriptor: string
  text: DescriptionText
}

export interface ExplainResult {
  ply: number
  findings: Finding[]
  sentences: string[]
  claims?: ExplainClaim[]
  descriptions?: ExplainDescription[]
  bestSan?: string | null
  // false when the game has no analysis run, or the run has no row for this ply.
  // Distinct from an empty `sentences` on an analysed ply, which means the rules
  // had nothing provable to say — the common and correct outcome.
  analysed: boolean
  ruleVersion?: number
}

export type GameSpeed = 'bullet' | 'blitz' | 'rapid' | 'classical'

export interface GameSummary {
  id: number
  playedAt: string
  /** null = the user's side could not be attributed (FIXPLAN O5) — never guessed. */
  playerColor: Color | null
  skillLevel: number
  /** Which level→Elo ladder `skillLevel` was chosen on; null = before it was
   *  recorded, so the number can't be compared with a current one. */
  ladderVersion: number | null
  result: string
  termination: string
  moveCount: number
  openingEco: string | null
  openingName: string | null
  source: GameSource
  /** The platform's own game id (chess.com numeric, Lichess 8 characters); null for local games. */
  externalId: string | null
  speed: GameSpeed | null
  rated: boolean | null
  white: string | null
  black: string | null
  whiteElo: number | null
  blackElo: number | null
  /** FRIENDS-2 (R1-R3): a friend game's ratings at its start, apart from whiteElo/blackElo; "≈" when
   *  estimated; null when neither is known */
  startRatings?: { white: { rating: number; estimated: boolean } | null; black: { rating: number; estimated: boolean } | null } | null
  whiteAccuracy: number | null
  blackAccuracy: number | null
  analyzed: boolean
}

/** One game in an imported PGN that did not come through cleanly. */
export interface ImportIssue {
  /** 1-based position in the file, so the user can find it again. */
  index: number
  /** From the headers only — "Magnus vs Hikaru, 2026.01.01". */
  label: string
  reason: string
  /** True = stored anyway, but truncated at the point parsing stopped. That is
   *  the case worth showing: it used to be counted as a plain success. */
  imported: boolean
}

export interface ImportResult {
  gameId: number
  gameIds: number[]
  count: number
  issues: ImportIssue[]
}

export interface PlyInfo {
  san: string
  uci: string
  fen: string
  check: boolean
  opening: { eco: string; name: string } | null
}

export interface GameAnalysis {
  /** the run shown (RUNS-DEPTH: the deepest complete run unless another was asked for) */
  runId: number
  depth: number
  whiteAccuracy: number | null
  blackAccuracy: number | null
  summary: Record<string, { counts: Record<string, number>; accuracy: number | null }>
  moves: MoveAnalysisInfo[]
}

/** One moment in the game report: a move that swung the game by at least 20 points
 *  of win probability on both stored searches. `before`/`after`/bands are from
 *  the report's point of view (`basis.pov`: the user, else White). */
export interface ReportMoment {
  ply: number
  side: 'white' | 'black'
  yours: boolean | null
  san: string | null
  bestSan: string | null
  label: string
  classification: string
  swing: number
  before: number
  after: number
  bandBefore: Band
  bandAfter: Band
  /** What the Review callout shows for this move (AUDIT-2): the engine-line claim where
   *  there is one, else the rule sentences. */
  sentences: string[]
  /** The callout's descriptions for this move, shown under their own heading. */
  descriptions?: string[]
  /** Seconds spent on the move, from [%clk]; null with no clocks, or when the clock
   *  rose (time added mid-game) so the time spent is unknown. */
  spent: number | null
  /** Clock left after the move, seconds. */
  clockLeft: number | null
  /** The stored best move, for judging a Try with no engine. */
  bestUci: string | null
  /** The stored best beats the stored second-best by the `great` gap: the only
   *  moments a Try is offered on when no engine is available. */
  unique: boolean
  /** GR2-6: on an opponent's card, the user's reply — "You answered X, the engine's move."
   *  or, where the reply is labelled an error, "You played X; the engine's move was Y." */
  reply?: string | null
  /** GR2-7: under a callout that names only a pawn on a swing of 0.30 or more. */
  qualifier?: string | null
}

/** `move_judged` — the live verdict on a Try (core/retry.py: errs toward accepting). */
export interface MoveJudgedEvent {
  token: number
  fen?: string
  error?: string
  accepted?: boolean
  loss?: number
  uci?: string
  san?: string
  bestUci?: string
  bestSan?: string
}

export type Band = 'winning' | 'better' | 'balanced' | 'worse' | 'losing'

/** Where the game left the book (core/game_report.opening_exit). Only `deviated`
 *  means anyone left anything; the others mean the book had nothing more to say. */
export interface ReportOpening {
  case: 'deviated' | 'no_book_move' | 'book_ended' | 'all_book'
  /** Ply of the first non-book move; null when every move was book. */
  ply: number | null
  side: 'white' | 'black' | null
  yours?: boolean | null
  label: string | null
  bookSans: string[]
  band?: Band | null
}

/** `rpc_game_report` — see core/game_report.py and GAME_REPORT.md. An unanalysed
 *  game still carries the opening line: it needs the book, not the engine. */
/** "Found it" (GR2-8): W1 brilliant, W2s a hard only move every stored alternative to which
 *  is 20 points worse, W4c a combination the user carried out after the opponent's error. */
export interface ReportFound {
  ply: number
  kind: 'brilliant' | 'only_move' | 'combination'
  side: 'white' | 'black'
  classification: string
  san: string | null
  label: string
  sentence: string
  /** combination: the opponent's move the engine proved the line after. */
  afterPly?: number
  linePlies?: number
  ownMoves?: number
}

export type GameReport =
  | { analysed: false; opening: ReportOpening | null; lines: string[] }
  | {
      analysed: true
      basis: {
        depth: number
        analysedPlies: number
        gamePlies: number
        complete: boolean
        pov: 'white' | 'black'
        /** PGN TimeControl, e.g. "600" or "180+2"; null when the game has no clocks. */
        timeControl: string | null
      }
      /** White's win probability per position, 0 = start; null where unscored. */
      series: (number | null)[]
      moments: { total: number; shown: ReportMoment[]; groups: number[][] }
      /** byPiece (GR2-2): byPly is the loser's move into the decided position that dropped a
       *  piece by its own callout, not a moment by the swing. */
      decided: {
        position: number
        side: 'white' | 'black'
        byPly: number | null
        byPiece?: boolean
        /** R5: the piece the deciding move dropped, by its callout; null to leave it unsaid. */
        piece?: string | null
        moveNumber?: number
      } | null
      ending: { loser: 'white' | 'black'; loserWp: number; termination: string } | null
      /** `peakMove` (lead_lost) and `fromMove` (saved, E1) are read by the headline. */
      fortune: {
        kind: 'lead_lost' | 'saved'; from: number; to: number; byPly: number | null
        peakMove?: number; fromMove?: number; endedBeforeGame?: boolean
      }[]
      lowClock: { ply: number; position: number; threshold: number; momentsAfter: number } | null
      opening: ReportOpening | null
      /** A decided game with no moment: where the loser's standing fell furthest. */
      slide: {
        from: number
        to: number
        side: 'white' | 'black'
        fromWp: number
        toWp: number
        /** 'game': no moment anywhere, said as the game's story. 'stretch': moments
         *  elsewhere, so it is said of this stretch only. */
        scope: 'game' | 'stretch'
      } | null
      /** A window that was computed but held a moment, so no slide was said. */
      slideGated: { from: number; to: number; blockedBy: number[] } | null
      /** GR2-3: the slide not shown because the loser climbed back to 40 % or more after it. */
      slideReversed?: { from: number; to: number } | null
      /** GR2-8 (R4): the game's one "found it" moment of the user's, or null. */
      found?: ReportFound | null
      /** R5 (GR2-12, -13): two sentences at most, every clause read off a field
       *  (core/game_report.headline). Shown first. */
      headline?: string[]
      /** R5: the lines shown after the cards (opening, clock). The per-game pattern line
       *  left the report when the Insights patterns card shipped (R6-5). */
      context?: string[]
      /** R5: the user's moves from the decided position to the end, and the errors among them. */
      conversion?: { moves: number; errors: number } | null
      /** The story lines as they were before R5; not rendered (headline and context are). */
      lines: string[]
    }

/** `rpc_home_summary` (core/home_summary.py). */
export interface HomeRating {
  platform: string
  speed: 'bullet' | 'blitz' | 'rapid' | 'classical' | 'daily' | 'puzzles'
  rating: number
  /** latest minus the last rating before the 30-day window; null when there is none */
  change: number | null
  games: number
  lastPlayed: string
  newPeak?: boolean
  series: { t: string; rating: number }[]
}
export interface HomeRecent {
  id: number
  playedAt: string
  playerColor: Color | null
  outcome: 'win' | 'loss' | 'draw' | null
  result: string
  termination: string
  source: GameSource
  opponent: string | null
  openingEco: string | null
  openingName: string | null
  timeControl: string | null
  accuracy: number | null
  opponentAccuracy: number | null
}
export interface HomeSummary {
  games: number
  analysed: number
  avgAccuracy: number | null
  winRate: number | null
  ratings: HomeRating[]
  puzzles: HomeRating | null
  recent: HomeRecent[]
}

/** `rpc_review_extras` (core/review_extras.py). */
export interface ReviewExtras {
  analysed: boolean
  depth: number | null
  plies: number
  /** the first ply of each phase by core/divider.py; null when the game never reached it */
  phases: { middlegame: number | null; endgame: number | null }
  clock: {
    timeControl: string | null
    base: number | null
    increment: number | null
    /** clock left after each ply, seconds */
    clocks: (number | null)[]
    /** seconds spent on each ply; null where unknown */
    spent: (number | null)[]
  }
  accuracyByPhase: Record<'white' | 'black', Record<'opening' | 'middlegame' | 'endgame', number | null>> | null
  errors: { ply: number; side: 'white' | 'black'; classification: string; kind: 'tactical' | null }[]
  errorCounts: Record<'white' | 'black', { tactical: number; errors: number }> | null
}

export interface GameDetail
  extends Omit<GameSummary, 'whiteAccuracy' | 'blackAccuracy' | 'analyzed' | 'white' | 'black'> {
  startFen: string
  plies: PlyInfo[]
  white: string
  black: string
  analysis: GameAnalysis | null
  /** every complete run of the game, deepest first (RUNS-DEPTH); `standard` is the depth-14
   *  run every aggregate reads */
  runs: RunInfo[]
}

export interface RunInfo {
  id: number
  depth: number
  engine: string
  completedAt: string
  standard: boolean
}

export interface AnalysisPlyEvent {
  gameId: number
  ply: number
  total: number
  analysis: MoveAnalysisInfo | null
}

export interface AnalysisDoneEvent {
  gameId: number
  summary: GameAnalysis['summary']
  whiteAccuracy: number | null
  blackAccuracy: number | null
}

export interface EngineLine {
  /** score from the side-to-move's perspective */
  cp: number | null
  mate: number | null
  uci: string[]
  san: string[]
}

export interface FenAnalyzedEvent {
  fen: string
  bestUci: string | null
  cp: number | null
  mate: number | null
  lines: EngineLine[]
  /** the live search's depth (config.ANALYSIS_DEPTH); absent from an older sidecar */
  depth?: number
}

export type ProbedMove =
  | { legal: false }
  | { legal: true; fen: string; san: string; check: boolean; gameOver: boolean }

// ── the Games screen (UI-BUILD-3 E) ─────────────────────────────────────────

export type GamesSpeed = 'bullet' | 'blitz' | 'rapid' | 'classical' | 'daily'
export type GamesSort = 'recent' | 'oldest' | 'accuracy_low' | 'accuracy_high' | 'opening'

export interface GamesPageParams {
  search?: string
  result?: 'all' | 'win' | 'draw' | 'loss'
  color?: 'all' | Color
  speeds?: GamesSpeed[]
  source?: 'all' | GameSource
  rated?: 'all' | 'rated' | 'casual'
  analysis?: 'all' | 'analyzed' | 'unanalyzed'
  opening?: string
  /** ISO instants: since inclusive, until exclusive */
  since?: string
  until?: string
  sort?: GamesSort
  offset?: number
  limit?: number
}

/** One listed game: list_games's fields plus what the Games screen shows. */
export interface GamesItem extends GameSummary {
  speedBucket: GamesSpeed | null
  /** the PGN's TimeControl ("180+2", "1/86400"); null for none, "-" or "?" */
  timeControl: string | null
  /** the user's result; null when unfinished or the side is unknown */
  outcome: 'win' | 'loss' | 'draw' | null
}

export interface GamesMonth {
  /** "2026-11", local calendar month */
  month: string
  games: number
  won: number
  lost: number
  drawn: number
}

export interface GamesPage {
  games: GamesItem[]
  /** games the filters keep */
  total: number
  /** every stored game */
  all: number
  offset: number
  /** each month's record over every game the filters keep, newest first */
  months: GamesMonth[]
}

// ── platform sync ────────────────────────────────────────────────────────────

export interface SyncSourceCounts {
  synced: number
  /** Everything the bulk action would queue: unanalysed + belowDepth. */
  pending: number
  /** Games with no analysis run at all. */
  unanalysed: number
  /** Games analysed below `depth`, which the bulk action re-analyses (W15). */
  belowDepth: number
  /** The depth the counts were taken against — the one selected in Settings. */
  depth: number
  /** Games the engine crashed on in repeated runs; no longer queued (VAL-DEATH-2). */
  needsAttention: number
}

export interface SyncStatus {
  syncing: boolean
  lichess: SyncSourceCounts
  chesscom: SyncSourceCounts
}

export interface SyncProgressEvent {
  phase: 'fetching' | 'analyzing'
  source?: GameSource
  done: number
  total: number
}

export interface SyncDoneEvent {
  source: GameSource
  new: number
  analyzed: number
}

export interface SyncErrorEvent {
  source: GameSource
  message: string
}

/** A game skipped or not analysed during a sync; the run carries on. */
export interface SyncWarningEvent {
  source: GameSource
  message: string
}

// ── insights ─────────────────────────────────────────────────────────────────

export type InsightsColor = 'all' | 'white' | 'black'
export type InsightsSpeed = 'bullet' | 'blitz' | 'rapid' | 'classical'
export type InsightsRated = 'all' | 'rated' | 'casual'

export interface InsightsOverview {
  total: number
  analyzed: number
  pending: number
  /** Games left out by the source rule — those played here against Stockfish.
   *  Zero when they are being included. */
  excluded: number
}

export interface InsightsOpening {
  eco: string
  name: string
  games: number
  accuracy: number
  win: number
  draw: number
  loss: number
  winRate: number
}

export interface InsightsTrendPoint {
  gameId: number
  date: string
  accuracy: number
  opening: string
  result: string
  color: Color
  outcome: 'win' | 'draw' | 'loss' | 'unknown'
}

export interface InsightsMoveAccuracyPoint {
  move: number
  accuracy: number
  samples: number
  /** True for the final bucket, which is every move from `move` onward. */
  cumulative: boolean
}

export interface InsightsMoveAccuracy {
  all: InsightsMoveAccuracyPoint[]
  white: InsightsMoveAccuracyPoint[]
  black: InsightsMoveAccuracyPoint[]
}

export interface InsightsCastlingRow {
  side: 'kingside' | 'queenside' | 'none'
  label: string
  win: number
  draw: number
  loss: number
  total: number
  winRate: number
}

export interface InsightsSummary {
  avgAccuracy: number | null
  gamesAnalyzed: number
  winRate: number
  totalGames: number
}

export interface InsightsQualityItem {
  key: string
  glyph: string
  color: string
  count: number
  pct: number
}

export interface InsightsQualityColumn {
  total: number
  items: InsightsQualityItem[]
}

export interface InsightsWdl {
  win: number
  draw: number
  loss: number
  total: number
  winRate: number
}

export interface InsightsResults {
  overall: InsightsWdl
  white: InsightsWdl
  black: InsightsWdl
}

export interface InsightsTerminationItem {
  label: string
  count: number
  pct: number
}

export interface InsightsTerminations {
  win: InsightsTerminationItem[]
  loss: InsightsTerminationItem[]
}

export interface InsightsTimeCell {
  label: string
  games: number
  winRate: number
  accuracy: number | null
}

export interface InsightsByTime {
  dayOfWeek: InsightsTimeCell[]
  timeOfDay: InsightsTimeCell[]
}

export interface InsightsPhase {
  phase: string
  total: number
  items: InsightsQualityItem[]
}

/** The single phase claim the screen is allowed to make, or null when the data
 *  cannot separate any phase from the next — see `_phase_verdict`. Null is the
 *  normal case for a small history and must be rendered as "can't tell yet",
 *  never as "no weakness". */
export interface InsightsPhaseVerdict {
  phase: string
  comparedTo: string
  rate: number
  comparedRate: number
  total: number
  comparedTotal: number
}

/** R6 (PATTERNS.md §6a): one ply behind a pattern sentence, which opens Review there. */
export interface InsightsPatternItem {
  gameId: number
  ply: number
  move: string | null
  label: string | null
  date: string
  opponent: string | null
}

/** A sentence of the patterns card. Only sentences that pass (a game-clustered interval
 *  excluding 1.0 in the measured direction, and Benjamini–Hochberg) are sent. */
export interface InsightsPatternSentence {
  key: 'punish' | 'decided'
  text: string
  link: { label: string; count: number; items: InsightsPatternItem[] }
}

export interface InsightsPatterns {
  /** Games under the filters with stored pattern facts — what the card covers. */
  covered: number
  /** Analysed games under the filters. */
  analysed: number
  sentences: InsightsPatternSentence[]
  /** Every sentence tested, shown or not, with its figures (for the record, not shown). */
  tested: {
    key: string; shown: boolean; rr: number; lo: number; hi: number; p: number
    nx: number; yx: number; no: number; yo: number; games: number
  }[]
}

/** The sidecar's answer when a newer insights request overtook this one before
 *  it ran. No data is built; the caller should keep what it has and wait for the
 *  newer reply. Every field but `superseded` is absent. */
export interface InsightsSuperseded {
  superseded: true
}

export interface InsightsResult {
  superseded?: false
  overview: InsightsOverview
  ready: boolean
  summary: InsightsSummary
  openings: InsightsOpening[]
  trend: InsightsTrendPoint[]
  move_quality: {
    white: InsightsQualityColumn
    black: InsightsQualityColumn
  }
  move_accuracy: InsightsMoveAccuracy
  results: InsightsResults
  terminations: InsightsTerminations
  by_time: InsightsByTime
  phase_quality: InsightsPhase[]
  phase_verdict: InsightsPhaseVerdict | null
  castling: InsightsCastlingRow[]
  /** R6: patterns across games, from stored per-run facts. */
  patterns: InsightsPatterns
}

// ── insights, redesigned (UI-BUILD-2 C; core/insights_v2.py) ─────────────────

export type InsightsSpeedV2 = InsightsSpeed | 'daily'
export type QualityClassV2 =
  | 'brilliant' | 'great' | 'best' | 'excellent' | 'good' | 'inaccuracy' | 'mistake' | 'miss' | 'blunder'
export interface QualityShares {
  moves: number
  counts: Record<QualityClassV2, number>
  pct: Record<QualityClassV2, number | null>
}
export interface InsightsMonth {
  month: string
  games: number
  analysed: number
  accuracy: number | null
  winRate: number | null
  blundersPerGame: number | null
}
export interface InsightsOpeningFamily {
  name: string
  eco: string | null
  games: number
  won: number | null
  drawn: number | null
  lost: number | null
  score: number | null
  accuracy: number | null
}
export interface InsightsEnd {
  games: number
  pct: number | null
  mate: number | null
  resigned: number | null
  time: number | null
  other: number | null
}
export interface InsightsV2 {
  view: 'v2'
  overview: { total: number; analyzed: number; pending: number; excluded: number }
  ready: boolean
  summary: { accuracy: number | null; winRate: number | null; games: number; analysed: number; blundersPerGame: number | null }
  monthly: InsightsMonth[]
  daily: { day: string; games: number; accuracy: number | null }[]
  heat: {
    cells: { day: number; block: number; games: number; accuracy: number | null }[]
    hours: string[]
    days: string[]
    minGames: number
    best: { day: number; block: number; games: number; accuracy: number; dayName: string; hours: string } | null
  }
  openings: { white: InsightsOpeningFamily[]; black: InsightsOpeningFamily[] }
  ends: { win: InsightsEnd; draw: InsightsEnd; loss: InsightsEnd }
  moveQuality: { you: QualityShares; opponents: QualityShares }
  byPhase: {
    phases: {
      phase: 'opening' | 'middlegame' | 'endgame'
      games: number
      accuracy: { you: number | null; opponents: number | null }
      quality: { you: QualityShares; opponents: QualityShares }
    }[]
  }
  castling: { side: string; label: string; games: number; share: number | null; winRate: number | null }[]
  patterns: InsightsPatterns
}

// ── puzzles ──────────────────────────────────────────────────────────────────

export interface PuzzleStatus {
  imported: boolean
  count: number
  importing: boolean
  /** what is importing: a download from Lichess or a file (FIX-B6 B); null when idle */
  importKind?: 'lichess' | 'file' | null
  /** where the copy you have came from, its file's date (Lichess's Last-Modified), when imported */
  source?: 'lichess' | 'file' | null
  sourceDate?: string | null
  importedAt?: string | null
  rating: number
  rd: number
  csvPath: string
  csvExists: boolean
}

/** `puzzle_check_update`: what Lichess serves now, and whether it is not the copy you have. */
export interface PuzzleUpdateInfo {
  date: string | null
  bytes: number | null
  newer: boolean
}

/** `puzzle_import_progress`: bytes of the file read (compressed, for a download) and rows imported. */
export interface PuzzleImportProgress {
  kind: 'lichess' | 'file'
  bytes: number
  totalBytes: number | null
  imported: number
}

export interface PuzzleRecord {
  id: string
  fen: string
  movesUci: string[]
  rating: number
  ratingDeviation: number
  themes: string
  /** Every move that mates in place of the final solution move, computed by the
   *  sidecar at fetch time. Empty unless the intended last move is itself mate.
   *  Optional so a reply from an older sidecar still type-checks. */
  finalMates?: string[]
}

export interface PuzzleMode {
  mode: 'rated' | 'theme' | 'rush' | 'survival'
  themes: string[]
  rushSeconds: number
  ratingRange: number
}

/** One row of the Puzzles lobby's recent sessions (`rpc_puzzle_summary`, core/puzzle_summary.py). */
export interface PuzzleSessionRow {
  /** null for an inferred session (attempts with no stored session, grouped by time) */
  id: number | null
  startedAt: string
  mode: 'rated' | 'theme' | 'rush' | 'survival' | string
  timeLimit: number | null
  tried: number
  /** solved without a miss */
  solved: number
  /** Rush and Survival: the session's score */
  score: number | null
  /** rated: last rating after minus first rating before */
  ratingChange: number | null
  /** Rush and Survival: equals that board's best */
  best: boolean
  inferred: boolean
}

/** `rpc_puzzle_summary`: the Puzzles lobby's figures. */
export interface PuzzleSummary {
  /** Home's puzzle row; null before any attempt in the last 30 days */
  rating: HomeRating | null
  tries: number
  solved: number
  /** best finished Rush score per length in seconds ("180", "300") */
  rushBest: Record<string, number | null>
  survivalBest: number | null
  sessions: PuzzleSessionRow[]
  sessionGapMin: number
}

export interface LeaderboardResult {
  entries: { score: number; date: string }[]
  newRank: number
}

// ── opening trainer ──────────────────────────────────────────────────────────

export interface TrainerFamilySummary {
  name: string
  ecoLo: string
  ecoHi: string
  firstMove: 'e4' | 'd4' | 'other'
  popularity: number
  lineCount: number
  threshold: number
  available: boolean
  sampleMoves: string
  /** the moves 90 % of the family's curated lines share, in order; '' when they share none (UI-BUILD-3 B2) */
  sharedMoves: string
  drilled: number
  mastered: number
}

export interface TrainerLineRecord {
  attempts: number
  completions: number
  distinctLines: number
  bestAccuracy: number | null
  mastered: boolean
}

export interface TrainerLineProgress {
  distinctLines: number
  bestAccuracy: number | null
  mastered: boolean
  /** ruling 18: the record per colour (UI-BUILD-2 E3) */
  byColor?: { white: TrainerLineRecord; black: TrainerLineRecord }
}

export interface TrainerLine {
  eco: string
  name: string
  fen: string
  pgn: string
  uci: string[]
  coverage: { white: boolean; black: boolean }
  progress: TrainerLineProgress
}

export interface TrainerFamily {
  label: string
  lines: TrainerLine[]
  mastered: number
  drilled: number
}

export interface TrainerConfig {
  color: Color
  mode: 'varied' | 'random' | 'pinned'
  threshold: number
  startFromMove1: boolean
  allowOffBook: boolean
}

export interface PuzzleAttempt {
  puzzle_id: string
  session_id: number | null
  mode: string
  solved: boolean
  failed: boolean
  used_hint: boolean
  gave_up: boolean
  solve_time_s: number | null
  rating_before: number | null
  rating_after: number | null
}

/** The sidecar's own answer about whether a game session survives. An
 *  unfinished game lives only in the sidecar's memory — it reaches the database
 *  when it ends — so after a backend restart this reports `active: false` and
 *  the fields below are absent. */
export interface GameState {
  active: boolean
  fen?: string
  playerColor?: Color
  skill?: number
}

export interface EngineStatus {
  ok: boolean
  path: string | null
  /** how find_stockfish found it: env, bundled, path (on PATH) or chosen (the user's pick) */
  source?: 'env' | 'bundled' | 'path' | 'chosen' | null
  /** the running engine's UCI name ("Stockfish 18"), when it is this binary */
  name?: string | null
}

export interface RelabelResult {
  runs: number
  labelsChanged: number
  backup: string | null
  integrity: string | null
  unstamped: number
  from: string[]
  seconds?: number
}

/** One opening book of the manifest (BOOK-DL, `books_status`). */
export interface BookInfo {
  id: string
  label: string
  minGames: number
  bytes: number
  sha256: string
  url: string
  default: boolean
  /** Downloaded and verified in this data folder. */
  installed: boolean
  /** The book in use. */
  active: boolean
}

/** A book job in flight: downloading, backing up, or relabelling the book plies. */
export interface BookJob {
  id: string
  phase: 'download' | 'backup' | 'relabel'
  done: number
  total: number
}

export interface BooksStatus {
  books: BookInfo[]
  active: string | null
  defaultId: string
  job: BookJob | null
  last: { id: string; ok: boolean; message?: string; labelsChanged?: number } | null
}

export interface BookDoneEvent {
  id: string
  ok: true
  runs: number
  labelsChanged: number
  backup: string
  seconds: number
}

export interface RelabelStatus {
  state: 'idle' | 'manual' | 'running' | 'done' | 'error'
  done: number
  total: number
  result: RelabelResult | null
  error: string | null
}

/** What this build is and where it keeps things (BETA, `rpc_app_info`). */
export interface AppInfo {
  version: string
  beta: boolean
  commit: string | null
  builtAt: string | null
  target: string | null
  frozen: boolean
  dataDir: string
  dbPath: string | null
  logPath: string
  flagsPath: string
  flagsDir: string
  classifierVersion: number
  ruleVersion: number
  stockfish: string | null
  stockfishSource: string
  /** Zugzwang's own source for this exact version (the public repo's tag). */
  source: string
  licence: string
}

/** One site's answer to the username check (UI-BUILD-3 G): found, not found, or the site could
 *  not be asked (message: why, e.g. "HTTP 503", "timed out"). */
export interface UsernameCheck {
  status: 'found' | 'not_found' | 'unreachable'
  message: string | null
}
/** check_usernames' reply: null for a name that was empty (not checked). */
export interface UsernameChecks {
  chesscom: UsernameCheck | null
  lichess: UsernameCheck | null
}

/** The user_move params (UI-BUILD-3 F): the move and, when the game has a clock, the user's clock
 *  after it in whole milliseconds; a missing or unusable clock is left out, as an older frontend
 *  sent it, and the sidecar then saves the game without clocks. */
export function userMoveParams(uci: string, clockMs?: number | null): { uci: string; clock_ms?: number } {
  return typeof clockMs === 'number' && Number.isFinite(clockMs) && clockMs >= 0
    ? { uci, clock_ms: Math.round(clockMs) }
    : { uci }
}

/** What a sidecar from before UI-BUILD-3 F answers a user_move carrying clock_ms: Python's own
 *  TypeError for the unknown keyword, raised while binding the arguments, before the move is
 *  touched (measured on 42bfa69's dispatch: "Server.rpc_user_move() got an unexpected keyword
 *  argument 'clock_ms'"). Matched narrowly: any other error is a real one. */
export const CLOCK_REFUSED = /rpc_user_move\(\) got an unexpected keyword argument 'clock_ms'/

/** user_move, tolerant of an older sidecar (the dev run hot-reloads the frontend while its
 *  sidecar keeps running): when the sidecar refuses clock_ms, the move is sent again once without
 *  it, and no clock is sent for the rest of that sidecar's life (until it is restarted). The game
 *  then saves without clocks, as an untimed one does. */
export function userMoveSender(
  request: (params: { uci: string; clock_ms?: number }) => Promise<MoveResult>,
  onStatus: (fn: (s: SidecarStatus) => void) => unknown,
): (uci: string, clockMs?: number | null) => Promise<MoveResult> {
  let refused = false
  // a new sidecar process may be a newer one: ask again with the clock
  onStatus((s) => {
    if (s !== 'up') refused = false
  })
  return async (uci, clockMs) => {
    const params = userMoveParams(uci, refused ? null : clockMs)
    try {
      return await request(params)
    } catch (e) {
      if (params.clock_ms === undefined || !(e instanceof Error) || !CLOCK_REFUSED.test(e.message)) throw e
      refused = true
      return request(userMoveParams(uci))
    }
  }
}
const sendUserMove = userMoveSender(
  (params) => sidecar.request<MoveResult>('user_move', params),
  (fn) => sidecar.onStatus(fn),
)

export const api = {
  engineStatus: () => sidecar.request<EngineStatus>('engine_status'),
  appInfo: () => sidecar.request<AppInfo>('app_info'),
  /** Relabel on update (BETA item 5). */
  relabelStatus: () => sidecar.request<RelabelStatus>('relabel_status'),
  /** Opening books (BOOK-DL): the manifest, what is installed, the one in use. */
  booksStatus: () => sidecar.request<BooksStatus>('books_status'),
  /** Download (if needed), verify and switch to a book; progress arrives as book_progress. */
  bookUse: (id: string) => sidecar.request<{ started: boolean }>('book_use', { id }),
  bookCancel: () => sidecar.request<{ cancelled: boolean }>('book_cancel'),
  /** "Flag this" (BETA): appended to a local file, never sent anywhere. */
  flagItem: (p: {
    kind: string
    shown: string
    note: string
    gameId: number | null
    ply: number | null
    label: string | null
    context?: string | null
  }) =>
    sidecar.request<{ path: string; count: number }>('flag_item', {
      kind: p.kind,
      shown: p.shown,
      note: p.note,
      game_id: p.gameId,
      ply: p.ply,
      label: p.label,
      context: p.context ?? null,
    }),
  /** The screen on view, so the sidecar's engine budget reserves live play and the
   *  FEN path only while their screens are open (FIXPLAN ENG-ALLOC). */
  setActiveScreen: (screen: string) =>
    sidecar.request<{ screen: string; bulkSlots: number; cores: number; ceiling: number }>(
      'set_active_screen', { screen },
    ),
  /** Adopt a user-picked Stockfish binary. Rejects anything that does not
   *  complete a UCI handshake, and on success the sidecar re-emits `ready`, so
   *  callers recover through their existing `ready` handler rather than here. */
  setStockfishPath: (path: string) =>
    sidecar.request<{ ok: boolean; path: string; name: string }>('set_stockfish_path', { path }),
  /** timeControl: the PGN TimeControl ("600+0") written into the saved game */
  newGame: (color: Color, skill: number, fen?: string, timeControl?: string) =>
    sidecar.request<NewGameResult>('new_game', {
      color,
      skill,
      ...(fen ? { fen } : {}),
      ...(timeControl ? { time_control: timeControl } : {}),
    }),
  getState: () => sidecar.request<GameState>('get_state'),
  /** Settings' check on Save (UI-BUILD-3 G, ruling 5): whether each name is a player on its site;
   *  an empty name is not sent and comes back null. The sidecar answers within a few seconds
   *  whatever the network does. */
  checkUsernames: (names: { chesscom: string; lichess: string }) =>
    sidecar.request<UsernameChecks>('check_usernames', {
      ...(names.chesscom.trim() ? { chesscom: names.chesscom.trim() } : {}),
      ...(names.lichess.trim() ? { lichess: names.lichess.trim() } : {}),
    }),
  /** clockMs: the user's clock after this move, increment included, saved as its [%clk]
   *  (UI-BUILD-3 F); left out when there is none, or when the running sidecar is older than the
   *  clocks (userMoveSender) */
  userMove: (uci: string, clockMs?: number | null) => sendUserMove(uci, clockMs),
  resign: () => sidecar.request<{ end: GameEndInfo }>('resign'),
  draw: () => sidecar.request<{ end: GameEndInfo }>('draw'),
  flag: (loser: Color) => sidecar.request<{ end: GameEndInfo }>('flag', { loser }),
  abandon: () => sidecar.request<{ end: GameEndInfo }>('abandon'),
  listGames: (limit?: number) =>
    sidecar.request<{ games: GameSummary[] }>('list_games', limit === undefined ? {} : { limit }),
  /** runId: one of the game's complete runs (Review's run switch, RUNS-DEPTH); none, the deepest */
  getGame: (gameId: number, runId?: number | null) =>
    sidecar.request<GameDetail>('get_game', { game_id: gameId, ...(runId != null ? { run_id: runId } : {}) }),
  // Takes the game and ply, not the position: the sidecar reads the stored row so
  // that the engine scores the rules need cannot be silently omitted here.
  explainMove: (gameId: number, ply: number, runId?: number | null) =>
    sidecar.request<ExplainResult>('explain_move', { game_id: gameId, ply, ...(runId != null ? { run_id: runId } : {}) }),
  judgeMove: (fen: string, uci: string) =>
    sidecar.request<{ token: number }>('judge_move', { fen, uci }),
  gameReport: (gameId: number, runId?: number | null) =>
    sidecar.request<GameReport>('game_report', { game_id: gameId, ...(runId != null ? { run_id: runId } : {}) }),
  /** The redesigned Home's figures (UI-BUILD C, core/home_summary.py). Read-only. */
  homeSummary: () => sidecar.request<HomeSummary>('home_summary'),
  /** The redesigned Review's figures (UI-BUILD B3): phases, accuracy by phase,
   *  tactical errors, N of M (gate P, ruling 3; never "positional"), clocks. Read-only. */
  reviewExtras: (gameId: number, runId?: number | null) =>
    sidecar.request<ReviewExtras>('review_extras', { game_id: gameId, ...(runId != null ? { run_id: runId } : {}) }),
  analyzeGame: (gameId: number, depth?: number) =>
    sidecar.request<{ runId: number; depth: number }>('analyze_game', {
      game_id: gameId,
      ...(depth ? { depth } : {}),
    }),
  cancelAnalysis: () => sidecar.request<{ ok: boolean }>('cancel_analysis'),
  importPgn: (pgn: string, usernames: string[] = []) =>
    sidecar.request<ImportResult>('import_pgn', {
      pgn,
      usernames,
    }),
  /** Import from a file the sidecar opens itself. An archive export runs to tens
   *  of megabytes and there is no reason to carry it through the RPC pipe. */
  importPgnFile: (path: string, usernames: string[] = []) =>
    sidecar.request<ImportResult>('import_pgn', { path, usernames }),
  analyzeFen: (fen: string) => sidecar.request<{ ok: boolean }>('analyze_fen', { fen }),
  /** Where one move lands, decided in Python. An illegal move answers `legal: false`
   *  and nothing else, so a variation node can never hold an unreachable position. */
  probeMove: (fen: string, uci: string) => sidecar.request<ProbedMove>('probe_move', { fen, uci }),
  // Sync and "analyse pending" send no depth: every game is analysed at depth 14 (ruling 17;
  // the sidecar ignores any depth sent, Server._clamp_depth). One game goes deeper only
  // through Analyse again (analyzeGame).
  syncStatus: () => sidecar.request<SyncStatus>('sync_status', {}),
  startSync: (lichess: string, chesscom = '') =>
    sidecar.request<{ started: boolean; sources: GameSource[] }>('start_sync', { lichess, chesscom }),
  cancelSync: () => sidecar.request<{ ok: boolean }>('cancel_sync'),
  /** Analyse synced games still pending, newest first. *count* is one "Analyse more"
   *  step (the *count* most recent pending games); omitted, all of them (BETA-PUB Q4). */
  analyzePending: (source?: 'lichess' | 'chesscom', count?: number) =>
    sidecar.request<{ started: boolean; sources: GameSource[]; count: number | null }>(
      'analyze_pending',
      {
        ...(source ? { source } : {}),
        ...(count != null ? { count } : {}),
      },
    ),
  /** Analyse exactly these games at depth 14 through the bulk queue and its sync_* events
   *  (Import PGN's games, UI-BUILD-3 E); those already analysed are skipped. */
  analyzeGames: (gameIds: number[]) =>
    sidecar.request<{ started: boolean; sources: GameSource[]; count: number }>('analyze_pending', {
      game_ids: gameIds,
    }),
  /** The Games screen's page (UI-BUILD-3 E, core/games_list.py): the games under the filters,
   *  the count they keep, and each month's record over all of them. Read-only. */
  gamesPage: (params: GamesPageParams) => sidecar.request<GamesPage>('games_page', { ...params }),
  repairColors: (lichess: string, chesscom = '') =>
    sidecar.request<{ changed: number }>('repair_colors', { lichess, chesscom }),
  insights: (
    opts: {
      color?: InsightsColor
      speeds?: InsightsSpeed[]
      since?: string
      rated?: InsightsRated
      includeLocal?: boolean
    } = {},
  ) =>
    sidecar.request<InsightsResult | InsightsSuperseded>('insights', {
      color: opts.color ?? 'all',
      ...(opts.speeds && opts.speeds.length ? { speeds: opts.speeds } : {}),
      ...(opts.since ? { since: opts.since } : {}),
      ...(opts.rated && opts.rated !== 'all' ? { rated: opts.rated } : {}),
      ...(opts.includeLocal ? { include_local: true } : {}),
    }),
  /** The redesigned Insights (UI-BUILD-2 C): one payload under the filter bar's filters. */
  insightsV2: (
    opts: { color?: InsightsColor; speeds?: InsightsSpeedV2[]; since?: string; rated?: InsightsRated; includeLocal?: boolean } = {},
  ) =>
    sidecar.request<InsightsV2 | InsightsSuperseded>('insights', {
      view: 'v2',
      color: opts.color ?? 'all',
      ...(opts.speeds && opts.speeds.length ? { speeds: opts.speeds } : {}),
      ...(opts.since ? { since: opts.since } : {}),
      ...(opts.rated && opts.rated !== 'all' ? { rated: opts.rated } : {}),
      ...(opts.includeLocal ? { include_local: true } : {}),
    }),
  puzzleStatus: () => sidecar.request<PuzzleStatus>('puzzle_status'),
  puzzleSummary: () => sidecar.request<PuzzleSummary>('puzzle_summary'),
  importPuzzles: (csvPath?: string) =>
    sidecar.request<{ started: boolean }>('import_puzzles', csvPath ? { csv_path: csvPath } : {}),
  cancelPuzzleImport: () => sidecar.request<{ ok: boolean }>('cancel_puzzle_import'),
  downloadPuzzles: () => sidecar.request<{ started: boolean }>('download_puzzles'),
  puzzleCheckUpdate: () => sidecar.request<PuzzleUpdateInfo>('puzzle_check_update'),
  getPuzzleRating: () =>
    sidecar.request<{ rating: number; rd: number; volatility: number }>('get_puzzle_rating'),
  nextPuzzles: (targetRating: number, ratingRange: number, themes?: string[]) =>
    sidecar.request<{ puzzles: PuzzleRecord[] }>('next_puzzles', {
      target_rating: targetRating,
      rating_range: ratingRange,
      ...(themes && themes.length ? { themes } : {}),
    }),
  ratePuzzle: (puzzleRating: number, puzzleRd: number, outcome: number) =>
    sidecar.request<{ before: number; rating: number; rd: number }>('rate_puzzle', {
      puzzle_rating: puzzleRating,
      puzzle_rd: puzzleRd,
      outcome,
    }),
  savePuzzleAttempt: (attempt: PuzzleAttempt) =>
    sidecar.request<{ attemptId: number }>('save_puzzle_attempt', { ...attempt }),
  startPuzzleSession: (mode: string, timeLimitS: number | null) =>
    sidecar.request<{ sessionId: number }>('start_puzzle_session', {
      mode,
      time_limit_s: timeLimitS,
    }),
  updatePuzzleSession: (sessionId: number, score: number, peakRating?: number) =>
    sidecar.request<{ ok: boolean }>('update_puzzle_session', {
      session_id: sessionId,
      score,
      ...(peakRating !== undefined ? { peak_rating: peakRating } : {}),
    }),
  countThemePuzzles: (themes: string[], ratingRange: number) =>
    sidecar.request<{ count: number }>('count_theme_puzzles', {
      themes,
      rating_range: ratingRange,
    }),
  puzzleLeaderboard: (mode: string, timeLimitS: number | null, limit = 10) =>
    sidecar.request<LeaderboardResult>('puzzle_leaderboard', {
      mode,
      time_limit_s: timeLimitS,
      limit,
    }),
  trainerLobby: () =>
    sidecar.request<{
      indexed: boolean
      indexing: boolean
      /** False when no Polyglot book loaded, which makes every family untrainable. */
      bookAvailable: boolean
      bookPath: string
      /** The manifest id of the book in use, or null (BOOK-DL). */
      bookId: string | null
      families: TrainerFamilySummary[]
    }>('trainer_lobby'),
  trainerIndexCoverage: () =>
    sidecar.request<{ started: boolean }>('trainer_index_coverage'),
  trainerFamily: (name: string) => sidecar.request<TrainerFamily>('trainer_family', { name }),
  bookMoves: (fen: string, threshold: number) =>
    sidecar.request<{ accepted: string[] }>('book_moves', { fen, threshold }),
  bookReply: (fen: string, mode: string) =>
    sidecar.request<{ uci: string | null }>('book_reply', { fen, mode }),
  openingAt: (fen: string) =>
    sidecar.request<{ opening: { eco: string; name: string } | null }>('opening_at', { fen }),
  trainerAttempt: (eco: string, name: string, color: Color) =>
    sidecar.request<{ ok: boolean }>('trainer_attempt', { eco, name, color }),
  trainerComplete: (params: {
    eco: string
    name: string
    color: Color
    mode: string
    terminal_fen: string
    moves_played: number
    errors_made: number
    accuracy: number | null
  }) => sidecar.request<{ progress: TrainerLineProgress }>('trainer_complete', { ...params }),
}

// ── trainer display constants (mirrors config.py) ───────────────────────────

export const TRAINER_DIFFICULTY_PRESETS: [string, number][] = [
  ['Strict', 0.3],
  ['Normal', 0.1],
  ['Loose', 0.02],
]
export const TRAINER_DIFFICULTY_DEFAULT = 1

// ── puzzle display constants (mirrors config.py + puzzle_lobby.py) ──────────

export const PUZZLE_RATING_RANGES = [50, 100, 200, 300]
export const PUZZLE_RATING_RANGE_DEFAULT = 1 // ±100

// ── survival difficulty ramp (personalized start) ──────────────────────────
// Start below the player's level for a warm-up, then climb +step per solve so
// difficulty passes their true rating after ~20 puzzles. Strong players get a
// shorter warm-up because of the absolute floor.
export const PUZZLE_SURVIVAL_START_OFFSET = -500
export const PUZZLE_SURVIVAL_FLOOR = 700
export const PUZZLE_SURVIVAL_STEP = 25
export const PUZZLE_SURVIVAL_RANGE = 50
export const PUZZLE_RUSH_TIMES: [number, string][] = [
  [180, '3 min'],
  [300, '5 min'],
]

// ── display constants (mirrors config.py) ───────────────────────────────────

export function describeTermination(termination: string): string {
  const names: Record<string, string> = {
    checkmate: 'checkmate',
    stalemate: 'stalemate',
    insufficient_material: 'insufficient material',
    fifty_moves: 'fifty-move rule',
    threefold_repetition: 'threefold repetition',
    resignation: 'resignation',
    draw_agreed: 'draw agreed',
    timeout: 'time forfeit',
    abandoned: 'abandoned',
  }
  return names[termination] ?? termination.replace(/_/g, ' ')
}
