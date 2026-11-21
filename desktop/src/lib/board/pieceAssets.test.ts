import { describe, expect, it } from 'vitest'
import { PIECE_FILES, PIECE_SETS } from './pieceSets'
import { pieceUrls, pieceVars } from './pieceAssets'

describe('piece set files reach the board', () => {
  it('every set resolves all twelve files, each set its own images', () => {
    const seen = new Set<string>()
    for (const s of PIECE_SETS) {
      const urls = pieceUrls(s.id)
      expect(Object.keys(urls).sort()).toEqual([...PIECE_FILES].sort())
      for (const f of PIECE_FILES) {
        // Vite inlines small SVGs as data URIs and emits larger ones as files
        expect(urls[f]).toMatch(new RegExp(`^data:image/svg\\+xml|${s.id}/${f}`))
        expect(seen.has(urls[f]!)).toBe(false)
        seen.add(urls[f]!)
      }
    }
  })

  it('a board wrapper gets twelve piece variables for the chosen set', () => {
    const vars = pieceVars('chessnut')
    expect(vars.match(/--pc-/g)?.length).toBe(12)
    expect(vars).toContain(`--pc-white-knight: url("${pieceUrls('chessnut').wN}")`)
    expect(pieceVars('chessnut')).not.toBe(pieceVars('merida'))
  })
})
