/**
 * COACH-2 D (ruling CB1): one store of the work running in the background, read by the sidebar's activity line, the
 * Review header and the Games rows. This file is the pure part: the state, how each sidecar event and the
 * background_jobs snapshot change it, and the words. Every run carries its id (ruling CB2), so a snapshot or a late
 * event never revives a run whose end was announced.
 */

export interface AnalysisJob {
  gameId: number
  runId: number
  depth: number
  done: number
  total: number
}
export interface SyncJob {
  run: number
  kind: 'sync' | 'analyse' | null
  phase: 'fetching' | 'analyzing' | null
  done: number
  total: number
}
export interface CoachJob {
  done: number
  total: number
}
export interface PuzzleJob {
  run: number
  kind: 'lichess' | 'file' | null
  bytes: number
  totalBytes: number | null
  imported: number
  finishing: boolean
}
export interface Jobs {
  analysis: AnalysisJob | null
  sync: SyncJob | null
  coach: CoachJob | null
  puzzles: PuzzleJob | null
  /** run ids whose end was announced */
  endedSync: number[]
  endedPuzzles: number[]
  endedAnalysis: number[]
}

export const EMPTY: Jobs = { analysis: null, sync: null, coach: null, puzzles: null, endedSync: [], endedPuzzles: [], endedAnalysis: [] }

/** the background_jobs RPC's answer (sidecar/main.py rpc_background_jobs) */
export interface JobsSnapshot {
  sync: { running: boolean; run: number; kind: 'sync' | 'analyse' | null; progress: { phase: 'fetching' | 'analyzing'; done: number; total: number } | null }
  analysis: AnalysisJob | null
  coach: CoachJob | null
  puzzles: { running: boolean; run: number; kind: 'lichess' | 'file' | null; progress: { bytes: number; totalBytes: number | null; imported: number } | null }
}

const num = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined)

/** the snapshot, as far as no event has said more: a run already ended stays ended; a newer run known from events
 *  is kept */
export function fromSnapshot(j: Jobs, s: JobsSnapshot): Jobs {
  const out = { ...j }
  const sr = s.sync
  if (sr.running && !j.endedSync.includes(sr.run) && (!j.sync || j.sync.run <= sr.run))
    out.sync = { run: sr.run, kind: sr.kind, phase: sr.progress?.phase ?? j.sync?.phase ?? null, done: sr.progress?.done ?? 0, total: sr.progress?.total ?? 0 }
  else if (!sr.running && j.sync && j.sync.run <= sr.run) out.sync = null
  const a = s.analysis
  if (a && !j.endedAnalysis.includes(a.runId) && (!j.analysis || j.analysis.runId <= a.runId)) out.analysis = { ...a }
  else if (!a && j.analysis && j.analysis.done === 0) out.analysis = null
  out.coach = s.coach && s.coach.total > s.coach.done ? { ...s.coach } : null
  const p = s.puzzles
  if (p.running && !j.endedPuzzles.includes(p.run) && (!j.puzzles || j.puzzles.run <= p.run))
    out.puzzles = { run: p.run, kind: p.kind, bytes: p.progress?.bytes ?? 0, totalBytes: p.progress?.totalBytes ?? null, imported: p.progress?.imported ?? 0, finishing: false }
  else if (!p.running && j.puzzles && j.puzzles.run <= p.run) out.puzzles = null
  return out
}

/** one sidecar event */
export function applyEvent(j: Jobs, event: string, d: Record<string, unknown>): Jobs {
  const run = num(d.run)
  switch (event) {
    case 'sync_progress': {
      if (run !== undefined && j.endedSync.includes(run)) return j
      const phase = d.phase === 'analyzing' ? 'analyzing' : 'fetching'
      const kind = j.sync && (run === undefined || j.sync.run === run) ? j.sync.kind : phase === 'fetching' ? 'sync' : null
      return { ...j, sync: { run: run ?? j.sync?.run ?? 0, kind, phase, done: num(d.done) ?? 0, total: num(d.total) ?? 0 } }
    }
    case 'sync_finished':
    case 'sync_cancelled': {
      const ended = run === undefined ? j.endedSync : [...j.endedSync, run]
      const over = !j.sync || run === undefined || j.sync.run <= run
      return { ...j, endedSync: ended, sync: over ? null : j.sync }
    }
    case 'analysis_ply': {
      const runId = num(d.runId)
      const gameId = num(d.gameId)
      if (gameId === undefined) return j
      if (runId !== undefined && j.endedAnalysis.includes(runId)) return j
      if (runId !== undefined && j.analysis && j.analysis.runId > runId) return j
      const depth = num(d.depth) ?? (j.analysis?.gameId === gameId ? j.analysis.depth : 14)
      return { ...j, analysis: { gameId, runId: runId ?? j.analysis?.runId ?? 0, depth, done: (num(d.ply) ?? 0) + 1, total: num(d.total) ?? 0 } }
    }
    case 'analysis_done':
    case 'analysis_cancelled':
    case 'analysis_error': {
      if (typeof d.fen === 'string') return j // a live position's failure, not a game's analysis
      const runId = num(d.runId)
      const gameId = num(d.gameId)
      const ended = runId === undefined ? j.endedAnalysis : [...j.endedAnalysis, runId]
      const mine = j.analysis && (runId !== undefined ? j.analysis.runId === runId : gameId === undefined || j.analysis.gameId === gameId)
      return { ...j, endedAnalysis: ended, analysis: mine ? null : j.analysis }
    }
    case 'coach_progress': {
      const done = num(d.done) ?? 0
      const total = num(d.total) ?? 0
      return { ...j, coach: d.finished || total <= done ? null : { done, total } }
    }
    case 'puzzle_import_progress': {
      if (run !== undefined && j.endedPuzzles.includes(run)) return j
      return {
        ...j,
        puzzles: {
          run: run ?? j.puzzles?.run ?? 0,
          kind: d.kind === 'file' ? 'file' : 'lichess',
          bytes: num(d.bytes) ?? 0,
          totalBytes: num(d.totalBytes) ?? null,
          imported: num(d.imported) ?? 0,
          finishing: false,
        },
      }
    }
    case 'puzzle_import_finishing':
      return j.puzzles ? { ...j, puzzles: { ...j.puzzles, finishing: true, imported: num(d.imported) ?? j.puzzles.imported } } : j
    case 'puzzle_import_done':
    case 'puzzle_import_cancelled':
    case 'puzzle_import_error': {
      const ended = run === undefined ? j.endedPuzzles : [...j.endedPuzzles, run]
      return { ...j, endedPuzzles: ended, puzzles: null }
    }
  }
  return j
}

/** the events the store listens to */
export const EVENTS = [
  'sync_progress', 'sync_finished', 'sync_cancelled',
  'analysis_ply', 'analysis_done', 'analysis_cancelled', 'analysis_error',
  'coach_progress',
  'puzzle_import_progress', 'puzzle_import_finishing', 'puzzle_import_done', 'puzzle_import_cancelled', 'puzzle_import_error',
] as const

export type JobTarget = { route: 'review'; gameId: number } | { route: 'games' } | { route: 'coach' } | { route: 'puzzles' }
export interface JobLine {
  key: 'analysis' | 'sync' | 'puzzles' | 'coach'
  text: string
  /** 0..1, or null for no bar */
  fraction: number | null
  target: JobTarget
}

const fmt = (n: number) => n.toLocaleString('en-US')
const mb = (b: number) => Math.round(b / 1_000_000).toLocaleString('en-US')

/** "Analysing at depth 24: 38 of 90 moves" */
export function analysisText(a: Pick<AnalysisJob, 'depth' | 'done' | 'total'>): string {
  return a.total ? `Analysing at depth ${a.depth}: ${fmt(a.done)} of ${fmt(a.total)} moves` : `Analysing at depth ${a.depth}…`
}

export function syncText(s: SyncJob): string {
  if (s.phase === 'analyzing' && s.total) {
    return s.kind === 'analyse'
      ? `Analysing your games: ${fmt(s.done)} of ${fmt(s.total)}`
      : `Syncing: analysing ${fmt(s.done)} of ${fmt(s.total)} games`
  }
  if (s.kind === 'analyse') return 'Analysing your games…'
  return 'Syncing: fetching your games…'
}

export function puzzleText(p: PuzzleJob): string {
  if (p.finishing) return 'Puzzles: finishing the import…'
  if (p.kind === 'file') return p.imported ? `Importing puzzles: ${fmt(p.imported)}` : 'Importing puzzles…'
  return p.totalBytes ? `Downloading puzzles: ${mb(p.bytes)} of ${mb(p.totalBytes)} MB` : 'Downloading puzzles…'
}

export function coachText(c: CoachJob): string {
  return `The coach is reading your games: ${fmt(c.done)} of ${fmt(c.total)}`
}

/** the lines to show, most specific first: a game's analysis, the sync, a puzzle download, the coach's reading */
export function jobLines(j: Jobs): JobLine[] {
  const out: JobLine[] = []
  if (j.analysis) {
    const a = j.analysis
    out.push({ key: 'analysis', text: analysisText(a), fraction: a.total ? a.done / a.total : null, target: { route: 'review', gameId: a.gameId } })
  }
  if (j.sync) {
    const s = j.sync
    out.push({ key: 'sync', text: syncText(s), fraction: s.phase === 'analyzing' && s.total ? s.done / s.total : null, target: { route: 'games' } })
  }
  if (j.puzzles) {
    const p = j.puzzles
    out.push({ key: 'puzzles', text: puzzleText(p), fraction: p.totalBytes && !p.finishing ? p.bytes / p.totalBytes : null, target: { route: 'puzzles' } })
  }
  if (j.coach) out.push({ key: 'coach', text: coachText(j.coach), fraction: j.coach.total ? j.coach.done / j.coach.total : null, target: { route: 'coach' } })
  return out
}

/** the game being analysed, if it is this one (the Review header, a Games row) */
export function analysisFor(j: Jobs, gameId: number | null | undefined): AnalysisJob | null {
  return gameId != null && j.analysis?.gameId === gameId ? j.analysis : null
}
