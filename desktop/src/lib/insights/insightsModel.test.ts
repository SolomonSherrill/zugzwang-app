import { describe, expect, it } from 'vitest'
import type { InsightsMonth } from '../api'
import { changeOver, heatOpacity, monthLabel, ratio, series, sinceFor, sparkCoords, sparkPoints, statValueText } from './insightsModel'

const m = (month: string, accuracy: number | null, games = 10): InsightsMonth => ({
  month, games, analysed: games, accuracy, winRate: 50, blundersPerGame: 1.1,
})

describe('insights model', () => {
  it('turns a time frame into a start date, none for All', () => {
    expect(sinceFor('all')).toBeUndefined()
    expect(sinceFor('7d', Date.UTC(2026, 10, 20))).toBe('2026-11-13T00:00:00.000Z')
  })
  it('names months', () => {
    expect(monthLabel('2026-11')).toBe('Nov')
    expect(monthLabel('2025-12')).toBe('Dec')
  })
  it('keeps only months with a figure, and changes from the first to the last', () => {
    const ms = [m('2025-12', null, 0), m('2026-01', 74.0), m('2026-02', null, 0), m('2026-11', 78.5)]
    const pts = series(ms, 'accuracy')
    expect(pts).toEqual([[1, 74], [3, 78.5]])
    expect(changeOver(pts)).toEqual({ delta: 4.5, text: '+4.5 over 2 months' })
    expect(changeOver([[0, 1.2], [11, 0.99]], 2)?.text).toBe('\u22120.21 over 11 months')
    expect(changeOver([[0, 1]])).toBeNull()
  })
  it('draws no sparkline from one point', () => {
    expect(sparkPoints([[0, 1]])).toBe('')
    expect(sparkPoints([[0, 1], [11, 2]], 12, 84, 26).split(' ')).toHaveLength(2)
  })
  it('scales heat cells and leaves empty ones blank', () => {
    expect(heatOpacity(null, 70, 80)).toBe(0)
    expect(heatOpacity(80, 70, 80)).toBeCloseTo(0.82)
    expect(heatOpacity(70, 70, 80)).toBeCloseTo(0.12)
  })
  it('gives a share only when there is a denominator', () => {
    expect(ratio(1, 4)).toBe(25)
    expect(ratio(1, 0)).toBeNull()
  })
  it('gives the sparkline readout its points and values', () => {
    const pts: [number, number][] = [[0, 70], [11, 80]]
    expect(sparkCoords(pts)).toEqual([[0, 23], [84, 3]])
    expect(sparkPoints(pts)).toBe('0.0,23.0 84.0,3.0')
    expect(sparkCoords([[3, 1]])).toEqual([])
    expect(statValueText('accuracy', 76.43)).toBe('76.4')
    expect(statValueText('winRate', 52.06)).toBe('52.1%')
    expect(statValueText('blundersPerGame', 1.294)).toBe('1.29')
    expect(statValueText('games', 1204)).toBe('1,204')
  })
})
