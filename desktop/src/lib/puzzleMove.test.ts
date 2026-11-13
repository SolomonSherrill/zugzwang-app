import { describe, expect, it } from 'vitest'
import { resolveUserMove } from './puzzleMove'

const play = (played: string, over: Partial<Parameters<typeof resolveUserMove>[0]> = {}) =>
  resolveUserMove({ expected: 'a1a8', played, isFinal: true, finalMates: [], ...over })

describe('the expected move', () => {
  it('is accepted', () => {
    expect(play('a1a8')).toEqual({ ok: true, uci: 'a1a8' })
  })

  it('is rejected when a different move is played', () => {
    expect(play('a1a7')).toEqual({ ok: false })
  })
})

describe('alternate mates on the final move', () => {
  const mates = ['a1a8', 'e1e8']

  it('accepts a mate that is not the stored solution', () => {
    expect(play('e1e8', { finalMates: mates })).toEqual({ ok: true, uci: 'e1e8' })
  })

  it('still accepts the stored solution', () => {
    expect(play('a1a8', { finalMates: mates })).toEqual({ ok: true, uci: 'a1a8' })
  })

  it('rejects a move that is not in the set', () => {
    expect(play('h1h2', { finalMates: mates })).toEqual({ ok: false })
  })

  it('rejects everything when the set is empty', () => {
    // An empty set means the intended last move does not mate, so the puzzle is
    // about a specific idea and no substitute is interchangeable with it.
    expect(play('e1e8', { finalMates: [] })).toEqual({ ok: false })
  })

  it('treats a missing set the same as an empty one', () => {
    // A reply from a sidecar older than F7 omits the field entirely.
    expect(play('e1e8', { finalMates: undefined })).toEqual({ ok: false })
  })
})

describe('non-final moves', () => {
  it('require the exact solution move even when alternates exist', () => {
    // Guards the gating itself: mid-solution, a different mate would break the
    // rest of the line, so finalMates must not be consulted.
    expect(play('e1e8', { isFinal: false, finalMates: ['a1a8', 'e1e8'] })).toEqual({
      ok: false,
    })
  })

  it('still accept the expected move', () => {
    expect(play('a1a8', { isFinal: false, finalMates: ['a1a8', 'e1e8'] })).toEqual({
      ok: true,
      uci: 'a1a8',
    })
  })
})

// ── F8: an underpromotion must be played, not inferred ───────────────────────
//
// The old rule accepted a bare from/to and substituted whatever piece the
// solution named. On a puzzle whose answer is g7g8r that reported "correct" for
// a move the user never chose — and queening is often the losing move these
// puzzles exist to teach (stalemate, or allowing a defence).

describe('underpromotion', () => {
  const under = { expected: 'g7g8r', isFinal: false } as const

  it('is accepted when the matching piece is chosen', () => {
    expect(play('g7g8r', under)).toEqual({ ok: true, uci: 'g7g8r' })
  })

  it('is rejected when a different piece is chosen', () => {
    expect(play('g7g8q', under)).toEqual({ ok: false })
    expect(play('g7g8n', under)).toEqual({ ok: false })
    expect(play('g7g8b', under)).toEqual({ ok: false })
  })

  it('is rejected when no piece is named at all', () => {
    // The whole F8 bug in one line: from/to alone must not adopt the rook.
    expect(play('g7g8', under)).toEqual({ ok: false })
  })
})

describe('queen promotion', () => {
  const queen = { expected: 'g7g8q', isFinal: false } as const

  it('is accepted from a bare from/to, since auto-queen is the default', () => {
    expect(play('g7g8', queen)).toEqual({ ok: true, uci: 'g7g8q' })
  })

  it('is accepted when named explicitly', () => {
    expect(play('g7g8q', queen)).toEqual({ ok: true, uci: 'g7g8q' })
  })

  it('is rejected when the user deliberately underpromotes instead', () => {
    expect(play('g7g8n', queen)).toEqual({ ok: false })
  })
})

describe('promotion interacting with alternate mates', () => {
  it('accepts a different promotion when it also mates on the final move', () => {
    // F7 and F8 compose: the piece is honoured exactly, and a queen that mates
    // is a legitimate alternative to a rook that mates.
    expect(
      play('g7g8q', { expected: 'g7g8r', finalMates: ['g7g8q', 'g7g8r'] }),
    ).toEqual({ ok: true, uci: 'g7g8q' })
  })

  it('rejects a promotion that is not among the mates', () => {
    expect(
      play('g7g8n', { expected: 'g7g8r', finalMates: ['g7g8q', 'g7g8r'] }),
    ).toEqual({ ok: false })
  })

  it('never widens a stated piece to a different one', () => {
    // 'g7g8n' is not a mate, so the queen being available must not rescue it.
    expect(play('g7g8n', { expected: 'a1a8', finalMates: ['g7g8q'] })).toEqual({
      ok: false,
    })
  })

  it('defaults to queen only when no piece was stated', () => {
    expect(
      play('h7h8', { expected: 'a1a8', finalMates: ['h7h8b', 'h7h8q', 'h7h8r'] }),
    ).toEqual({ ok: true, uci: 'h7h8q' })
  })

  it('falls back to the only candidate when no queen promotion mates', () => {
    expect(play('h7h8', { expected: 'a1a8', finalMates: ['h7h8n'] })).toEqual({
      ok: true,
      uci: 'h7h8n',
    })
  })
})
