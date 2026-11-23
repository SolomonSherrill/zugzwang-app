import { describe, expect, it } from 'vitest'
import {
  ago, dayLabel, deltaLabel, handleShape, initial, onlineFirst, presence, ratingCell, recordLabel, scoutingNote,
  shortOpening, tcLabel, wdlWidths,
} from './friendsModel'

const NOW = Date.UTC(2026, 10, 21, 12)

describe('friends model', () => {
  it('checks a handle the way the server does, first', () => {
    expect(handleShape('')).toBeNull()
    expect(handleShape('ab')).toMatch(/short/)
    expect(handleShape('x'.repeat(21))).toMatch(/long/)
    expect(handleShape('hannah.k')).toMatch(/Only letters/)
    expect(handleShape('ri_tan')).toBeNull()
  })
  it('names presence and time ago', () => {
    expect(presence({ online: true, last_seen: NOW }, NOW)).toEqual({ text: 'Online', online: true })
    expect(presence({ online: false, last_seen: NOW - 2 * 3600_000 }, NOW).text).toBe('Last seen 2 h ago')
    expect(presence({ online: false, last_seen: null }, NOW).text).toBe('Offline')
    expect(ago(NOW - 12 * 60_000, NOW)).toBe('12 min ago')
    expect(ago(NOW - 30 * 3600_000, NOW)).toBe('Yesterday')
    expect(ago(NOW - 3 * 86400_000, NOW)).toBe('3 days ago')
    expect(ago(NOW - 15 * 86400_000, NOW)).toBe('2 weeks ago')
  })
  it('sorts online first', () => {
    const fs = [
      { handle: 'b', online: false, last_seen: 5 },
      { handle: 'a', online: true, last_seen: 1 },
      { handle: 'c', online: false, last_seen: 9 },
    ]
    expect(onlineFirst(fs).map((f) => f.handle)).toEqual(['a', 'c', 'b'])
  })
  it('prints ratings, records, deltas', () => {
    expect(ratingCell({ speed: 'blitz', rating: 1390, approx: true, lichess: 1680 }, 'ChessGoals')).toEqual({
      label: 'Blitz',
      value: '≈1390',
      title: 'Lichess blitz 1680, about 1390 on Chess.com (ChessGoals)',
    })
    expect(ratingCell({ speed: 'rapid', rating: 1520, approx: false }, 'x').title).toBe('Chess.com rapid')
    expect(recordLabel({ games: 9, won: 5, drawn: 1, lost: 3, score: 61 })).toBe('5 / 1 / 3')
    expect(recordLabel({ games: 0, won: 0, drawn: 0, lost: 0, score: null })).toBe('')
    expect(deltaLabel(12)).toEqual({ text: '+12 over 30 days', tone: 'up' })
    expect(deltaLabel(-18)).toEqual({ text: '−18 over 30 days', tone: 'down' })
    expect(deltaLabel(null)).toBeNull()
    expect(wdlWidths({ games: 4, won: 2, drawn: 1, lost: 1, score: 62.5 })).toEqual([50, 25, 25])
  })
  it('shortens opening names and time controls as the mockups do', () => {
    expect(shortOpening('Sicilian Defense: Najdorf Variation')).toBe('Sicilian, Najdorf')
    expect(shortOpening('Italian Game')).toBe('Italian Game')
    expect(shortOpening('Caro-Kann Defense: Advance Variation, Short Variation')).toBe('Caro-Kann, Advance')
    expect(tcLabel('180+2')).toBe('3+2')
    expect(tcLabel('600')).toBe('10+0')
    expect(tcLabel('300+0')).toBe('5+0')
  })
  it('labels days and the scouting basis', () => {
    const now = new Date(NOW)
    expect(dayLabel(new Date(NOW - 3600_000).toISOString(), now)).toBe('Today')
    expect(dayLabel('2026-11-03T10:00:00Z', now)).toBe('3 Nov')
    expect(dayLabel('2024-11-03T10:00:00Z', now)).toBe('3 Nov 2024')
    expect(scoutingNote('maxk', { chesscom: 312 }, '2026-01-02T00:00:00Z', now)).toBe(
      "From maxk's 312 Chess.com games in the last 12 months. No engine involved.",
    )
    expect(scoutingNote('maxk', {}, null, now)).toBe('No games yet. No engine involved.')
    expect(initial('_ri')).toBe('R')
  })
})
