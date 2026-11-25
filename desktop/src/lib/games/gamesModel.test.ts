import { describe, expect, it } from 'vitest'
import type { GamesItem, GamesMonth } from '../api'
import {
  appendPage,
  shortOpening,
  countPgnGames,
  countText,
  dateRange,
  dateText,
  defaultFilters,
  filtersActive,
  importLabel,
  monthLabel,
  moreFiltersSet,
  opponentCell,
  pageParams,
  playerLines,
  analysisNote,
  recordText,
  resultCell,
  step,
  syncedText,
  timeText,
  toggleSpeed,
  userAccuracy,
  opponentAccuracy,
  withMonths,
} from './gamesModel'

function game(over: Partial<GamesItem> = {}): GamesItem {
  return {
    id: 1, playedAt: '2026-11-19T10:00:00Z', playerColor: 'black', skillLevel: 0, ladderVersion: 1,
    result: '0-1', termination: 'resignation', moveCount: 40, openingEco: 'B01', openingName: 'Scandinavian Defense',
    source: 'chesscom', externalId: '100', speed: 'blitz', rated: true, white: 'bob', black: 'alice',
    whiteElo: 1438, blackElo: 1500, whiteAccuracy: 82.2, blackAccuracy: 90.7, analyzed: true,
    speedBucket: 'blitz', timeControl: '180+2', outcome: 'win',
    ...over,
  }
}

describe('filters', () => {
  it('sends only what is set, and the date as instants', () => {
    const now = new Date('2026-11-20T12:00:00Z')
    expect(pageParams(defaultFilters(), 0, 50, now)).toEqual({ sort: 'recent', offset: 0, limit: 50 })
    const f = { ...defaultFilters(), result: 'win' as const, speeds: ['blitz' as const, 'daily' as const], search: ' 483 ', date: 'week' as const }
    expect(pageParams(f, 50, 50, now)).toEqual({
      sort: 'recent', offset: 50, limit: 50, result: 'win', speeds: ['blitz', 'daily'], search: '483',
      since: '2026-11-13T12:00:00.000Z',
    })
  })
  it('a custom range is whole local days, both ends kept', () => {
    const r = dateRange({ date: 'custom', customFrom: '2026-11-01', customTo: '2026-11-03' })
    expect(r.since).toBe(new Date(2026, 10, 1).toISOString())
    expect(r.until).toBe(new Date(2026, 10, 4).toISOString())
    expect(dateRange({ date: 'custom', customFrom: '', customTo: '' })).toEqual({})
    expect(dateRange({ date: 'all', customFrom: '2026-11-01', customTo: '' })).toEqual({})
  })
  it('knows when a filter is set; the sort is not one', () => {
    expect(filtersActive(defaultFilters())).toBe(false)
    expect(filtersActive({ ...defaultFilters(), sort: 'opening' })).toBe(false)
    expect(filtersActive({ ...defaultFilters(), speeds: ['rapid'] })).toBe(true)
    expect(moreFiltersSet({ ...defaultFilters(), source: 'local', opening: 'b01' })).toBe(2)
  })
  it('speeds toggle on and off', () => {
    expect(toggleSpeed([], 'blitz')).toEqual(['blitz'])
    expect(toggleSpeed(['blitz', 'rapid'], 'blitz')).toEqual(['rapid'])
  })
})

describe('month headers', () => {
  const nov: GamesMonth = { month: '2026-11', games: 24, won: 14, lost: 9, drawn: 1 }
  const oct: GamesMonth = { month: '2026-10', games: 110, won: 61, lost: 44, drawn: 5 }
  it('words', () => {
    expect(monthLabel('2026-11')).toBe('November 2026')
    expect(recordText(nov)).toBe('14 won, 9 lost, 1 drawn')
    expect(recordText({ won: 0, lost: 2, drawn: 0 })).toBe('0 won, 2 lost, 0 drawn')
  })
  it('a header before each month\'s first loaded game, from the sidecar\'s record of the whole month', () => {
    const local = (y: number, m: number, d: number) => new Date(y, m - 1, d, 12).toISOString()
    const gs = [game({ id: 1, playedAt: local(2026, 11, 19) }), game({ id: 2, playedAt: local(2026, 11, 2) }), game({ id: 3, playedAt: local(2026, 10, 31) })]
    const list = withMonths(gs, [nov, oct], 'recent')
    expect(list.map((e) => (e.kind === 'month' ? e.month.month : e.game.id))).toEqual(['2026-11', 1, 2, '2026-10', 3])
    expect(withMonths(gs, [nov, oct], 'accuracy_low').every((e) => e.kind === 'game')).toBe(true)
  })
})

describe('rows', () => {
  it('result from the user\'s side; unknown sides and unfinished games show the score', () => {
    expect(resultCell(game())).toEqual({ word: 'Won', tone: 'win' })
    expect(resultCell(game({ outcome: null, result: '*' }))).toEqual({ word: 'Unfinished', tone: null })
    expect(resultCell(game({ outcome: null, result: '1-0' }))).toEqual({ word: '1–0', tone: null })
    expect(resultCell(game({ outcome: null, result: '1/2-1/2' }))).toEqual({ word: 'Drawn', tone: 'draw' })
  })
  it('the opponent with a rating, or Stockfish with its level', () => {
    expect(opponentCell(game())).toEqual({ name: 'bob', detail: '1438' })
    expect(opponentCell(game({ playerColor: 'white' }))).toEqual({ name: 'alice', detail: '1500' })
    expect(opponentCell(game({ source: 'local', skillLevel: 10 }))).toEqual({ name: 'Stockfish', detail: 'Level 10' })
    expect(opponentCell(game({ source: 'local', skillLevel: 10, ladderVersion: null })).detail).toBe('Level 10, old scale')
    expect(opponentCell(game({ white: null, whiteElo: null }))).toEqual({ name: 'Unknown', detail: null })
  })
  it('accuracies are the user\'s and the opponent\'s, none unanalysed', () => {
    expect([userAccuracy(game()), opponentAccuracy(game())]).toEqual([90.7, 82.2])
    expect(userAccuracy(game({ analyzed: false }))).toBeNull()
    expect(userAccuracy(game({ playerColor: null }))).toBeNull()
  })
  it('time and date', () => {
    expect(timeText('180+2')).toBe('3+2')
    expect(timeText('1/86400')).toBe('Daily')
    expect(timeText(null)).toBe('—')
    const now = new Date(2026, 10, 20, 15)
    expect(dateText(new Date(2026, 10, 20, 1).toISOString(), now)).toBe('Today')
    expect(dateText(new Date(2026, 10, 19, 23).toISOString(), now)).toBe('Yesterday')
    expect(dateText(new Date(2026, 10, 4, 9).toISOString(), now)).toBe('4 Nov')
    expect(dateText(new Date(2025, 10, 4, 9).toISOString(), now)).toBe('4 Nov 2025')
  })
  it('the count says what the filters keep of all', () => {
    expect(countText(3620, 3620, false)).toBe('3,620 games')
    expect(countText(212, 3620, true)).toBe('212 of 3,620 games')
    expect(countText(1, 1, true)).toBe('1 game')
  })
})

describe('stacked rows (UI-BUILD-4 B)', () => {
  it('White on top, Black below, each with a colour square', () => {
    const [top, bottom] = playerLines(game())
    expect([top.color, top.name, bottom.color, bottom.name]).toEqual(['white', 'bob', 'black', 'alice'])
    // the user as White: still White on top
    const [w, b] = playerLines(game({ playerColor: 'white', white: 'alice', black: 'bob' }))
    expect([w.name, w.you, b.name, b.you]).toEqual(['alice', true, 'bob', false])
  })
  it("the opponent's name bright, yours dimmer", () => {
    const [w, b] = playerLines(game())
    expect([w.you, w.nameTone]).toEqual([false, 'bright'])
    expect([b.you, b.nameTone]).toEqual([true, 'dim'])
  })
  it("each player's accuracy on that player's line, yours bright, theirs dim", () => {
    const [w, b] = playerLines(game())
    expect([w.accuracy, w.accTone]).toEqual(['82.2', 'dim'])
    expect([b.accuracy, b.accTone]).toEqual(['90.7', 'bright'])
    const [w2, b2] = playerLines(game({ playerColor: 'white', whiteAccuracy: 61, blackAccuracy: 88.25 }))
    expect([w2.accuracy, w2.accTone, b2.accuracy, b2.accTone]).toEqual(['61.0', 'bright', '88.3', 'dim'])
  })
  it('the rating in brackets; no rating, no brackets', () => {
    const [w, b] = playerLines(game())
    expect([w.detail, b.detail]).toEqual(['(1438)', '(1500)'])
    const [w2, b2] = playerLines(game({ whiteElo: null, blackElo: null }))
    expect([w2.detail, b2.detail]).toEqual([null, null])
    expect(playerLines(game({ white: null }))[0].name).toBe('Unknown')
  })
  it('an engine game: Stockfish (Level N) on its line, the user as stored', () => {
    const local = { source: 'local' as const, playerColor: 'white' as const, white: 'You', black: 'Stockfish', whiteElo: null, blackElo: null, skillLevel: 10 }
    const [w, b] = playerLines(game(local))
    expect([w.name, w.detail, w.nameTone]).toEqual(['You', null, 'dim'])
    expect([b.name, b.detail, b.nameTone]).toEqual(['Stockfish', '(Level 10)', 'bright'])
    expect(playerLines(game({ ...local, ladderVersion: null }))[1].detail).toBe('(Level 10, old scale)')
    // the user as Black against the engine
    const [w3, b3] = playerLines(game({ ...local, playerColor: 'black', white: 'Stockfish', black: 'You' }))
    expect([w3.name, w3.detail, b3.name, b3.you]).toEqual(['Stockfish', '(Level 10)', 'You', true])
  })
  it('an unanalysed game: both accuracies "—", off; "Not analysed" with Analyse under its opening', () => {
    const g = game({ analyzed: false, whiteAccuracy: null, blackAccuracy: null })
    expect(playerLines(g).map((l) => [l.accuracy, l.accTone])).toEqual([['—', 'off'], ['—', 'off']])
    // a stored figure is not shown for a game with no complete run
    expect(playerLines(game({ analyzed: false })).map((l) => l.accuracy)).toEqual(['—', '—'])
    expect(analysisNote(g, null, [], undefined)).toEqual({ text: 'Not analysed', canAnalyse: true })
    expect(analysisNote(g, null, [], 'engine died')).toEqual({ text: 'Analysis stopped', canAnalyse: true })
    expect(analysisNote(g, { id: g.id, done: 0, total: 0 }, [], undefined)).toEqual({ text: 'Analysing…', canAnalyse: false })
    expect(analysisNote(g, { id: g.id, done: 37, total: 90 }, [], undefined)?.text).toBe('Analysing 37 of 90')
    // COACH-2 D (ruling CB1): a game being analysed from anywhere says so on its row, a re-analysis as one
    const bg = { gameId: g.id, depth: 24, done: 38, total: 90 }
    expect(analysisNote({ ...g, analyzed: true }, null, [], undefined, bg)).toEqual({ text: 'Re-analysing at depth 24: 38 of 90', canAnalyse: false })
    expect(analysisNote({ ...g, analyzed: false }, null, [], undefined, { ...bg, done: 0, total: 0 })?.text).toBe('Analysing at depth 24…')
    expect(analysisNote({ ...g, analyzed: true }, null, [], undefined, { ...bg, gameId: g.id + 1 })).toBeNull()
    expect(analysisNote(g, { id: 99, done: 1, total: 9 }, [g.id], undefined)).toEqual({ text: 'Waiting to analyse', canAnalyse: false })
    expect(analysisNote(game(), null, [], undefined)).toBeNull()
  })
  it('a side the app does not know: no "yours", both names bright, both accuracies dim', () => {
    const lines = playerLines(game({ playerColor: null }))
    expect(lines.map((l) => [l.you, l.nameTone, l.accTone])).toEqual([[false, 'bright', 'dim'], [false, 'bright', 'dim']])
  })
})

describe('keys', () => {
  it('J and K step and stop at the ends', () => {
    expect(step(-1, 1, 5)).toBe(0)
    expect(step(0, -1, 5)).toBe(0)
    expect(step(3, 1, 5)).toBe(4)
    expect(step(4, 1, 5)).toBe(4)
    expect(step(0, 1, 0)).toBe(-1)
  })
})

describe('header', () => {
  it('the latest recorded sync of a connected account', () => {
    const now = new Date(2026, 10, 20, 22, 0)
    const at = new Date(2026, 10, 20, 21, 12).toISOString()
    const before = new Date(2026, 10, 18, 9, 3).toISOString()
    expect(syncedText({ chesscom: at, lichess: before }, ['chesscom', 'lichess'], now)).toBe('Synced today at 21:12')
    expect(syncedText({ chesscom: at, lichess: before }, ['lichess'], now)).toBe('Synced on 18 Nov at 09:03')
    expect(syncedText({ chesscom: null }, ['chesscom'], now)).toBeNull()
  })
})

describe('Import PGN', () => {
  it('counts the games pasted, live', () => {
    expect(countPgnGames('')).toBe(0)
    expect(countPgnGames('[Event "a"]\n[White "alice"]\n\n1. e4 e5 1-0\n')).toBe(1)
    expect(countPgnGames('[Event "a"]\n\n1. e4 *\n\n[Event "b"]\n[Site "x"]\n\n1. d4 *\n')).toBe(2)
    expect(countPgnGames('1. e4 e5 2. Nf3')).toBe(1)
    expect(countPgnGames('hello there')).toBe(0)
    expect(importLabel(0)).toBe('Import')
    expect(importLabel(1)).toBe('Import 1 game')
    expect(importLabel(1200)).toBe('Import 1,200 games')
  })
})

describe('opening names (as drawn)', () => {
  it('shortens a family with a variation', () => {
    expect(shortOpening('Italian Game: Two Knights Defense')).toBe('Italian, Two Knights')
    expect(shortOpening('Scandinavian Defense: Valencian Variation')).toBe('Scandinavian, Valencian')
    expect(shortOpening('Sicilian Defense: Alapin Variation')).toBe('Sicilian, Alapin')
    expect(shortOpening('Ruy Lopez: Berlin Defense')).toBe('Ruy Lopez, Berlin')
    expect(shortOpening('Queen\'s Gambit Declined: Queen\'s Knight Variation')).toBe('Queen\'s Gambit Declined, Queen\'s Knight')
    expect(shortOpening('Slav Defense: Quiet Variation, Pin Defense')).toBe('Slav, Quiet, Pin')
  })
  it('leaves a bare family whole', () => {
    expect(shortOpening("Queen's Pawn Game")).toBe("Queen's Pawn Game")
    expect(shortOpening('Petrov\'s Defense')).toBe("Petrov's Defense")
    expect(shortOpening(null)).toBe('Unknown opening')
  })
})

describe('FRIENDS-2: a friend game\'s ratings at its start (R1-R3)', () => {
  it('shows the PGN rating first, else the start rating, ≈ for an estimate, nothing when unknown', async () => {
    const { ratingOf } = await import('./gamesModel')
    expect(ratingOf({ whiteElo: 1500, blackElo: null, startRatings: null }, 'white')).toBe('1500')
    const sr = { white: { rating: 1446, estimated: false }, black: { rating: 1390, estimated: true } }
    expect(ratingOf({ whiteElo: null, blackElo: null, startRatings: sr }, 'white')).toBe('1446')
    expect(ratingOf({ whiteElo: null, blackElo: null, startRatings: sr }, 'black')).toBe('≈1390')
    expect(ratingOf({ whiteElo: null, blackElo: null, startRatings: { white: null, black: null } }, 'black')).toBeNull()
    expect(ratingOf({ whiteElo: null, blackElo: null }, 'black')).toBeNull()
  })
})

describe('appendPage (FIX-B7)', () => {
  it('drops a game the list already holds: a game synced between pages shifts the next page by one', () => {
    const shown = [{ id: 9 }, { id: 8 }, { id: 7 }]
    expect(appendPage(shown, [{ id: 7 }, { id: 6 }, { id: 5 }]).map((g) => g.id)).toEqual([9, 8, 7, 6, 5])
  })
  it('appends a page with nothing in common as it is', () => {
    expect(appendPage([{ id: 2 }], [{ id: 1 }]).map((g) => g.id)).toEqual([2, 1])
  })
})
