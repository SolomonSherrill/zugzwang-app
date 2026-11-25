import { describe, expect, it } from 'vitest'
import { dueLine, minutesLeft, percent, promptText, sourceParts } from './practiceModel'
import type { PracticeItem } from '../api'

const base: PracticeItem = {
  id: 1, kind: 'find', source: 'game', fen: '8/8/8/8/8/8/8/8 w - - 0 1', side: 'white', hintSquare: 'b5', gameId: 3, ply: 16,
  date: new Date(2026, 10, 15, 12).toISOString(), opponent: 'Someone', played: '9. Bf4', oppMove: null, puzzleRating: null,
}

describe('Practice words (COACH-2 C)', () => {
  it('prompts, with no theme before the answer', () => {
    expect(promptText(base)).toBe('There was a better move here than the one you played. Find it.')
    expect(promptText({ ...base, kind: 'threat', side: 'black', oppMove: '9. Nd5' })).toBe(
      'White just played 9. Nd5. Your move in the game let White win by force. Find one that deals with the threat.',
    )
    expect(promptText({ ...base, source: 'probe' })).toBe('A new position, not from your games. Find the best move.')
  })
  it('says where the position comes from', () => {
    const now = new Date(2026, 10, 24, 12)
    expect(sourceParts(base, now)).toEqual({ before: 'From your game against ', name: 'Someone', after: ', 15 Nov. You played 9. Bf4.' })
    expect(sourceParts({ ...base, source: 'probe' }, now)).toBeNull()
  })
  it('counts time and shares', () => {
    expect(minutesLeft(5, 30)).toBe('About 3 minutes left')
    expect(minutesLeft(1, 20)).toBe('About 1 minute left')
    expect(minutesLeft(0, 30)).toBe('')
    expect(dueLine({ due: 7, minutes: 5 })).toBe('due today, about 5 minutes')
    expect(percent(0.678)).toBe('68%')
    expect(percent(null)).toBe('—')
  })
})
