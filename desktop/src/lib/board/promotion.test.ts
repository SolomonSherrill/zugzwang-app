import { describe, expect, it } from 'vitest'
import { choose, needsPicker, openPicker, pickerKey, pickerSquares, pieceAt, promotingSide, staleAfter, uciOf } from './promotion'

// b7 pawn, a8 rook, c8 bishop, b8 empty: three promotions for White (1. e4 d5 2. exd5 c6 3. dxc6 Nf6 4. cxb7 Nbd7)
const WHITE_PROMO = 'r1bqkb1r/pP1npppp/5n2/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 1 5'
// a black pawn on g2, Black to move
const BLACK_PROMO = '4k3/8/8/8/8/8/6p1/4K3 b - - 0 1'

describe('pieceAt', () => {
  it('reads the placement field', () => {
    expect(pieceAt(WHITE_PROMO, 'b7')).toBe('P')
    expect(pieceAt(WHITE_PROMO, 'a8')).toBe('r')
    expect(pieceAt(WHITE_PROMO, 'b8')).toBe(null)
    expect(pieceAt(WHITE_PROMO, 'e1')).toBe('K')
    expect(pieceAt(BLACK_PROMO, 'g2')).toBe('p')
    expect(pieceAt(BLACK_PROMO, 'h2')).toBe(null)
  })
})

describe('which moves need the picker', () => {
  it('a white pawn from the 7th to the 8th, straight or capturing', () => {
    expect(promotingSide(WHITE_PROMO, 'b7', 'b8')).toBe('white')
    expect(promotingSide(WHITE_PROMO, 'b7', 'a8')).toBe('white')
    expect(promotingSide(WHITE_PROMO, 'b7', 'c8')).toBe('white')
  })
  it('a black pawn from the 2nd to the 1st', () => {
    expect(promotingSide(BLACK_PROMO, 'g2', 'g1')).toBe('black')
  })
  it('not a pawn move elsewhere, nor a piece reaching the last rank', () => {
    expect(promotingSide(WHITE_PROMO, 'e2', 'e4')).toBe(null)
    expect(promotingSide(WHITE_PROMO, 'd1', 'd8')).toBe(null) // the queen
    expect(promotingSide(BLACK_PROMO, 'e8', 'e7')).toBe(null)
    expect(promotingSide(WHITE_PROMO, 'b7', 'd8')).toBe(null) // not a pawn's move
  })
  it('only a move the board offers (its legal destinations)', () => {
    const dests = new Map([['b7', ['a8', 'b8', 'c8']]])
    expect(needsPicker(WHITE_PROMO, 'b7', 'a8', dests)).toBe(true)
    expect(needsPicker(WHITE_PROMO, 'b7', 'd8', dests)).toBe(false)
    expect(needsPicker(WHITE_PROMO, 'e2', 'e4', new Map([['e2', ['e3', 'e4']]]))).toBe(false)
    expect(needsPicker(BLACK_PROMO, 'g2', 'g1', new Map([['g2', []]]))).toBe(false)
  })
})

describe('where the four squares go', () => {
  it('White at the bottom, White promoting on b8: down the b-file from the top, queen first', () => {
    const sq = pickerSquares('b8', 'white')
    expect(sq.map((s) => s.role)).toEqual(['queen', 'knight', 'rook', 'bishop'])
    expect(sq.map((s) => s.square)).toEqual(['b8', 'b7', 'b6', 'b5'])
    expect(sq.map((s) => [s.col, s.row])).toEqual([[1, 0], [1, 1], [1, 2], [1, 3]])
    // b8 is dark, b7 light: the theme's own colours, alternating
    expect(sq.map((s) => s.light)).toEqual([false, true, false, true])
  })
  it('White at the bottom, Black promoting on g1: up from the bottom edge', () => {
    const sq = pickerSquares('g1', 'white')
    expect(sq.map((s) => s.square)).toEqual(['g1', 'g2', 'g3', 'g4'])
    expect(sq.map((s) => [s.col, s.row])).toEqual([[6, 7], [6, 6], [6, 5], [6, 4]])
  })
  it('Black at the bottom flips the column: Black promoting on g1 is at the top, mirrored', () => {
    const sq = pickerSquares('g1', 'black')
    expect(sq.map((s) => s.square)).toEqual(['g1', 'g2', 'g3', 'g4'])
    expect(sq.map((s) => [s.col, s.row])).toEqual([[1, 0], [1, 1], [1, 2], [1, 3]])
  })
  it('Black at the bottom, White promoting on b8: at the bottom, going up', () => {
    const sq = pickerSquares('b8', 'black')
    expect(sq.map((s) => s.square)).toEqual(['b8', 'b7', 'b6', 'b5'])
    expect(sq.map((s) => [s.col, s.row])).toEqual([[6, 7], [6, 6], [6, 5], [6, 4]])
  })
})

describe('keys', () => {
  it('Q / R / B / N choose, in either case; Esc cancels', () => {
    expect(pickerKey({ key: 'q' })).toBe('q')
    expect(pickerKey({ key: 'N' })).toBe('n')
    expect(pickerKey({ key: 'r' })).toBe('r')
    expect(pickerKey({ key: 'B' })).toBe('b')
    expect(pickerKey({ key: 'Escape' })).toBe('cancel')
  })
  it('other keys, and modified ones, are not the picker’s', () => {
    expect(pickerKey({ key: 'k' })).toBe(null)
    expect(pickerKey({ key: 'ArrowLeft' })).toBe(null)
    expect(pickerKey({ key: 'f' })).toBe(null)
    expect(pickerKey({ key: 'q', metaKey: true })).toBe(null)
    expect(pickerKey({ key: 'n', ctrlKey: true })).toBe(null)
  })
})

describe('open, choose, cancel', () => {
  it('a promotion opens the picker; another move does not', () => {
    expect(openPicker(WHITE_PROMO, 'b7', 'a8')).toEqual({ orig: 'b7', dest: 'a8', side: 'white', fen: WHITE_PROMO })
    expect(openPicker(WHITE_PROMO, 'e2', 'e4')).toBe(null)
  })
  it('a piece completes the move with its UCI suffix', () => {
    const s = openPicker(WHITE_PROMO, 'b7', 'a8')!
    expect(choose(s, 'n')).toEqual({ kind: 'move', orig: 'b7', dest: 'a8', piece: 'n', uci: 'b7a8n' })
    expect(choose(s, 'q')).toMatchObject({ uci: 'b7a8q' })
    expect(choose(openPicker(BLACK_PROMO, 'g2', 'g1')!, 'r')).toMatchObject({ uci: 'g2g1r' })
  })
  it('Esc cancels: no move', () => {
    expect(choose(openPicker(WHITE_PROMO, 'b7', 'b8')!, 'cancel')).toEqual({ kind: 'cancel' })
  })
  it('closes by itself when the position changes or the board stops taking moves', () => {
    const s = openPicker(WHITE_PROMO, 'b7', 'b8')
    expect(staleAfter(s, WHITE_PROMO, true)).toBe(false)
    expect(staleAfter(s, BLACK_PROMO, true)).toBe(true)
    expect(staleAfter(s, WHITE_PROMO, false)).toBe(true)
    expect(staleAfter(null, BLACK_PROMO, false)).toBe(false)
  })
  it('uciOf', () => {
    expect(uciOf('e2', 'e4')).toBe('e2e4')
    expect(uciOf('e7', 'e8', 'b')).toBe('e7e8b')
  })
})
