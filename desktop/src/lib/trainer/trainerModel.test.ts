import { describe, expect, it } from 'vitest'
import {
  familyMovesText,
  ACCEPT_DEFAULT, ACCEPT_OPTIONS, ACCEPT_THRESHOLD, REPLIES_OPTIONS, fullMoves, lineTail, movesText,
  plyLabel, progressWord, shortName, summaryLine,
} from './trainerModel'

const rec = (attempts: number, completions: number, distinctLines: number, mastered = false) => ({
  attempts, completions, distinctLines, bestAccuracy: null, mastered,
})

describe('trainer words and options', () => {
  it('offers ruling 9\'s three Accept options, Popular moves by default, no Strict', () => {
    expect(ACCEPT_OPTIONS.map((o) => o.label)).toEqual(['This line only', 'Popular moves', 'Any book move'])
    expect(ACCEPT_DEFAULT).toBe('popular')
    expect(ACCEPT_THRESHOLD).toEqual({ popular: 0.1, any: 0.02 })
  })
  it('maps Replies to the book reply modes (ruling 21)', () => {
    expect(REPLIES_OPTIONS.map((o) => [o.label, o.value])).toEqual([
      ['Popular', 'varied'], ['Any book move', 'random'], ['Main line', 'pinned'],
    ])
  })
  it('words the record and claims nothing more (ruling 18)', () => {
    expect(progressWord(null).word).toBe('Not tried')
    expect(progressWord(rec(0, 0, 0)).word).toBe('Not tried')
    expect(progressWord(rec(2, 0, 0)).word).toBe('Tried')
    expect(progressWord(rec(3, 1, 1))).toEqual({ word: 'Finished', detail: null })
    expect(progressWord(rec(5, 4, 2))).toEqual({ word: 'Finished', detail: '2 ends' })
    expect(progressWord(rec(5, 4, 3, true))).toEqual({ word: 'Mastered', detail: '3 ends' })
    for (const r of [null, rec(1, 0, 0), rec(5, 4, 3, true)]) {
      expect(JSON.stringify(progressWord(r))).not.toMatch(/learn|due/i)
    }
  })
  it('folds the options into one line', () => {
    expect(summaryLine('black', 'varied', 'line', true)).toBe('As Black, this line only, from move 1')
    expect(summaryLine('white', 'pinned', 'popular', false)).toBe('As White, main-line replies, popular moves, from the line start')
  })
  it('names lines without the family', () => {
    expect(shortName('Scandinavian Defense', 'Scandinavian Defense: Valencian Variation')).toBe('Valencian Variation')
    expect(shortName('Scandinavian Defense', 'Scandinavian Defense')).toBe('Main line')
  })
  it('writes moves in SAN, numbered', () => {
    const uci = ['e2e4', 'd7d5', 'e4d5', 'd8d5', 'b1c3', 'd5d8']
    expect(movesText(uci)).toBe('1. e4 d5 2. exd5 Qxd5 3. Nc3 Qd8')
    expect(lineTail(uci)).toBe('3. Nc3 Qd8')
    expect(fullMoves(uci.length)).toBe(3)
    expect(fullMoves(7)).toBe(4)
    expect(plyLabel(4, false, 'Nf6')).toBe('4… Nf6')
  })
})

describe('families list moves (UI-BUILD-3 B2)', () => {
  it('shows the shared moves, not the top line', () => {
    expect(familyMovesText({ sharedMoves: '1. e4 e5 2. Nf3 Nc6 3. Bc4' })).toBe('1. e4 e5 2. Nf3 Nc6 3. Bc4')
    expect(familyMovesText({ sharedMoves: '1. e4 c5' })).toBe('1. e4 c5')
  })
  it('says so when the lines share no first move', () => {
    expect(familyMovesText({ sharedMoves: '' })).toBe('Several move orders')
    expect(familyMovesText({})).toBe('Several move orders')
  })
})
