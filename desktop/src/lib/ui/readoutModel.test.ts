import { describe, expect, it } from 'vitest'
import type { MoveAnalysisInfo } from '../api'
import {
  dayKey, dayText, materialText, monthText, moveReadout, nearestIndex, placeLabel, readoutText, stepIndex,
} from './readoutModel'

const ma = (ply: number, o: Partial<MoveAnalysisInfo> = {}): MoveAnalysisInfo => ({
  ply, playedUci: '', bestUci: null, pvUci: '', scoreBeforeCp: null, scoreBeforeMate: null,
  scoreAfterCp: null, scoreAfterMate: null, classification: 'good', isBook: false, lines: [], ...o,
})
const sans = (n: number) => Array.from({ length: n }, (_, i) => (i === 46 || i === 47 ? 'Nxe4' : `m${i}`))

describe('nearest point', () => {
  it('finds the x nearest the pointer, ties to the left', () => {
    const xs = [0, 10, 20]
    expect(nearestIndex(xs, 4)).toBe(0)
    expect(nearestIndex(xs, 6)).toBe(1)
    expect(nearestIndex(xs, 15)).toBe(1)
    expect(nearestIndex(xs, 16)).toBe(2)
    expect(nearestIndex(xs, -5)).toBe(0)
    expect(nearestIndex(xs, 500)).toBe(2)
    expect(nearestIndex([7], 0)).toBe(0)
    expect(nearestIndex([], 3)).toBe(-1)
  })
  it('matches rounding on an evenly spaced move chart', () => {
    const n = 91
    const w = 380
    const xs = Array.from({ length: n }, (_, i) => (i / (n - 1)) * w)
    for (const px of [0, 3, 2.1, 190, 377.9, 380]) expect(nearestIndex(xs, px)).toBe(Math.round((px / w) * (n - 1)))
  })
})

describe('keyboard steps', () => {
  it('steps by date, landing on the date\'s last point, and stops at the ends', () => {
    const keys = ['a', 'a', 'b', 'c', 'c', 'c']
    expect(stepIndex(keys, 0, 1)).toBe(2)
    expect(stepIndex(keys, 2, 1)).toBe(5)
    expect(stepIndex(keys, 5, 1)).toBe(5)
    expect(stepIndex(keys, 5, -1)).toBe(2)
    expect(stepIndex(keys, 3, -1)).toBe(2)
    expect(stepIndex(keys, 2, -1)).toBe(1)
    expect(stepIndex(keys, 1, -1)).toBe(1)
    expect(stepIndex([], 0, 1)).toBe(-1)
  })
  it('steps one point at a time when no two share a key', () => {
    const keys = ['0', '1', '2']
    expect(stepIndex(keys, 1, 1)).toBe(2)
    expect(stepIndex(keys, 1, -1)).toBe(0)
  })
})

describe('label placement', () => {
  it('sits right of the point and flips left at the right edge', () => {
    expect(placeLabel({ x: 10, labelW: 60, labelH: 22, boxW: 200, placement: 'side', top: 14 })).toEqual({ left: 18, top: 14, flipped: false })
    expect(placeLabel({ x: 180, labelW: 60, labelH: 22, boxW: 200, placement: 'side' })).toEqual({ left: 112, top: 4, flipped: true })
    // exactly fitting stays right
    expect(placeLabel({ x: 132, labelW: 60, labelH: 22, boxW: 200, placement: 'side' }).flipped).toBe(false)
  })
  it('never leaves the box: a flipped label near the left edge is held at 0', () => {
    const p = placeLabel({ x: 50, labelW: 60, labelH: 22, boxW: 100, placement: 'side' })
    expect(p.flipped).toBe(true)
    expect(p.left).toBe(0)
    expect(p.left + 60).toBeLessThanOrEqual(100)
  })
  it('centres above a sparkline, held inside its width; wider labels grow left from the right edge', () => {
    expect(placeLabel({ x: 40, labelW: 30, labelH: 20, boxW: 84, placement: 'above' })).toEqual({ left: 25, top: -28, flipped: false })
    expect(placeLabel({ x: 2, labelW: 30, labelH: 20, boxW: 84, placement: 'above' }).left).toBe(0)
    expect(placeLabel({ x: 84, labelW: 30, labelH: 20, boxW: 84, placement: 'above' }).left).toBe(54)
    expect(placeLabel({ x: 10, labelW: 100, labelH: 20, boxW: 84, placement: 'above', gap: 4 })).toEqual({ left: -16, top: -24, flipped: false })
    expect(placeLabel({ x: 84, labelW: 100, labelH: 20, boxW: 84, placement: 'above' }).left).toBe(-16)
  })
})

describe('move chart labels', () => {
  const moves = new Map<number, MoveAnalysisInfo>([
    [0, ma(0, { scoreBeforeCp: 25 })],
    [46, ma(46, { scoreAfterCp: 140, classification: 'best' })],
    [47, ma(47, { scoreAfterCp: 140, classification: 'blunder' })],
    [48, ma(48, { scoreAfterMate: -3, classification: 'mistake' })],
  ])
  const base = { sans: sans(60), moves, startsWhite: true }
  it("numbers White's and Black's moves as the move list does, with the eval from White's side", () => {
    expect(moveReadout({ ...base, position: 47, kind: 'eval' })).toEqual({ title: '24. Nxe4', value: '+1.4', cls: null })
    expect(moveReadout({ ...base, position: 48, kind: 'eval' })).toEqual({ title: '24\u2026 Nxe4', value: '\u22121.4', cls: 'blunder' })
    expect(moveReadout({ ...base, position: 49, kind: 'eval' }).value).toBe('#\u22123')
    expect(moveReadout({ ...base, position: 30, kind: 'eval' }).value).toBe('')
  })
  it('shows the icon only for the classes the charts mark', () => {
    expect(moveReadout({ ...base, position: 47, kind: 'eval' }).cls).toBeNull()
    expect(moveReadout({ ...base, position: 49, kind: 'eval' }).cls).toBe('mistake')
  })
  it('names the start, with its eval', () => {
    expect(moveReadout({ ...base, position: 0, kind: 'eval' })).toEqual({ title: 'Start', value: '+0.3', cls: null })
    expect(moveReadout({ ...base, position: 0, kind: 'time', spent: [] })).toEqual({ title: 'Start', value: '', cls: null })
  })
  it('a game starting with Black starts at 1… and its evals turn with the side to move', () => {
    const black = new Map([[0, ma(0, { scoreAfterCp: 50, scoreBeforeCp: -20 })], [1, ma(1, { scoreAfterCp: 50 })]])
    const o = { sans: ['e5', 'Nf3'], moves: black, startsWhite: false, kind: 'eval' as const }
    expect(moveReadout({ ...o, position: 1 })).toEqual({ title: '1\u2026 e5', value: '\u22120.5', cls: null })
    expect(moveReadout({ ...o, position: 2 })).toEqual({ title: '2. Nf3', value: '+0.5', cls: null })
    expect(moveReadout({ ...o, position: 0 }).value).toBe('+0.2')
  })
  it('material from White\'s side and time spent on the move', () => {
    const material = Array(60).fill(0)
    material[48] = 2
    material[49] = -1
    expect(moveReadout({ ...base, position: 48, kind: 'material', material }).value).toBe('+2')
    expect(moveReadout({ ...base, position: 49, kind: 'material', material }).value).toBe('\u22121')
    expect(moveReadout({ ...base, position: 10, kind: 'material', material }).value).toBe('0')
    const spent: (number | null)[] = Array(60).fill(null)
    spent[47] = 12
    spent[46] = 4.25
    expect(moveReadout({ ...base, position: 48, kind: 'time', spent })).toEqual({ title: '24\u2026 Nxe4', value: '12 s', cls: 'blunder' })
    expect(moveReadout({ ...base, position: 47, kind: 'time', spent }).value).toBe('4.3 s')
    expect(moveReadout({ ...base, position: 20, kind: 'time', spent }).value).toBe('')
  })
  it('material text', () => {
    expect(materialText(0)).toBe('0')
    expect(materialText(3)).toBe('+3')
    expect(materialText(-1)).toBe('\u22121')
  })
})

describe('date chart labels', () => {
  it('names months and days', () => {
    expect(monthText('2026-03')).toBe('Mar 2026')
    expect(monthText('2025-12')).toBe('Dec 2025')
    const now = new Date(2026, 10, 20)
    expect(dayText('2026-11-14', now)).toBe('14 Nov')
    expect(dayText('2021-04-22', now)).toBe('22 Apr 2021')
    const t = new Date(2026, 10, 14, 15, 30).toISOString()
    expect(dayText(t, now)).toBe('14 Nov')
    expect(dayKey(t)).toBe('2026-11-14')
  })
  it('reads as one line for assistive tech', () => {
    expect(readoutText({ title: 'Mar 2026', value: '76.4', note: '120 games' })).toBe('Mar 2026, 76.4, 120 games')
    expect(readoutText({ title: '24\u2026 Nxe4', value: '\u22121.4', cls: 'blunder' })).toBe('24\u2026 Nxe4, blunder, \u22121.4')
    expect(readoutText(null)).toBe('')
  })
})
