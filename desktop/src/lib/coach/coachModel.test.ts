import { describe, expect, it } from 'vitest'
import { coachDate, countText, recentText, rowsFor, windowText } from './coachModel'
import type { CoachOverview } from '../api'

describe('coach words (COACH-1 C)', () => {
  it('counts', () => {
    expect(countText({ missed: 9, total: 14 })).toBe('Missed <b>9</b> of 14')
    expect(countText({ missed: 853, total: 5091 })).toBe('Missed <b>853</b> of 5,091')
  })
  it('names the window (CF1)', () => {
    expect(windowText(365)).toBe('last 12 months')
    expect(windowText(undefined)).toBe('last 12 months')
    expect(windowText(90)).toBe('last 90 days')
  })
  it('recent', () => {
    expect(recentText({ recentCaught: 4, recentTotal: 5 })).toBe('Caught 4 of your last 5')
    expect(recentText({ recentCaught: 0, recentTotal: 1 })).toBe('Missed the last one')
    expect(recentText({ recentCaught: 0, recentTotal: 0 })).toBe('')
  })
  it('dates', () => {
    const now = new Date(2026, 10, 23, 12)
    expect(coachDate(new Date(2026, 10, 23, 8).toISOString(), now)).toBe('Today')
    expect(coachDate(new Date(2026, 10, 22, 8).toISOString(), now)).toBe('Yesterday')
    expect(coachDate(new Date(2026, 10, 19, 8).toISOString(), now)).toBe('19 Nov')
    expect(coachDate(new Date(2025, 0, 2, 8).toISOString(), now)).toBe('2 Jan 2025')
  })
  it('rows behind one item or all', () => {
    const row = { gameId: 1, ply: 3, date: '', opponent: null, move: '2... Nc6', theme: 'Fork', kind: 'threat' as const, outcome: 'missed' as const, key: 'threat:fork' }
    const o: Extract<CoachOverview, { status: 'ready' }> = {
      status: 'ready', games: 1, pending: 0, moments: 1, behind: [row],
      focus: [{ key: 'threat:fork', kind: 'threat', theme: 'fork', title: 'Forks against you', name: 'Fork', missed: 1, total: 1, recentCaught: 0, recentTotal: 1, rows: [row], rowCount: 1 }],
    }
    expect(rowsFor(o, null)).toEqual([row])
    expect(rowsFor(o, 'threat:fork')).toEqual([row])
    expect(rowsFor(o, 'chance:pin')).toEqual([])
  })
})
