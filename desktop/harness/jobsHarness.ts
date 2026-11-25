/**
 * COACH-2 D (ruling CB1): background jobs in the browser harness. `?jobs=all` answers background_jobs with a depth-24
 * analysis of the main game (38 of 90 moves), a sync analysing 4 of 10 games, a puzzle download and the coach reading
 * your games; `?jobs=analysis` with the analysis alone. Without the parameter nothing runs. Synthetic, no owner data.
 */
import type { Fixtures } from './fakeSidecar'

type Emit = (event: string, data: Record<string, unknown>) => void
type Handler = (params: Record<string, unknown>, emit: Emit) => unknown

export function jobsHandlers(fx: Fixtures, which: string | null): Record<string, Handler> {
  const none = {
    sync: { running: false, run: 0, kind: null, progress: null },
    analysis: null,
    coach: null,
    puzzles: { running: false, run: 0, kind: null, progress: null },
  }
  const analysis = { gameId: fx.meta.mainGameId, runId: 9001, depth: 24, done: 38, total: 90 }
  const snapshot =
    which === 'all'
      ? {
          sync: { running: true, run: 3, kind: 'sync', progress: { phase: 'analyzing', done: 4, total: 10 } },
          analysis,
          coach: { done: 120, total: 412 },
          puzzles: { running: true, run: 1, kind: 'lichess', progress: { bytes: 120_000_000, totalBytes: 310_000_000, imported: 400_000 } },
        }
      : which === 'analysis'
        ? { ...none, analysis }
        : none
  return { background_jobs: () => snapshot }
}
