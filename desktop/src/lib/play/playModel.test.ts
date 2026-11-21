import { describe, expect, it } from 'vitest'
import { CLOCK_REFUSED, userMoveParams, userMoveSender, type MoveResult, type SidecarStatus } from '../api'
import {
  PLAY_TIME_CONTROLS, TC_GROUPS, TIME_CONTROL_DEFAULT, clockAfterMove, clockText, engineClockAfter, crumbTitle, engineStrip, moveRows,
  openingSub, readPrefs, resultSentence, speedOf, tcLabel, tcPgn, writePrefs, youStrip,
} from './playModel'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

describe('time controls', () => {
  it('are the ten of ruling 15, grouped by speed in order', () => {
    expect(TC_GROUPS.map((g) => [g.label, g.indexes.map((i) => tcLabel(PLAY_TIME_CONTROLS[i]))])).toEqual([
      ['Bullet', ['1+0', '2+1']],
      ['Blitz', ['3+0', '3+2', '5+0', '5+3']],
      ['Rapid', ['10+0', '10+5', '15+10']],
      ['Classical', ['30+0']],
    ])
    expect(PLAY_TIME_CONTROLS).toHaveLength(10)
  })
  it('group as the database files a game (base + 40 x increment)', () => {
    expect(speedOf({ initialS: 120, incrementS: 1 })).toBe('bullet') // 160
    expect(speedOf({ initialS: 180, incrementS: 0 })).toBe('blitz') // 180
    expect(speedOf({ initialS: 300, incrementS: 3 })).toBe('blitz') // 420
    expect(speedOf({ initialS: 600, incrementS: 0 })).toBe('rapid')
    expect(speedOf({ initialS: 900, incrementS: 10 })).toBe('rapid') // 1300
    expect(speedOf({ initialS: 1800, incrementS: 0 })).toBe('classical')
  })
  it('default to 10+0 and write the PGN header in seconds', () => {
    expect(tcLabel(PLAY_TIME_CONTROLS[TIME_CONTROL_DEFAULT])).toBe('10+0')
    expect(tcPgn(PLAY_TIME_CONTROLS[TIME_CONTROL_DEFAULT])).toBe('600+0')
    expect(tcPgn({ initialS: 180, incrementS: 2 })).toBe('180+2')
  })
})

describe('labels', () => {
  it('name the engine as ruled', () => {
    expect(engineStrip(10)).toEqual({ name: 'Stockfish', rating: 'Level 10' })
    expect(engineStrip(0).rating).toBe('Level 0')
    expect(crumbTitle(20)).toBe('Stockfish, level 20')
  })
  it('name the user from Settings, else "You"', () => {
    expect(youStrip({ chesscom: 'alice', lichess: 'bob' })).toEqual({ name: 'alice', you: true })
    expect(youStrip({ chesscom: ' ', lichess: 'bob' })).toEqual({ name: 'bob', you: true })
    expect(youStrip({ chesscom: '', lichess: '' })).toEqual({ name: 'You', you: false })
  })
  it('say "casual" with the ECO once there is one', () => {
    expect(openingSub('B90')).toBe('B90, casual')
    expect(openingSub(null)).toBe('casual')
  })
})

describe('clock text', () => {
  it('reads m:ss, tenths under ten seconds, hours past one', () => {
    expect(clockText(600_000)).toBe('10:00')
    expect(clockText(552_400)).toBe('9:12')
    expect(clockText(10_000)).toBe('0:10')
    expect(clockText(9_950)).toBe('0:09.9')
    expect(clockText(400)).toBe('0:00.4')
    expect(clockText(-5)).toBe('0:00.0')
    expect(clockText(3_725_000)).toBe('1:02:05')
  })
})

describe('move list rows', () => {
  it('pair White and Black from the start', () => {
    expect(moveRows(['e4', 'c5', 'Nf3'], START)).toEqual([
      { number: 1, white: { san: 'e4', ply: 0 }, black: { san: 'c5', ply: 1 } },
      { number: 2, white: { san: 'Nf3', ply: 2 }, black: null },
    ])
    expect(moveRows([], START)).toEqual([])
  })
  it('start with Black from a set position', () => {
    const fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 7'
    expect(moveRows(['c5', 'Nf3'], fen)).toEqual([
      { number: 7, white: null, black: { san: 'c5', ply: 0 } },
      { number: 8, white: { san: 'Nf3', ply: 1 }, black: null },
    ])
  })
})

describe('result sentence', () => {
  it('speaks in the player\'s terms', () => {
    expect(resultSentence({ result: '1-0', termination: 'checkmate' }, 'white')).toBe('You won by checkmate.')
    expect(resultSentence({ result: '1-0', termination: 'checkmate' }, 'black')).toBe('Stockfish won by checkmate.')
    expect(resultSentence({ result: '0-1', termination: 'resignation' }, 'white')).toBe('You resigned.')
    expect(resultSentence({ result: '0-1', termination: 'timeout' }, 'black')).toBe('You won on time.')
    expect(resultSentence({ result: '0-1', termination: 'timeout' }, 'white')).toBe('You lost on time.')
    expect(resultSentence({ result: '1/2-1/2', termination: 'draw_agreed' }, 'white')).toBe('Draw agreed.')
    expect(resultSentence({ result: '1/2-1/2', termination: 'threefold_repetition' }, 'white')).toBe('Draw by threefold repetition.')
    expect(resultSentence({ result: '*', termination: 'abandoned' }, 'white')).toBe('Game abandoned.')
  })
})

describe('preferences', () => {
  it('read the old screen\'s saved choice and fall back on anything odd', () => {
    expect(readPrefs(JSON.stringify({ color: 'black', skill: 3, tc: 2, hideSidebar: true }))).toEqual({ color: 'black', level: 3, tc: 2 })
    expect(readPrefs(null)).toEqual({ color: 'white', level: 10, tc: TIME_CONTROL_DEFAULT })
    expect(readPrefs('not json')).toEqual({ color: 'white', level: 10, tc: TIME_CONTROL_DEFAULT })
    expect(readPrefs(JSON.stringify({ skill: 25, tc: 99 }))).toEqual({ color: 'white', level: 10, tc: TIME_CONTROL_DEFAULT })
  })
  it('round-trip', () => {
    const p = { color: 'black' as const, level: 0, tc: 9 }
    expect(readPrefs(writePrefs(p))).toEqual(p)
  })
})

describe('the clock saved with each move (UI-BUILD-3 F, ruling 9)', () => {
  it('is the time left when the move was made plus the increment, in whole ms', () => {
    expect(clockAfterMove(178_812.6, 2000)).toBe(180_813)
    expect(clockAfterMove(9_040, 0)).toBe(9_040)
    expect(clockAfterMove(-30, 1000)).toBe(1000) // a clock never goes below zero
  })
  it('goes to user_move as clock_ms, and is left out when there is none', () => {
    expect(userMoveParams('e2e4', 180_813)).toEqual({ uci: 'e2e4', clock_ms: 180_813 })
    expect(userMoveParams('e7e8q', 0)).toEqual({ uci: 'e7e8q', clock_ms: 0 })
    expect(userMoveParams('e2e4', 12.6)).toEqual({ uci: 'e2e4', clock_ms: 13 })
    expect(userMoveParams('e2e4')).toEqual({ uci: 'e2e4' })
    expect(userMoveParams('e2e4', null)).toEqual({ uci: 'e2e4' })
    expect(userMoveParams('e2e4', Number.NaN)).toEqual({ uci: 'e2e4' })
    expect(userMoveParams('e2e4', -5)).toEqual({ uci: 'e2e4' })
  })
  it("shows the engine's clock as the sidecar measured it, else the screen's own", () => {
    expect(engineClockAfter(178_800, 178_650)).toBe(178_800)
    expect(engineClockAfter(null, 178_650)).toBe(178_650)
    expect(engineClockAfter(undefined, 178_650)).toBe(178_650)
    expect(engineClockAfter('1', 5)).toBe(5)
  })
})

describe('user_move against a sidecar older than the clocks (UI-BUILD-3 F)', () => {
  // the old dispatch's reply, verbatim (measured on 42bfa69)
  const OLD = "Server.rpc_user_move() got an unexpected keyword argument 'clock_ms'"
  const OK: MoveResult = { ok: true, san: 'e4', fen: 'x', end: null }
  function harness(old: () => boolean) {
    const sent: { uci: string; clock_ms?: number }[] = []
    let status: ((s: SidecarStatus) => void) | null = null
    const send = userMoveSender(
      async (p) => {
        sent.push(p)
        if ('clock_ms' in p && old()) throw new Error(OLD)
        return OK
      },
      (fn) => {
        status = fn
        fn('up')
      },
    )
    return { sent, send, status: (s: SidecarStatus) => status!(s) }
  }
  it('matches only the old TypeError', () => {
    expect(CLOCK_REFUSED.test(OLD)).toBe(true)
    expect(CLOCK_REFUSED.test("Server.rpc_user_move() got an unexpected keyword argument 'uci'")).toBe(false)
    expect(CLOCK_REFUSED.test('no active game')).toBe(false)
  })
  it('sends the clock to a sidecar that takes it', async () => {
    const h = harness(() => false)
    expect(await h.send('e2e4', 180_000)).toEqual(OK)
    expect(h.sent).toEqual([{ uci: 'e2e4', clock_ms: 180_000 }])
  })
  it('resends once without the clock, then sends none until the sidecar restarts', async () => {
    let old = true
    const h = harness(() => old)
    expect(await h.send('e2e4', 180_000)).toEqual(OK)
    expect(await h.send('g1f3', 178_000)).toEqual(OK)
    expect(h.sent).toEqual([{ uci: 'e2e4', clock_ms: 180_000 }, { uci: 'e2e4' }, { uci: 'g1f3' }])
    // a respawn may bring a newer sidecar: ask with the clock again
    old = false
    h.status('restarting')
    h.status('up')
    await h.send('d2d4', 170_000)
    expect(h.sent.at(-1)).toEqual({ uci: 'd2d4', clock_ms: 170_000 })
  })
  it('passes any other error on, and never resends a move that carried no clock', async () => {
    const errs = userMoveSender(
      async () => {
        throw new Error('no active game')
      },
      () => {},
    )
    await expect(errs('e2e4', 1000)).rejects.toThrow('no active game')
    let calls = 0
    const noClock = userMoveSender(
      async () => {
        calls++
        throw new Error(OLD)
      },
      () => {},
    )
    await expect(noClock('e2e4')).rejects.toThrow(OLD)
    expect(calls).toBe(1)
  })
})
