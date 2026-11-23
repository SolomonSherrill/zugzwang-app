/** FRIENDS-2's game rules (gamecore.ts), each driven by an explicit clock: P1–P4, C1, the clocks, the endings. */
import { Chess } from 'chess.js'
import { describe, expect, it } from 'vitest'
import * as g from '../src/gamecore'
import type { GameState } from '../src/gamecore'

const W = { id: 1, handle: 'white_p', linked: [], chat: true }
const B = { id: 2, handle: 'black_p', linked: [], chat: true }
const T = { firstMoveMs: 30_000, disconnectMs: 30_000 }
const both = { white: true, black: true }

function fresh(tc: g.TimeControl = '5+3', now = 0): GameState {
  return g.newGame('abcdefghijklmnop', W, B, tc, now, T)
}

/** SAN moves to UCI, through chess.js */
function uci(...sans: string[]): string[] {
  const c = new Chess()
  return sans.map((s) => c.move(s).lan)
}

/** play SAN moves, one second apart from `t0`; returns the time after the last */
function play(s: GameState, sans: string[], t0 = 1000, step = 1000): number {
  let t = t0
  const ucis = uci(...s.sans, ...sans).slice(s.sans.length)
  for (const m of ucis) {
    g.move(s, g.turnOf(s), m, s.moves.length, t)
    t += step
  }
  return t - step
}

describe('time controls (C1)', () => {
  it('are the ten live ones, nothing else', () => {
    expect([...g.TIME_CONTROLS]).toEqual(['1+0', '2+1', '3+0', '3+2', '5+0', '5+3', '10+0', '10+5', '15+10', '30+0'])
    for (const bad of ['0+1', '1+1', '60+0', '5', 'daily', 3]) expect(g.isTimeControl(bad)).toBe(false)
    expect(g.parseTc('15+10')).toEqual({ base: 900_000, inc: 10_000 })
  })
  it('map to the Chess.com mode of ruling R1: bullet, blitz, rapid (30+0 rapid)', () => {
    expect(g.TIME_CONTROLS.map(g.speedOf)).toEqual(['bullet', 'bullet', 'blitz', 'blitz', 'blitz', 'blitz', 'rapid', 'rapid', 'rapid', 'rapid'])
  })
})

describe('the first moves and the abort (P2)', () => {
  it('aborts when White makes no first move within 30 s', () => {
    const s = fresh()
    expect(g.tick(s, 29_999)).toBe(false)
    expect(s.status).toBe('waiting')
    expect(g.tick(s, 30_000)).toBe(true)
    expect(s).toMatchObject({ status: 'over', termination: 'aborted', result: '*', winner: null })
  })
  it('gives Black 30 s from White\'s first move, then aborts', () => {
    const s = fresh()
    g.move(s, 'white', 'e2e4', 0, 20_000)
    expect(s.first_deadline).toBe(50_000)
    g.tick(s, 49_999)
    expect(s.status).toBe('waiting')
    g.tick(s, 50_000)
    expect(s.termination).toBe('aborted')
  })
  it('runs no clock before Black\'s first move, then starts White\'s', () => {
    const s = fresh('5+3')
    g.move(s, 'white', 'e2e4', 0, 10_000)
    g.move(s, 'black', 'e7e5', 1, 25_000)
    expect(s.status).toBe('playing')
    expect(s.clock).toEqual({ white: 300_000, black: 300_000 })
    expect(g.remaining(s, 'white', 35_000)).toBe(290_000)
    expect(g.remaining(s, 'black', 35_000)).toBe(300_000)
  })
  it('a resignation before the clocks run aborts the game', () => {
    const s = fresh()
    g.resign(s, 'white', 1000)
    expect(s.termination).toBe('aborted')
  })
})

describe('the clocks', () => {
  it('deduct the time used and add the increment after each move on a running clock', () => {
    const s = fresh('5+3')
    g.move(s, 'white', 'e2e4', 0, 0)
    g.move(s, 'black', 'e7e5', 1, 1000)
    g.move(s, 'white', 'g1f3', 2, 11_000) // White used 10 s, gains 3
    expect(s.clock.white).toBe(293_000)
    g.move(s, 'black', 'b8c6', 3, 15_000) // Black used 4 s, gains 3
    expect(s.clock.black).toBe(299_000)
  })
  it('flag: the side to move loses on time when its clock reaches zero', () => {
    const s = fresh('1+0')
    g.move(s, 'white', 'e2e4', 0, 0)
    g.move(s, 'black', 'e7e5', 1, 1000)
    expect(g.nextWake(s, both, T)).toBe(61_000)
    expect(g.tick(s, 60_999)).toBe(false)
    expect(g.tick(s, 61_000)).toBe(true)
    expect(s).toMatchObject({ status: 'over', termination: 'timeout', winner: 'black', result: '0-1' })
    expect(s.clock.white).toBe(0)
    expect(s.ended).toBe(61_000)
  })
  it('FLAG_TEST_MS (local end-to-end runs only) shortens a 1+0 game and nothing else', () => {
    expect(g.newGame('abcdefghijklmnop', W, B, '1+0', 0, { ...T, flagTestMs: 3000 }).clock.white).toBe(3000)
    expect(g.newGame('abcdefghijklmnop', W, B, '3+0', 0, { ...T, flagTestMs: 3000 }).clock.white).toBe(180_000)
    expect(g.newGame('abcdefghijklmnop', W, B, '1+0', 0, T).clock.white).toBe(60_000)
  })
  it('a move made after the flag fell is refused: the game is over', () => {
    const s = fresh('1+0')
    g.move(s, 'white', 'e2e4', 0, 0)
    g.move(s, 'black', 'e7e5', 1, 1000)
    expect(() => g.move(s, 'white', 'g1f3', 2, 70_000)).toThrow(/over/)
    expect(s.termination).toBe('timeout')
  })
  it('a side that cannot mate does not win on time: a bare king, or king and one minor piece', () => {
    expect(g.cannotMate('8/8/8/8/8/8/k7/7K w - - 0 1', 'white')).toBe(true)
    expect(g.cannotMate('8/8/8/8/8/8/k7/6NK w - - 0 1', 'white')).toBe(true)
    expect(g.cannotMate('8/8/8/8/8/8/k7/5BBK w - - 0 1', 'white')).toBe(false)
    expect(g.cannotMate('8/8/8/8/8/8/kp6/7K w - - 0 1', 'black')).toBe(false)
    expect(g.cannotMate('8/8/8/8/8/8/k7/7K w - - 0 1', 'black')).toBe(true)
  })
})

describe('moves (legality on the server; no takebacks, P4)', () => {
  it('refuses an illegal move, a move out of turn, a stale ply and a malformed move', () => {
    const s = fresh()
    expect(() => g.move(s, 'white', 'e2e5', 0, 0)).toThrow(g.RuleError)
    expect(() => g.move(s, 'black', 'e7e5', 0, 0)).toThrow(/not your move/)
    expect(() => g.move(s, 'white', 'e2e4', 3, 0)).toThrow(/another position/)
    expect(() => g.move(s, 'white', 'castle', 0, 0)).toThrow(/not a move/)
    expect(s.moves).toEqual([])
  })
  it('promotes as asked', () => {
    const s = fresh()
    play(s, ['a4', 'b5', 'axb5', 'a6', 'bxa6', 'Bb7', 'axb7', 'Nc6'])
    g.move(s, 'white', 'b7a8n', s.moves.length, 20_000)
    expect(s.sans.at(-1)).toBe('bxa8=N')
  })
})

describe('endings decided on the board', () => {
  it('checkmate', () => {
    const s = fresh()
    play(s, ['f3', 'e5', 'g4', 'Qh4#'])
    expect(s).toMatchObject({ status: 'over', termination: 'checkmate', winner: 'black', result: '0-1' })
  })
  it('stalemate', () => {
    const s = fresh('30+0')
    play(s, ['e3', 'a5', 'Qh5', 'Ra6', 'Qxa5', 'h5', 'h4', 'Rah6', 'Qxc7', 'f6', 'Qxd7+', 'Kf7', 'Qxb7', 'Qd3', 'Qxb8', 'Qh7', 'Qxc8', 'Kg6', 'Qe6'])
    expect(s).toMatchObject({ status: 'over', termination: 'stalemate', result: '1/2-1/2', winner: null })
  })
  it('threefold repetition, at once', () => {
    const s = fresh()
    play(s, ['Nf3', 'Nf6', 'Ng1', 'Ng8', 'Nf3', 'Nf6', 'Ng1', 'Ng8'])
    expect(s).toMatchObject({ status: 'over', termination: 'repetition', result: '1/2-1/2' })
  })
  it('the PGN carries the handles, the result, the time control and the termination', () => {
    const s = fresh('3+2', Date.UTC(2026, 10, 22))
    play(s, ['f3', 'e5', 'g4', 'Qh4#'], Date.UTC(2026, 10, 22) + 1000)
    const p = g.pgn(s)
    const tag = (k: string, v: string) => '[' + k + ' "' + v + '"]'
    for (const [k, v] of [['White', W.handle], ['Black', B.handle], ['Result', '0-1'], ['TimeControl', '180+2'], ['Termination', 'checkmate'], ['Date', '2026.11.22'], ['Event', 'Zugzwang friend game']]) {
      expect(p).toContain(tag(k, v))
    }
    expect(p).toContain('1. f3 e5 2. g4 Qh4# 0-1')
  })
})

describe('resign and draws', () => {
  it('resigning gives the game to the other side', () => {
    const s = fresh()
    play(s, ['e4', 'e5'])
    g.resign(s, 'black', 5000)
    expect(s).toMatchObject({ termination: 'resign', winner: 'white', result: '1-0' })
    expect(() => g.resign(s, 'white', 6000)).toThrow(/over/)
  })
  it('a draw can be offered once both have moved, and accepted', () => {
    const s = fresh()
    expect(() => g.offerDraw(s, 'white', 0)).toThrow(g.RuleError)
    play(s, ['e4', 'e5'])
    g.offerDraw(s, 'white', 3000)
    expect(s.draw_offer).toBe('white')
    expect(() => g.offerDraw(s, 'white', 3100)).toThrow(/already/)
    expect(() => g.answerDraw(s, 'white', true, 3200)).toThrow(/no draw offer/)
    g.answerDraw(s, 'black', true, 4000)
    expect(s).toMatchObject({ termination: 'agreed', result: '1/2-1/2' })
  })
  it('offering back accepts the standing offer', () => {
    const s = fresh()
    play(s, ['e4', 'e5'])
    g.offerDraw(s, 'black', 3000)
    g.offerDraw(s, 'white', 3500)
    expect(s.termination).toBe('agreed')
  })
  it('draw-offer spam (decided): after a decline the same player waits 10 plies; a move by the other declines', () => {
    const s = fresh()
    play(s, ['e4', 'e5'])
    g.offerDraw(s, 'white', 3000)
    g.answerDraw(s, 'black', false, 3500)
    expect(s.draw_offer).toBeNull()
    expect(g.canOfferDraw(s, 'white')).toBe(false)
    expect(() => g.offerDraw(s, 'white', 3600)).toThrow(/recently/)
    expect(g.canOfferDraw(s, 'black')).toBe(true)
    play(s, ['Nf3', 'Nc6', 'Bc4', 'Bc5', 'c3', 'Nf6', 'd3', 'd6', 'O-O'], 4000)
    expect(s.moves.length).toBe(11)
    expect(g.canOfferDraw(s, 'white')).toBe(false)
    play(s, ['O-O'], 20_000)
    expect(g.canOfferDraw(s, 'white')).toBe(true)
    // black offers; white answers by moving: declined, and black now waits
    g.offerDraw(s, 'black', 21_000)
    play(s, ['a3'], 22_000)
    expect(s.draw_offer).toBeNull()
    expect(g.canOfferDraw(s, 'black')).toBe(false)
  })
  it('the offerer\'s own move keeps the offer standing', () => {
    const s = fresh()
    play(s, ['e4', 'e5'])
    g.offerDraw(s, 'white', 3000)
    play(s, ['Nf3'], 3500)
    expect(s.draw_offer).toBe('white')
  })
})

describe('a player who leaves (P1)', () => {
  function gone(): GameState {
    const s = fresh('10+0')
    play(s, ['e4', 'e5', 'Nf3'])
    s.gone.black = 100_000
    return s
  }
  it('no claim while the opponent is connected, or before 30 s', () => {
    const s = gone()
    expect(g.claimAt(s, 'white', both, T)).toBeNull()
    const conn = { white: true, black: false }
    expect(g.claimAt(s, 'white', conn, T)).toBe(130_000)
    expect(() => g.claim(s, 'white', true, both, T, 140_000)).toThrow(/still connected/)
    expect(() => g.claim(s, 'white', true, conn, T, 129_999)).toThrow(/Wait/)
    expect(s.status).toBe('playing')
  })
  it('claim the win after 30 s', () => {
    const s = gone()
    g.claim(s, 'white', true, { white: true, black: false }, T, 130_000)
    expect(s).toMatchObject({ termination: 'abandoned', winner: 'white', result: '1-0' })
  })
  it('or call it a draw', () => {
    const s = gone()
    g.claim(s, 'white', false, { white: true, black: false }, T, 131_000)
    expect(s).toMatchObject({ termination: 'abandoned_draw', winner: null, result: '1/2-1/2' })
  })
  it('the one who left cannot claim; nobody can when both are gone, and the clock runs on to a flag (decided)', () => {
    const s = gone()
    s.gone.white = 100_000
    const none = { white: false, black: false }
    expect(g.claimAt(s, 'white', none, T)).toBeNull()
    expect(g.claimAt(s, 'black', none, T)).toBeNull()
    expect(() => g.claim(s, 'black', true, none, T, 200_000)).toThrow(g.RuleError)
    // black to move: its clock runs out, and the game ends on time
    const flag = g.nextWake(s, none, T)!
    g.tick(s, flag)
    expect(s).toMatchObject({ termination: 'timeout', winner: 'white' })
  })
  it('the alarm is set for the earliest of the flag and the claim', () => {
    const s = gone()
    const conn = { white: true, black: false }
    expect(g.nextWake(s, conn, T)).toBe(130_000)
  })
  it('a deleted account resigns its game, or aborts it before the first moves', () => {
    const s = gone()
    g.abandon(s, 'black', 101_000)
    expect(s).toMatchObject({ termination: 'resign', winner: 'white' })
    const t = fresh()
    g.abandon(t, 'white', 10)
    expect(t.termination).toBe('aborted')
  })
})

describe('the CPU a message costs (the Free plan allows 10 ms per invocation)', () => {
  it('a move in a long game stays far under it: no replay of the game', () => {
    const s = fresh('30+0')
    let seed = 7
    const rnd = () => (seed = (seed * 16807) % (2 ** 31 - 1)) / (2 ** 31 - 1)
    const c = new Chess()
    let t = 1000
    while (s.status !== 'over' && s.moves.length < 160) {
      const ms = c.moves({ verbose: true })
      const m = ms[Math.floor(rnd() * ms.length)]
      c.move(m)
      g.move(s, g.turnOf(s), m.lan, s.moves.length, (t += 10))
    }
    expect(s.moves.length).toBeGreaterThan(60)
    if (s.status === 'over') return
    const next = c.moves({ verbose: true })[0].lan
    const times = Array.from({ length: 20 }, () => {
      const copy: GameState = JSON.parse(JSON.stringify(s)) // as after a wake: no board in memory
      const t0 = performance.now()
      g.move(copy, g.turnOf(copy), next, copy.moves.length, t + 20)
      g.canOfferDraw(copy, 'white')
      return performance.now() - t0
    })
    expect(Math.max(...times.slice(1))).toBeLessThan(5)
  })
  it('the stored position matches a replay of the moves', () => {
    const s = fresh()
    play(s, ['e4', 'c5', 'Nf3', 'd6', 'd4', 'cxd4', 'Nxd4', 'Nf6', 'Nc3', 'a6'])
    const c = new Chess()
    for (const m of s.sans) c.move(m)
    expect(s.fen).toBe(c.fen())
  })
})
