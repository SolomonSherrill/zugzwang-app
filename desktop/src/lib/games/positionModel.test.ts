import { describe, expect, it } from 'vitest'
import { START_FEN, firstGame, previewPlacement, readPosition } from './positionModel'

describe('readPosition', () => {
  it('nothing pasted is the starting position', () => {
    const r = readPosition('  ')
    expect(r).toMatchObject({ ok: true, fen: START_FEN, turn: 'white', from: 'start' })
  })
  it('reads a legal FEN, with or without its counters', () => {
    const fen = 'r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4'
    expect(readPosition(fen)).toMatchObject({ ok: true, fen, turn: 'white', from: 'fen', over: false })
    expect(readPosition('8/8/8/8/8/5k2/8/4K3 b - -')).toMatchObject({ ok: true, turn: 'black' })
  })
  it('says why a position is not legal', () => {
    const no = (t: string) => {
      const r = readPosition(t)
      return r.ok ? null : r.reason
    }
    expect(no('8/8/8/8/8/8/8/4K3 w - - 0 1')).toBe('Black has no king.')
    expect(no('4k3/8/8/8/8/8/8/3KK3 w - - 0 1')).toBe('White has more than one king.')
    expect(no('4k3/8/8/8/8/8/8/P3K3 w - - 0 1')).toBe('A pawn stands on the first or last rank.')
    // Black's king attacked by the rook with White to move
    expect(no('4k3/8/8/8/8/8/8/4KR2 w - - 0 1')).toBe(null)
    expect(no('4k3/8/8/8/8/8/8/R3K3 w - - 0 1')).toBe(null)
    expect(no('4k3/8/8/8/8/8/8/4RK2 w - - 0 1')).toBe('Black is in check, but it is White to move.')
    expect(no('4k3/8/8/8/8/8/8/4RK2 x - - 0 1')).toBe('The side to move must be w or b.')
    expect(no('4k3/8/8/8/8/8/4RK2 w - - 0 1')).toBe('The board part does not describe 8 ranks of 8 squares.')
    expect(no('hello')).toBe('Not a FEN, and not a PGN that can be read.')
  })
  it('keeps what can be read of an illegal placement for the preview', () => {
    const r = readPosition('8/8/8/8/8/8/8/4K3 w - - 0 1')
    expect(previewPlacement(r)).toBe('8/8/8/8/8/8/8/4K3')
    expect(previewPlacement(readPosition('nonsense'))).toBe('8/8/8/8/8/8/8/8')
  })
  it('a PGN starts from its last move; of several, the first game', () => {
    const pgn = '[Event "a"]\n[White "alice"]\n[Black "bob"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n\n[Event "b"]\n\n1. d4 *\n'
    const r = readPosition(pgn)
    expect(r).toMatchObject({ ok: true, from: 'pgn', turn: 'black', over: true, check: true })
    expect(firstGame(pgn)).not.toContain('1. d4')
    const bad = readPosition('1. e4 e5 2. Ke3 Ke6 3. Kxe6')
    expect(bad.ok).toBe(false)
    expect(bad.ok ? '' : bad.reason).toMatch(/illegal move/)
  })
})
