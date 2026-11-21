import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  DEFAULT_PIECE_SET,
  PIECE_FILES,
  PIECE_SETS,
  SHIPPABLE_LICENCES,
  creditLine,
  pieceSet,
  pieceSetVars,
  pieceVar,
} from './pieceSets'

const assets = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'assets', 'pieces')

describe('piece sets (ruling 20)', () => {
  it('are the five ruled sets, cburnett first and default', () => {
    expect(PIECE_SETS.map((s) => [s.id, s.licence])).toEqual([
      ['cburnett', 'GPLv2+'],
      ['merida', 'GPLv2+'],
      ['chessnut', 'Apache 2.0'],
      ['mpchess', 'GPLv3+'],
      ['fantasy', 'MIT'],
    ])
    expect(DEFAULT_PIECE_SET).toBe('cburnett')
    expect(pieceSet('alpha').id).toBe('cburnett')
    expect(pieceSet(null).id).toBe('cburnett')
    expect(pieceSet('fantasy').name).toBe('Fantasy')
  })

  it('never carry a non-commercial or unknown licence', () => {
    for (const s of PIECE_SETS) {
      expect(SHIPPABLE_LICENCES.has(s.licence)).toBe(true)
      expect(s.licence).not.toMatch(/NC|non.?commercial/i)
    }
  })

  it('ship twelve plain SVG files and a licence file each, beside the code', () => {
    for (const s of PIECE_SETS) {
      const dir = resolve(assets, s.id)
      expect(readdirSync(dir).sort()).toEqual([...PIECE_FILES.map((f) => `${f}.svg`), 'LICENSE.txt'].sort())
      for (const f of PIECE_FILES) {
        const svg = readFileSync(resolve(dir, `${f}.svg`), 'utf8')
        expect(svg.trimStart().startsWith('<svg')).toBe(true)
        expect(svg).not.toMatch(/<script|javascript:|\son[a-z]+\s*=|<foreignObject/i)
      }
      const lic = readFileSync(resolve(dir, 'LICENSE.txt'), 'utf8')
      expect(lic).toContain(s.author)
      expect(lic).toContain(s.source)
      expect(lic).toContain(s.licence)
    }
    // the set Lichess ships under "personal non commercial use" is not here
    expect(existsSync(resolve(assets, 'alpha'))).toBe(false)
  })

  it('name each piece by chessground\'s colour and role', () => {
    expect(pieceVar('wN')).toBe('--pc-white-knight')
    expect(pieceVar('bK')).toBe('--pc-black-king')
    expect(new Set(PIECE_FILES.map(pieceVar)).size).toBe(12)
  })

  it('give a board one variable per piece it has a file for', () => {
    expect(pieceSetVars({ wP: '/a/wP.svg', bQ: '/a/bQ.svg' })).toBe(
      '--pc-white-pawn: url("/a/wP.svg"); --pc-black-queen: url("/a/bQ.svg");',
    )
    expect(pieceSetVars({})).toBe('')
  })

  it('credit every set with its author and licence', () => {
    const line = creditLine()
    for (const s of PIECE_SETS) expect(line).toContain(`${s.name} by ${s.author} (${s.licence})`)
  })
})

describe('the chosen set persists like the board theme', () => {
  afterEach(() => vi.unstubAllGlobals())

  function storage(initial: Record<string, string> = {}) {
    const store = new Map(Object.entries(initial))
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    })
    return store
  }

  it('reads a stored set back and falls back to cburnett on anything else', async () => {
    storage({ 'zugzwang.pieceSet': 'merida' })
    vi.resetModules()
    expect((await import('./appearance.svelte')).appearance.pieceSet).toBe('merida')
    storage({ 'zugzwang.pieceSet': 'alpha' })
    vi.resetModules()
    expect((await import('./appearance.svelte')).appearance.pieceSet).toBe('cburnett')
  })

  it('stores the choice', async () => {
    const store = storage()
    vi.resetModules()
    const mod = await import('./appearance.svelte')
    mod.setPieceSet('fantasy')
    expect(mod.appearance.pieceSet).toBe('fantasy')
    expect(store.get('zugzwang.pieceSet')).toBe('fantasy')
  })
})
