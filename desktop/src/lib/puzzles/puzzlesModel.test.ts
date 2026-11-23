import { describe, expect, it } from 'vitest'
import type { PuzzleSessionRow, PuzzleSummary } from '../api'
import {
  canMove, clockText, lookingBack, newLine, nextUci, opponentMoveText, puzzleMoveRows, selectView, shownIndex, shownPly, stepOf, stepView,
  withPly, withSolution, withTry, puzzleThemes, ratingSubLine, rushBest, sessionModeLabel,
  sessionRatingText, sessionSolvedText, shareOfTries, sideOf, signed, tally, themeLabel,
  RATED_THEMES, RATED_THEMES_SHOWN,
  copyLine, doneLine, longDate, mb, progressLine, progressShare, updateLine,
} from './puzzlesModel'

const row = (o: Partial<PuzzleSessionRow>): PuzzleSessionRow => ({
  id: 1, startedAt: '2026-11-20T10:00:00+00:00', mode: 'rated', timeLimit: null, tried: 19, solved: 14,
  score: null, ratingChange: 31, best: false, inferred: false, ...o,
})
const summary = (o: Partial<PuzzleSummary>): PuzzleSummary => ({
  rating: null, tries: 0, solved: 0, rushBest: {}, survivalBest: null, sessions: [], sessionGapMin: 30, ...o,
})
const rating = (o: Record<string, unknown>) =>
  ({ platform: 'Zugzwang', speed: 'puzzles', rating: 1587, change: null, games: 3, lastPlayed: '', newPeak: false, series: [], ...o }) as PuzzleSummary['rating']

describe('themes', () => {
  it('labels Lichess tags in sentence case', () => {
    expect(themeLabel('discoveredAttack')).toBe('Discovered attack')
    expect(themeLabel('backRankMate')).toBe('Back rank mate')
    expect(themeLabel('mateIn2')).toBe('Mate in 2')
    expect(themeLabel('mate')).toBe('Checkmate')
    expect(themeLabel('someNewTag')).toBe('Some new tag')
  })
  it("lists a puzzle's motifs, not its length, size or source; the phase only when nothing else", () => {
    expect(puzzleThemes('crushing fork middlegame short')).toEqual(['Fork'])
    expect(puzzleThemes('advantage endgame long')).toEqual(['Endgame'])
    expect(puzzleThemes('')).toEqual([])
  })
  it('offers the six drawn first, then the rest', () => {
    expect(RATED_THEMES.slice(0, RATED_THEMES_SHOWN)).toEqual(['fork', 'pin', 'skewer', 'discoveredAttack', 'backRankMate', 'mateIn2'])
    expect(new Set(RATED_THEMES).size).toBe(RATED_THEMES.length)
  })
})

describe('the board line', () => {
  it("names the opponent's move with its number", () => {
    expect(opponentMoveText('r1b2rk1/pp3ppp/8/8/8/8/PP3PPP/R4RK1 b - - 0 21', 'e6')).toBe('Black played 21… e6')
    expect(opponentMoveText('8/8/8/8/8/8/8/K6k w - - 3 40', 'Kb2')).toBe('White played 40. Kb2')
  })
  it('reads the side to move', () => {
    expect(sideOf('8/8/8/8/8/8/8/K6k b - - 0 1')).toBe('Black')
    expect(sideOf('8/8/8/8/8/8/8/K6k w - - 0 1')).toBe('White')
  })
})

describe('recent sessions', () => {
  it('names the mode', () => {
    expect(sessionModeLabel(row({}))).toBe('Rated')
    expect(sessionModeLabel(row({ mode: 'theme' }))).toBe('Rated, themes')
    expect(sessionModeLabel(row({ mode: 'rush', timeLimit: 180 }))).toBe('Rush, 3 min')
    expect(sessionModeLabel(row({ mode: 'survival' }))).toBe('Survival')
  })
  it('shows solved of tried for rated, the score for Rush and Survival', () => {
    expect(sessionSolvedText(row({}))).toBe('14 of 19')
    expect(sessionSolvedText(row({ mode: 'rush', score: 22 }))).toBe('22')
  })
  it('shows a rated change in colour, Best for a best score, else nothing', () => {
    expect(sessionRatingText(row({}))).toEqual({ text: '+31', tone: 'win' })
    expect(sessionRatingText(row({ ratingChange: -12 }))).toEqual({ text: '\u221212', tone: 'loss' })
    expect(sessionRatingText(row({ ratingChange: null }))).toBeNull()
    expect(sessionRatingText(row({ mode: 'rush', score: 22, best: true }))).toEqual({ text: 'Best', tone: 'win' })
    expect(sessionRatingText(row({ mode: 'survival', score: 17 }))).toBeNull()
  })
  it('signs zero plainly', () => {
    expect(signed(0)).toEqual({ text: '0', tone: null })
  })
})

describe('stats row', () => {
  it('shows a new peak only when the row says so (the day it was reached)', () => {
    expect(ratingSubLine(summary({ tries: 3, rating: rating({ newPeak: true, change: 12 }) }))).toEqual({ text: '↑ New peak today', tone: 'win' })
    expect(ratingSubLine(summary({ tries: 3, rating: rating({ change: 12 }) }))).toEqual({ text: '+12 in 30 days', tone: 'win' })
    expect(ratingSubLine(summary({ tries: 3, rating: rating({}) }))).toBeNull()
  })
  it('calls the rating the starting one before any try, and says nothing when the window is empty', () => {
    expect(ratingSubLine(summary({}))).toEqual({ text: 'Starting rating', tone: null })
    expect(ratingSubLine(summary({ tries: 5 }))).toBeNull()
  })
  it('gives the share of tries, none without a try', () => {
    expect(shareOfTries(54, 67)).toBe('81% of tries')
    expect(shareOfTries(0, 0)).toBeNull()
  })
  it('reads the Rush best by length', () => {
    const s = summary({ rushBest: { '180': 24 } })
    expect(rushBest(s, 180)).toBe(24)
    expect(rushBest(s, 300)).toBeNull()
  })
})

describe('the session panel', () => {
  const r = (clean: boolean) => ({ id: 'x', rating: 1500, themes: 'fork', clean, change: null })
  it('counts the streak from the end, and solved without a miss', () => {
    expect(tally([r(true), r(false), r(true), r(true)])).toEqual({ streak: 2, solved: 3, tried: 4 })
    expect(tally([r(true), r(false)])).toEqual({ streak: 0, solved: 1, tried: 2 })
    expect(tally([])).toEqual({ streak: 0, solved: 0, tried: 0 })
  })
  it('writes a Rush clock', () => {
    expect(clockText(161)).toBe('2:41')
    expect(clockText(-3)).toBe('0:00')
  })
})

describe('the move list', () => {
  const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  // the user plays Black: the setup move is White's
  const played = () =>
    ['e7e5', 'g1f3', 'b8c6'].reduce((l, u) => withPly(l, u, 'played'), withPly(newLine(START), 'e2e4', 'setup'))

  it('starts with the setup move and keeps a position after each move', () => {
    const l = played()
    expect(l.plies.map((p) => p.san)).toEqual(['e4', 'e5', 'Nf3', 'Nc6'])
    expect(l.plies.map((p) => p.kind)).toEqual(['setup', 'played', 'played', 'played'])
    expect(l.plies[0].fen).toBe('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1')
    expect(l.plies[3].fen).toBe('r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3')
    expect(() => withPly(l, 'e2e4', 'played')).toThrow()
  })

  it('numbers the rows from the puzzle FEN, a Black setup move first', () => {
    const l = withPly(withPly(newLine('r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR b KQkq - 3 3'), 'a7a6', 'setup'), 'f3f7', 'played')
    const rows = puzzleMoveRows(l)
    expect(rows.map((r) => [r.number, r.white?.san ?? null, r.black?.san ?? null])).toEqual([[3, null, 'a6'], [4, 'Qxf7#', null]])
    expect(puzzleMoveRows(played()).map((r) => [r.number, r.white?.san, r.black?.san])).toEqual([[1, 'e4', 'e5'], [2, 'Nf3', 'Nc6']])
  })

  it('keeps a wrong try beside the move it was tried for, struck, never as a position', () => {
    let l = withPly(newLine(START), 'e2e4', 'setup')
    l = withTry(l, 'd7d5')
    expect(l.plies).toHaveLength(1)
    // still to find: a cell with the try and no move
    expect(puzzleMoveRows(l)[0].black).toEqual({ index: 1, san: null, kind: null, tries: ['d5'] })
    l = withTry(l, 'c7c5')
    l = withPly(l, 'e7e5', 'played')
    expect(puzzleMoveRows(l)[0].black).toEqual({ index: 1, san: 'e5', kind: 'played', tries: ['d5', 'c5'] })
    // the setup move is the earliest view: a try is not something to step to
    expect(stepView(l, null, -1)).toBe(0)
    expect(stepView(l, 0, -1)).toBe(0)
  })

  it('steps back and forward, clamped, and returns to play at the end', () => {
    const l = played()
    expect(shownIndex(l, null)).toBe(3)
    expect(stepView(l, null, -1)).toBe(2)
    expect(stepView(l, 2, -1)).toBe(1)
    expect(stepView(l, 1, 1)).toBe(2)
    expect(stepView(l, 2, 1)).toBeNull() // the last move is play again
    expect(stepView(l, null, 1)).toBeNull()
    expect(stepView(l, 2, 'start')).toBe(0)
    expect(stepView(l, 0, 'end')).toBeNull()
    expect(selectView(l, 99)).toBeNull()
    expect(selectView(l, -4)).toBe(0)
    expect(shownPly(l, 1)?.san).toBe('e5')
    expect(shownPly(l, null)?.san).toBe('Nc6')
  })

  it('has nothing to step before the setup move is played', () => {
    const l = newLine(START)
    expect(stepView(l, null, -1)).toBeNull()
    expect(stepView(l, null, 'start')).toBeNull()
    expect(shownPly(l, null)).toBeNull()
    expect(shownIndex(l, null)).toBe(-1)
    expect(puzzleMoveRows(l)).toEqual([])
  })

  it('locks the board while looking back, and only then', () => {
    const l = played()
    expect(lookingBack(l, null)).toBe(false)
    expect(lookingBack(l, 2)).toBe(true)
    expect(canMove('awaiting', l, null)).toBe(true)
    expect(canMove('awaiting', l, 2)).toBe(false)
    expect(canMove('awaiting', l, 0)).toBe(false)
    expect(canMove('animating', l, null)).toBe(false)
    expect(canMove('complete', l, null)).toBe(false)
  })

  it('folds the solution into the same list, with the next move for the arrow', () => {
    let l = withPly(newLine(START), 'e2e4', 'setup')
    l = withSolution(l, ['e7e5', 'g1f3'])
    expect(l.plies.map((p) => [p.san, p.kind])).toEqual([['e4', 'setup'], ['e5', 'solution'], ['Nf3', 'solution']])
    expect(nextUci(l, 0)).toBe('e7e5')
    expect(nextUci(l, null)).toBeNull()
  })

  it('maps the keys: ← → step, Home the setup move, End back to play', () => {
    expect(['ArrowLeft', 'ArrowRight', 'Home', 'End', 'ArrowUp', 'h'].map(stepOf)).toEqual([-1, 1, 'start', 'end', null, null])
  })

  it('is pure: stepping returns a view and leaves the line (and so the rating) alone', () => {
    const l = played()
    const before = JSON.stringify(l)
    let v: number | null = null
    for (const s of [-1, -1, 'start', 1, 'end'] as const) v = stepView(l, v, s)
    expect(JSON.stringify(l)).toBe(before)
    expect(v).toBeNull()
  })
})

describe('the puzzle database lines (FIX-B6 B)', () => {
  it('dates the copy from the file and counts it from the import', () => {
    expect(longDate('2026-11-01T07:57:40+00:00')).toBe('1 November 2026')
    expect(longDate('')).toBeNull()
    expect(copyLine({ count: 5531622, source: 'lichess', sourceDate: '2026-11-01T07:57:40+00:00' }))
      .toBe("5,531,622 puzzles, from Lichess's puzzle database of 1 November 2026.")
    expect(copyLine({ count: 2, source: 'file', sourceDate: '', importedAt: '2026-11-23T08:00:00+00:00' }))
      .toBe('2 puzzles, imported from a file on 23 November 2026.')
    expect(copyLine({ count: 1 })).toBe('1 puzzle.')
  })
  it('shows progress in MB of the file', () => {
    const p = { kind: 'lichess' as const, bytes: 123_400_000, totalBytes: 309_751_173, imported: 2_100_000 }
    expect(mb(309_751_173)).toBe('310 MB')
    expect(progressLine(p, false)).toBe('Downloading from Lichess: 123 MB of 310 MB, 2,100,000 puzzles so far.')
    expect(progressLine({ ...p, kind: 'file' }, false)).toMatch(/^Reading the file: /)
    expect(progressLine(null, false)).toBe('Downloading from Lichess…')
    expect(progressLine(p, true)).toBe('Building the puzzle index…')
    expect(progressShare(p)).toBeCloseTo(0.398, 2)
    expect(progressShare({ ...p, totalBytes: null })).toBeNull()
  })
  it('says what an update changed, removed puzzles included', () => {
    expect(doneLine({ count: 4, added: 4, removed: 0, removedAttempted: 0 })).toBe('4 puzzles imported.')
    expect(doneLine({ count: 5531622, added: 12000, removed: 3000, removedAttempted: 2 }))
      .toBe('Puzzles updated: 12,000 new, 3,000 removed by Lichess (2 you had tried; your results are kept). 5,531,622 in all.')
  })
  it('answers the check', () => {
    expect(updateLine({ date: '2026-12-01T07:00:00+00:00', bytes: 311_000_000, newer: true }))
      .toBe('Lichess has puzzles of 1 December 2026 (311 MB to download).')
    expect(updateLine({ date: '2026-11-01T07:57:40+00:00', bytes: 1, newer: false }))
      .toBe("You have the newest: Lichess's puzzle database of 1 November 2026.")
  })
})
