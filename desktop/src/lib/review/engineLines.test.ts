import { describe, expect, it } from 'vitest'
import type { FenAnalyzedEvent, GameDetail, MoveAnalysisInfo } from '../api'
import { liveRows, liveWp, positionEnd, sideToMove, storedRows } from './engineLines'
import { cellRows } from './reviewModel'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'

function ma(ply: number, lines: { uci: string[]; san: string[]; cp: number }[], after = 20): MoveAnalysisInfo {
  return {
    ply,
    lines: lines.map((l) => ({ ...l, mate: null })),
    scoreAfterCp: after,
    scoreAfterMate: null,
  } as unknown as MoveAnalysisInfo
}
const game = {
  startFen: START,
  plies: [
    { uci: 'e2e4', san: 'e4', fen: AFTER_E4 },
    { uci: 'e7e5', san: 'e5', fen: 'x' },
  ],
} as unknown as GameDetail

describe('storedRows', () => {
  it("keeps each line's UCI moves (a click plays them) and marks the best and the played", () => {
    const by = new Map([[0, ma(0, [{ uci: ['e2e4', 'e7e5'], san: ['e4', 'e5'], cp: 30 }, { uci: ['d2d4'], san: ['d4'], cp: 20 }])]])
    const rows = storedRows(game, by, 0)
    expect(rows.map((r) => [r.ucis, r.best, r.played, r.eval])).toEqual([
      [['e2e4', 'e7e5'], true, true, '+0.2'], // the played move's line: its after-score (D5)
      [['d2d4'], false, false, '+0.2'],
    ])
  })

  it("adds the played move's line, with its UCI moves, when it is not among them", () => {
    const by = new Map([
      [0, ma(0, [{ uci: ['d2d4'], san: ['d4'], cp: 30 }], 10)],
      [1, ma(1, [{ uci: ['c7c5', 'g1f3'], san: ['c5', 'Nf3'], cp: -10 }])],
    ])
    const played = storedRows(game, by, 0).find((r) => r.played)!
    expect(played.ucis).toEqual(['e2e4', 'c7c5', 'g1f3'])
    expect(played.sans).toEqual(['e4', 'c5', 'Nf3'])
  })

  it("D5: the line that starts with the played move shows the move's after-score, other lines their own", () => {
    // ply 0 played e4; its line scores +0.3 from the position before, the after-score (ply 1's search) reads +0.4
    const by = new Map([[0, ma(0, [{ uci: ['d2d4'], san: ['d4'], cp: 50 }, { uci: ['e2e4', 'e7e5'], san: ['e4', 'e5'], cp: 30 }], 40)]])
    const rows = storedRows(game, by, 0)
    expect(rows.map((r) => [r.sans[0], r.played, r.eval])).toEqual([
      ['d4', false, '+0.5'],
      ['e4', true, '+0.4'],
    ])
  })

  it("D5: keeps the line's own score when no after-score is stored", () => {
    const m = ma(0, [{ uci: ['e2e4'], san: ['e4'], cp: 30 }])
    ;(m as unknown as { scoreAfterCp: null }).scoreAfterCp = null
    expect(storedRows(game, new Map([[0, m]]), 0)[0].eval).toBe('+0.3')
  })

  it('is empty where nothing is stored', () => {
    expect(storedRows(game, new Map(), 1)).toEqual([])
  })
})

describe('live lines', () => {
  const ev = (fen: string, cp: number | null, mate: number | null = null): FenAnalyzedEvent => ({
    fen,
    bestUci: 'e7e5',
    cp,
    mate,
    lines: [{ cp, mate, uci: ['e7e5'], san: ['e5'] }],
    depth: 18,
  })

  it("turns the side to move's score to White's side", () => {
    expect(liveRows(ev(START, 40))[0].eval).toBe('+0.4')
    expect(liveRows(ev(AFTER_E4, 40))[0].eval).toBe('−0.4')
    expect(liveRows(ev(AFTER_E4, 40))[0]).toMatchObject({ best: true, played: false, ucis: ['e7e5'] })
  })

  it('gives the eval bar a win probability, 1 or 0 for a mate', () => {
    expect(liveWp(ev(START, 0))).toBeCloseTo(0.5)
    expect(liveWp(ev(START, 300))!).toBeGreaterThan(0.7)
    expect(liveWp(ev(AFTER_E4, null, 2))).toBe(0)
    expect(liveWp(ev(START, null, 3))).toBe(1)
    expect(liveWp(null)).toBeNull()
  })
})

describe('positionEnd and sideToMove', () => {
  it('names a finished position, and nothing while moves remain', () => {
    expect(positionEnd('r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4')).toBe('Checkmate.')
    expect(positionEnd('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')).toBe('Stalemate.')
    expect(positionEnd('8/8/8/4k3/8/8/4K3/8 w - - 0 1')).toBe('A draw: neither side can mate.')
    expect(positionEnd(START)).toBeNull()
    expect(positionEnd('not a fen')).toBeNull()
  })

  it('reads the side to move', () => {
    expect(sideToMove(START)).toBe('White')
    expect(sideToMove(AFTER_E4)).toBe('Black')
  })
})

describe('cellRows', () => {
  const cell = (ply: number) => ({ ply, san: `m${ply}`, cls: null, eval: '' })
  it("numbers rows from the FEN's move number, Black's first move on a row of its own", () => {
    const rows = cellRows([cell(0), cell(1), cell(2)], 45) // Black to move at move 23
    expect(rows.map((r) => [r.number, r.white?.ply ?? null, r.black?.ply ?? null])).toEqual([
      [23, null, 0],
      [24, 1, 2],
    ])
  })
})
