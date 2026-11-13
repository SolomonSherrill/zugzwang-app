import { describe, expect, it } from 'vitest'
import { matchesId, matchesSearch } from './gameSearch'

// A chess.com id (synthetic) on app game 483.
const chesscom = { id: 483, externalId: '900000000001' }
const lichess = { id: 12, externalId: 'AbCd1234' }
const local = { id: 7, externalId: null }
const text = ['some_opponent', "King's Pawn Game: Damiano Defense", 'C40', 'Apr 11']

describe('matchesId', () => {
  it('finds a game by its platform id, exactly', () => {
    expect(matchesId('900000000001', chesscom)).toBe(true)
    expect(matchesId(' 900000000001 ', chesscom)).toBe(true)
    expect(matchesId('90000000000', chesscom)).toBe(false)
  })
  it('matches a Lichess id regardless of case', () => {
    expect(matchesId('abcd1234', lichess)).toBe(true)
  })
  it('finds a game by its app id, bare or with #', () => {
    expect(matchesId('483', chesscom)).toBe(true)
    expect(matchesId('#483', chesscom)).toBe(true)
    expect(matchesId('#48', chesscom)).toBe(false)
  })
  it('never matches a local game on a missing platform id', () => {
    expect(matchesId('null', local)).toBe(false)
    expect(matchesId('#7', local)).toBe(true)
  })
})

describe('matchesSearch', () => {
  it('still matches opponent, opening, ECO and date as text', () => {
    expect(matchesSearch('some_opp', chesscom, text)).toBe(true)
    expect(matchesSearch('damiano', chesscom, text)).toBe(true)
    expect(matchesSearch('c40', chesscom, text)).toBe(true)
    expect(matchesSearch('najdorf', chesscom, text)).toBe(false)
  })
  it('matches an id exactly but not as part of one', () => {
    expect(matchesSearch('900000000001', chesscom, text)).toBe(true)
    expect(matchesSearch('00000', chesscom, text)).toBe(false)
  })
  it('treats # as the app id only, never as text', () => {
    expect(matchesSearch('#483', chesscom, ['player#483'])).toBe(true)
    expect(matchesSearch('#11', chesscom, text)).toBe(false)
  })
  it('an empty query matches everything', () => {
    expect(matchesSearch('  ', local, [])).toBe(true)
  })
})
