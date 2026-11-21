import { describe, expect, it } from 'vitest'
import {
  clocksAt, formatEval, lineTokens, materialBalance, moveLabel, moveRows, notableDots, numberedLine,
  phaseBands, players, swingWords, toWhite, evalAfter,
} from './reviewModel'
import type { GameDetail, MoveAnalysisInfo } from '../api'

const ma = (ply: number, cls: string, after: number | null, mate: number | null = null): MoveAnalysisInfo => ({
  ply, playedUci: '', bestUci: null, pvUci: '', scoreBeforeCp: 0, scoreBeforeMate: null,
  scoreAfterCp: after, scoreAfterMate: mate, classification: cls, isBook: false, lines: [],
})

function game(over: Partial<GameDetail> = {}): GameDetail {
  const plies = ['e4', 'e5', 'Qh5', 'Nc6', 'Bc4'].map((san) => ({ san, uci: '', fen: '8/8/8/8/8/8/8/8 w - - 0 1', check: false, opening: null }))
  return {
    id: 1, playedAt: '2026-11-19T23:07:57+00:00', playerColor: 'black', skillLevel: 0, ladderVersion: null,
    result: '1-0', termination: 'checkmate', moveCount: 3, openingEco: null, openingName: null,
    source: 'chesscom', externalId: null, speed: 'blitz', rated: false, whiteElo: 999, blackElo: 1034,
    startFen: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', plies, white: 'Opp', black: 'Me',
    runs: [{ id: 1, depth: 14, engine: 'Stockfish', completedAt: '2026-11-19T23:10:00+00:00', standard: true }],
    analysis: { runId: 1, depth: 14, whiteAccuracy: 80, blackAccuracy: 90, summary: {},
      moves: [ma(0, 'book', 30), ma(1, 'mistake', 120), ma(2, 'great', -50), ma(3, 'inaccuracy', 20), ma(4, 'blunder', null, 2)] },
    ...over,
  }
}

describe('evals from White\'s side (ruling 4)', () => {
  it('turns a mover-POV score to White\'s side', () => {
    expect(toWhite(0, 30, null)).toEqual({ cp: 30, mate: null })
    expect(toWhite(1, 30, null)).toEqual({ cp: -30, mate: null })
    expect(toWhite(1, null, 3)).toEqual({ cp: null, mate: -3 })
    expect(evalAfter(ma(67, 'blunder', 420))).toEqual({ cp: -420, mate: null })
  })
  it('formats as the mockups: sign, one decimal, minus sign, mates', () => {
    expect(formatEval({ cp: -420, mate: null })).toBe('\u22124.2')
    expect(formatEval({ cp: 31, mate: null })).toBe('+0.3')
    expect(formatEval({ cp: 4, mate: null })).toBe('0.0')
    expect(formatEval({ cp: null, mate: 3 })).toBe('#3')
    expect(formatEval({ cp: null, mate: -2 })).toBe('#\u22122')
    expect(formatEval({ cp: null, mate: 0 })).toBe('#')
    expect(formatEval({ cp: null, mate: null })).toBe('')
  })
})

describe('move numbering', () => {
  it('labels plies as the mockups', () => {
    expect(moveLabel(66, 'b5')).toBe('34. b5')
    expect(moveLabel(67, 'axb5')).toBe('34… axb5')
  })
  it('numbers a line from either side', () => {
    expect(numberedLine(67, ['Qa1+', 'Kh2', 'Qe5+'])).toBe('34… Qa1+ 35. Kh2 Qe5+')
    expect(numberedLine(66, ['b5', 'axb5'])).toBe('34. b5 axb5')
    expect(lineTokens(67, ['Qa1+', 'Kh2'])).toEqual([{ num: '34…' }, { san: 'Qa1+' }, { num: '35.' }, { san: 'Kh2' }])
  })
})

describe('the move table', () => {
  it('pairs White and Black with icons and evals from White\'s side', () => {
    const rows = moveRows(game())
    expect(rows.map((r) => r.number)).toEqual([1, 2, 3])
    expect(rows[0].white).toMatchObject({ san: 'e4', cls: 'book', eval: '+0.3' })
    expect(rows[0].black).toMatchObject({ san: 'e5', cls: 'mistake', eval: '\u22121.2' })
    expect(rows[2].white).toMatchObject({ san: 'Bc4', cls: 'blunder', eval: '#2' })
    expect(rows[2].black).toBeNull()
  })
  it('leaves icons and evals out of an unanalysed game', () => {
    const rows = moveRows(game({ analysis: null }))
    expect(rows[0].white).toMatchObject({ cls: null, eval: '' })
  })
})

describe('charts', () => {
  it('counts material from White\'s side', () => {
    expect(materialBalance('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')).toBe(0)
    expect(materialBalance('4k3/8/8/8/8/8/8/3QK3 w - - 0 1')).toBe(9)
    expect(materialBalance('3qk3/8/8/8/8/8/8/R3K3 w - - 0 1')).toBe(-4)
  })
  it('dots only brilliant, great, miss, mistake and blunder (ruling 5), after the move', () => {
    expect(notableDots(game()).map((d) => [d.ply, d.position, d.cls])).toEqual([
      [1, 2, 'mistake'], [2, 3, 'great'], [4, 5, 'blunder'],
    ])
  })
  it('bands the phases from the game\'s own division', () => {
    expect(phaseBands(25, 46, 91)).toEqual([
      { phase: 'Opening', from: 0, to: 25 },
      { phase: 'Middlegame', from: 25, to: 46 },
      { phase: 'Endgame', from: 46, to: 90 },
    ])
    expect(phaseBands(null, null, 8)).toEqual([{ phase: 'Opening', from: 0, to: 7 }])
    expect(phaseBands(null, 30, 61).map((b) => b.phase)).toEqual(['Opening', 'Endgame'])
  })
})

describe('moments', () => {
  it('say the swing in the reader\'s words', () => {
    expect(swingWords({ bandBefore: 'balanced', bandAfter: 'winning' })).toBe('Level to winning')
    expect(swingWords({ bandBefore: 'winning', bandAfter: 'balanced' })).toBe('Winning to level')
    expect(swingWords({ bandBefore: 'losing', bandAfter: 'losing' })).toBe('Losing')
  })
})

describe('strips', () => {
  it('read each side\'s last clock at a position, the base before a side has moved', () => {
    const clocks = [180.8, 181.2, 170.0, 150.5]
    expect(clocksAt(clocks, 180, 0)).toEqual({ white: 180, black: 180 })
    expect(clocksAt(clocks, 180, 1)).toEqual({ white: 180.8, black: 180 })
    expect(clocksAt(clocks, 180, 4)).toEqual({ white: 170.0, black: 150.5 })
    expect(clocksAt([], null, 3)).toEqual({ white: null, black: null })
  })
  it('name players "Name (rating)", the rating only when stored (ruling 6)', () => {
    const p = players(game())
    expect(p.white).toEqual({ name: 'Opp', rating: 999, you: false })
    expect(p.black).toEqual({ name: 'Me', rating: 1034, you: true })
    expect(players(game({ whiteElo: null })).white.rating).toBeNull()
  })
  it('show the engine\'s level in a local game', () => {
    const p = players(game({ source: 'local', skillLevel: 10, playerColor: 'white' }))
    expect(p.black).toEqual({ name: 'Stockfish', rating: 'Level 10', you: false })
  })
})
