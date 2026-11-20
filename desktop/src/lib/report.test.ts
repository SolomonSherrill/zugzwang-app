import { describe, expect, it } from 'vitest'
import type { MoveAnalysisInfo, ReportFound, ReportMoment } from './api'
import {
  bandChange,
  bookTick,
  canTry,
  judgeOffline,
  verdictText,
  clockText,
  momentClock,
  spentText,
  timeControlText,
  basisText,
  cards,
  graphMarkers,
  leadingGap,
  liveSeries,
  momentsHeading,
  replyHidden,
  reportItems,
  type AnalysedReport,
} from './report'

function moment(ply: number, yours: boolean | null): ReportMoment {
  return {
    ply,
    side: ply % 2 === 0 ? 'white' : 'black',
    yours,
    san: 'x',
    bestSan: 'y',
    label: `${ply}`,
    classification: 'blunder',
    swing: 0.3,
    before: 0.5,
    after: 0.2,
    bandBefore: 'balanced',
    bandAfter: 'worse',
    sentences: [],
    spent: null,
    clockLeft: null,
    bestUci: 'e2e4',
    unique: false,
  }
}

function report(shown: ReportMoment[], groups: number[][], total = shown.length): AnalysedReport {
  return {
    analysed: true,
    basis: {
      depth: 10,
      analysedPlies: 40,
      gamePlies: 40,
      complete: true,
      pov: 'white',
      timeControl: null,
    },
    series: [],
    moments: { total, shown, groups },
    decided: null,
    ending: null,
    fortune: [],
    lowClock: null,
    opening: null,
    slide: null,
    slideGated: null,
    lines: [],
  }
}

describe('momentsHeading', () => {
  it('says how many the cap dropped', () => {
    expect(momentsHeading(7, 3)).toBe('3 of 7 moments')
  })
  it('does not imply a cap when there was none', () => {
    expect(momentsHeading(2, 2)).toBe('2 moments')
    expect(momentsHeading(1, 1)).toBe('1 moment')
  })
  it('has no heading when there is nothing to head', () => {
    expect(momentsHeading(0, 0)).toBeNull()
  })
})

describe('cards and markers', () => {
  const r = report([moment(17, true), moment(18, false), moment(40, false)], [[17, 18], [40]], 5)
  it('puts an error and its unpunished reply on one card', () => {
    expect(cards(r).map((g) => g.map((m) => m.ply))).toEqual([[17, 18], [40]])
  })
  it('marks each card once, after its first move, numbered as the cards are', () => {
    expect(graphMarkers(r)).toEqual([
      { position: 18, n: 1, tone: 'you' },
      { position: 41, n: 2, tone: 'opponent' },
    ])
  })
})

describe('found it (GR2-8)', () => {
  const found: ReportFound = {
    ply: 30,
    kind: 'only_move',
    side: 'white',
    classification: 'great',
    san: 'Kf5',
    label: '16.Kf5',
    sentence: 'Kf5 was the only move that kept the advantage; the next best, c5, was level.',
  }
  const r = { ...report([moment(17, true), moment(18, false), moment(40, false)], [[17, 18], [40]], 5), found }
  it('sits among the cards in game order, unnumbered, the cards keeping their numbers', () => {
    expect(reportItems(r).map((it) => (it.kind === 'card' ? it.n : 'found'))).toEqual([1, 'found', 2])
  })
  it('comes last when it is after every card, and alone when there are none', () => {
    expect(reportItems({ ...r, found: { ...found, ply: 60 } }).map((it) => it.kind)).toEqual([
      'card',
      'card',
      'found',
    ])
    expect(reportItems({ ...report([], []), found }).map((it) => it.kind)).toEqual(['found'])
  })
  it('gets a check-marked graph marker after its move', () => {
    expect(graphMarkers(r)).toContainEqual({ position: 31, n: 0, tone: 'found' })
    expect(graphMarkers(report([moment(17, true)], [[17]])).some((m) => m.tone === 'found')).toBe(false)
  })
})

function ma(ply: number, before: number | null, after: number | null): MoveAnalysisInfo {
  return {
    ply,
    scoreBeforeCp: before,
    scoreBeforeMate: null,
    scoreAfterCp: after,
    scoreAfterMate: null,
  } as MoveAnalysisInfo
}

describe('liveSeries', () => {
  it('leaves unscored positions empty rather than carrying a value forward', () => {
    const s = liveSeries(3, { 0: ma(0, null, null), 1: ma(1, null, null), 2: ma(2, 0, 0) })
    expect(s[0]).toBeNull()
    expect(s[1]).toBeNull()
    expect(s[2]).toBeCloseTo(0.5)
    expect(s[3]).toBeCloseTo(0.5)
  })
  it('falls back to the previous move’s after-search', () => {
    const s = liveSeries(1, { 0: ma(0, null, 300) })
    expect(s[1]!).toBeGreaterThan(0.7)
  })
})

describe('leadingGap', () => {
  it('measures the unscored opening', () => {
    expect(leadingGap([null, null, 0.5, 0.6])).toBe(2)
    expect(leadingGap([0.5, null])).toBe(0)
  })
  it('is not a gap when nothing is scored at all', () => {
    expect(leadingGap([null, null])).toBe(0)
  })
})

describe('text', () => {
  it('shows a band change, or the band when it held', () => {
    expect(bandChange(moment(3, true))).toBe('balanced → worse')
    expect(bandChange({ ...moment(3, true), bandBefore: 'losing', bandAfter: 'losing' })).toBe(
      'losing',
    )
  })
  it('says when the run stops short of the game', () => {
    const r = report([], [])
    expect(basisText(r)).toBe('Depth 10 · 40 half-moves analysed')
    r.basis = { ...r.basis, complete: false, analysedPlies: 14 }
    expect(basisText(r)).toBe('Depth 10 · 14 of 40 half-moves analysed')
  })
})

describe('clock', () => {
  it('formats time spent and time left', () => {
    expect(spentText(2.44)).toBe('2.4 s')
    expect(spentText(12.4)).toBe('12 s')
    expect(spentText(65)).toBe('1:05')
    expect(clockText(221.9)).toBe('3:41')
  })
  it('shows only the clock left when the time spent is unknown', () => {
    expect(momentClock({ ...moment(3, true), spent: 12, clockLeft: 221 })).toBe('12 s · 3:41 left')
    expect(momentClock({ ...moment(3, true), spent: null, clockLeft: 221 })).toBe('3:41 left')
    expect(momentClock(moment(3, true))).toBeNull()
  })
  it('names the time control', () => {
    expect(timeControlText('600')).toBe('10 min')
    expect(timeControlText('180+2')).toBe('3+2')
    expect(timeControlText('15')).toBe('15 s')
    expect(timeControlText('1/86400')).toBeNull()
  })
  it('puts the time control in the basis line', () => {
    const r = report([], [])
    r.basis = { ...r.basis, timeControl: '180+2' }
    expect(basisText(r)).toBe('Depth 10 · 40 half-moves analysed · 3+2, clock times from the game')
  })
})

describe('bookTick', () => {
  it('says "out of book" only where someone left it', () => {
    expect(bookTick({ case: 'deviated', ply: 9 })).toEqual({ position: 9, label: 'out of book' })
    expect(bookTick({ case: 'no_book_move', ply: 9 })).toEqual({ position: 9, label: 'book ends' })
    expect(bookTick({ case: 'book_ended', ply: 20 })).toEqual({ position: 20, label: 'book ends' })
  })
  it('has no tick when every move was book, or there is no line', () => {
    expect(bookTick({ case: 'all_book', ply: null })).toBeNull()
    expect(bookTick(null)).toBeNull()
  })
})

describe('Try', () => {
  const mine = { ...moment(3, true), bestUci: 'e2e4', bestSan: 'e4', unique: true }
  it('is offered on the user’s moments; with no engine only on unique answers', () => {
    expect(canTry(mine, true)).toBe(true)
    expect(canTry({ ...mine, unique: false }, true)).toBe(true)
    expect(canTry({ ...mine, unique: false }, false)).toBe(false)
    expect(canTry(mine, false)).toBe(true)
    expect(canTry({ ...mine, yours: false }, true)).toBe(false)
  })
  it('with no engine, accepts the stored answer and never calls another move wrong', () => {
    expect(judgeOffline(mine, 'e2e4', 'e4').kind).toBe('good')
    const other = judgeOffline(mine, 'd2d4', 'd4')
    expect(other.kind).toBe('unjudged')
    expect(verdictText(other)).not.toMatch(/wrong|mistake|bad|gives up/)
  })
  it('says how much a rejected move gives up, in points', () => {
    expect(verdictText({ kind: 'not-it', san: 'a3', bestSan: 'e4', loss: 0.123 })).toBe(
      "a3 gives up about 12 points; the engine's move is e4.",
    )
  })
})

describe('replyHidden', () => {
  const theirs = { ...moment(4, false), reply: "You played 3…Nxe5; the engine's move was 3…Qh4+." }
  it('hides the reply while the next move is being tried and not yet judged', () => {
    expect(replyHidden(theirs, 5, null)).toBe(true)
    expect(replyHidden(theirs, 5, { kind: 'judging' })).toBe(true)
  })
  it('shows it otherwise', () => {
    expect(replyHidden(theirs, null, null)).toBe(false)
    expect(replyHidden(theirs, 4, null)).toBe(false)
    expect(replyHidden(theirs, 5, { kind: 'good', san: 'Qh4+', bestSan: 'Qh4+', exact: true })).toBe(false)
  })
})
