import { describe, expect, it } from 'vitest'
import { EMPTY, analysisFor, applyEvent, fromSnapshot, jobLines, type Jobs, type JobsSnapshot } from './jobsModel'

const run = (j: Jobs, ...evs: [string, Record<string, unknown>][]) => evs.reduce((a, [e, d]) => applyEvent(a, e, d), j)
const snap = (over: Partial<JobsSnapshot> = {}): JobsSnapshot => ({
  sync: { running: false, run: 0, kind: null, progress: null },
  analysis: null,
  coach: null,
  puzzles: { running: false, run: 0, kind: null, progress: null },
  ...over,
})

describe('the background jobs store (COACH-2 D, ruling CB1)', () => {
  it('shows a deeper analysis as the ruling words it, with a bar', () => {
    const j = run(EMPTY, ['analysis_ply', { gameId: 7, runId: 40, depth: 24, ply: 37, total: 90 }])
    const [line] = jobLines(j)
    expect(line).toEqual({ key: 'analysis', text: 'Analysing at depth 24: 38 of 90 moves', fraction: 38 / 90, target: { route: 'review', gameId: 7 } })
    expect(analysisFor(j, 7)?.done).toBe(38)
    expect(analysisFor(j, 8)).toBeNull()
  })
  it('a cancelled earlier run does not end the one that replaced it', () => {
    const j = run(
      EMPTY,
      ['analysis_ply', { gameId: 7, runId: 41, depth: 14, ply: 0, total: 80 }],
      ['analysis_cancelled', { gameId: 6, runId: 40, depth: 24 }],
      ['analysis_ply', { gameId: 6, runId: 40, depth: 24, ply: 5, total: 90 }], // late, from the ended run
    )
    expect(j.analysis?.runId).toBe(41)
    expect(run(j, ['analysis_done', { gameId: 7, runId: 41 }]).analysis).toBeNull()
  })
  it('a live position failing is not a game analysis ending', () => {
    const j = run(EMPTY, ['analysis_ply', { gameId: 7, runId: 41, depth: 14, ply: 0, total: 80 }], ['analysis_error', { fen: 'x', message: 'no' }])
    expect(j.analysis?.runId).toBe(41)
  })
  it('the sync: from progress to its end, and a snapshot taken on sync_finished does not revive it', () => {
    let j = run(EMPTY, ['sync_progress', { phase: 'fetching', done: 0, total: 0, run: 3 }])
    expect(jobLines(j).map((l) => l.text)).toEqual(['Syncing: fetching your games…'])
    j = run(j, ['sync_progress', { phase: 'analyzing', done: 4, total: 10, run: 3 }])
    expect(jobLines(j)[0].text).toBe('Syncing: analysing 4 of 10 games')
    j = run(j, ['sync_done', { source: 'lichess', run: 3 }], ['sync_finished', { run: 3 }])
    expect(j.sync).toBeNull()
    // the order of the bug: the status asked on sync_finished still said running (the thread was alive)
    j = fromSnapshot(j, snap({ sync: { running: true, run: 3, kind: 'sync', progress: null } }))
    expect(j.sync).toBeNull()
    // a later run shows
    j = fromSnapshot(j, snap({ sync: { running: true, run: 4, kind: 'analyse', progress: { phase: 'analyzing', done: 1, total: 5 } } }))
    expect(jobLines(j)[0].text).toBe('Analysing your games: 1 of 5')
  })
  it('a snapshot saying nothing runs closes a sync still shown', () => {
    const j = run(EMPTY, ['sync_progress', { phase: 'fetching', done: 0, total: 0, run: 3 }])
    expect(fromSnapshot(j, snap({ sync: { running: false, run: 3, kind: 'sync', progress: null } })).sync).toBeNull()
  })
  it('the coach reading, and a puzzle download', () => {
    let j = run(EMPTY, ['coach_progress', { done: 10, total: 412 }])
    expect(jobLines(j)[0].text).toBe('The coach is reading your games: 10 of 412')
    j = run(j, ['coach_progress', { done: 412, total: 412, finished: true }])
    expect(j.coach).toBeNull()
    j = run(j, ['puzzle_import_progress', { kind: 'lichess', bytes: 120_000_000, totalBytes: 310_000_000, imported: 5, run: 2 }])
    expect(jobLines(j)[0]).toMatchObject({ text: 'Downloading puzzles: 120 of 310 MB', target: { route: 'puzzles' } })
    j = run(j, ['puzzle_import_done', { run: 2 }])
    expect(j.puzzles).toBeNull()
    expect(fromSnapshot(j, snap({ puzzles: { running: true, run: 2, kind: 'lichess', progress: null } })).puzzles).toBeNull()
  })
  it('lists the jobs most specific first', () => {
    const j = run(
      EMPTY,
      ['coach_progress', { done: 1, total: 3 }],
      ['sync_progress', { phase: 'fetching', done: 0, total: 0, run: 1 }],
      ['analysis_ply', { gameId: 2, runId: 9, depth: 24, ply: 1, total: 50 }],
    )
    expect(jobLines(j).map((l) => l.key)).toEqual(['analysis', 'sync', 'coach'])
  })
})
