import { describe, expect, it } from 'vitest'
import type { BookInfo, SyncStatus } from '../api'
import {
  BOOK_SWITCH_LINE,
  DEPTH_LINE,
  attentionLine,
  bookFloor,
  checkLine,
  checksAnswered,
  checksFailed,
  checksStarted,
  bookSize,
  connected,
  engineSource,
  engineTitle,
  finishedText,
  importedLine,
  progressFraction,
  progressText,
  waitingLine,
  whenText,
} from './settingsModel'

const counts = (synced: number, pending: number, needsAttention = 0) => ({
  synced, pending, unanalysed: pending, belowDepth: 0, depth: 14, needsAttention,
})
const status = (cc = counts(3615, 2), li = counts(0, 0)): SyncStatus => ({ syncing: false, chesscom: cc, lichess: li })

describe('the rulings\' words', () => {
  it('keep ruling 17\'s line and the book line verbatim', () => {
    expect(DEPTH_LINE).toBe(
      'Every game is analysed at depth 14, so all your games compare. To look deeper at one game, use Analyse again in its review.',
    )
    expect(BOOK_SWITCH_LINE).toBe('Switching books relabels book moves in your games.')
  })
})

describe('game sync lines', () => {
  it('lists the connected accounts, Chess.com first', () => {
    expect(connected({ lichess: 'alice', chesscom: 'bob' })).toEqual(['chesscom', 'lichess'])
    expect(connected({ lichess: ' ', chesscom: '' })).toEqual([])
  })

  it('counts the games waiting for analysis, naming the one platform that has any', () => {
    expect(waitingLine(status(), ['chesscom'])).toBe('2 games from Chess.com waiting for analysis')
    expect(waitingLine(status(counts(10, 1), counts(5, 0)), ['chesscom', 'lichess'])).toBe(
      '1 game from Chess.com waiting for analysis',
    )
    expect(waitingLine(status(counts(10, 3), counts(5, 1200)), ['chesscom', 'lichess'])).toBe(
      '1,203 games waiting for analysis',
    )
    expect(waitingLine(status(counts(10, 0)), ['chesscom'])).toBe('Every synced game is analysed')
    expect(waitingLine(status(), [])).toBeNull()
  })

  it('counts only the connected accounts\' games', () => {
    expect(waitingLine(status(counts(10, 0), counts(5, 4)), ['chesscom'])).toBe('Every synced game is analysed')
  })

  it('says how many were imported and when this computer last synced', () => {
    const now = new Date(2026, 10, 20, 22, 0)
    expect(importedLine(status(), ['chesscom'], {}, now)).toBe('3,615 imported')
    expect(
      importedLine(status(), ['chesscom'], { chesscom: new Date(2026, 10, 20, 21, 12).toISOString() }, now),
    ).toBe('3,615 imported, last synced today at 21:12')
    expect(
      importedLine(
        status(counts(3615, 0), counts(10, 0)),
        ['chesscom', 'lichess'],
        { chesscom: new Date(2026, 10, 17, 8, 5).toISOString(), lichess: new Date(2026, 10, 19, 9, 3).toISOString() },
        now,
      ),
    ).toBe('3,625 imported, last synced yesterday at 09:03')
    expect(importedLine(status(), [], {}, now)).toBeNull()
  })

  it('words a date in local time', () => {
    const now = new Date(2026, 10, 20, 12, 0)
    expect(whenText(new Date(2026, 10, 18, 21, 12), now)).toBe('on 18 Nov at 21:12')
    expect(whenText(new Date(2025, 0, 2, 7, 5), now)).toBe('on 2 Jan 2025 at 07:05')
  })

  it('names games a sync stopped retrying', () => {
    expect(attentionLine(status(counts(10, 0, 2)), ['chesscom'])).toBe(
      '2 games could not be analysed and are left out; Games lists them.',
    )
    expect(attentionLine(status(), ['chesscom'])).toBeNull()
  })

  it('describes a running sync and its progress', () => {
    expect(progressText(null)).toBe('Syncing: fetching your games…')
    expect(progressText({ phase: 'fetching', source: 'chesscom', done: 0, total: 0 })).toBe(
      'Syncing: fetching your games from Chess.com…',
    )
    expect(progressText({ phase: 'analyzing', source: 'chesscom', done: 37, total: 100 })).toBe(
      'Syncing: analysing Chess.com games at depth 14, 37 of 100.',
    )
    expect(progressFraction({ phase: 'analyzing', done: 37, total: 100 })).toBe(0.37)
    expect(progressFraction({ phase: 'fetching', done: 0, total: 0 })).toBeNull()
  })

  it('sums a finished run', () => {
    expect(finishedText([{ new: 3, analyzed: 3 }, { new: 1, analyzed: 0 }])).toBe('Sync finished: 4 new games, 3 analysed.')
    expect(finishedText([{ new: 1, analyzed: 1 }])).toBe('Sync finished: 1 new game, 1 analysed.')
    expect(finishedText([])).toBe('Sync finished: no new games.')
  })
})

describe('engine row', () => {
  it('names the engine by its own UCI name, else its file', () => {
    expect(engineTitle({ ok: true, path: '/x/stockfish', name: 'Stockfish 18', source: 'bundled' })).toBe('Stockfish 18')
    expect(engineTitle({ ok: true, path: '/x/sf-dev', name: null, source: 'chosen' })).toBe('sf-dev')
    expect(engineTitle({ ok: true, path: 'C:\\sf\\stockfish.exe' })).toBe('stockfish.exe')
  })
  it('says how it was found', () => {
    expect(engineSource({ ok: true, path: '/x', source: 'bundled' })).toBe('Bundled with the app')
    expect(engineSource({ ok: true, path: '/x', source: 'chosen' })).toBe('The binary you chose')
    expect(engineSource({ ok: true, path: '/x', source: 'path' })).toBe('Found on your PATH')
    expect(engineSource({ ok: true, path: '/x' })).toBe('/x')
  })
})

describe('books', () => {
  const b = (minGames: number, bytes: number): BookInfo => ({
    id: 'x', label: 'X', minGames, bytes, sha256: '', url: '', default: false, installed: false, active: false,
  })
  it('state the three hosted sizes as the mockup does', () => {
    expect(bookSize(151_320_480)).toBe('151 MB')
    expect(bookSize(572_067_472)).toBe('572 MB')
    expect(bookSize(1_323_905_200)).toBe('1.32 GB')
  })
  it('state the floor as the book was built: moves played in N or more games', () => {
    expect(bookFloor(b(20, 1))).toBe('moves played in 20+ games')
  })
})

describe('the username check on Save (UI-BUILD-3 G, ruling 5)', () => {
  const found = { status: 'found', message: null } as const
  it('checks each saved name, and an empty one not at all', () => {
    expect(checksStarted({ chesscom: 'alice', lichess: '' })).toEqual({ chesscom: { status: 'checking' }, lichess: null })
    expect(checksStarted({ chesscom: ' ', lichess: 'bob' })).toEqual({ chesscom: null, lichess: { status: 'checking' } })
    expect(checksStarted({ chesscom: '', lichess: '' })).toEqual({ chesscom: null, lichess: null })
  })
  it('lays the reply over what was asked', () => {
    const started = checksStarted({ chesscom: 'alice', lichess: 'bob' })
    expect(checksAnswered(started, { chesscom: found, lichess: { status: 'not_found', message: null } })).toEqual({
      chesscom: found,
      lichess: { status: 'not_found', message: null },
    })
    // a site the reply leaves out was not answered
    expect(checksAnswered(started, { chesscom: found, lichess: null }).lichess).toEqual({ status: 'unreachable', message: 'No answer' })
    // a name not asked about stays unchecked whatever comes back
    expect(checksAnswered(checksStarted({ chesscom: 'alice', lichess: '' }), { chesscom: found, lichess: found }).lichess).toBeNull()
  })
  it('reads a failed check as a site not reached', () => {
    expect(checksFailed(checksStarted({ chesscom: 'alice', lichess: '' }), 'unknown method: check_usernames')).toEqual({
      chesscom: { status: 'unreachable', message: 'unknown method: check_usernames' },
      lichess: null,
    })
  })
  it("says the ruling's words beside each field", () => {
    expect(checkLine('chesscom', 'alice', found)).toEqual({ text: 'Found', tone: 'found', detail: null })
    expect(checkLine('lichess', 'alice', found)?.text).toBe('Found')
    expect(checkLine('chesscom', ' bob ', { status: 'not_found', message: null })).toEqual({
      text: 'No Chess.com player named bob',
      tone: 'missing',
      detail: null,
    })
    expect(checkLine('lichess', 'bob', { status: 'not_found', message: null })?.text).toBe('No Lichess player named bob')
    expect(checkLine('chesscom', 'alice', { status: 'unreachable', message: 'timed out' })).toEqual({
      text: "Couldn't reach Chess.com to check; saved anyway.",
      tone: 'unreachable',
      detail: 'timed out',
    })
    expect(checkLine('lichess', 'alice', { status: 'unreachable', message: 'HTTP 503' })?.text).toBe(
      "Couldn't reach Lichess to check; saved anyway.",
    )
    expect(checkLine('chesscom', 'alice', { status: 'checking' })).toEqual({ text: 'Checking…', tone: 'checking', detail: null })
    expect(checkLine('chesscom', '', null)).toBeNull()
  })
})
