import { describe, expect, it } from 'vitest'
import { coverageText, emptyText, itemText, linkText } from './patterns'
import type { InsightsPatterns } from './api'

const base: InsightsPatterns = { covered: 3500, analysed: 3500, sentences: [], tested: [] }

describe('patterns card text', () => {
  it('says how many games it covers', () => {
    expect(coverageText(base)).toBe('Across 3,500 analysed games.')
    expect(coverageText({ ...base, covered: 1 , analysed: 1 })).toBe('Across 1 analysed game.')
  })
  it('says how many games it leaves out', () => {
    expect(coverageText({ ...base, covered: 3400 })).toBe(
      'Across 3,400 of 3,500 analysed games; the other 100 have no pattern facts stored yet.',
    )
  })
  it('claims nothing when no sentence passes', () => {
    expect(emptyText(base)).toBe('No pattern clears the bar on these games.')
    expect(emptyText({ ...base, covered: 0, analysed: 0 })).toBe(
      'No games with pattern facts under these filters.',
    )
  })
  it('renders a linked ply', () => {
    expect(
      itemText({ gameId: 1, ply: 44, move: '23.Nh4', label: 'inaccuracy', date: '2026-06-04T12:00:00', opponent: 'X' }),
    ).toBe('2026-06-04 · vs X · 23.Nh4 (inaccuracy)')
    expect(itemText({ gameId: 1, ply: 20, move: '11.Bxf7+', label: null, date: '2026-06-04', opponent: null })).toBe(
      '2026-06-04 · 11.Bxf7+',
    )
  })
  it('renders the link with its count', () => {
    expect(linkText("Your answers that weren't the engine's move, newest first", 5914)).toBe(
      "Your answers that weren't the engine's move, newest first → (5,914)",
    )
  })
})
