/**
 * COACH-2 D (ruling CB1): the one store of background jobs. Started once by the app (start()), it reads the
 * sidecar's background_jobs snapshot and then follows the events (jobsModel.ts), and again after a respawn.
 */
import { api, sidecar } from '../api'
import { EMPTY, EVENTS, applyEvent, fromSnapshot, type AnalysisJob, type Jobs } from './jobsModel'

export const jobs = $state<{ now: Jobs }>({ now: { ...EMPTY } })

let started = false
export function start(): () => void {
  if (started) return () => {}
  started = true
  const handlers = EVENTS.map((e) => {
    const fn = (d: Record<string, unknown>) => (jobs.now = applyEvent(jobs.now, e, d ?? {}))
    sidecar.on(e, fn)
    return [e, fn] as const
  })
  sidecar.on('ready', refresh)
  void refresh()
  return () => {
    for (const [e, fn] of handlers) sidecar.off(e, fn)
    sidecar.off('ready', refresh)
    started = false
  }
}

/** read the sidecar's snapshot (at start, and when the backend comes (back) up) */
export function refresh(): void {
  api
    .backgroundJobs()
    .then((s) => (jobs.now = fromSnapshot(jobs.now, s)))
    .catch(() => {})
}

/** a view started a game's analysis (analyze_game answered): shown before its first move is analysed */
export function analysisStarted(a: Pick<AnalysisJob, 'gameId' | 'runId' | 'depth'>): void {
  if (jobs.now.analysis && jobs.now.analysis.runId > a.runId) return
  jobs.now = { ...jobs.now, analysis: { ...a, done: 0, total: 0 } }
}
