import { describe, expect, it } from 'vitest'
import { claimIn, clockText, footerState, mmss, overLines, ratingText, ratingsLine, speedWord } from './liveModel'
import type { GameState } from './friendsApi'

function st(over: Partial<GameState> = {}): GameState {
  return {
    t: 'state', id: 'g'.repeat(16), you: 'white', tc: '10+0', speed: 'rapid', created: 0, ended: null,
    white: { handle: 'you_demo', linked: [] }, black: { handle: 'maxk', linked: [] }, moves: [], sans: [],
    fen: '', turn: 'white', status: 'playing', result: null, termination: null, termination_text: null, winner: null,
    clock: { white: 600_000, black: 600_000 }, running: 'white', server_time: 1000, first_deadline: null, draw_offer: null,
    can_offer_draw: true, claim_at: null, opponent: { connected: true, gone_since: null, chat_on: true }, chat_on: true,
    chat_blocked: false, muted: false, rematch_from: null, acked: false, pgn: null, ...over,
  }
}

describe('FRIENDS-2 screens, pure parts', () => {
  it('ratings: the Chess.com figure, ≈ for an estimate, blank when unknown (R1-R3)', () => {
    expect(ratingText({ rating: 1446, estimated: false })).toBe('1446')
    expect(ratingText({ rating: 1390, estimated: true })).toBe('≈1390')
    expect(ratingText({ rating: null, estimated: false })).toBeNull()
    expect(ratingText(null)).toBeNull()
    expect(ratingsLine({ rating: 1438, estimated: false }, { rating: 1446, estimated: false }, 'maxk', '5+0')).toBe(
      'Ratings shown in the game: you 1438, maxk 1446 (Chess.com blitz).',
    )
    expect(ratingsLine(null, { rating: 1390, estimated: true }, 'benji', '3+2')).toBe(
      'Ratings shown in the game: you —, benji ≈1390 (Chess.com blitz, ≈ from Lichess).',
    )
  })
  it('speed words follow R1 for the ten time controls', () => {
    expect(['1+0', '2+1', '3+0', '3+2', '5+0', '5+3', '10+0', '10+5', '15+10', '30+0'].map((t) => speedWord(t as never))).toEqual([
      'bullet', 'bullet', 'blitz', 'blitz', 'blitz', 'blitz', 'rapid', 'rapid', 'rapid', 'rapid',
    ])
  })
  it('clocks: m:ss, h:mm:ss, tenths under 10 s', () => {
    expect(clockText(600_000)).toBe('10:00')
    expect(clockText(552_100)).toBe('9:13')
    expect(clockText(9_450)).toBe('0:09.4')
    expect(clockText(-5)).toBe('0:00.0')
    expect(mmss(24.2)).toBe('0:25')
  })
  it('the footer: waiting, playing, draw offered, opponent left, over', () => {
    expect(footerState(st({ status: 'waiting' }))).toBe('waiting')
    expect(footerState(st())).toBe('playing')
    expect(footerState(st({ draw_offer: 'white' }))).toBe('playing')
    expect(footerState(st({ draw_offer: 'black' }))).toBe('draw-offered')
    expect(footerState(st({ opponent: { connected: false, gone_since: 5, chat_on: true } }))).toBe('opponent-left')
    expect(footerState(st({ status: 'over' }))).toBe('over')
  })
  it('the game-over lines', () => {
    expect(overLines(st({ status: 'over', result: '1-0', winner: 'white', termination: 'resign' }))).toEqual({ title: 'You won', reason: 'maxk resigned' })
    expect(overLines(st({ status: 'over', result: '0-1', winner: 'black', termination: 'timeout' }))).toEqual({ title: 'You lost', reason: 'You ran out of time' })
    expect(overLines(st({ status: 'over', result: '1/2-1/2', termination: 'agreed' })).title).toBe('Draw')
    expect(overLines(st({ status: 'over', result: '*', termination: 'aborted' })).title).toBe('Aborted')
    expect(overLines(st({ status: 'over', result: '1-0', winner: 'white', termination: 'abandoned' })).reason).toBe('maxk left the game')
  })
  it('the claim countdown runs on the server clock', () => {
    expect(claimIn(st({ claim_at: 31_000, server_time: 1000 }), 0, 7000)).toBe(24)
    expect(claimIn(st({ claim_at: 31_000 }), 0, 40_000)).toBe(0)
    expect(claimIn(st(), 0)).toBeNull()
  })
})
