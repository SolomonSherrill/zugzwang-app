import { describe, expect, it } from 'vitest'
import { ANALYSE_AGAIN_FIT, DEEP_RUNS_AVAILABLE, estimateSeconds, estimateText } from './depth'

describe('Analyse again estimates (ruling 7, RUNS-DEPTH: measured on ten games)', () => {
  it('use the measured line a + b * plies, rounded and said as "about"', () => {
    expect(estimateSeconds(14, 90)).toBeCloseTo(3.76 + 0.0491 * 90)
    expect(estimateText(14, 90)).toBe('about 8 s')
    expect(estimateText(18, 90)).toBe('about 55 s')
    expect(estimateText(24, 90)).toBe('about 8 min')
  })
  it('offer exactly 14, 18 and 24 (ruling 8 of 2026-11-20: no custom depth)', () => {
    expect(Object.keys(ANALYSE_AGAIN_FIT).map(Number)).toEqual([14, 18, 24])
  })
  it('say nothing without a measurement or a game', () => {
    expect(estimateText(20, 90)).toBeNull()
    expect(estimateText(14, 0)).toBeNull()
  })
  it('open the deeper depths now that a deeper run is kept beside the depth-14 one', () => {
    expect(DEEP_RUNS_AVAILABLE).toBe(true)
  })
})
