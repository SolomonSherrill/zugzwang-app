import { describe, expect, it } from 'vitest'
import { RunGuard } from './runGuard'

describe('the sync card after a sync ends (COACH-2 D, ruling CB2)', () => {
  it('reproduces the order that left the card stuck, and does not revive the run', () => {
    // sync_done -> refreshStatus() asked; sync_finished (the card finishes) -> refreshStatus() asked; both
    // answered syncing: true because the thread was still alive (run 3).
    const g = new RunGuard()
    g.started() // Sync now
    const askedOnDone = g.ask()
    g.end(3) // sync_finished {run: 3}
    const askedOnFinished = g.ask()
    // the card is finished (not running) when the answers arrive
    expect(g.verdict({ running: true, run: 3 }, askedOnDone, false)).toBe('keep')
    expect(g.verdict({ running: true, run: 3 }, askedOnFinished, false)).toBe('keep')
    expect(g.live({ running: true, run: 3 })).toBe(false)
  })
  it('a run started elsewhere is still shown', () => {
    const g = new RunGuard()
    g.end(3)
    expect(g.verdict({ running: true, run: 4 }, g.ask(), false)).toBe('revive')
  })
  it('a status that says nothing runs closes a card still showing one', () => {
    const g = new RunGuard()
    g.started()
    const t = g.ask()
    expect(g.verdict({ running: false, run: 4 }, t, true)).toBe('close')
  })
  it('but not a card started after the status was asked', () => {
    const g = new RunGuard()
    const t = g.ask() // a status asked on mount
    g.started() // Sync now before its answer came
    expect(g.verdict({ running: false, run: 3 }, t, true)).toBe('keep')
  })
  it('an older sidecar without run ids still closes and revives', () => {
    const g = new RunGuard()
    expect(g.verdict({ running: true }, g.ask(), false)).toBe('revive')
    expect(g.verdict({ running: false }, g.ask(), true)).toBe('close')
  })
})
