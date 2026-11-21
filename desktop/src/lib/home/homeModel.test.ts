import { describe, expect, it } from 'vitest'
import { changeText, dayWord, openingFamily, resultSentence, retryMoment, shortTimeControl, sparkCoords, sparkline } from './homeModel'
import type { ReportMoment } from '../api'

describe('Home wording', () => {
  it('says the result from stored fields', () => {
    expect(resultSentence({ outcome: 'win', opponent: 'alice', termination: 'checkmate' })).toBe('You beat alice by checkmate')
    expect(resultSentence({ outcome: 'loss', opponent: 'X', termination: 'timeout' })).toBe('You lost to X on time')
    expect(resultSentence({ outcome: 'draw', opponent: 'X', termination: 'stalemate' })).toBe('You drew with X (stalemate)')
    expect(resultSentence({ outcome: null, opponent: 'X', termination: '' })).toBeNull()
  })
  it('shortens openings and time controls', () => {
    expect(openingFamily('Scandinavian Defense: Valencian Variation')).toBe('Scandinavian Defense')
    expect(shortTimeControl('180+2')).toBe('3+2')
    expect(shortTimeControl('600')).toBe('10+0')
    expect(shortTimeControl('1/86400')).toBe('Daily')
    expect(shortTimeControl('-')).toBeNull()
  })
  it('names days', () => {
    const now = new Date('2026-11-20T12:00:00')
    expect(dayWord('2026-11-20T09:00:00', now)).toBe('Today')
    expect(dayWord('2026-11-19T09:00:00', now)).toBe('Yesterday')
    expect(dayWord('2026-11-12T09:00:00', now)).toBe('12 Nov')
  })
  it('signs changes and leaves none blank', () => {
    expect(changeText(18)).toBe('+18')
    expect(changeText(-6)).toBe('\u22126')
    expect(changeText(0)).toBe('0')
    expect(changeText(null)).toBeNull()
  })
  it('retries the user\'s own moment with the largest swing', () => {
    const m = (ply: number, yours: boolean, swing: number) => ({ ply, yours, swing, bestUci: 'a1a2' }) as unknown as ReportMoment
    expect(retryMoment([m(1, false, 0.9), m(2, true, 0.3), m(3, true, 0.5)])?.ply).toBe(3)
    expect(retryMoment([m(1, false, 0.9)])).toBeNull()
  })
  it('draws a sparkline only with two points', () => {
    expect(sparkline([1])).toBe('')
    expect(sparkline([1, 2]).split(' ')).toHaveLength(2)
  })
  it('gives the rating sparkline readout its points', () => {
    expect(sparkCoords([1000, 1010, 1020])).toEqual([[0, 22], [48, 12], [96, 2]])
    expect(sparkline([1000, 1010, 1020])).toBe('0.0,22.0 48.0,12.0 96.0,2.0')
    expect(sparkCoords([1000])).toEqual([])
  })
})
