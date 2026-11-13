import { describe, expect, it } from 'vitest'
import type { SyncSourceCounts } from './api'
import {
  analyseMoreLabel,
  analyseMoreStep,
  pendingButtonLabel,
  pendingSplit,
  pendingSummary,
} from './pendingLabel'

const counts = (unanalysed: number, belowDepth: number): SyncSourceCounts => ({
  synced: 3000,
  pending: unanalysed + belowDepth,
  unanalysed,
  belowDepth,
  depth: 14,
  needsAttention: 0,
})

describe('pendingButtonLabel (W15)', () => {
  it('never calls analysed games unanalysed', () => {
    // The case W15 found: every game analysed at depth 10, Settings at 14.
    expect(pendingButtonLabel(pendingSplit(counts(0, 2484)))).toBe(
      'Re-analyse 2,484 below depth 14',
    )
  })
  it('names both parts when the queue holds both', () => {
    expect(pendingButtonLabel(pendingSplit(counts(3, 2481)))).toBe(
      'Analyse 3 unanalysed · re-analyse 2,481 below depth 14',
    )
  })
  it('keeps the plain wording when only unanalysed games are queued', () => {
    expect(pendingButtonLabel(pendingSplit(counts(5, 0)))).toBe('Analyse 5 unanalysed')
  })
  it('has no button when nothing is queued', () => {
    expect(pendingButtonLabel(pendingSplit(counts(0, 0)))).toBeNull()
  })
  it('sums both platforms', () => {
    expect(pendingSplit(counts(1, 2), counts(3, 4))).toEqual({
      unanalysed: 4,
      belowDepth: 6,
      depth: 14,
    })
  })
})

describe('pendingSummary', () => {
  it('splits the Settings line the same way', () => {
    expect(pendingSummary(counts(3, 2481))).toBe(' · 3 unanalysed · 2,481 below depth 14')
    expect(pendingSummary(counts(0, 0))).toBe('')
  })
  it('names the games the engine keeps crashing on (VAL-DEATH-2)', () => {
    expect(pendingSummary({ ...counts(3, 0), needsAttention: 1 })).toBe(
      ' · 3 unanalysed · 1 the engine keeps crashing on — not analysed',
    )
  })
})

describe('Analyse more (BETA-PUB Q4)', () => {
  it('takes a whole step between 1 and everything pending', () => {
    expect(analyseMoreStep(100, 2484)).toBe(100)
    expect(analyseMoreStep('250', 2484)).toBe(250)
    expect(analyseMoreStep(' 12.7 ', 2484)).toBe(12)
    expect(analyseMoreStep(5000, 2484)).toBe(2484)
  })
  it('refuses a step that is not one', () => {
    expect(analyseMoreStep(0, 10)).toBeNull()
    expect(analyseMoreStep(-3, 10)).toBeNull()
    expect(analyseMoreStep('', 10)).toBeNull()
    expect(analyseMoreStep('abc', 10)).toBeNull()
    expect(analyseMoreStep(5, 0)).toBeNull()
  })
  it('says how many one click starts', () => {
    expect(analyseMoreLabel(100, 2484)).toBe('Analyse the next 100')
    expect(analyseMoreLabel(1000, 2484)).toBe('Analyse the next 1,000')
    expect(analyseMoreLabel(37, 37)).toBe('Analyse all 37')
    expect(analyseMoreLabel(null, 37)).toBe('Analyse')
  })
})
