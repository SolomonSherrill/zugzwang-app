/**
 * The Puzzles screens over the fake sidecar (UI-BUILD-2 E2). Answers come from
 * `puzzles_fixtures.json` (review/ui_fixtures/record_puzzle_fixtures.py, recorded from the
 * real sidecar on a copy of a backup; private). Puzzles are served in order, so a session sees
 * each recorded puzzle once; rate_puzzle replays the recorded Glicko-2 answers in order.
 *
 * Scenarios (?state=) for the drafted states:
 *   puzzles-not-imported   the CSV is where the app looks, nothing imported yet
 *   puzzles-no-csv         nothing imported and no CSV found
 *   puzzles-importing      an import running (progress events up to 40 % of the recorded count)
 *   puzzles-import-error   Import puzzles fails (the sidecar's own message for a .zst file)
 *   puzzles-error          puzzle_status fails
 *   puzzles-new            imported, never played (no attempt, no session)
 *   puzzles-slow           next_puzzles answers after 60 s (the cold first search)
 *   puzzles-empty          next_puzzles finds nothing
 */
type Emit = (event: string, data: Record<string, unknown>) => void
type Handler = (params: Record<string, unknown>, emit: Emit) => unknown

interface PuzzleRec {
  id: string
  rating: number
  [k: string]: unknown
}
export interface PuzzleFixtures {
  status: Record<string, unknown> & { count: number; csvPath: string }
  summary: Record<string, unknown>
  rating: { rating: number; rd: number; volatility: number }
  leaderboards: Record<string, unknown>
  rated: PuzzleRec[]
  survival: PuzzleRec[]
  rateSequence: { before: number; rating: number; rd: number }[]
  rateFirstMiss: { before: number; rating: number; rd: number }
  meta: { outcomes: number[] }
  themeCounts: Record<string, number>
  noPuzzleThemes?: string[]
}

export function puzzleHandlers(pf: PuzzleFixtures | null, scenario: string | undefined): Record<string, Handler> {
  if (!pf) return {}
  let ratedAt = 0
  let survivalAt = 0
  let rateAt = 0
  let ids = 100
  const status = () => {
    switch (scenario) {
      case 'puzzles-not-imported':
        return { ...pf.status, imported: false, count: 0, csvExists: true }
      case 'puzzles-no-csv':
        return { ...pf.status, imported: false, count: 0, csvExists: false }
      case 'puzzles-import-error':
        return { ...pf.status, imported: false, count: 0, csvExists: true }
      case 'puzzles-importing':
        return { ...pf.status, imported: false, importing: true, count: 0 }
      case 'puzzles-error':
        throw new Error('database is locked')
      case 'puzzles-new':
        return { ...pf.status, rating: 800, rd: 350 }
      default:
        return pf.status
    }
  }
  const handlers: Record<string, Handler> = {
    puzzle_status: (_p, emit) => {
      const s = status()
      if (scenario === 'puzzles-importing') {
        // a progress event part-way, out of the recorded puzzle count
        const total = pf.status.count
        setTimeout(() => emit('puzzle_import_progress', { imported: Math.round(total * 0.4), total }), 50)
      }
      return s
    },
    puzzle_summary: () =>
      scenario === 'puzzles-new'
        ? { rating: null, tries: 0, solved: 0, rushBest: {}, survivalBest: null, sessions: [], sessionGapMin: 30 }
        : pf.summary,
    get_puzzle_rating: () => (scenario === 'puzzles-new' ? { rating: 800, rd: 350, volatility: 0.06 } : pf.rating),
    import_puzzles: (p) => {
      if (scenario === 'puzzles-import-error') {
        throw new Error('lichess_db_puzzle.csv.zst is still compressed. Decompress it first (`zstd -d lichess_db_puzzle.csv.zst`) and pick the .csv.')
      }
      return { started: !!p }
    },
    cancel_puzzle_import: () => ({ ok: true }),
    next_puzzles: async (p) => {
      if (scenario === 'puzzles-slow') await new Promise((r) => setTimeout(r, 60_000))
      if (scenario === 'puzzles-empty') return { puzzles: [] }
      if (p.rating_range === 50) {
        const out = pf.survival.slice(survivalAt, survivalAt + 10)
        survivalAt += out.length
        return { puzzles: out }
      }
      const out = pf.rated.slice(ratedAt, ratedAt + 10)
      ratedAt += out.length
      return { puzzles: out }
    },
    rate_puzzle: (p) => {
      // the recorded run, in order; or the first puzzle missed (then nothing more is recorded)
      const at = rateAt++
      if (at === 0 && p.outcome === 0) {
        rateAt = Infinity
        return pf.rateFirstMiss
      }
      const r = pf.rateSequence[at]
      if (!r || pf.meta.outcomes[at] !== p.outcome) throw new Error('harness: no recorded rate_puzzle answer for this run')
      return r
    },
    save_puzzle_attempt: () => ({ attemptId: ++ids }),
    start_puzzle_session: () => ({ sessionId: ++ids }),
    update_puzzle_session: () => ({ ok: true }),
    count_theme_puzzles: (p) => {
      const t = (p.themes as string[]) ?? []
      if (pf.noPuzzleThemes && t.length === pf.noPuzzleThemes.length && t.every((x) => pf.noPuzzleThemes!.includes(x))) return { count: 0 }
      if (t.length === 1 && t[0] in pf.themeCounts) return { count: pf.themeCounts[t[0]] }
      throw new Error(`harness: no recorded count for ${t.join(', ')}`)
    },
    puzzle_leaderboard: (p) =>
      p.mode === 'survival' ? pf.leaderboards.survival : p.time_limit_s === 300 ? pf.leaderboards.rush300 : pf.leaderboards.rush180,
  }
  return handlers
}
