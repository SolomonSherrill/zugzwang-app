/**
 * The Puzzles screens over the fake sidecar (UI-BUILD-2 E2). Answers come from
 * `puzzles_fixtures.json` (review/ui_fixtures/record_puzzle_fixtures.py, recorded from the
 * real sidecar on a copy of a backup; private). Puzzles are served in order, so a session sees
 * each recorded puzzle once; rate_puzzle replays the recorded Glicko-2 answers in order.
 *
 * Scenarios (?state=) for the drafted states:
 *   puzzles-not-imported   nothing imported yet: "Download puzzles from Lichess" (FIX-B6 B)
 *   puzzles-no-csv         the same (kept for older shot lists)
 *   puzzles-importing      a first download running (a progress event at 40 % of the file's MB)
 *   puzzles-import-error   the download fails (the message a dropped connection gives)
 *   puzzles-updating       imported, an update downloading beside the lobby
 *   puzzles-check-newer    imported; "Check for new puzzles" answers that Lichess has newer ones
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
        return { ...pf.status, imported: false, importing: true, importKind: 'lichess', count: 0 }
      case 'puzzles-updating':
        return { ...pf.status, importing: true, importKind: 'lichess' }
      case 'puzzles-error':
        throw new Error('database is locked')
      case 'puzzles-new':
        return { ...pf.status, rating: 800, rd: 350 }
      default:
        // the recorded status predates FIX-B6's source fields: the copy as Lichess's file of 1 Nov 2026
        return { sourceDate: '2026-11-01T07:57:40+00:00', source: 'lichess', ...pf.status }
    }
  }
  const handlers: Record<string, Handler> = {
    puzzle_status: (_p, emit) => {
      const s = status()
      if (scenario === 'puzzles-importing' || scenario === 'puzzles-updating') {
        // a progress event part-way: 40 % of the file's bytes (the size Lichess served 2026-11-23)
        const totalBytes = 309_751_173
        setTimeout(() => emit('puzzle_import_progress', {
          kind: 'lichess', bytes: Math.round(totalBytes * 0.4), totalBytes, imported: 2_212_000,
        }), 50)
      }
      return s
    },
    download_puzzles: () => {
      if (scenario === 'puzzles-import-error') throw new Error('The download stopped: [Errno 54] Connection reset by peer.')
      return { started: true }
    },
    puzzle_check_update: () =>
      scenario === 'puzzles-check-newer'
        ? { date: '2026-12-01T07:57:40+00:00', bytes: 311_204_118, newer: true }
        : { date: (pf.status.sourceDate as string | undefined) ?? '2026-11-01T07:57:40+00:00', bytes: 309_751_173, newer: false },
    puzzle_summary: () =>
      scenario === 'puzzles-new'
        ? { rating: null, tries: 0, solved: 0, rushBest: {}, survivalBest: null, sessions: [], sessionGapMin: 30 }
        : pf.summary,
    get_puzzle_rating: () => (scenario === 'puzzles-new' ? { rating: 800, rd: 350, volatility: 0.06 } : pf.rating),
    import_puzzles: (p) => ({ started: !!p }),
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
