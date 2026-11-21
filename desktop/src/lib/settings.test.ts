import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const DEPTH_KEY = 'zugzwang-analysis-depth'

/** Install a fresh localStorage before each import: the store reads it at module scope. */
function withStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial))
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  return store
}

beforeEach(() => vi.resetModules())
afterEach(() => vi.unstubAllGlobals())

describe('no sync depth (ruling 17)', () => {
  it('exports no depth presets and no stored depth', async () => {
    withStorage({})
    const mod = (await import('./settings.svelte')) as Record<string, unknown>
    expect(mod.DEPTH_PRESETS).toBeUndefined()
    expect(mod.analysisDepth).toBeUndefined()
    expect(mod.saveAnalysisDepth).toBeUndefined()
  })

  it('clears a depth an older version stored', async () => {
    const store = withStorage({ [DEPTH_KEY]: '18' })
    await import('./settings.svelte')
    expect(store.has(DEPTH_KEY)).toBe(false)
  })
})

describe('accounts', () => {
  it('reads saved usernames and saves them trimmed', async () => {
    const store = withStorage({ 'zugzwang-accounts': JSON.stringify({ lichess: 'alice', chesscom: '' }) })
    const mod = await import('./settings.svelte')
    expect(mod.accounts.lichess).toBe('alice')
    expect(mod.hasAnyAccount()).toBe(true)
    mod.saveAccounts(' alice ', ' bob ')
    expect(JSON.parse(store.get('zugzwang-accounts')!)).toEqual({ lichess: 'alice', chesscom: 'bob' })
  })

  it('rejects a username with a space and allows an empty one', async () => {
    withStorage({})
    const { validateUsername } = await import('./settings.svelte')
    expect(validateUsername('a b')).toBe('No spaces allowed')
    expect(validateUsername('  ')).toBeNull()
    expect(validateUsername('alice')).toBeNull()
  })
})
