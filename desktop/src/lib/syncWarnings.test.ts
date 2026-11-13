import { describe, expect, it } from 'vitest'
import { addSyncWarning, syncWarningLines, syncWarningText, type SyncWarning } from './syncWarnings'

const label = (s: string) => (s === 'lichess' ? 'Lichess' : s === 'chesscom' ? 'Chess.com' : '')

describe('sync warnings', () => {
  it("shows the skip for a game whose side can't be told", () => {
    // The shape sidecar/main.py emits for AttributionPending.
    const msg =
      "Skipped Alice vs Bob: This game's side cannot be attributed (no configured handle " +
      'matches either player), and this database has not yet run the attribution migration'
    const list = addSyncWarning([], { source: 'chesscom', message: msg })
    expect(syncWarningLines(list, label)).toEqual([`Chess.com: ${msg}`])
  })

  it('collapses a repeated message into one line with a count', () => {
    let list = addSyncWarning([], { source: 'lichess', message: 'Skipped a game: bad PGN' })
    list = addSyncWarning(list, { source: 'lichess', message: 'Skipped a game: bad PGN' })
    list = addSyncWarning(list, { source: 'chesscom', message: 'Skipped a game: bad PGN' })
    expect(list.map((w) => syncWarningText(w, label))).toEqual([
      'Lichess: Skipped a game: bad PGN (×2)',
      'Chess.com: Skipped a game: bad PGN',
    ])
  })

  it('shows the needs-attention notice', () => {
    const msg = 'Not analysing 1 game(s): the engine crashed on each in 2 separate runs.'
    const list = addSyncWarning([], { source: 'chesscom', message: msg })
    expect(syncWarningText(list[0], label)).toBe(`Chess.com: ${msg}`)
  })

  it('lists at most five lines, then how many more', () => {
    let list: SyncWarning[] = []
    for (let i = 0; i < 8; i++) list = addSyncWarning(list, { source: 'lichess', message: `Skipped game ${i}` })
    list = addSyncWarning(list, { source: 'lichess', message: 'Skipped game 7' })
    const lines = syncWarningLines(list, label)
    expect(lines).toHaveLength(6)
    expect(lines[5]).toBe('… and 4 more warnings')
  })
})
