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

describe('the colour repair runs by itself when a username is added or changed (CR1)', () => {
  it('Settings has no "Fix game colours" and no Maintenance section', async () => {
    const src = (await import('./settings/SettingsView.svelte?raw')).default as string
    const markup = src.slice(src.indexOf('</script>'))
    expect(markup).not.toContain('Fix game colours')
    expect(markup).not.toContain('Maintenance')
    expect(src).not.toContain('api.repairColors')
  })

  const load = async (saved: Record<string, string> = {}) => {
    withStorage({ 'zugzwang-accounts': JSON.stringify(saved) })
    return await import('./settings.svelte')
  }

  it('runs once with the saved names when a name is added', async () => {
    const mod = await load({})
    const repair = vi.fn()
    expect(mod.saveAccounts('', ' someone ', repair)).toBe(true)
    expect(repair).toHaveBeenCalledTimes(1)
    expect(repair).toHaveBeenCalledWith({ lichess: '', chesscom: 'someone' })
  })

  it('runs when a name is changed', async () => {
    const mod = await load({ lichess: 'old', chesscom: 'kept' })
    const repair = vi.fn()
    expect(mod.saveAccounts('new', 'kept', repair)).toBe(true)
    expect(repair).toHaveBeenCalledWith({ lichess: 'new', chesscom: 'kept' })
  })

  it('does not run when nothing changed, or a name was only removed', async () => {
    const mod = await load({ lichess: 'a', chesscom: 'b' })
    const repair = vi.fn()
    expect(mod.saveAccounts('a', ' b ', repair)).toBe(false)
    expect(mod.saveAccounts('', 'b', repair)).toBe(false)
    expect(repair).not.toHaveBeenCalled()
  })

  it('decides from the names before and after', async () => {
    const { namesAddedOrChanged } = await load({})
    expect(namesAddedOrChanged({ lichess: '', chesscom: '' }, { lichess: 'x', chesscom: '' })).toBe(true)
    expect(namesAddedOrChanged({ lichess: 'x', chesscom: '' }, { lichess: 'X', chesscom: '' })).toBe(true)
    expect(namesAddedOrChanged({ lichess: 'x', chesscom: 'y' }, { lichess: '', chesscom: '' })).toBe(false)
  })
})
